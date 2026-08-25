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

class LivePositionsAndBalanceFetcher:
    def __init__ (self):
        os.environ['HOST'] = 'demo'
        self.bot = SimpleCTraderBot()
        self.result_data = {}

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
                t = res.trader
                balance = t.balance / 100.0
                leverage = int(t.leverageInCents / 100)
                
                # Fetch positions
                positions_list = []
                for p in self.bot.positions:
                    positions_list.append({
                        "position_id": p['id'],
                        "symbol_id": p['symbol_id'],
                        "volume": p['volume'],
                        "side": p['side'],
                        "entry_price": p['entry_price'],
                        "pnl": p.get('pnl', 0.0),
                        "swap": p.get('swap', 0.0),
                        "commission": p.get('commission', 0.0)
                    })

                self.result_data = {
                    "account_id": self.bot.account_id,
                    "balance": balance,
                    "leverage": f"1:{leverage}",
                    "positions_count": len(positions_list),
                    "positions": positions_list
                }

                print("\n================ REAL CTRADER ACCOUNT STATE ================")
                print(json.dumps(self.result_data, indent=2))
                print("============================================================\n")
                reactor.callLater(1, self.finish)

        self.bot._on_message = custom_on_message
        self.bot.start()
        reactor.callLater(12, self.finish)

    def finish(self):
        self.bot.stop()

if __name__ == "__main__":
    fetcher = LivePositionsAndBalanceFetcher()
    fetcher.start()
    reactor.run()
