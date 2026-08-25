#!/usr/bin/env python3
import os
import sys
import time
import json
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from ctrader_bot import SimpleCTraderBot
from ctrader_open_api import Protobuf
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAErrorRes
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoErrorRes
from twisted.internet import reactor

class TickFetcher:
    def __init__(self, target_symbol="XAUUSD", host_override=None, max_ticks=3, timeout=35):
        # Allow overriding host via argument or test demo if requested
        if host_override:
            os.environ['HOST'] = host_override
        
        self.bot = SimpleCTraderBot()
        self.target_symbol = target_symbol.upper()
        self.max_ticks = max_ticks
        self.timeout = timeout
        self.ticks_received = []
        self.start_time = time.time()
        self.subscribed_symbol = None
        self.error_occurred = None

    def start(self):
        original_on_message = self.bot._on_message
        
        def custom_on_message(client, message):
            if message.payloadType == ProtoOAErrorRes().payloadType:
                err = Protobuf.extract(message)
                err_msg = f"ProtoOAErrorRes: errorCode={getattr(err, 'errorCode', '')}, description={getattr(err, 'description', '')}"
                print(f"✗ {err_msg}")
                self.error_occurred = getattr(err, 'errorCode', '')
            elif message.payloadType == ProtoErrorRes().payloadType:
                err = Protobuf.extract(message)
                err_msg = f"ProtoErrorRes: errorCode={getattr(err, 'errorCode', '')}, description={getattr(err, 'description', '')}"
                print(f"✗ {err_msg}")
                self.error_occurred = getattr(err, 'errorCode', '')
            
            original_on_message(client, message)

        self.bot._on_message = custom_on_message

        original_handle_spot = self.bot._handle_spot_event
        
        def custom_handle_spot(message):
            original_handle_spot(message)
            try:
                response = Protobuf.extract(message)
                symbol_name = next((s['name'] for s in self.bot.symbols.values() if s['id'] == response.symbolId), 'Unknown')
                
                if self.subscribed_symbol and symbol_name.upper() == self.subscribed_symbol.upper():
                    symbol_info = self.bot.symbols.get(symbol_name, {})
                    digits = symbol_info.get('digits', 2 if 'XAU' in symbol_name.upper() else 5)
                    divisor = 100000.0
                    
                    bid = (response.bid / divisor) if hasattr(response, 'bid') and response.bid else None
                    ask = (response.ask / divisor) if hasattr(response, 'ask') and response.ask else None
                    
                    tick = {
                        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
                        'symbol': symbol_name,
                        'bid': round(bid, digits) if bid else None,
                        'ask': round(ask, digits) if ask else None,
                        'raw_bid': getattr(response, 'bid', None),
                        'raw_ask': getattr(response, 'ask', None),
                        'digits': digits
                    }
                    self.ticks_received.append(tick)
                    print(f"✓ Captured Tick #{len(self.ticks_received)}: Bid={tick['bid']} | Ask={tick['ask']}")
                    
                    if len(self.ticks_received) >= self.max_ticks:
                        self.finish()
            except Exception as e:
                print(f"Error extracting spot event: {e}")

        self.bot._handle_spot_event = custom_handle_spot

        self.bot.start()

        reactor.callLater(1, self._check_and_subscribe)
        reactor.callLater(self.timeout, self._timeout_check)

    def _check_and_subscribe(self):
        if self.subscribed_symbol or self.ticks_received:
            return

        if self.error_occurred == "CH_CTID_TRADER_ACCOUNT_NOT_FOUND":
            print("Account not found error detected. Stopping current run.")
            self.finish()
            return

        if not self.bot.is_account_authenticated:
            print("Waiting for account authentication...")
            reactor.callLater(1, self._check_and_subscribe)
            return

        if not self.bot.symbols:
            print("Waiting for symbols list...")
            reactor.callLater(1, self._check_and_subscribe)
            return

        print(f"✓ Account Authenticated. Total symbols loaded: {len(self.bot.symbols)}")
        matched_symbol = None
        for sym_name in self.bot.symbols.keys():
            if sym_name.upper() == self.target_symbol or self.target_symbol in sym_name.upper():
                matched_symbol = sym_name
                break

        if not matched_symbol:
            matching = [s for s in self.bot.symbols.keys() if 'XAU' in s.upper() or 'GOLD' in s.upper()]
            print(f"Symbol {self.target_symbol} not exact match. Matching gold symbols: {matching}")
            if matching:
                matched_symbol = matching[0]

        if not matched_symbol:
            print(f"Error: Symbol {self.target_symbol} not found in available symbols!")
            self.finish()
            return

        self.subscribed_symbol = matched_symbol
        print(f"Subscribing to spot ticks for {matched_symbol} (ID: {self.bot.get_symbol_id(matched_symbol)})...")
        res = self.bot.subscribe_to_ticks(matched_symbol)
        print(f"Subscription request sent: {res}")

    def _timeout_check(self):
        if len(self.ticks_received) < self.max_ticks:
            print(f"Reached timeout ({self.timeout}s). Stopping.")
            self.finish()

    def finish(self):
        print("\n=== FINAL TICK DATA RESULT ===")
        print(json.dumps(self.ticks_received, indent=2))
        print("==============================\n")
        self.bot.stop()

if __name__ == "__main__":
    # Test with demo host if environment HOST is set to demo or via arg
    host = sys.argv[1] if len(sys.argv) > 1 else os.getenv("HOST", "demo")
    print(f"Running TickFetcher on host: {host}")
    fetcher = TickFetcher("XAUUSD", host_override=host, max_ticks=3, timeout=35)
    fetcher.start()
    reactor.run()
