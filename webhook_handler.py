"""
Webhook Handler V3.0 - Receives signals from FREE Pine Script
===============================================================
Single unified webhook endpoint - no more GainzAlgo/LuxAlgo!
The Pine Script sends everything in one payload:
  - Signal (CALL/PUT)
  - Score + indicator count
  - OHLC data (for wick filter)
  - Order Block type (free SMC detection)
"""

import logging
import time
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

import config

logger = logging.getLogger(__name__)


class WebhookHandler:

    def __init__(self):
        self._signals: Dict[str, Dict[str, Any]] = {}
        self._last_signal_candle: Dict[str, str] = {}
        self._lock = asyncio.Lock()

    async def process_signal(self, data: dict) -> Optional[dict]:
        """
        Process a signal from the FREE ABOOD Pine Script V3.0.
        Expected payload:
        {
            "secret": "abood_v3_secret",
            "symbol": "EURUSD",
            "signal": "CALL" or "PUT",
            "price": 1.08500,
            "open": 1.08400,
            "high": 1.08600,
            "low": 1.08350,
            "close": 1.08500,
            "score": "4.2",
            "indicators": "4",
            "ob_type": "bullish" / "bearish" / "none"
        }
        """
        # Validate secret
        if data.get("secret") != config.WEBHOOK_SECRET:
            logger.warning("Webhook: invalid secret")
            return None

        symbol = self._normalize_symbol(data.get("symbol", ""))
        signal_type = data.get("signal", "").upper()
        price = float(data.get("price", 0))

        if symbol not in config.TRADING_PAIRS:
            logger.warning(f"Webhook: symbol {symbol} not in allowed pairs")
            return None
        if signal_type not in ("CALL", "PUT"):
            logger.warning(f"Webhook: invalid signal type: {signal_type}")
            return None

        now_utc = datetime.now(timezone.utc)
        candle_id = self._get_candle_id(now_utc)

        async with self._lock:
            if self._last_signal_candle.get(symbol) == candle_id:
                logger.info(f"Webhook: duplicate signal for {symbol} candle {candle_id}")
                return None

            remaining_seconds = self._seconds_until_candle_close(now_utc)

            # Extract OHLC for wick filter
            candle_data = None
            if all(k in data for k in ("open", "high", "low", "close")):
                candle_data = {
                    "open": float(data["open"]),
                    "high": float(data["high"]),
                    "low": float(data["low"]),
                    "close": float(data["close"]),
                }

            # Extract score and OB info
            score = float(data.get("score", 0))
            indicators = int(data.get("indicators", 0))
            ob_type = data.get("ob_type", "none").lower()

            signal_data = {
                "symbol": symbol,
                "signal": signal_type,
                "price": price,
                "received_at": now_utc,
                "received_ts": time.time(),
                "candle_id": candle_id,
                "remaining_seconds": remaining_seconds,
                "candle_data": candle_data,
                "score": score,
                "indicators": indicators,
                "ob_type": ob_type,
                "source": "tradingview",
            }

            self._signals[symbol] = signal_data

        logger.info(f"Signal received: {symbol} {signal_type} @ {price:.5f} "
                     f"score={score} ind={indicators} OB={ob_type} "
                     f"(candle {candle_id}, {remaining_seconds}s remaining)")

        return signal_data

    def register_internal_signal(self, signal_data: dict):
        """Register a signal from the internal scanner (backup)."""
        symbol = signal_data["symbol"]
        self._signals[symbol] = signal_data
        logger.info(f"Internal signal registered: {symbol} {signal_data['signal']}")

    def get_latest_signal(self, symbol: str) -> Optional[dict]:
        return self._signals.get(symbol)

    def mark_signal_used(self, symbol: str):
        candle_id = self._signals.get(symbol, {}).get("candle_id")
        if candle_id:
            self._last_signal_candle[symbol] = candle_id
        self._signals.pop(symbol, None)

    def clear_signal(self, symbol: str):
        self._signals.pop(symbol, None)

    @staticmethod
    def _normalize_symbol(raw: str) -> str:
        return raw.upper().replace("/", "").replace("_", "").replace("=X", "").strip()

    @staticmethod
    def _get_candle_id(dt: datetime) -> str:
        minute = (dt.minute // config.CANDLE_INTERVAL) * config.CANDLE_INTERVAL
        return f"{dt.strftime('%Y-%m-%d')}_{dt.hour:02d}:{minute:02d}"

    @staticmethod
    def _seconds_until_candle_close(now: datetime) -> int:
        interval = config.CANDLE_INTERVAL
        current_boundary = (now.minute // interval) * interval
        next_boundary_minute = current_boundary + interval
        if next_boundary_minute >= 60:
            next_close = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        else:
            next_close = now.replace(minute=next_boundary_minute, second=0, microsecond=0)
        remaining = (next_close - now).total_seconds()
        return max(0, int(remaining))
