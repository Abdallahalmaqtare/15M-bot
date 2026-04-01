"""
Precision Timer V2.0 - Zero Latency Scheduler (Improved)
==========================================================
Ensures all time-critical events fire at the EXACT second.
Improvements: Better error handling, graceful shutdown.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Callable, Optional

import config

logger = logging.getLogger(__name__)

UTC3 = timezone(timedelta(hours=config.UTC_OFFSET))


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_utc3() -> datetime:
    return datetime.now(UTC3)


def utc_to_utc3(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(UTC3)


def utc_to_utc3_str(dt: datetime) -> str:
    return utc_to_utc3(dt).strftime("%H:%M")


def next_candle_boundary() -> datetime:
    now = now_utc()
    interval = config.CANDLE_INTERVAL
    current_boundary = (now.minute // interval) * interval
    next_min = current_boundary + interval

    if next_min >= 60:
        boundary = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        boundary = now.replace(minute=next_min, second=0, microsecond=0)

    return boundary


def seconds_until(target: datetime) -> float:
    delta = (target - now_utc()).total_seconds()
    return max(0.0, delta)


def seconds_until_candle_close() -> float:
    return seconds_until(next_candle_boundary())


class PrecisionTimer:
    def __init__(self):
        self._tasks: dict = {}
        self._running = True

    async def schedule_at(self, target_dt: datetime, callback, *args,
                          task_id: str = None, label: str = ""):
        delay = seconds_until(target_dt)
        if delay <= 0:
            logger.warning(f"PrecisionTimer: target already passed for {label}")
            try:
                await callback(*args)
            except Exception as e:
                logger.error(f"PrecisionTimer callback error [{label}]: {e}")
            return

        task_id = task_id or f"task_{time.time()}"

        async def _precise_wait_and_fire():
            try:
                if delay > 0.5:
                    await asyncio.sleep(delay - 0.1)

                while now_utc() < target_dt:
                    await asyncio.sleep(0.01)

                target_utc3 = utc_to_utc3(target_dt).strftime("%H:%M:%S")
                actual_utc3 = now_utc3().strftime("%H:%M:%S")
                logger.info(f"PrecisionTimer FIRE [{label}]: target={target_utc3} actual={actual_utc3}")

                await callback(*args)

            except asyncio.CancelledError:
                logger.info(f"PrecisionTimer: task {task_id} cancelled")
            except Exception as e:
                logger.error(f"PrecisionTimer error [{label}]: {e}", exc_info=True)
            finally:
                self._tasks.pop(task_id, None)

        task = asyncio.ensure_future(_precise_wait_and_fire())
        self._tasks[task_id] = task
        target_str = utc_to_utc3(target_dt).strftime("%H:%M:%S")
        logger.info(f"PrecisionTimer: scheduled [{label}] at {target_str} (UTC+3) in {delay:.1f}s")

    async def schedule_after(self, delay_seconds: float, callback, *args,
                              task_id: str = None, label: str = ""):
        target = now_utc() + timedelta(seconds=delay_seconds)
        await self.schedule_at(target, callback, *args, task_id=task_id, label=label)

    async def schedule_stability_check(self, symbol: str, callback, *args):
        await self.schedule_after(
            config.STABILITY_WINDOW_SECONDS,
            callback, *args,
            task_id=f"stability_{symbol}",
            label=f"120s Stability Check - {symbol}",
        )

    async def schedule_candle_close_confirmation(self, symbol: str, callback, *args):
        target = next_candle_boundary()
        await self.schedule_at(
            target, callback, *args,
            task_id=f"confirm_{symbol}",
            label=f"Candle Close Confirm - {symbol}",
        )

    async def schedule_result_check(self, symbol: str, expiry_dt: datetime, callback, *args):
        target = expiry_dt + timedelta(seconds=config.RESULT_CHECK_DELAY_SECONDS)
        await self.schedule_at(
            target, callback, *args,
            task_id=f"result_{symbol}",
            label=f"Result Check - {symbol}",
        )

    def cancel(self, task_id: str):
        task = self._tasks.pop(task_id, None)
        if task and not task.done():
            task.cancel()
            logger.info(f"PrecisionTimer: cancelled {task_id}")

    def cancel_all_for_symbol(self, symbol: str):
        to_cancel = [k for k in self._tasks if symbol in k]
        for k in to_cancel:
            self.cancel(k)

    def shutdown(self):
        self._running = False
        for task_id in list(self._tasks.keys()):
            self.cancel(task_id)
