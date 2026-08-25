#!/usr/bin/env python3
import os
import sys
import json
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(dotenv_path='c:/Users/benjaminnlow/OneDrive/AI Trader/aibot.env')

from ctrader_bot import SimpleCTraderBot
from ctrader_open_api import Protobuf
import ctrader_open_api.messages.OpenApiMessages_pb2 as oa_msg
from twisted.internet import reactor

class RealAccountFetcher:
    def __init__(self):
        os.environ['HOST'] = 'demo'
        self.bot = SimpleCTraderBot()

    def start(self):
        orig_on_msg = self.bot._on_message
        
        def custom_on_message(client, message):
            orig_on_msg(client, message)
            
            # Catch ProtoOATraderRes
            if message.payloadType == oa_msg.ProtoOATraderRes().payloadType:
                res = Protobuf.extract(message)
                trader = res.trader
                balance = trader.balance / 100.0
                print(f"\nREAL CTRADER BALANCE: ${balance:,.2f}")
                print(f"ACCOUNT ID: {trader.ctidTraderAccountId}")
                print(f"DEPOSIT ASSET ID: {trader.depositAssetId}")
                reactor.callLater(1, self.finish)

            if self.bot.is_account_authenticated:
                # Send ProtoOATraderReq
                req = oa_msg.ProtoOATraderReq()
                req.ctidTraderAccountId = self.bot.account_id
                self.bot.client.send(req)

        self.bot._on_message = custom_on_message
        self.bot.start()
        reactor.callLater(10, self.finish)

    def finish(self):
        self.bot.stop()

if __name__ == "__main__":
    fetcher = RealAccountFetcher()
    fetcher.start()
    reactor.run()
