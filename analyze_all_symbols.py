#!/usr/bin/env python3
import os
import sys
import json
import urllib.request
import numpy as np
import pandas as pd
from datetime import datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from ctrader_bot import SimpleCTraderBot
from twisted.internet import reactor

def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def calc_sma(series, period):
    return series.rolling(period).mean()

def calc_wma(series, period):
    weights = np.arange(1, period + 1)
    return series.rolling(period).apply(lambda np_slice: np.dot(np_slice, weights) / weights.sum(), raw=True)

def calc_vwma(price_series, vol_series, period):
    pv = price_series * vol_series
    sum_pv = pv.rolling(period).sum()
    sum_v = vol_series.rolling(period).sum()
    vwma = np.where(sum_v > 0, sum_pv / sum_v, calc_sma(price_series, period))
    return pd.Series(vwma, index=price_series.index)

def calc_rsi(series, period):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)

def calc_mfi(high, low, close, volume, period=10):
    typical_price = (high + low + close) / 3.0
    money_flow = typical_price * volume
    positive_flow = np.where(typical_price > typical_price.shift(1), money_flow, 0)
    negative_flow = np.where(typical_price < typical_price.shift(1), money_flow, 0)
    
    pos_mf = pd.Series(positive_flow, index=close.index).rolling(period).sum()
    neg_mf = pd.Series(negative_flow, index=close.index).rolling(period).sum()
    
    mfr = pos_mf / neg_mf.replace(0, np.nan)
    mfi = 100 - (100 / (1 + mfr))
    return mfi.fillna(50)

def calc_atr(high, low, close, period=14):
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def calc_adx(high, low, close, period=14):
    up = high - high.shift(1)
    down = low.shift(1) - low
    plus_dm = np.where((up > down) & (up > 0), up, 0)
    minus_dm = np.where((down > up) & (down > 0), down, 0)
    
    tr = calc_atr(high, low, close, 1)
    tr_sum = tr.rolling(period).sum()
    
    plus_di = 100 * (pd.Series(plus_dm, index=close.index).rolling(period).sum() / tr_sum)
    minus_di = 100 * (pd.Series(minus_dm, index=close.index).rolling(period).sum() / tr_sum)
    
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.rolling(period).mean()
    return adx.fillna(0)

TARGET_SYMBOLS = ["XAUUSD", "PAXGUSD", "PAXUSD", "GoldIndex", "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD"]

class MultiSymbolBenMasAnalyzer:
    def __init__(self, symbols=None):
        os.environ['HOST'] = 'demo'
        self.bot = SimpleCTraderBot()
        self.symbols = symbols or TARGET_SYMBOLS
        self.current_symbol_idx = 0
        self.results = {}

    def start(self):
        original_on_message = self.bot._on_message
        
        def custom_on_message(client, message):
            original_on_message(client, message)
            if self.bot.is_account_authenticated and not hasattr(self, 'started_fetch'):
                self.started_fetch = True
                reactor.callLater(1, self.fetch_next_symbol)

        self.bot._on_message = custom_on_message
        self.bot.start()
        reactor.callLater(60, self.finish)

    def fetch_next_symbol(self):
        if self.current_symbol_idx >= len(self.symbols):
            print("\n✓ Finished fetching all symbols!")
            self.generate_report()
            return

        symbol = self.symbols[self.current_symbol_idx]
        if not self.bot.symbols:
            print("Waiting for symbols catalog...")
            reactor.callLater(1, self.fetch_next_symbol)
            return

        print(f"[{self.current_symbol_idx+1}/{len(self.symbols)}] Requesting data for {symbol}...")
        self.bot.get_historical_data(symbol, timeframe="H1", count=150)
        self.bot.get_historical_data(symbol, timeframe="H4", count=100)
        reactor.callLater(3, self.process_symbol, symbol)

    def process_symbol(self, symbol):
        df_h1 = self.bot.historical_data.get(f"{symbol}_H1")
        df_h4 = self.bot.historical_data.get(f"{symbol}_H4")

        if df_h1 is not None and df_h4 is not None and not df_h1.empty and not df_h4.empty:
            res = self.analyze_single(symbol, df_h1, df_h4)
            self.results[symbol] = res
            print(f"✓ Processed {symbol}: Trend={res['htf_4h_trend']}, Score={res['six_veins_score']}/6")
        else:
            print(f"⚠️ Warning: Could not retrieve data for {symbol}")

        self.current_symbol_idx += 1
        reactor.callLater(1, self.fetch_next_symbol)

    def analyze_single(self, symbol, df, df4):
        ha_close = (df['open'] + df['high'] + df['low'] + df['close']) / 4.0
        ha_open = np.zeros(len(df))
        ha_open[0] = (df['open'].iloc[0] + df['close'].iloc[0]) / 2.0
        for i in range(1, len(df)):
            ha_open[i] = (ha_open[i-1] + ha_close.iloc[i-1]) / 2.0
        ha_open = pd.Series(ha_open, index=df.index)

        hlc3 = (df['high'] + df['low'] + df['close']) / 3.0
        vol = df['volume']
        
        fast_ma = calc_vwma(df['close'], vol, 13)
        mid_ma  = calc_vwma(df['close'], vol, 34)
        slow_ma = calc_vwma(hlc3, vol, 89)

        hlc3_4h = (df4['high'] + df4['low'] + df4['close']) / 3.0
        slow_ma_4h = calc_vwma(hlc3_4h, df4['volume'], 89)
        htf_close_latest = df4['close'].iloc[-1]
        htf_slow_ma_latest = slow_ma_4h.iloc[-1]
        htf_bull = htf_close_latest > htf_slow_ma_latest

        diff = calc_ema(ha_close, 6) - calc_ema(ha_close, 13)
        dea = calc_ema(diff, 5)
        s1 = (diff > dea).astype(int)

        llv8 = df['low'].rolling(8).min()
        hhv8 = df['high'].rolling(8).max()
        rsv = np.where(hhv8 - llv8 == 0, 50, (ha_close - llv8) / (hhv8 - llv8) * 100)
        rsv = pd.Series(rsv, index=df.index)
        k = calc_sma(rsv, 3)
        d = calc_sma(k, 3)
        s2 = (k > d).astype(int)

        rsi5 = calc_rsi(ha_close, 5)
        rsi13 = calc_rsi(ha_close, 13)
        s3 = (rsi5 > rsi13).astype(int)

        hhv13 = df['high'].rolling(13).max()
        llv13 = df['low'].rolling(13).min()
        lwr_rsv = np.where(hhv13 - llv13 == 0, 0, -(hhv13 - ha_close) / (hhv13 - llv13) * 100)
        lwr1 = calc_sma(pd.Series(lwr_rsv, index=df.index), 3)
        lwr2 = calc_sma(lwr1, 3)
        s4 = (lwr1 > lwr2).astype(int)

        bbi = (calc_sma(ha_close, 3) + calc_sma(ha_close, 6) + calc_sma(ha_close, 12) + calc_sma(ha_close, 24)) / 4.0
        s5 = (ha_close > bbi).astype(int)

        mtm = ha_close - ha_close.shift(12)
        mtmma = calc_sma(mtm, 6)
        s6 = (mtm > mtmma).astype(int)

        bull_score = s1 + s2 + s3 + s4 + s5 + s6

        mfi10 = calc_mfi(df['high'], df['low'], ha_close, vol, 10)
        val_banker = np.maximum(0, np.minimum(20, (mfi10 - 20) * 0.2))
        val_retail = np.maximum(0, 20 - val_banker)

        adx_val = calc_adx(df['high'], df['low'], df['close'], 14)
        atr_val = calc_atr(df['high'], df['low'], df['close'], 14)
        raw_tm = calc_rsi(df['close'], 14)

        idx = -1
        curr_price = float(df['close'].iloc[idx])
        curr_score = int(bull_score.iloc[idx])
        curr_atr = float(atr_val.iloc[idx])
        curr_fast_ma = float(fast_ma.iloc[idx])
        curr_mid_ma = float(mid_ma.iloc[idx])
        curr_banker = float(val_banker.iloc[idx])
        curr_retail = float(val_retail.iloc[idx])
        curr_adx = float(adx_val.iloc[idx])

        # Overextension & Pullback Detection
        dist_from_mid = abs(curr_price - curr_mid_ma)
        is_overextended = bool(dist_from_mid > (curr_atr * 1.8) or (raw_tm.iloc[idx] > 70 if htf_bull else raw_tm.iloc[idx] < 30))

        bullish_pullback = bool(
            (df['low'].iloc[idx] <= curr_fast_ma or df['low'].iloc[idx-1] <= fast_ma.iloc[idx-1]) and
            (curr_price >= curr_mid_ma - (curr_atr * 0.3)) and
            (raw_tm.iloc[idx] <= 68) and
            (ha_close.iloc[idx] > ha_open.iloc[idx])
        )

        bearish_pullback = bool(
            (df['high'].iloc[idx] >= curr_fast_ma or df['high'].iloc[idx-1] >= fast_ma.iloc[idx-1]) and
            (curr_price <= curr_mid_ma + (curr_atr * 0.3)) and
            (raw_tm.iloc[idx] >= 32) and
            (ha_close.iloc[idx] < ha_open.iloc[idx])
        )

        if htf_bull and curr_score >= 4 and curr_banker >= 10 and bullish_pullback and not is_overextended:
            signal_status = "🟢 OPTIMAL BUY (Pullback)"
        elif not htf_bull and curr_score <= 2 and curr_retail >= 10 and bearish_pullback and not is_overextended:
            signal_status = "🔴 OPTIMAL SELL (Pullback)"
        elif is_overextended:
            signal_status = "⚠️ OVEREXTENDED (Wait for Dip)"
        else:
            signal_status = "⏳ WAITING SETUP"

        return {
            "symbol": symbol,
            "current_price": round(curr_price, 4),
            "htf_4h_trend": "BULLISH 🟢" if htf_bull else "BEARISH 🔴",
            "six_veins_score": int(curr_score),
            "mcdx_banker": round(curr_banker, 1),
            "signal_status": signal_status,
            "adx_volatility": round(curr_adx, 2),
            "atr": round(curr_atr, 4)
        }

    def generate_report(self):
        print("\n================ MULTI-SYMBOL BENMAS DIGEST ================")
        print(json.dumps(self.results, indent=2))
        print("============================================================\n")

        lines = ["📊 *Multi-Symbol High-WinRate Strategy Scan*\n"]
        for sym, data in self.results.items():
            lines.append(f"• *{sym}*: `{data['current_price']}` | {data['signal_status']} | Score: `{data['six_veins_score']}/6` | Banker: `{data['mcdx_banker']}`")

        msg = "\n".join(lines)
        
        # Send Telegram notification
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "8738012570:AAGqsOVWsM2rwdBPniRNNo0mNpm5UNTUtMQ")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "203001100")
        
        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            data = json.dumps({"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"}).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req) as resp:
                print("✓ Multi-symbol report delivered to Telegram!")
        except Exception as e:
            print(f"Failed to send Telegram report: {e}")

        self.finish()

    def finish(self):
        self.bot.stop()

if __name__ == "__main__":
    analyzer = MultiSymbolBenMasAnalyzer()
    analyzer.start()
    reactor.run()
