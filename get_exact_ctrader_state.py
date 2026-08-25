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

class ExactStateFetcher:
    def __init__(self):
        os.environ['HOST'] = 'demo'
        self.bot = SimpleCTraderBot()
        self.bot.account_id = 48034167

    def start(self):
        orig_on_msg = self.bot._on_message
        
        def custom_on_message(client, message):
            orig_on_msg(client, message)
            
            if message.payloadType == oa_msg.ProtoOAAccountAuthRes().payloadType:
                req = oa_msg.ProtoOATraderReq()
                req.ctidTraderAccountId = 48034167
                self.bot.client.send(req)
                
            if message.payloadType == oa_msg.ProtoOATraderRes().payloadType:
                res = Protobuf.extract(message)
                t = res.trader
                balance = t.balance / 100.0
                leverage = int(t.leverageInCents / 100)
                
                print("\n================ EXACT CTRADER OPEN API STATE ================")
                print(f"Account ID: {48034167} (Trader Login: {t.traderLogin})")
                print(f"Balance: ${balance:,.2f}")
                print(f"Leverage: 1:{leverage}")
                print(f"Total Open Positions: {len(self.bot.positions)}")
                for pos in self.bot.positions:
                    sym_name = next((s['name'] for s in self.bot.symbols.values() if s['id'] == pos['symbol_id']), 'Unknown')
                    print(f"  • Position #{pos['id']}: {sym_name} {pos['side']} {pos['volume']} units @ {pos['entry_price']} | Net PnL: ${pos['pnl']}")
                print("===============================================================\n")
                reactor.callLater(1, self.finish)

        self.bot._on_message = custom_on_message
        self.bot.start()
        reactor.callLater(12, self.finish)

    def finish(self):
        self.bot.stop()

if __name__ == "__main__":
    fetcher = ExactStateFetcher()
    fetcher.start()
    reactor.run()
