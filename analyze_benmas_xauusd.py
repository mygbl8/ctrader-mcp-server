#!/usr/bin/env python3
import os
import sys
import json
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

def calc_hma(series, period):
    half_length = int(period / 2)
    sqrt_length = int(np.sqrt(period))
    wma_half = calc_wma(series, half_length)
    wma_full = calc_wma(series, period)
    diff = 2 * wma_half - wma_full
    return calc_wma(diff, sqrt_length)

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

def calc_chop_index(high, low, close, period=14):
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    
    atr_sum = tr.rolling(period).sum()
    range_span = (high.rolling(period).max() - low.rolling(period).min()).replace(0, np.nan)
    chop = 100 * np.log10(atr_sum / range_span) / np.log10(period)
    return chop.fillna(50)

def is_in_bb_squeeze(close, period=20, mult=2.0):
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = sma + (std * mult)
    lower = sma - (std * mult)
    bb_width = (upper - lower) / sma * 100
    bb_width_ma = bb_width.rolling(20).mean()
    return bool(bb_width.iloc[-1] < bb_width_ma.iloc[-1])

def is_crypto_or_perp(symbol):
    """
    Checks if a symbol is a Cryptocurrency or Perpetual contract.
    Crypto/Perps trade 24/7/365 without weekend market closures.
    """
    s = str(symbol).upper()
    crypto_keys = [
        'BTC', 'ETH', 'SOL', 'XRP', 'DOGE', 'ADA', 'BNB', 'AVAX', 'LINK', 
        'DOT', 'LTC', 'MATIC', 'NEAR', 'SHIB', 'UNI', 'ATOM', 'USDT', 
        'PERP', 'CRYPTO', 'XLM', 'TRX', 'BCH', 'FIL', 'APT', 'SUI'
    ]
    return any(k in s for k in crypto_keys)

def is_trading_holiday(symbol, dt=None):
    """
    Checks if given UTC datetime is a market trading holiday for the asset.
    - Crypto/Perp: 24/7 continuous trading (No holiday closures).
    - Traditional (Forex, Metals, Indices): Checks New Year, Good Friday, Easter Monday, Memorial Day, July 4, Labor Day, Thanksgiving, Christmas.
    """
    if is_crypto_or_perp(symbol):
        return False, None
    if dt is None:
        dt = datetime.now(timezone.utc)
    
    month, day, weekday, year = dt.month, dt.day, dt.weekday(), dt.year
    
    # Jan 1 (New Year)
    if month == 1 and (day == 1 or (day == 2 and weekday == 0)):
        return True, "New Year's Day"
    # Dec 25 (Christmas)
    if month == 12 and (day == 25 or (day == 26 and weekday in (0, 1))):
        return True, "Christmas Day"
    # July 4 (US Independence Day)
    if month == 7 and (day == 4 or (day == 5 and weekday == 0) or (day == 3 and weekday == 4)):
        return True, "US Independence Day"
    
    # Computus Easter / Good Friday
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    easter_m = (h + l - 7 * m + 114) // 31
    easter_d = ((h + l - 7 * m + 114) % 31) + 1
    easter_date = datetime(year, easter_m, easter_d, tzinfo=timezone.utc)
    
    good_friday = easter_date - timedelta(days=2)
    if month == good_friday.month and day == good_friday.day:
        return True, "Good Friday"
        
    return False, None

def check_trading_session(symbol="XAUUSD"):
    """
    Evaluates trading session allowances based on asset class:
    - Crypto & Perps: 24/7 active trading. (No weekend/holiday closures)
    - Traditional Assets (FX, Metals, Indices):
        1. Trading Holidays (Global / Bank Holidays) - closed
        2. Friday Late Night (> 19:00 UTC) - wide spreads, book squaring
        3. Weekend (Saturday & Sunday) - closed / gap risk
        4. Monday Morning Asian Session (< 08:00 UTC) - low volume, fakeouts
    """
    if is_crypto_or_perp(symbol):
        return True, "CRYPTO/PERPETUAL: 24/7 continuous market open."

    now_utc = datetime.now(timezone.utc) if hasattr(datetime, 'now') else datetime.utcnow()
    weekday = now_utc.weekday()  # 0=Mon, 4=Fri, 5=Sat, 6=Sun
    hour = now_utc.hour
    
    is_holiday, holiday_name = is_trading_holiday(symbol, now_utc)
    if is_holiday:
        return False, f"TRADING HOLIDAY: {holiday_name}. Market closed. No trading."
    
    if weekday in (5, 6):
        return False, "TRADITIONAL ASSET WEEKEND: Market closed."
    if weekday == 4 and hour >= 19:
        return False, "FRIDAY LATE NIGHT: Low liquidity & gap protection active."
    if weekday == 0 and hour < 8:
        return False, "MONDAY ASIAN SESSION: Awaiting London Open liquidity."
    return True, "ACTIVE TRADING SESSION: Normal execution permitted."

def calc_daily_benchmarks(df_h1):
    """
    Extracts Previous Day High (PDH), Previous Day Low (PDL), Previous Day Close (PDC),
    and Today's Open from hourly trendbars.
    Determines the daily open regime (Above PDH, Inside Range, Below PDL).
    """
    try:
        if not isinstance(df_h1.index, pd.DatetimeIndex):
            df_copy = df_h1.copy()
            df_copy.index = pd.to_datetime(df_copy.index)
        else:
            df_copy = df_h1

        df_daily = df_copy.resample('D').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last'
        }).dropna()

        if len(df_daily) >= 2:
            yesterday = df_daily.iloc[-2]
            today = df_daily.iloc[-1]

            pdh = float(yesterday['high'])
            pdl = float(yesterday['low'])
            pdc = float(yesterday['close'])
            today_open = float(today['open'])
            curr_price = float(df_h1['close'].iloc[-1])

            if today_open > pdh:
                open_regime = "BULLISH_EXPANSION_ABOVE_PDH"
                bias = "HEAVY_BULLISH"
            elif today_open < pdl:
                open_regime = "BEARISH_EXPANSION_BELOW_PDL"
                bias = "HEAVY_BEARISH"
            else:
                open_regime = "INSIDE_YESTERDAY_RANGE"
                bias = "NEUTRAL_RANGE"

            price_vs_open = "ABOVE_TODAY_OPEN" if curr_price >= today_open else "BELOW_TODAY_OPEN"

            return {
                "pdh": round(pdh, 2),
                "pdl": round(pdl, 2),
                "pdc": round(pdc, 2),
                "today_open": round(today_open, 2),
                "open_regime": open_regime,
                "daily_bias": bias,
                "price_vs_open": price_vs_open
            }
    except Exception:
        pass

    # Fallback to rolling 24-bar window if resample fails
    curr_price = float(df_h1['close'].iloc[-1])
    bars_24 = df_h1.iloc[-48:-24] if len(df_h1) >= 48 else df_h1.iloc[:-1]
    pdh = float(bars_24['high'].max())
    pdl = float(bars_24['low'].min())
    pdc = float(bars_24['close'].iloc[-1])
    today_open = float(df_h1['open'].iloc[-24]) if len(df_h1) >= 24 else float(df_h1['open'].iloc[0])

    if today_open > pdh:
        open_regime = "BULLISH_EXPANSION_ABOVE_PDH"
        bias = "HEAVY_BULLISH"
    elif today_open < pdl:
        open_regime = "BEARISH_EXPANSION_BELOW_PDL"
        bias = "HEAVY_BEARISH"
    else:
        open_regime = "INSIDE_YESTERDAY_RANGE"
        bias = "NEUTRAL_RANGE"

    return {
        "pdh": round(pdh, 2),
        "pdl": round(pdl, 2),
        "pdc": round(pdc, 2),
        "today_open": round(today_open, 2),
        "open_regime": open_regime,
        "daily_bias": bias,
        "price_vs_open": "ABOVE_TODAY_OPEN" if curr_price >= today_open else "BELOW_TODAY_OPEN"
    }

class BenMasAnalyzer:
    def __init__(self, symbol="XAUUSD"):
        os.environ['HOST'] = 'demo'
        self.bot = SimpleCTraderBot()
        self.symbol = symbol
        self.df_h1 = None
        self.df_h4 = None
        self.data_requested = False
        self.analysis_res = {}

    def start(self):
        original_on_message = self.bot._on_message
        
        def custom_on_message(client, message):
            original_on_message(client, message)
            if self.bot.is_account_authenticated and not self.data_requested:
                self.data_requested = True
                reactor.callLater(1, self.check_and_fetch)

        self.bot._on_message = custom_on_message
        self.bot.start()
        reactor.callLater(35, self.finish)

    def check_and_fetch(self):
        if not self.bot.symbols:
            print("Waiting for symbols list before requesting trendbars...")
            reactor.callLater(1, self.check_and_fetch)
            return

        print(f"✓ Symbols loaded ({len(self.bot.symbols)}). Requesting historical data for {self.symbol}...")
        self.bot.get_historical_data(self.symbol, timeframe="H1", count=150)
        self.bot.get_historical_data(self.symbol, timeframe="H4", count=100)
        reactor.callLater(3, self.check_and_run)

    def check_and_run(self):
        self.df_h1 = self.bot.historical_data.get(f"{self.symbol}_H1")
        self.df_h4 = self.bot.historical_data.get(f"{self.symbol}_H4")
        
        if self.df_h1 is None or self.df_h4 is None or self.df_h1.empty or self.df_h4.empty:
            print("Waiting for historical trendbars cache...")
            reactor.callLater(2, self.check_and_run)
            return
        
        self.run_analysis()

    def run_analysis(self):
        df = self.df_h1.copy()
        df4 = self.df_h4.copy()

        # Calculate Heikin-Ashi
        ha_close = (df['open'] + df['high'] + df['low'] + df['close']) / 4.0
        ha_open = np.zeros(len(df))
        ha_open[0] = (df['open'].iloc[0] + df['close'].iloc[0]) / 2.0
        for i in range(1, len(df)):
            ha_open[i] = (ha_open[i-1] + ha_close.iloc[i-1]) / 2.0
        ha_open = pd.Series(ha_open, index=df.index)

        # 1. 3-MA Engine (VWMA 13, 34, HLC3 89)
        hlc3 = (df['high'] + df['low'] + df['close']) / 3.0
        vol = df['volume']
        
        fast_ma = calc_vwma(df['close'], vol, 13)
        mid_ma  = calc_vwma(df['close'], vol, 34)
        slow_ma = calc_vwma(hlc3, vol, 89)

        # HTF 4H 89-VWMA calculation
        hlc3_4h = (df4['high'] + df4['low'] + df4['close']) / 3.0
        slow_ma_4h = calc_vwma(hlc3_4h, df4['volume'], 89)
        htf_close_latest = df4['close'].iloc[-1]
        htf_slow_ma_latest = slow_ma_4h.iloc[-1]
        htf_bull = htf_close_latest > htf_slow_ma_latest

        # 2. Six Vein Calculations
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

        # 3. MCDX Calculations
        mfi10 = calc_mfi(df['high'], df['low'], ha_close, vol, 10)
        val_banker = np.maximum(0, np.minimum(20, (mfi10 - 20) * 0.2))
        val_hot = np.maximum(0, np.minimum(20, (mfi10 - 20) * 0.4))
        val_retail = np.maximum(0, 20 - val_banker - val_hot)

        val_banker = pd.Series(val_banker, index=df.index)
        val_retail = pd.Series(val_retail, index=df.index)

        # 4. Indicators & Smart Filters
        adx_val = calc_adx(df['high'], df['low'], df['close'], 14)
        atr_val = calc_atr(df['high'], df['low'], df['close'], 14)

        raw_tm = calc_rsi(df['close'], 14)
        tm_val = calc_wma(raw_tm, 5)
        tm_buy = tm_val > tm_val.shift(1)

        # Latest Bar Values
        idx = -1
        curr_price = float(df['close'].iloc[idx])
        curr_fast_ma = float(fast_ma.iloc[idx])
        curr_mid_ma = float(mid_ma.iloc[idx])
        curr_slow_ma = float(slow_ma.iloc[idx])

        fast_up = bool(curr_fast_ma > fast_ma.iloc[idx-1])
        mid_up = bool(curr_mid_ma > mid_ma.iloc[idx-1])
        slow_up = bool(curr_slow_ma > slow_ma.iloc[idx-1])

        fast_dn = bool(curr_fast_ma < fast_ma.iloc[idx-1])
        mid_dn = bool(curr_mid_ma < mid_ma.iloc[idx-1])
        slow_dn = bool(curr_slow_ma < slow_ma.iloc[idx-1])

        curr_atr = float(atr_val.iloc[idx])
        curr_adx = float(adx_val.iloc[idx])
        prev_adx = float(adx_val.iloc[idx-1])

        curr_banker = float(val_banker.iloc[idx])
        curr_retail = float(val_retail.iloc[idx])
        banker_rising = bool(curr_banker > val_banker.iloc[idx-1])
        retail_rising = bool(curr_retail > val_retail.iloc[idx-1])
        curr_score = int(bull_score.iloc[idx])

        ma_bull_align = bool((curr_fast_ma > curr_mid_ma > curr_slow_ma) and fast_up and mid_up and slow_up)
        ma_bear_align = bool((curr_fast_ma < curr_mid_ma < curr_slow_ma) and fast_dn and mid_dn and slow_dn)

        # Volatility, Chop & Regime Checks
        is_crypto = is_crypto_or_perp(self.symbol)
        chop_val = calc_chop_index(df['high'], df['low'], df['close'], 14)
        bb_squeeze = is_in_bb_squeeze(df['close'], 20, 2.0)
        session_ok, session_msg = check_trading_session(self.symbol)
        curr_chop = float(chop_val.iloc[idx])
        adx_rising = bool(curr_adx > prev_adx and curr_adx >= 20)
        is_consolidating = bool((curr_chop > 58.0) or bb_squeeze or (not adx_rising))

        # Daily Benchmark Guide (Today's Open vs Yesterday's High & Low)
        daily_bench = calc_daily_benchmarks(df)
        pdh = daily_bench.get('pdh', curr_price)
        pdl = daily_bench.get('pdl', curr_price)
        today_open = daily_bench.get('today_open', curr_price)
        open_regime = daily_bench.get('open_regime', 'INSIDE_YESTERDAY_RANGE')
        daily_bias = daily_bench.get('daily_bias', 'NEUTRAL_RANGE')
        price_vs_open = daily_bench.get('price_vs_open', 'ABOVE_TODAY_OPEN')

        # Overextension Guard & Pullback Value Zone Engine (Protects Against Peak-Buying)
        dist_from_mid_ma = abs(curr_price - curr_mid_ma)
        dist_from_fast_ma = abs(curr_price - curr_fast_ma)
        not_overextended = bool(dist_from_mid_ma <= (curr_atr * 1.8) and (raw_tm.iloc[idx] <= 70 if htf_bull else raw_tm.iloc[idx] >= 30))

        # Value Zone: Price retracing into the 13-34 VWMA corridor
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

        # High-Conviction Signal Checks (Score >= 4/6 and MCDX >= 10 for 85% win rate targeting)
        tb_raw = bool(
            htf_bull and 
            ma_bull_align and 
            (curr_banker >= 10) and 
            banker_rising and 
            (curr_score >= 4) and 
            tm_buy.iloc[idx] and 
            (curr_adx > 20) and 
            not_overextended and 
            bullish_pullback
        )

        ts_raw = bool(
            (not htf_bull) and 
            ma_bear_align and 
            (curr_retail >= 10) and 
            retail_rising and 
            (curr_score <= 2) and 
            (not tm_buy.iloc[idx]) and 
            (curr_adx > 20) and 
            not_overextended and 
            bearish_pullback
        )

        # Daily Benchmark Filter
        if open_regime == "BULLISH_EXPANSION_ABOVE_PDH" and curr_price >= pdh:
            ts_raw = False
        elif open_regime == "BEARISH_EXPANSION_BELOW_PDL" and curr_price <= pdl:
            tb_raw = False

        filtered_tb = bool(tb_raw and session_ok and (not is_consolidating))
        filtered_ts = bool(ts_raw and session_ok and (not is_consolidating))

        sl_dist = curr_atr * 1.5
        tp_dist = curr_atr * 3.0

        is_bear_setup = ma_bear_align or (not htf_bull)
        proj_sl = curr_price + sl_dist if is_bear_setup else curr_price - sl_dist
        proj_tp = curr_price - tp_dist if is_bear_setup else curr_price + tp_dist

        self.analysis_res = {
            "symbol": self.symbol,
            "asset_class": "CRYPTO / PERPETUAL (24/7)" if is_crypto else "TRADITIONAL (FX / COMMODITY / INDEX)",
            "timestamp": str(df.index[-1]),
            "current_price": round(curr_price, 2),
            "daily_benchmarks": {
                "pdh_yesterday_high": pdh,
                "pdl_yesterday_low": pdl,
                "today_open_price": today_open,
                "daily_open_regime": open_regime,
                "daily_bias": daily_bias,
                "intraday_state": price_vs_open
            },
            "session_allowed": session_ok,
            "session_status": session_msg,
            "market_regime": "CONSOLIDATION / CHOP" if is_consolidating else "TRENDING",
            "choppiness_index": round(curr_chop, 2),
            "bb_squeeze": bb_squeeze,
            "htf_4h_trend": "BULLISH" if htf_bull else "BEARISH",
            "htf_4h_close": round(htf_close_latest, 2),
            "htf_4h_89vwma": round(htf_slow_ma_latest, 2),
            "3ma_alignment": "BULLISH" if ma_bull_align else ("BEARISH" if ma_bear_align else "MIXED/CONSOLIDATING"),
            "fast_ma_13": round(curr_fast_ma, 2),
            "mid_ma_34": round(curr_mid_ma, 2),
            "slow_ma_89": round(curr_slow_ma, 2),
            "six_veins_score": int(curr_score),
            "vein_s1_macd": int(s1.iloc[idx]),
            "vein_s2_kdj": int(s2.iloc[idx]),
            "vein_s3_rsi": int(s3.iloc[idx]),
            "vein_s4_lwr": int(s4.iloc[idx]),
            "vein_s5_bbi": int(s5.iloc[idx]),
            "vein_s6_mtm": int(s6.iloc[idx]),
            "mcdx_banker_red": round(curr_banker, 2),
            "mcdx_retail_green": round(curr_retail, 2),
            "adx_volatility": round(curr_adx, 2),
            "volatility_ok": bool(curr_adx > 20),
            "atr_14": round(curr_atr, 2),
            "dist_from_fast_ma": round(dist_from_ma, 2),
            "rubber_band_ok": bool(not_overextended),
            "tm_momentum": "UP" if tm_buy.iloc[idx] else "DOWN",
            "raw_tb_signal": bool(tb_raw),
            "raw_ts_signal": bool(ts_raw),
            "filtered_tb_signal": bool(filtered_tb),
            "filtered_ts_signal": bool(filtered_ts),
            "projected_sl": round(proj_sl, 2),
            "projected_tp": round(proj_tp, 2),
            "sl_pips": round(sl_dist * 10, 1),
            "tp_pips": round(tp_dist * 10, 1)
        }

        print("\n=== BENMAS TREND FINDER V2 - XAUUSD ANALYSIS ===")
        print(json.dumps(self.analysis_res, indent=2))
        print("=================================================\n")
        self.finish()

    def finish(self):
        self.bot.stop()

if __name__ == "__main__":
    target_symbol = sys.argv[1].upper() if len(sys.argv) > 1 else "XAUUSD"
    analyzer = BenMasAnalyzer(target_symbol)
    analyzer.start()
    reactor.run()
