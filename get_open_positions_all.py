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

class LiveAccountPositionsInspector:
    def __init__(self, acc_id=5316354):
        self.bot = SimpleCTraderBot()
        self.bot.account_id = acc_id
        self.account_info = {}

    def start(self):
        orig_on_msg = self.bot._on_message
        
        def custom_on_message(client, message):
            orig_on_msg(client, message)
            
            if message.payloadType == oa_msg.ProtoOAAccountAuthRes().payloadType:
                req = oa_msg.ProtoOATraderReq()
                req.ctidTraderAccountId = self.bot.account_id
                self.bot.client.send(req)
                
            if message.payloadType == oa_msg.ProtoOATraderRes().payloadType:
                res = Protobuf.extract(message)
                trader = res.trader
                balance = trader.balance / 100.0
                print(f"\n=== LIVE CTRADER ACCOUNT {self.bot.account_id} ===")
                print(f"Balance: ${balance:,.2f}")
                print(f"Open Positions: {len(self.bot.positions)}")
                for pos in self.bot.positions:
                    print(f"  - Pos #{pos['id']}: {pos['side']} {pos['volume']} units | Entry: {pos['entry_price']} | PnL: ${pos['pnl']}")
                print("==============================================\n")
                reactor.callLater(1, self.finish)

        self.bot._on_message = custom_on_message
        self.bot.start()
        reactor.callLater(10, self.finish)

    def finish(self):
        self.bot.stop()

if __name__ == "__main__":
    acc = int(sys.argv[1]) if len(sys.argv) > 1 else 5316354
    inspector = LiveAccountPositionsInspector(acc_id=acc)
    inspector.start()
    reactor.run()
