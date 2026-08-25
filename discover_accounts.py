#!/usr/bin/env python3
import os
import sys
import json

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from ctrader_bot import SimpleCTraderBot
from ctrader_open_api import Protobuf
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAGetAccountListByAccessTokenReq,
    ProtoOAGetAccountListByAccessTokenRes,
    ProtoOAErrorRes
)
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import ProtoErrorRes
from twisted.internet import reactor

class AccountDiscoverer:
    def __init__(self, host_type="live"):
        os.environ['HOST'] = host_type
        self.bot = SimpleCTraderBot()
        self.host_type = host_type
        self.accounts = []

    def start(self):
        original_on_message = self.bot._on_message
        
        def custom_on_message(client, message):
            if message.payloadType == ProtoOAGetAccountListByAccessTokenRes().payloadType:
                res = Protobuf.extract(message)
                for acc in res.ctidTraderAccount:
                    acc_info = {
                        'ctidTraderAccountId': acc.ctidTraderAccountId,
                        'isLive': getattr(acc, 'isLive', None),
                        'traderAccountId': getattr(acc, 'traderAccountId', None),
                        'accountNumber': getattr(acc, 'accountNumber', None)
                    }
                    self.accounts.append(acc_info)
                print(f"✓ Discovered accounts on {self.host_type}: {json.dumps(self.accounts, indent=2)}")
                self.finish()
            elif message.payloadType == ProtoOAErrorRes().payloadType:
                err = Protobuf.extract(message)
                print(f"✗ ProtoOAErrorRes: errorCode={getattr(err, 'errorCode', '')}, description={getattr(err, 'description', '')}")
                self.finish()
            elif message.payloadType == ProtoErrorRes().payloadType:
                err = Protobuf.extract(message)
                print(f"✗ ProtoErrorRes: errorCode={getattr(err, 'errorCode', '')}, description={getattr(err, 'description', '')}")
                self.finish()
            else:
                original_on_message(client, message)

        self.bot._on_message = custom_on_message

        # Override _authenticate_account to request account list instead
        def custom_authenticate_account():
            req = ProtoOAGetAccountListByAccessTokenReq()
            req.accessToken = self.bot.access_token
            deferred = self.bot.client.send(req)
            deferred.addErrback(self.bot._on_error)
            print(f"Requesting account list for access token on {self.host_type}...")

        self.bot._authenticate_account = custom_authenticate_account
        self.bot.start()
        reactor.callLater(15, self.finish)

    def finish(self):
        self.bot.stop()

if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else "live"
    discoverer = AccountDiscoverer(host)
    discoverer.start()
    reactor.run()
