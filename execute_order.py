#!/usr/bin/env python3
import os
import sys
import json

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv('c:/Users/benjaminnlow/OneDrive/AI Trader/aibot.env')

from ctrader_bot import SimpleCTraderBot
from ctrader_open_api import Protobuf
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOANewOrderReq,
    ProtoOAExecutionEvent,
    ProtoOAOrderErrorEvent
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
    ProtoOAExecutionType,
    ProtoOAOrderType,
    ProtoOATradeSide
)
from twisted.internet import reactor

class OrderExecutor:
    def __init__(self, symbol="XAUUSD", side="SELL", volume=0.01, sl=None, tp=None):
        self.bot = SimpleCTraderBot()
        self.symbol = symbol.upper()
        self.side = side.upper()
        self.volume = volume
        self.sl = sl
        self.tp = tp
        self.execution_result = None
        self.order_submitted = False

    def start(self):
        original_on_message = self.bot._on_message
        
        def custom_on_message(client, message):
            original_on_message(client, message)
            
            if message.payloadType == ProtoOAExecutionEvent().payloadType:
                event = Protobuf.extract(message)
                exec_type = getattr(event, 'executionType', None)
                print(f"✓ Execution Event Received: execType={exec_type}")
                
                pos_id = getattr(event.position, 'positionId', None) if hasattr(event, 'position') else None
                order_id = getattr(event.order, 'orderId', None) if hasattr(event, 'order') else None
                exec_price = getattr(event.position, 'price', None) if hasattr(event, 'position') else getattr(event.order, 'executionPrice', None)
                
                self.execution_result = {
                    "success": True,
                    "execution_type": str(exec_type),
                    "position_id": pos_id,
                    "order_id": order_id,
                    "symbol": self.symbol,
                    "side": self.side,
                    "volume_lots": self.volume,
                    "execution_price": exec_price,
                    "stop_loss": self.sl,
                    "take_profit": self.tp
                }
                reactor.callLater(1, self.finish)

            if message.payloadType == ProtoOAOrderErrorEvent().payloadType:
                error = Protobuf.extract(message)
                print(f"✗ Order Error Received: {error.errorCode} - {error.description}")
                self.execution_result = {
                    "success": False,
                    "error_code": error.errorCode,
                    "description": error.description
                }
                reactor.callLater(1, self.finish)

            if self.bot.is_account_authenticated and not self.order_submitted and len(self.bot.symbols) > 0:
                self.order_submitted = True
                reactor.callLater(1, self.send_order)

        self.bot._on_message = custom_on_message
        self.bot.start()
        reactor.callLater(15, self.finish)

    def send_order(self):
        symbol_info = self.bot.symbols.get(self.symbol)
        if not symbol_info:
            print(f"✗ Symbol {self.symbol} not found in catalog")
            self.execution_result = {"success": False, "error": f"Symbol {self.symbol} not found"}
            self.finish()
            return

        symbol_id = symbol_info['id']
        api_volume = int(self.volume * 1000000)

        request = ProtoOANewOrderReq()
        request.ctidTraderAccountId = self.bot.account_id
        request.symbolId = symbol_id
        request.orderType = ProtoOAOrderType.MARKET
        request.tradeSide = ProtoOATradeSide.BUY if self.side == "BUY" else ProtoOATradeSide.SELL
        request.volume = api_volume

        if self.sl:
            request.stopLoss = self.sl
        if self.tp:
            request.takeProfit = self.tp

        print(f"Submitting {self.side} market order for {self.symbol} (Lots: {self.volume}, API Volume: {api_volume})...")
        deferred = self.bot.client.send(request)
        deferred.addErrback(self.bot._on_error)

    def finish(self):
        print("\n=== FINAL EXECUTION RESULT ===")
        print(json.dumps(self.execution_result, indent=2))
        print("==============================\n")
        self.bot.stop()

if __name__ == "__main__":
    sym = sys.argv[1] if len(sys.argv) > 1 else "XAUUSD"
    side = sys.argv[2] if len(sys.argv) > 2 else "SELL"
    vol = float(sys.argv[3]) if len(sys.argv) > 3 else 0.01
    sl = float(sys.argv[4]) if len(sys.argv) > 4 else None
    tp = float(sys.argv[5]) if len(sys.argv) > 5 else None
    
    executor = OrderExecutor(symbol=sym, side=side, volume=vol, sl=sl, tp=tp)
    executor.start()
    reactor.run()
