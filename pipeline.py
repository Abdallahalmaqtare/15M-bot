"""
Signal Pipeline V3.0 - "القناص" Engine (FREE Edition)
=======================================================
Simplified pipeline - no external paid indicators needed!

Stage 1: Signal Detection (TradingView webhook OR internal scanner)
Stage 2: 120-Second Stability Rule
Stage 3: Wick Filter + OB Confirmation (from Pine Script data)
Stage 4: Candle Close Confirmation
Stage 5: Post-Trade Audit (15min + 1s)
"""

import logging
import time
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Tuple

import config
from webhook_handler import WebhookHandler
from database import save_pipeline_state, clear_pipeline_state

logger = logging.getLogger(__name__)


class SignalPipeline:

    STATE_DETECTED = "DETECTED"
    STATE_STABILITY_PASSED = "STABLE"
    STATE_FILTERED = "FILTERED"
    STATE_READY = "READY"
    STATE_CONFIRMED = "CONFIRMED"
    STATE_ACTIVE = "ACTIVE"
    STATE_COMPLETED = "COMPLETED"
    STATE_REJECTED = "REJECTED"

    def __init__(self, webhook_handler: WebhookHandler):
        self.wh = webhook_handler
        self._entries: Dict[str, dict] = {}
        self._lock = asyncio.Lock()

    # ----------------------------------------------------------
    # Stage 1: Detection
    # ----------------------------------------------------------

    async def on_signal_detected(self, signal_data: dict) -> dict:
        async with self._lock:
            symbol = signal_data["symbol"]

            existing = self._entries.get(symbol)
            if existing and existing["state"] not in (self.STATE_COMPLETED, self.STATE_REJECTED):
                return existing

            entry = {
                "symbol": symbol,
                "signal": signal_data["signal"],
                "price_at_detection": signal_data["price"],
                "detected_at": signal_data["received_at"],
                "detected_ts": signal_data["received_ts"],
                "candle_id": signal_data["candle_id"],
                "remaining_seconds": signal_data["remaining_seconds"],
                "candle_data": signal_data.get("candle_data"),
                "score": signal_data.get("score", 0),
                "indicators": signal_data.get("indicators", 0),
                "ob_type": signal_data.get("ob_type", "none"),
                "source": signal_data.get("source", "unknown"),
                "state": self.STATE_DETECTED,
                "stability_start_ts": time.time(),
                "entry_time": None,
                "entry_price": None,
                "entry_datetime": None,
                "expiry_datetime": None,
                "result": None,
                "signal_id": None,
            }

            self._entries[symbol] = entry

            save_pipeline_state(
                symbol=symbol, signal_type=signal_data["signal"],
                state=self.STATE_DETECTED,
                price_at_detection=signal_data["price"],
                detected_at=signal_data["received_at"].isoformat(),
            )

            logger.info(f"Pipeline Stage 1: {symbol} {signal_data['signal']} detected "
                         f"(score={signal_data.get('score', '?')}, "
                         f"OB={signal_data.get('ob_type', '?')}, "
                         f"source={signal_data.get('source', '?')})")

            return entry

    # ----------------------------------------------------------
    # Stage 2: 120-Second Stability
    # ----------------------------------------------------------

    async def check_stability(self, symbol: str) -> Tuple[bool, str]:
        async with self._lock:
            entry = self._entries.get(symbol)
            if not entry:
                return False, "No pipeline entry"
            if entry["state"] == self.STATE_REJECTED:
                return False, "Signal was rejected"

            latest_signal = self.wh.get_latest_signal(symbol)
            if latest_signal is None:
                entry["state"] = self.STATE_REJECTED
                clear_pipeline_state(symbol)
                return False, "Signal vanished (flicker)"

            if latest_signal["signal"] != entry["signal"]:
                entry["state"] = self.STATE_REJECTED
                clear_pipeline_state(symbol)
                return False, "Signal direction changed"

            elapsed = time.time() - entry["stability_start_ts"]
            if elapsed < config.STABILITY_WINDOW_SECONDS:
                return False, f"{config.STABILITY_WINDOW_SECONDS - elapsed:.0f}s remaining"

            entry["state"] = self.STATE_STABILITY_PASSED
            save_pipeline_state(symbol=symbol, signal_type=entry["signal"],
                                state=self.STATE_STABILITY_PASSED,
                                price_at_detection=entry["price_at_detection"])
            return True, "Stability confirmed"

    # ----------------------------------------------------------
    # Stage 3: Wick Filter + OB Confirmation
    # ----------------------------------------------------------

    async def check_filters(self, symbol: str) -> Tuple[bool, str]:
        """Combined wick filter + OB check."""
        async with self._lock:
            entry = self._entries.get(symbol)
            if not entry:
                return False, "No pipeline entry"

            # --- Wick Filter ---
            if config.WICK_FILTER_ENABLED:
                candle_data = entry.get("candle_data")
                if candle_data:
                    o = candle_data.get("open", 0)
                    h = candle_data.get("high", 0)
                    l = candle_data.get("low", 0)
                    c = candle_data.get("close", 0)
                    body = abs(c - o)

                    if body < 0.00001:
                        entry["state"] = self.STATE_REJECTED
                        clear_pipeline_state(symbol)
                        return False, "Doji candle"

                    if entry["signal"] == "CALL":
                        wick = min(o, c) - l
                    else:
                        wick = h - max(o, c)

                    ratio = wick / body if body > 0 else 999
                    if ratio > config.WICK_BODY_RATIO_MAX:
                        entry["state"] = self.STATE_REJECTED
                        clear_pipeline_state(symbol)
                        return False, f"Wick too long ({ratio:.2f})"

            # --- OB Confirmation ---
            ob_type = entry.get("ob_type", "none")
            if config.ENABLE_SMC_FILTER and ob_type != "none":
                if entry["signal"] == "CALL" and ob_type == "bearish":
                    entry["state"] = self.STATE_REJECTED
                    clear_pipeline_state(symbol)
                    return False, f"CALL conflicts with bearish OB"
                if entry["signal"] == "PUT" and ob_type == "bullish":
                    entry["state"] = self.STATE_REJECTED
                    clear_pipeline_state(symbol)
                    return False, f"PUT conflicts with bullish OB"

            entry["state"] = self.STATE_FILTERED
            return True, f"Filters passed (OB={ob_type})"

    # ----------------------------------------------------------
    # Mark READY
    # ----------------------------------------------------------

    async def mark_ready(self, symbol: str):
        async with self._lock:
            entry = self._entries.get(symbol)
            if entry:
                entry["state"] = self.STATE_READY
                save_pipeline_state(symbol=symbol, signal_type=entry["signal"],
                                    state=self.STATE_READY,
                                    price_at_detection=entry["price_at_detection"])

    # ----------------------------------------------------------
    # Stage 4: Candle Close Confirmation
    # ----------------------------------------------------------

    async def on_candle_close_confirmation(self, symbol: str, still_valid: bool,
                                            entry_price: float) -> Tuple[bool, str]:
        async with self._lock:
            entry = self._entries.get(symbol)
            if not entry:
                return False, "No pipeline entry"

            if not still_valid:
                entry["state"] = self.STATE_REJECTED
                clear_pipeline_state(symbol)
                return False, "Signal disappeared at candle close"

            now_utc = datetime.now(timezone.utc)
            entry_dt = now_utc.replace(second=0, microsecond=0)
            expiry_dt = entry_dt + timedelta(minutes=config.TRADE_DURATION)

            utc3 = timezone(timedelta(hours=config.UTC_OFFSET))
            entry_utc3 = entry_dt.astimezone(utc3)

            entry["state"] = self.STATE_CONFIRMED
            entry["entry_time"] = entry_utc3.strftime("%H:%M")
            entry["entry_datetime"] = entry_dt
            entry["entry_price"] = entry_price
            entry["expiry_datetime"] = expiry_dt

            save_pipeline_state(
                symbol=symbol, signal_type=entry["signal"],
                state=self.STATE_CONFIRMED,
                entry_time=entry["entry_time"],
                entry_price=entry_price,
                expiry_datetime=expiry_dt.isoformat(),
            )

            return True, f"Confirmed at {entry['entry_time']} (UTC+3)"

    # ----------------------------------------------------------
    # Stage 5: Resolve Trade
    # ----------------------------------------------------------

    async def resolve_trade(self, symbol: str, close_price: float) -> Optional[dict]:
        async with self._lock:
            entry = self._entries.get(symbol)
            if not entry:
                return None

            entry_price = entry["entry_price"]
            signal_type = entry["signal"]

            entry_rounded = round(entry_price, config.PRICE_PRECISION)
            close_rounded = round(close_price, config.PRICE_PRECISION)

            if signal_type == "CALL":
                result = "WIN" if close_rounded > entry_rounded else "LOSS"
            else:
                result = "WIN" if close_rounded < entry_rounded else "LOSS"

            entry["state"] = self.STATE_COMPLETED
            entry["close_price"] = close_price
            entry["result"] = result

            self.wh.mark_signal_used(symbol)
            clear_pipeline_state(symbol)

            return {
                "symbol": symbol,
                "signal": signal_type,
                "entry_time": entry["entry_time"],
                "entry_price": entry_price,
                "close_price": close_price,
                "result": result,
            }

    # ----------------------------------------------------------
    # Query Methods
    # ----------------------------------------------------------

    def get_entry(self, symbol: str) -> Optional[dict]:
        return self._entries.get(symbol)

    def get_active_entries(self) -> list:
        return [e for e in self._entries.values()
                if e["state"] not in (self.STATE_COMPLETED, self.STATE_REJECTED)]

    def has_active_trade(self, symbol: str = None) -> bool:
        active_count = 0
        for e in self._entries.values():
            if e["state"] in (self.STATE_CONFIRMED, self.STATE_ACTIVE):
                if config.ALLOW_MULTI_PAIR_TRADES:
                    if symbol and e["symbol"] == symbol:
                        return True
                    active_count += 1
                else:
                    return True
        return active_count >= config.MAX_CONCURRENT_TRADES

    async def mark_active(self, symbol: str):
        async with self._lock:
            entry = self._entries.get(symbol)
            if entry:
                entry["state"] = self.STATE_ACTIVE
                save_pipeline_state(
                    symbol=symbol, signal_type=entry["signal"],
                    state=self.STATE_ACTIVE,
                    entry_time=entry.get("entry_time"),
                    entry_price=entry.get("entry_price"),
                    expiry_datetime=entry["expiry_datetime"].isoformat() if entry.get("expiry_datetime") else None,
                    signal_id=entry.get("signal_id"),
                )

    def cleanup_completed(self):
        now = time.time()
        to_remove = [s for s, e in self._entries.items()
                     if e["state"] in (self.STATE_COMPLETED, self.STATE_REJECTED)
                     and now - e.get("detected_ts", now) > 1800]
        for s in to_remove:
            del self._entries[s]
            clear_pipeline_state(s)
