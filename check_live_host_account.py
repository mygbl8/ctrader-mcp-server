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

class LiveHostAccountChecker:
    def __init__(self):
        os.environ['HOST'] = 'live'
        self.bot = SimpleCTraderBot()

    def start(self):
        orig_on_msg = self.bot._on_message
        
        def custom_on_message(client, message):
            orig_on_msg(client, message)
            
            if self.bot.is_app_authenticated:
                req = oa_msg.ProtoOAGetAccountListByAccessTokenReq()
                req.accessToken = self.bot.access_token
                self.bot.client.send(req)
                
            if message.payloadType == oa_msg.ProtoOAGetAccountListByAccessTokenRes().payloadType:
                res = Protobuf.extract(message)
                print("\n================ LIVE HOST CTRADER ACCOUNTS ================")
                for acc in res.ctidTraderAccount:
                    print(f"• Account ID: {acc.ctidTraderAccountId} | Live/Demo: {'LIVE' if acc.isLive else 'DEMO'} | Trader: {acc.traderLogin}")
                print("============================================================\n")
                reactor.callLater(1, self.finish)

        self.bot._on_message = custom_on_message
        self.bot.start()
        reactor.callLater(12, self.finish)

    def finish(self):
        self.bot.stop()

if __name__ == "__main__":
    checker = LiveHostAccountChecker()
    checker.start()
    reactor.run()
