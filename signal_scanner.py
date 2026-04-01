"""
Internal Signal Scanner V3.0 - BACKUP Signal Generator
========================================================
🆓 100% FREE - Uses yfinance data + ta library
Runs as backup when TradingView webhooks are not available.
Includes built-in SMC Order Block detection!
"""

import logging
import time
import math
import pandas as pd
import numpy as np
import yfinance as yf
from ta.volatility import BollingerBands
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import EMAIndicator, ADXIndicator
from datetime import datetime, timedelta, timezone

import config

logger = logging.getLogger(__name__)


def _next_candle_time():
    now = datetime.now(timezone.utc)
    interval = config.CANDLE_INTERVAL
    next_boundary = (math.floor(now.minute / interval) + 1) * interval
    if next_boundary >= 60:
        entry_dt = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        entry_dt = now.replace(minute=next_boundary, second=0, microsecond=0)
    minutes_until = (entry_dt - now).total_seconds() / 60
    return entry_dt, minutes_until


class InternalScanner:
    """Backup scanner using free yfinance data."""

    def __init__(self):
        self.last_signal_times = {}

    def fetch_data(self, yf_symbol):
        for attempt in range(3):
            try:
                data = yf.download(yf_symbol, period="5d", interval=config.TIMEFRAME,
                                   progress=False, auto_adjust=False, threads=False)
                if data.empty:
                    raise ValueError(f"No data for {yf_symbol}")
                if isinstance(data.columns, pd.MultiIndex):
                    data.columns = data.columns.get_level_values(0)
                return data.copy()
            except Exception as e:
                logger.warning(f"Fetch attempt {attempt+1}/3 for {yf_symbol}: {e}")
                time.sleep(2)
        return None

    def add_indicators(self, df):
        close, high, low = df["Close"], df["High"], df["Low"]

        if config.ENABLE_BOLLINGER:
            bb = BollingerBands(close=close, window=config.BB_PERIOD, window_dev=config.BB_STD)
            df["BB_Upper"] = bb.bollinger_hband()
            df["BB_Lower"] = bb.bollinger_lband()

        if config.ENABLE_RSI:
            df["RSI"] = RSIIndicator(close=close, window=config.RSI_PERIOD).rsi()

        if config.ENABLE_EMA:
            df["EMA_Fast"] = EMAIndicator(close=close, window=config.EMA_FAST).ema_indicator()
            df["EMA_Slow"] = EMAIndicator(close=close, window=config.EMA_SLOW).ema_indicator()

        if config.ENABLE_STOCHASTIC:
            stoch = StochasticOscillator(high=high, low=low, close=close,
                                         window=config.STOCH_K, smooth_window=config.STOCH_SMOOTH)
            df["Stoch_K"] = stoch.stoch()
            df["Stoch_D"] = stoch.stoch_signal()

        if config.ENABLE_ADX:
            adx = ADXIndicator(high=high, low=low, close=close, window=config.ADX_PERIOD)
            df["ADX"] = adx.adx()
            df["DI_Plus"] = adx.adx_pos()
            df["DI_Minus"] = adx.adx_neg()

        if config.ENABLE_MOMENTUM:
            df["ROC"] = close.pct_change(3) * 100

        # ATR for OB detection
        tr = pd.concat([high - low,
                        (high - close.shift()).abs(),
                        (low - close.shift()).abs()], axis=1).max(axis=1)
        df["ATR"] = tr.rolling(14).mean()

        return df.dropna().copy()

    def detect_order_blocks(self, df):
        """FREE Order Block detection from price data."""
        if len(df) < config.OB_LOOKBACK + 5:
            return "none"

        curr = df.iloc[-2]
        atr = curr.get("ATR", 0)
        if atr <= 0:
            return "none"

        close_price = curr["Close"]

        # Look for recent Order Blocks
        for i in range(2, min(len(df) - 3, config.OB_LOOKBACK + 2)):
            candle = df.iloc[-i]
            next_candle = df.iloc[-i + 1]
            body = next_candle["Close"] - next_candle["Open"]

            # Bullish OB: bearish candle followed by strong bullish impulse
            if candle["Close"] < candle["Open"]:  # bearish candle
                if body > atr * config.OB_MIN_IMPULSE_ATR:  # strong bullish after
                    ob_high = candle["High"]
                    ob_low = candle["Low"]
                    if close_price >= ob_low - atr * config.OB_PROXIMITY_ATR and \
                       close_price <= ob_high + atr * config.OB_PROXIMITY_ATR:
                        return "bullish"

            # Bearish OB: bullish candle followed by strong bearish impulse
            if candle["Close"] > candle["Open"]:  # bullish candle
                if body < -atr * config.OB_MIN_IMPULSE_ATR:  # strong bearish after
                    ob_high = candle["High"]
                    ob_low = candle["Low"]
                    if close_price >= ob_low - atr * config.OB_PROXIMITY_ATR and \
                       close_price <= ob_high + atr * config.OB_PROXIMITY_ATR:
                        return "bearish"

        return "none"

    def evaluate(self, df, symbol):
        if len(df) < 12:
            return None

        curr = df.iloc[-2]
        prev = df.iloc[-3]

        call_score, put_score = 0.0, 0.0
        call_ind, put_ind = 0, 0

        # Bollinger
        if config.ENABLE_BOLLINGER and "BB_Lower" in df.columns:
            bb_w = curr["BB_Upper"] - curr["BB_Lower"]
            if bb_w > 0:
                if curr["Close"] <= curr["BB_Lower"]:
                    call_score += 1.2; call_ind += 1
                elif (curr["Close"] - curr["BB_Lower"]) / bb_w < 0.15:
                    call_score += 0.7; call_ind += 1
                if curr["Close"] >= curr["BB_Upper"]:
                    put_score += 1.2; put_ind += 1
                elif (curr["BB_Upper"] - curr["Close"]) / bb_w < 0.15:
                    put_score += 0.7; put_ind += 1

        # RSI
        if config.ENABLE_RSI and "RSI" in df.columns:
            rsi = curr["RSI"]
            if rsi <= config.RSI_OVERSOLD: call_score += 1.2; call_ind += 1
            elif rsi <= 38: call_score += 0.6; call_ind += 1
            if rsi >= config.RSI_OVERBOUGHT: put_score += 1.2; put_ind += 1
            elif rsi >= 62: put_score += 0.6; put_ind += 1

        # EMA
        if config.ENABLE_EMA and "EMA_Fast" in df.columns:
            if curr["EMA_Fast"] > curr["EMA_Slow"] and prev["EMA_Fast"] <= prev["EMA_Slow"]:
                call_score += 1.5; call_ind += 1
            elif curr["EMA_Fast"] > curr["EMA_Slow"]:
                call_score += 0.5; call_ind += 1
            if curr["EMA_Fast"] < curr["EMA_Slow"] and prev["EMA_Fast"] >= prev["EMA_Slow"]:
                put_score += 1.5; put_ind += 1
            elif curr["EMA_Fast"] < curr["EMA_Slow"]:
                put_score += 0.5; put_ind += 1

        # Stochastic
        if config.ENABLE_STOCHASTIC and "Stoch_K" in df.columns:
            sk, sd = curr["Stoch_K"], curr["Stoch_D"]
            if sk <= config.STOCH_OVERSOLD:
                if sk > sd: call_score += 1.2; call_ind += 1
                else: call_score += 0.6; call_ind += 1
            if sk >= config.STOCH_OVERBOUGHT:
                if sk < sd: put_score += 1.2; put_ind += 1
                else: put_score += 0.6; put_ind += 1

        # ADX
        if config.ENABLE_ADX and "ADX" in df.columns:
            if curr["ADX"] >= config.ADX_THRESHOLD:
                if curr["DI_Plus"] > curr["DI_Minus"]: call_score += 0.6; call_ind += 1
                else: put_score += 0.6; put_ind += 1

        # Candle patterns
        if config.ENABLE_CANDLE_PATTERNS:
            body_c = curr["Close"] - curr["Open"]
            body_p = prev["Close"] - prev["Open"]
            if body_p < 0 and body_c > 0 and abs(body_c) > abs(body_p) * 1.2:
                call_score += 0.8; call_ind += 1
            if body_p > 0 and body_c < 0 and abs(body_c) > abs(body_p) * 1.2:
                put_score += 0.8; put_ind += 1

        # Momentum
        if config.ENABLE_MOMENTUM and "ROC" in df.columns:
            roc = curr["ROC"]
            if roc > 0.08: call_score += 0.4; call_ind += 1
            if roc < -0.08: put_score += 0.4; put_ind += 1

        # SMC Order Block
        ob_type = "none"
        if config.ENABLE_SMC_FILTER:
            ob_type = self.detect_order_blocks(df)
            if ob_type == "bullish": call_score += 1.0; call_ind += 1
            elif ob_type == "bearish": put_score += 1.0; put_ind += 1

        # Filters
        if abs(call_score - put_score) < config.CONFLICT_THRESHOLD:
            return None

        # Wick filter
        if config.WICK_FILTER_ENABLED:
            body = abs(curr["Close"] - curr["Open"])
            if body > 0.00001:
                if call_score > put_score:
                    wick = min(curr["Open"], curr["Close"]) - curr["Low"]
                else:
                    wick = curr["High"] - max(curr["Open"], curr["Close"])
                if wick / body > config.WICK_BODY_RATIO_MAX:
                    return None

        now_utc = datetime.now(timezone.utc)
        candle_id = f"{now_utc.strftime('%Y-%m-%d')}_{now_utc.hour:02d}:{(now_utc.minute // 15) * 15:02d}"
        remaining = WebhookHandler._seconds_until_candle_close(now_utc) if hasattr(WebhookHandler, '_seconds_until_candle_close') else 0

        if call_score >= config.MIN_SIGNAL_SCORE and call_score > put_score and call_ind >= config.MIN_CONFIRMING_INDICATORS:
            return {
                "symbol": symbol, "signal": "CALL", "price": float(curr["Close"]),
                "received_at": now_utc, "received_ts": time.time(),
                "candle_id": candle_id, "remaining_seconds": remaining,
                "candle_data": {"open": float(curr["Open"]), "high": float(curr["High"]),
                                "low": float(curr["Low"]), "close": float(curr["Close"])},
                "score": round(call_score, 1), "indicators": call_ind,
                "ob_type": ob_type, "source": "internal_scanner",
            }
        elif put_score >= config.MIN_SIGNAL_SCORE and put_score > call_score and put_ind >= config.MIN_CONFIRMING_INDICATORS:
            return {
                "symbol": symbol, "signal": "PUT", "price": float(curr["Close"]),
                "received_at": now_utc, "received_ts": time.time(),
                "candle_id": candle_id, "remaining_seconds": remaining,
                "candle_data": {"open": float(curr["Open"]), "high": float(curr["High"]),
                                "low": float(curr["Low"]), "close": float(curr["Close"])},
                "score": round(put_score, 1), "indicators": put_ind,
                "ob_type": ob_type, "source": "internal_scanner",
            }

        return None

    def _is_on_cooldown(self, symbol):
        last = self.last_signal_times.get(symbol)
        if not last:
            return False
        return (datetime.now(timezone.utc) - last).total_seconds() / 60 < config.MIN_SIGNAL_INTERVAL

    def scan_all_pairs(self):
        _, minutes_until = _next_candle_time()
        if minutes_until > 6 or minutes_until < 2:
            return []

        signals = []
        for symbol in config.TRADING_PAIRS:
            if self._is_on_cooldown(symbol):
                continue
            try:
                yf_sym = config.YF_SYMBOL_MAP.get(symbol, f"{symbol}=X")
                df = self.fetch_data(yf_sym)
                if df is None or len(df) < 30:
                    continue
                df = self.add_indicators(df)
                signal = self.evaluate(df, symbol)
                if signal:
                    self.last_signal_times[symbol] = datetime.now(timezone.utc)
                    signals.append(signal)
            except Exception as e:
                logger.error(f"Scanner error {symbol}: {e}")
        return signals


# Import at module level for the candle ID helper
from webhook_handler import WebhookHandler
