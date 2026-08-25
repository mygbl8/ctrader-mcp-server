#!/usr/bin/env python3
import os
import sys
import json
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from ctrader_bot import SimpleCTraderBot
from ctrader_open_api import Protobuf
import ctrader_open_api.messages.OpenApiMessages_pb2 as oa_msg
import ctrader_open_api.messages.OpenApiModelMessages_pb2 as oa_model
from twisted.internet import reactor

class PositionMonitor:
    def __init__(self, target_position_id=234072036, symbol="XAUUSD"):
        os.environ['HOST'] = 'demo'
        self.bot = SimpleCTraderBot()
        self.target_position_id = target_position_id
        self.symbol = symbol
        self.result = {}

    def start(self):
        original_on_message = self.bot._on_message
        
        def custom_on_message(client, message):
            original_on_message(client, message)
            if self.bot.is_account_authenticated and not self.result:
                reactor.callLater(2, self.check_positions)

        self.bot._on_message = custom_on_message
        self.bot.start()
        reactor.callLater(25, self.finish)

    def check_positions(self):
        acc_status = self.bot.get_account_status()
        positions = self.bot.positions
        
        target_pos = next((p for p in positions if p['id'] == self.target_position_id), None)
        
        if not target_pos and len(positions) > 0:
            # Fallback to first open position if position ID changed
            target_pos = positions[0]

        if target_pos:
            entry_price = target_pos.get('entry_price', 0)
            side = target_pos.get('side', 'SELL')
            volume = target_pos.get('volume', 0.01)
            pnl = target_pos.get('pnl', 0.0)
            
            self.result = {
                "status": "OPEN",
                "position_id": target_pos['id'],
                "symbol": self.symbol,
                "side": side,
                "volume": volume,
                "entry_price": entry_price,
                "unrealized_pnl": round(pnl, 2),
                "account_balance": acc_status.get('balance', 0),
                "account_equity": acc_status.get('equity', 0),
                "account_margin": acc_status.get('margin', 0),
                "account_free_margin": acc_status.get('free_margin', 0),
                "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        else:
            self.result = {
                "status": "CLOSED_OR_NOT_FOUND",
                "position_id": self.target_position_id,
                "positions_count": len(positions),
                "account_balance": acc_status.get('balance', 0) if acc_status else 0,
                "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }

        print("\n=== HOURLY POSITION MONITORING RESULT ===")
        print(json.dumps(self.result, indent=2))
        print("=========================================\n")
        self.finish()

    def finish(self):
        self.bot.stop()

if __name__ == "__main__":
    pos_id = int(sys.argv[1]) if len(sys.argv) > 1 else 234072036
    monitor = PositionMonitor(target_position_id=pos_id)
    monitor.start()
    reactor.run()
