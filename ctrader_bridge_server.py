#!/usr/bin/env python3
# Run with: venv\Scripts\python.exe ctrader_bridge_server.py
"""
cTrader Real-Time Bridge Server
================================
Runs on your PC. Connects to the real cTrader Open API via TCP,
then exposes simple HTTP endpoints for Cloudflare Worker to call:

  GET  /account   → Real balance, equity, positions, margin
  POST /order     → Execute buy/sell/close on real cTrader account
  GET  /health    → Health check
  GET  /price     → Live XAUUSD spot price (bid/ask)

Start with:
  python ctrader_bridge_server.py

Then expose with ngrok:
  ngrok http 8765
"""

import os
import sys
import json
import time
import asyncio
import threading
from datetime import datetime, timezone

# Add ctrader-mcp-server to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv('c:/Users/benjaminnlow/OneDrive/AI Trader/aibot.env')

# Force demo mode
os.environ['HOST'] = 'demo'

from twisted.internet import reactor
from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *
from ctrader_open_api.messages.OpenApiMessages_pb2 import *
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import *

from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.parse

# ─────────────────────────────────────────────
# Global State (thread-safe via lock)
# ─────────────────────────────────────────────
state_lock = threading.Lock()
shared_state = {
    "connected": False,
    "app_auth": False,
    "account_auth": False,
    "symbols": {},          # symbolId -> {name, digits}
    "symbols_by_name": {},  # name -> symbolId
    "positions": [],
    "account": {
        "id": int(os.getenv("ACCOUNT_ID", "5316354")),
        "balance": 0.0,
        "equity": 0.0,
        "margin_used": 0.0,
        "free_margin": 0.0,
        "margin_level": 0.0,
        "leverage": 500,
        "currency": "USD"
    },
    "live_prices": {},       # symbolId -> {bid, ask, ts}
    "last_updated": None,
    "error": None,
    "ready": False,
    "pending_orders": []     # queue of orders to execute after auth
}

ctrader_client = None
ctrader_client_ref = None


# ─────────────────────────────────────────────
# cTrader Connection & Message Handling
# ─────────────────────────────────────────────
def on_connected(client):
    global ctrader_client_ref
    ctrader_client_ref = client
    print("[cTrader] ✓ Connected")
    with state_lock:
        shared_state["connected"] = True
        shared_state["error"] = None

    # App auth
    req = ProtoOAApplicationAuthReq()
    req.clientId = os.getenv("CLIENT_ID")
    req.clientSecret = os.getenv("CLIENT_SECRET")
    client.send(req)
    print("[cTrader] → App auth sent")


def on_disconnected(client, reason):
    print(f"[cTrader] ✗ Disconnected: {reason}")
    with state_lock:
        shared_state["connected"] = False
        shared_state["app_auth"] = False
        shared_state["account_auth"] = False
        shared_state["ready"] = False
        shared_state["error"] = str(reason)
    # Reconnect after 5s
    reactor.callLater(5, start_ctrader_connection)


def on_message(client, message):
    try:
        ptype = message.payloadType

        # App auth response
        if ptype == ProtoOAApplicationAuthRes().payloadType:
            print("[cTrader] ✓ App authenticated")
            with state_lock:
                shared_state["app_auth"] = True
            # Account auth
            req = ProtoOAAccountAuthReq()
            req.ctidTraderAccountId = shared_state["account"]["id"]
            req.accessToken = os.getenv("ACCESS_TOKEN")
            client.send(req)
            print("[cTrader] → Account auth sent")

        # Account auth response
        elif ptype == ProtoOAAccountAuthRes().payloadType:
            print("[cTrader] ✓ Account authenticated")
            with state_lock:
                shared_state["account_auth"] = True
            # Request symbols
            req = ProtoOASymbolsListReq()
            req.ctidTraderAccountId = shared_state["account"]["id"]
            client.send(req)
            print("[cTrader] → Symbols list requested")

        # Symbols list
        elif ptype == ProtoOASymbolsListRes().payloadType:
            res = Protobuf.extract(message)
            with state_lock:
                for sym in res.symbol:
                    digits = getattr(sym, 'digits', 5)
                    shared_state["symbols"][sym.symbolId] = {
                        "name": sym.symbolName,
                        "digits": digits
                    }
                    shared_state["symbols_by_name"][sym.symbolName.upper()] = sym.symbolId
            print(f"[cTrader] ✓ Loaded {len(res.symbol)} symbols")
            # Now request trader info + reconcile
            _request_trader_info(client)
            _request_reconcile(client)
            # Subscribe to XAUUSD ticks for live price
            _subscribe_to_symbol(client, "XAUUSD")

        # Trader info (balance, leverage)
        elif ptype == ProtoOATraderRes().payloadType:
            res = Protobuf.extract(message)
            t = res.trader
            with state_lock:
                shared_state["account"]["balance"] = t.balance / 100.0
                shared_state["account"]["leverage"] = int(t.leverageInCents / 100) if t.leverageInCents else 500
                shared_state["account"]["currency"] = t.depositAsset.name if hasattr(t, 'depositAsset') and t.depositAsset else "USD"
                shared_state["last_updated"] = datetime.now(timezone.utc).isoformat()
            print(f"[cTrader] ✓ Trader info: Balance=${t.balance/100:.2f}, Leverage=1:{int(t.leverageInCents/100) if t.leverageInCents else 500}")

        # Reconcile response (positions, orders, margins)
        elif ptype == ProtoOAReconcileRes().payloadType:
            res = Protobuf.extract(message)
            positions = []
            with state_lock:
                syms = shared_state["symbols"]
                for pos in res.position:
                    sym_info = syms.get(pos.tradeData.symbolId, {})
                    sym_name = sym_info.get("name", f"SYM#{pos.tradeData.symbolId}")
                    digits = sym_info.get("digits", 5)
                    divisor = 10 ** digits
                    entry_price = pos.price / divisor if pos.price > 100 else pos.price
                    # Volume: cTrader stores in units (100 = 0.01 lot for standard)
                    volume_lots = pos.tradeData.volume / 100.0
                    trade_side = "BUY" if pos.tradeData.tradeSide == ProtoOATradeSide.BUY else "SELL"
                    # Swap/commission in cents
                    swap = getattr(pos, 'swap', 0) / 100.0
                    commission = getattr(pos, 'commission', 0) / 100.0

                    positions.append({
                        "position_id": pos.positionId,
                        "symbol": sym_name,
                        "symbol_id": pos.tradeData.symbolId,
                        "side": trade_side,
                        "volume_lots": volume_lots,
                        "entry_price": entry_price,
                        "swap": swap,
                        "commission": commission,
                        "sl": getattr(pos, 'stopLoss', 0) / divisor if getattr(pos, 'stopLoss', 0) > 0 else None,
                        "tp": getattr(pos, 'takeProfit', 0) / divisor if getattr(pos, 'takeProfit', 0) > 0 else None,
                        "open_timestamp": getattr(pos.tradeData, 'openTimestamp', 0),
                        "pnl_usd": 0.0  # Will be calculated with live price
                    })

                shared_state["positions"] = positions
                shared_state["ready"] = True
                shared_state["last_updated"] = datetime.now(timezone.utc).isoformat()

            print(f"[cTrader] ✓ Reconcile: {len(positions)} open positions")

        # Live spot ticks (real-time XAUUSD price)
        elif ptype == ProtoOASpotEvent().payloadType:
            res = Protobuf.extract(message)
            with state_lock:
                sym_info = shared_state["symbols"].get(res.symbolId, {})
                digits = sym_info.get("digits", 5)
                divisor = 10 ** digits
                bid = res.bid / divisor if res.bid > 0 else 0
                ask = res.ask / divisor if res.ask > 0 else 0
                shared_state["live_prices"][res.symbolId] = {
                    "bid": bid,
                    "ask": ask,
                    "mid": (bid + ask) / 2,
                    "ts": datetime.now(timezone.utc).isoformat()
                }
                # Recalculate equity with latest price
                _recalculate_equity_locked()
                shared_state["last_updated"] = datetime.now(timezone.utc).isoformat()

        # Execution event (order fill confirmation)
        elif ptype == ProtoOAExecutionEvent().payloadType:
            event = Protobuf.extract(message)
            etype = event.executionType
            type_names = {
                ProtoOAExecutionType.ORDER_ACCEPTED: "ACCEPTED",
                ProtoOAExecutionType.ORDER_FILLED: "FILLED",
                ProtoOAExecutionType.ORDER_CANCELLED: "CANCELLED",
                ProtoOAExecutionType.ORDER_REJECTED: "REJECTED",
            }
            ename = type_names.get(etype, str(etype))
            print(f"[cTrader] ✓ Execution Event: {ename}")
            if etype == ProtoOAExecutionType.ORDER_FILLED:
                # Refresh positions after fill
                reactor.callLater(0.5, lambda: _request_reconcile(client))

        # Error event
        elif ptype == ProtoOAErrorRes().payloadType:
            err = Protobuf.extract(message)
            print(f"[cTrader] ✗ API Error: {err.errorCode} - {err.description}")

    except Exception as e:
        print(f"[cTrader] ✗ Message processing error: {e}")


def _request_trader_info(client):
    req = ProtoOATraderReq()
    req.ctidTraderAccountId = shared_state["account"]["id"]
    client.send(req)


def _request_reconcile(client):
    req = ProtoOAReconcileReq()
    req.ctidTraderAccountId = shared_state["account"]["id"]
    client.send(req)


def _subscribe_to_symbol(client, symbol_name):
    with state_lock:
        symbol_id = shared_state["symbols_by_name"].get(symbol_name.upper())
    if not symbol_id:
        print(f"[cTrader] ✗ Symbol {symbol_name} not found for tick subscription, retrying in 3s...")
        reactor.callLater(3, lambda: _subscribe_to_symbol(client, symbol_name))
        return
    req = ProtoOASubscribeSpotsReq()
    req.ctidTraderAccountId = shared_state["account"]["id"]
    req.symbolId.append(symbol_id)
    client.send(req)
    print(f"[cTrader] ✓ Subscribed to {symbol_name} ticks (ID: {symbol_id})")


def _recalculate_equity_locked():
    """Recalculate equity, PnL, margin. Must be called with state_lock held."""
    acc = shared_state["account"]
    balance = acc["balance"]
    total_pnl = 0.0

    for pos in shared_state["positions"]:
        sym_id = pos["symbol_id"]
        price_data = shared_state["live_prices"].get(sym_id)
        if price_data:
            live_price = price_data["mid"]
            sym_info = shared_state["symbols"].get(sym_id, {})
            digits = sym_info.get("digits", 5)
            # PnL formula: For XAUUSD 0.01 lot = $1 per pip ($0.10 per 0.1 pip)
            # Volume in lots × pip value per lot × (exit - entry) in price units
            lots = pos["volume_lots"]
            entry = pos["entry_price"]
            if pos["side"] == "BUY":
                price_diff = live_price - entry
            else:
                price_diff = entry - live_price
            # For XAUUSD: 1 lot = $100/pip, 0.01 lot = $1/pip
            # pip = 0.01 for XAUUSD (2 decimal places price)
            # But digits=5 → price in full, so $1 per 1.0 price unit per 0.01 lot
            if digits >= 5:
                # Forex pairs: pip = 0.0001
                pnl = price_diff * lots * 100000 * 0.0001
            else:
                # Metals/indices: e.g. XAUUSD digits=2, 1 lot = $100
                pnl = price_diff * lots * 100
            pos["pnl_usd"] = round(pnl + pos.get("swap", 0.0) + pos.get("commission", 0.0), 2)
            total_pnl += pos["pnl_usd"]

    equity = balance + total_pnl
    # Margin used = (volume_lots * contract_size * price) / leverage
    # For XAUUSD: contract_size = 100 oz, so $100 * price
    margin_used = 0.0
    leverage = acc.get("leverage", 500)
    for pos in shared_state["positions"]:
        sym_id = pos["symbol_id"]
        price_data = shared_state["live_prices"].get(sym_id)
        live_price = price_data["mid"] if price_data else pos["entry_price"]
        sym_info = shared_state["symbols"].get(sym_id, {})
        digits = sym_info.get("digits", 5)
        lots = pos["volume_lots"]
        if digits >= 5:
            contract_size = 100000
            margin_used += (lots * contract_size * live_price) / leverage / live_price  # simplified
        else:
            contract_size = 100
            margin_used += (lots * contract_size * live_price) / leverage

    acc["equity"] = round(equity, 2)
    acc["total_pnl"] = round(total_pnl, 2)
    acc["margin_used"] = round(margin_used, 2)
    acc["free_margin"] = round(equity - margin_used, 2)
    if margin_used > 0:
        acc["margin_level"] = round((equity / margin_used) * 100, 2)
    else:
        acc["margin_level"] = 0.0


def start_ctrader_connection():
    global ctrader_client
    print("[cTrader] Connecting to demo.ctraderapi.com:5035...")
    ctrader_client = Client(EndPoints.PROTOBUF_DEMO_HOST, EndPoints.PROTOBUF_PORT, TcpProtocol)
    ctrader_client.setConnectedCallback(on_connected)
    ctrader_client.setDisconnectedCallback(on_disconnected)
    ctrader_client.setMessageReceivedCallback(on_message)
    ctrader_client.startService()


def run_twisted():
    """Run Twisted reactor in a background thread."""
    reactor.callLater(0, start_ctrader_connection)
    reactor.run(installSignalHandlers=False)


# ─────────────────────────────────────────────
# HTTP Bridge Server (pure stdlib, no dependencies)
# ─────────────────────────────────────────────
class BridgeHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress verbose HTTP logs

    def _send_json(self, data, status=200):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_cors(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_OPTIONS(self):
        self._send_cors()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/health":
            with state_lock:
                self._send_json({
                    "status": "ok",
                    "connected": shared_state["connected"],
                    "ready": shared_state["ready"],
                    "account_auth": shared_state["account_auth"],
                    "positions_count": len(shared_state["positions"]),
                    "last_updated": shared_state["last_updated"]
                })

        elif path == "/account":
            # Refresh reconcile in background
            if ctrader_client_ref and shared_state["account_auth"]:
                reactor.callFromThread(_request_reconcile, ctrader_client_ref)
                reactor.callFromThread(_request_trader_info, ctrader_client_ref)

            with state_lock:
                acc = shared_state["account"].copy()
                positions = []
                for p in shared_state["positions"]:
                    sym_id = p["symbol_id"]
                    price_data = shared_state["live_prices"].get(sym_id, {})
                    positions.append({
                        "position_id": p["position_id"],
                        "symbol": p["symbol"],
                        "side": p["side"],
                        "volume_lots": p["volume_lots"],
                        "entry_price": p["entry_price"],
                        "live_price": price_data.get("bid", p["entry_price"]),
                        "live_ask": price_data.get("ask", p["entry_price"]),
                        "pnl_usd": p["pnl_usd"],
                        "swap": p.get("swap", 0.0),
                        "commission": p.get("commission", 0.0),
                        "sl": p.get("sl"),
                        "tp": p.get("tp"),
                        "open_timestamp": p.get("open_timestamp", 0)
                    })

                self._send_json({
                    "account_id": acc["id"],
                    "balance": acc["balance"],
                    "equity": acc["equity"],
                    "total_pnl": acc.get("total_pnl", 0.0),
                    "margin_used": acc["margin_used"],
                    "free_margin": acc["free_margin"],
                    "margin_level": acc["margin_level"],
                    "leverage": f"1:{acc['leverage']}",
                    "currency": acc.get("currency", "USD"),
                    "positions": positions,
                    "positions_count": len(positions),
                    "last_updated": shared_state["last_updated"],
                    "ready": shared_state["ready"]
                })

        elif path == "/price":
            with state_lock:
                sym_id = shared_state["symbols_by_name"].get("XAUUSD")
                price_data = shared_state["live_prices"].get(sym_id, {}) if sym_id else {}
            self._send_json({
                "symbol": "XAUUSD",
                "bid": price_data.get("bid", 0),
                "ask": price_data.get("ask", 0),
                "mid": price_data.get("mid", 0),
                "ts": price_data.get("ts", datetime.now(timezone.utc).isoformat())
            })

        else:
            self._send_json({"error": "Not found", "path": path}, 404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/order":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length)) if length > 0 else {}
                action = body.get("action", "").upper()  # BUY / SELL / CLOSE
                symbol = body.get("symbol", "XAUUSD").upper()
                lots = float(body.get("lots", 0.01))
                sl = body.get("sl")
                tp = body.get("tp")
                position_id = body.get("position_id")

                if not shared_state["account_auth"]:
                    self._send_json({"success": False, "error": "Not authenticated to cTrader"}, 503)
                    return

                if action in ("BUY", "SELL"):
                    with state_lock:
                        symbol_id = shared_state["symbols_by_name"].get(symbol)
                    if not symbol_id:
                        self._send_json({"success": False, "error": f"Symbol {symbol} not found"}, 400)
                        return

                    def place_order():
                        req = ProtoOANewOrderReq()
                        req.ctidTraderAccountId = shared_state["account"]["id"]
                        req.symbolId = symbol_id
                        req.orderType = ProtoOAOrderType.MARKET
                        req.tradeSide = ProtoOATradeSide.BUY if action == "BUY" else ProtoOATradeSide.SELL
                        req.volume = int(lots * 100)  # centilots
                        if sl:
                            req.stopLoss = float(sl)
                        if tp:
                            req.takeProfit = float(tp)
                        ctrader_client_ref.send(req)
                        print(f"[cTrader] → {action} {lots} {symbol} SL={sl} TP={tp}")

                    reactor.callFromThread(place_order)
                    self._send_json({"success": True, "action": action, "symbol": symbol, "lots": lots, "sl": sl, "tp": tp})

                elif action == "CLOSE":
                    if not position_id:
                        # Close all positions for symbol
                        with state_lock:
                            to_close = [(p["position_id"], p["volume_lots"]) for p in shared_state["positions"] if p["symbol"].upper() == symbol]
                    else:
                        with state_lock:
                            pos = next((p for p in shared_state["positions"] if p["position_id"] == int(position_id)), None)
                        to_close = [(pos["position_id"], lots or pos["volume_lots"])] if pos else []

                    if not to_close:
                        self._send_json({"success": False, "error": "No matching positions to close"}, 404)
                        return

                    def close_positions(positions_to_close):
                        for pid, vol in positions_to_close:
                            req = ProtoOAClosePositionReq()
                            req.ctidTraderAccountId = shared_state["account"]["id"]
                            req.positionId = pid
                            req.volume = int(vol * 100)
                            ctrader_client_ref.send(req)
                            print(f"[cTrader] → Close position {pid} {vol} lots")

                    reactor.callFromThread(close_positions, to_close)
                    self._send_json({"success": True, "action": "CLOSE", "closed": len(to_close)})

                else:
                    self._send_json({"success": False, "error": f"Unknown action: {action}"}, 400)

            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)

        elif path == "/refresh":
            if ctrader_client_ref and shared_state["account_auth"]:
                reactor.callFromThread(_request_reconcile, ctrader_client_ref)
                reactor.callFromThread(_request_trader_info, ctrader_client_ref)
            self._send_json({"status": "refresh_requested"})

        else:
            self._send_json({"error": "Not found"}, 404)


def run_http_server(port=8765):
    server = HTTPServer(("0.0.0.0", port), BridgeHandler)
    print(f"\n{'='*60}")
    print(f"  cTrader Real-Time Bridge Server")
    print(f"  http://localhost:{port}")
    print(f"  Endpoints:")
    print(f"    GET  /health   → Status check")
    print(f"    GET  /account  → Real balance, equity, positions")
    print(f"    GET  /price    → Live XAUUSD bid/ask")
    print(f"    POST /order    → Execute BUY/SELL/CLOSE")
    print(f"{'='*60}\n")
    server.serve_forever()


# ─────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────
if __name__ == "__main__":
    PORT = int(os.environ.get("BRIDGE_PORT", "8765"))

    # Run Twisted reactor in a background thread
    twisted_thread = threading.Thread(target=run_twisted, daemon=True)
    twisted_thread.start()

    print("[Bridge] Twisted reactor started in background thread")
    print("[Bridge] Waiting for cTrader connection...")

    # Wait up to 15s for initial connection
    for i in range(15):
        time.sleep(1)
        with state_lock:
            if shared_state["ready"]:
                print("[Bridge] ✓ cTrader ready!")
                break
        print(f"[Bridge] Waiting... {i+1}s")

    # Start HTTP server (main thread)
    run_http_server(PORT)
