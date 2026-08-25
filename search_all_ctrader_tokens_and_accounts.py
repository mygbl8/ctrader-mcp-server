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

class FullAccountAndPositionInspector:
    def __init__(self, host_mode='demo'):
        os.environ['HOST'] = host_mode
        self.host_mode = host_mode
        self.bot = SimpleCTraderBot()

    def start(self):
        orig_on_msg = self.bot._on_message
        
        def custom_on_message(client, message):
            orig_on_msg(client, message)
            
            if message.payloadType == oa_msg.ProtoOAAccountAuthRes().payloadType:
                req = oa_msg.ProtoOAReconcileReq()
                req.ctidTraderAccountId = self.bot.account_id
                self.bot.client.send(req)
                
            if message.payloadType == oa_msg.ProtoOAReconcileRes().payloadType:
                res = Protobuf.extract(message)
                positions = getattr(res, 'position', [])
                print(f"\n================ FULL INSPECTOR ({self.host_mode.upper()} - Account {self.bot.account_id}) ================")
                print(f"Total Open Positions Returned by cTrader API: {len(positions)}")
                for p in positions:
                    print(f"  • Position ID: {p.positionId} | Symbol ID: {p.tradeData.symbolId} | Side: {p.tradeData.tradeSide} | Volume: {p.tradeData.volume} | Entry: {p.price}")
                print("========================================================================================\n")
                reactor.callLater(1, self.finish)

        self.bot._on_message = custom_on_message
        self.bot.start()
        reactor.callLater(10, self.finish)

    def finish(self):
        self.bot.stop()

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "demo"
    inspector = FullAccountAndPositionInspector(host_mode=mode)
    inspector.start()
    reactor.run()
