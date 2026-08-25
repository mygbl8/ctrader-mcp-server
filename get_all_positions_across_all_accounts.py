#!/usr/bin/env python3
import os
import sys
import json

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv('c:/Users/benjaminnlow/OneDrive/AI Trader/aibot.env')

from ctrader_bot import SimpleCTraderBot
from ctrader_open_api import Protobuf
import ctrader_open_api.messages.OpenApiMessages_pb2 as oa_msg
from twisted.internet import reactor

class ComprehensivePositionScanner:
    def __init__(self, host_mode='demo'):
        os.environ['HOST'] = host_mode
        self.host_mode = host_mode
        self.bot = SimpleCTraderBot()

    def start(self):
        orig_on_msg = self.bot._on_message
        
        def custom_on_message(client, message):
            orig_on_msg(client, message)
            
            if self.bot.is_account_authenticated:
                print(f"\n=== SCANNING {self.host_mode.upper()} SERVER (Account ID: {self.bot.account_id}) ===")
                print(f"Total Positions Detected: {len(self.bot.positions)}")
                for pos in self.bot.positions:
                    sym_name = next((s['name'] for s in self.bot.symbols.values() if s['id'] == pos['symbol_id']), str(pos['symbol_id']))
                    print(f"  • Position ID: {pos['id']} | Symbol: {sym_name} | Side: {pos['side']} | Volume: {pos['volume']} | Price: {pos['entry_price']} | PnL: ${pos.get('pnl', 0.0)}")
                print("========================================================================\n")
                reactor.callLater(1, self.finish)

        self.bot._on_message = custom_on_message
        self.bot.start()
        reactor.callLater(10, self.finish)

    def finish(self):
        self.bot.stop()

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "demo"
    scanner = ComprehensivePositionScanner(host_mode=mode)
    scanner.start()
    reactor.run()
