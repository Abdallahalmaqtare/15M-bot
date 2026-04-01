#!/usr/bin/env python3
"""
ABOOD "القناص" V3.0 - FREE Edition Main Bot
==============================================
🆓 100% FREE - No paid indicators needed!

Signal Sources:
  1. TradingView Plus Webhook (PRIMARY) - Free Pine Script
  2. Internal Scanner (BACKUP) - yfinance + ta library

Pipeline:
  Stage 1: Detection → Stage 2: 120s Stability → Stage 3: Filters
  Stage 4: Candle Close Confirm → Stage 5: Result (15min + 1s)

Hosting: Render.com (free tier with keep-alive)
"""

import asyncio
import logging
import sys
import os
import threading
import time
import httpx
import uvicorn
from fastapi import FastAPI, Request, HTTPException
from datetime import datetime, timedelta, timezone
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes

sys.path.insert(0, os.path.dirname(__file__))

import config
from database import (
    init_db, save_signal, get_daily_stats, get_pair_stats,
    get_overall_stats, get_recent_signals, cleanup_old_data,
    update_signal_result, update_daily_stats, get_pending_signals,
    get_weekly_stats, get_monthly_stats, log_health_event,
)
from webhook_handler import WebhookHandler
from pipeline import SignalPipeline
from signal_scanner import InternalScanner
from precision_timer import (
    PrecisionTimer, now_utc, now_utc3, utc_to_utc3_str,
    next_candle_boundary, seconds_until_candle_close, UTC3,
)
from result_tracker import ResultTracker
from message_formatter import (
    format_pre_alert, format_execution, format_result,
    format_startup_message, format_stats_message, format_overall_stats,
    format_daily_report, format_weekly_report, format_health_status,
    format_system_alert,
)

# ============================================================
# LOGGING
# ============================================================
os.makedirs(os.path.join(os.path.dirname(__file__), "logs"), exist_ok=True)
logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler(os.path.join(os.path.dirname(__file__), "logs", "bot.log")),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# ============================================================
# CORE COMPONENTS
# ============================================================
webhook_handler = WebhookHandler()
pipeline = SignalPipeline(webhook_handler)
timer = PrecisionTimer()
result_tracker = ResultTracker()
scanner = InternalScanner()

app = FastAPI(title=f"ABOOD القناص {config.BOT_VERSION}")
telegram_application = None


# ============================================================
# TELEGRAM SEND (with retry)
# ============================================================

async def _send(text: str):
    if not telegram_application:
        return False
    chat_id = config.TELEGRAM_CHAT_ID
    if not chat_id:
        return False

    for attempt in range(config.TELEGRAM_RETRY_ATTEMPTS):
        try:
            await telegram_application.bot.send_message(chat_id=chat_id, text=text)
            logger.info(f"Telegram sent ({len(text)} chars)")
            return True
        except Exception as e:
            logger.error(f"Telegram attempt {attempt+1}/{config.TELEGRAM_RETRY_ATTEMPTS}: {e}")
            if attempt < config.TELEGRAM_RETRY_ATTEMPTS - 1:
                await asyncio.sleep(config.TELEGRAM_RETRY_DELAY)

    log_health_event("TELEGRAM_FAILURE", "Message send failed")
    return False


# ============================================================
# TRADING HOURS
# ============================================================

def is_trading_hours() -> bool:
    now = now_utc()
    if config.ENABLE_TRADING_DAYS and now.weekday() not in config.TRADING_DAYS:
        return False
    if config.ENABLE_TRADING_HOURS:
        if not (config.TRADING_START_HOUR_UTC <= now.hour < config.TRADING_END_HOUR_UTC):
            return False
    return True


# ============================================================
# KEEP-ALIVE (Render.com free tier)
# ============================================================

async def keep_alive(context: ContextTypes.DEFAULT_TYPE):
    url = config.RENDER_EXTERNAL_URL or f"http://localhost:{config.PORT}"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.get(f"{url}/")
    except Exception:
        pass


# ============================================================
# FASTAPI ENDPOINTS
# ============================================================

@app.get("/")
async def health():
    return {
        "status": "ok",
        "bot": f"ABOOD القناص {config.BOT_VERSION} (FREE)",
        "active": len(pipeline.get_active_entries()),
        "time_utc3": now_utc3().strftime("%H:%M:%S"),
    }


@app.post("/webhook")
async def webhook_endpoint(request: Request):
    """
    Unified webhook endpoint for FREE Pine Script.
    Just ONE endpoint - no more separate GainzAlgo/LuxAlgo!
    """
    try:
        data = await request.json()
        logger.info(f"Webhook received: {data}")

        if not is_trading_hours():
            return {"status": "skipped", "reason": "Outside trading hours"}

        symbol = WebhookHandler._normalize_symbol(data.get("symbol", ""))
        if pipeline.has_active_trade(symbol=symbol):
            return {"status": "skipped", "reason": f"Active trade for {symbol}"}

        signal_data = await webhook_handler.process_signal(data)
        if signal_data is None:
            return {"status": "rejected", "reason": "Invalid signal"}

        # Start pipeline
        entry = await pipeline.on_signal_detected(signal_data)

        await timer.schedule_stability_check(
            signal_data["symbol"],
            _on_stability_complete,
            signal_data["symbol"],
        )

        return {
            "status": "accepted",
            "symbol": signal_data["symbol"],
            "signal": signal_data["signal"],
            "score": signal_data.get("score"),
        }

    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


# ============================================================
# INTERNAL SCANNER (BACKUP)
# ============================================================

async def run_internal_scanner(context: ContextTypes.DEFAULT_TYPE):
    """Backup: scan pairs using yfinance if no webhook received."""
    if not config.ENABLE_INTERNAL_SCANNER:
        return
    if not is_trading_hours():
        return

    try:
        signals = scanner.scan_all_pairs()
        for sig in signals:
            symbol = sig["symbol"]

            if pipeline.has_active_trade(symbol=symbol):
                continue

            # Check if we already have a signal from TradingView for this pair
            existing = webhook_handler.get_latest_signal(symbol)
            if existing and existing.get("source") == "tradingview":
                continue  # TradingView signal takes priority

            logger.info(f"Internal scanner signal: {symbol} {sig['signal']} "
                         f"score={sig['score']} OB={sig['ob_type']}")

            # Register and start pipeline
            webhook_handler.register_internal_signal(sig)
            entry = await pipeline.on_signal_detected(sig)

            await timer.schedule_stability_check(
                symbol, _on_stability_complete, symbol,
            )

    except Exception as e:
        logger.error(f"Internal scanner error: {e}", exc_info=True)


# ============================================================
# PIPELINE CALLBACKS
# ============================================================

async def _on_stability_complete(symbol: str):
    logger.info(f"Stage 2 check: {symbol}")

    passed, reason = await pipeline.check_stability(symbol)
    if not passed:
        logger.info(f"Stage 2 FAIL {symbol}: {reason}")
        webhook_handler.clear_signal(symbol)
        return
    logger.info(f"Stage 2 PASS {symbol}: {reason}")

    # Stage 3: Filters (wick + OB)
    filter_passed, filter_reason = await pipeline.check_filters(symbol)
    if not filter_passed:
        logger.info(f"Stage 3 FAIL {symbol}: {filter_reason}")
        webhook_handler.clear_signal(symbol)
        return
    logger.info(f"Stage 3 PASS {symbol}: {filter_reason}")

    # Ready! Send pre-alert
    await pipeline.mark_ready(symbol)
    await _send_pre_alert(symbol)

    # Schedule candle close confirmation
    await timer.schedule_candle_close_confirmation(
        symbol, _on_candle_close, symbol,
    )


async def _send_pre_alert(symbol: str):
    entry = pipeline.get_entry(symbol)
    if not entry:
        return

    next_boundary = next_candle_boundary()
    entry_time_utc3 = utc_to_utc3_str(next_boundary)
    remaining_min = max(1, int(seconds_until_candle_close() / 60))

    stats = get_daily_stats()
    pair_stats = get_pair_stats(symbol)

    source = entry.get("source", "unknown")
    source_tag = "📡 TradingView" if source == "tradingview" else "🔍 Scanner"

    message = format_pre_alert(
        symbol=symbol, signal_type=entry["signal"],
        entry_time_utc3=entry_time_utc3, remaining_minutes=remaining_min,
        wins=stats["wins"], losses=stats["losses"],
        pair_wins=pair_stats["wins"], pair_losses=pair_stats["losses"],
    )
    message += f"\n\n{source_tag} | Score: {entry.get('score', '?')} | OB: {entry.get('ob_type', 'none')}"

    await _send(message)


async def _on_candle_close(symbol: str):
    logger.info(f"Stage 4: {symbol}")

    entry = pipeline.get_entry(symbol)
    if not entry or entry["state"] == pipeline.STATE_REJECTED:
        return

    latest = webhook_handler.get_latest_signal(symbol)
    still_valid = (latest is not None and latest["signal"] == entry["signal"])

    entry_price = result_tracker.get_current_price(symbol)
    if entry_price is None:
        await asyncio.sleep(1)
        entry_price = result_tracker.get_current_price(symbol)

    if entry_price is None:
        logger.error(f"Stage 4: No price for {symbol}")
        await _send(format_system_alert("warning", f"⚠️ لم يتم الحصول على سعر {symbol}"))
        return

    confirmed, reason = await pipeline.on_candle_close_confirmation(symbol, still_valid, entry_price)
    if not confirmed:
        logger.info(f"Stage 4 FAIL {symbol}: {reason}")
        return

    entry = pipeline.get_entry(symbol)
    signal_id = save_signal(
        symbol=symbol, signal_type=entry["signal"],
        entry_time=entry["entry_time"], entry_datetime=entry["entry_datetime"],
        expiry_datetime=entry["expiry_datetime"], entry_price=entry_price,
        score=entry.get("score", 0), reasons=f"Source: {entry.get('source', '?')}",
    )
    entry["signal_id"] = signal_id

    await pipeline.mark_active(symbol)

    exec_msg = format_execution(symbol=symbol, signal_type=entry["signal"],
                                 entry_time_utc3=entry["entry_time"])
    await _send(exec_msg)

    await timer.schedule_result_check(
        symbol, entry["expiry_datetime"], _on_result_check, symbol,
    )


async def _on_result_check(symbol: str):
    logger.info(f"Stage 5: {symbol}")

    entry = pipeline.get_entry(symbol)
    if not entry:
        return

    close_price = result_tracker.get_current_price(symbol)
    if close_price is None:
        await asyncio.sleep(3)
        close_price = result_tracker.get_current_price(symbol)
    if close_price is None:
        await asyncio.sleep(5)
        close_price = result_tracker.get_current_price(symbol)

    if close_price is None:
        logger.error(f"Stage 5: No close price for {symbol}")
        return

    result_data = await pipeline.resolve_trade(symbol, close_price)
    if result_data is None:
        return

    signal_id = entry.get("signal_id")
    if signal_id:
        update_signal_result(signal_id, close_price, result_data["result"])
        update_daily_stats(symbol)

    result_msg = format_result(symbol=symbol, entry_time_utc3=entry["entry_time"],
                                result=result_data["result"])
    await _send(result_msg)


# ============================================================
# FALLBACK RESULT CHECKER
# ============================================================

async def check_pending_results(context: ContextTypes.DEFAULT_TYPE):
    try:
        resolved = result_tracker.check_and_resolve_pending()
        for r in resolved:
            msg = format_result(symbol=r["symbol"], entry_time_utc3=r.get("entry_time", "??:??"),
                                 result=r["result"])
            await _send(msg)
        pipeline.cleanup_completed()
    except Exception as e:
        logger.error(f"Fallback check error: {e}")


# ============================================================
# AUTO REPORTS
# ============================================================

async def send_daily_report(context: ContextTypes.DEFAULT_TYPE):
    if not config.ENABLE_DAILY_REPORT:
        return
    try:
        now = now_utc3()
        if now.hour != config.DAILY_REPORT_HOUR_UTC3:
            return
        stats = get_daily_stats()
        if stats["wins"] + stats["losses"] == 0:
            return
        await _send(format_daily_report(stats))
    except Exception as e:
        logger.error(f"Daily report error: {e}")


async def send_weekly_report(context: ContextTypes.DEFAULT_TYPE):
    if not config.ENABLE_WEEKLY_REPORT:
        return
    try:
        now = now_utc3()
        if now.weekday() != config.WEEKLY_REPORT_DAY or now.hour != config.DAILY_REPORT_HOUR_UTC3:
            return
        stats = get_weekly_stats()
        if stats["total"] == 0:
            return
        await _send(format_weekly_report(stats))
    except Exception as e:
        logger.error(f"Weekly report error: {e}")


# ============================================================
# HEALTH CHECK
# ============================================================

async def check_health(context: ContextTypes.DEFAULT_TYPE):
    try:
        health = result_tracker.get_health_status()
        if health["status"] == "degraded":
            await _send(format_system_alert("critical",
                        f"🚨 Yahoo Finance: {health['consecutive_failures']} فشل متتالي"))

        now = now_utc()
        if now.weekday() == 6 and now.hour == 0:
            cleanup_old_data(days=30)
    except Exception as e:
        logger.error(f"Health check error: {e}")


# ============================================================
# CRASH RECOVERY
# ============================================================

async def recover_from_crash():
    try:
        pending = get_pending_signals()
        now = datetime.now(timezone.utc)
        recovered = 0

        for sig in pending:
            expiry_dt = datetime.fromisoformat(sig["expiry_datetime"])
            if expiry_dt.tzinfo is None:
                expiry_dt = expiry_dt.replace(tzinfo=timezone.utc)

            if now < expiry_dt:
                await timer.schedule_result_check(
                    sig["symbol"], expiry_dt,
                    _on_recovery_result, sig["symbol"], sig["id"],
                    sig["entry_price"], sig["signal_type"], sig["entry_time"],
                )
                recovered += 1
            else:
                close_price = result_tracker.get_price_at_time(sig["symbol"], sig["expiry_datetime"])
                if close_price:
                    entry_price = round(float(sig["entry_price"]), config.PRICE_PRECISION)
                    result = "WIN" if (sig["signal_type"] == "CALL" and close_price > entry_price) or \
                                      (sig["signal_type"] == "PUT" and close_price < entry_price) else "LOSS"
                    update_signal_result(sig["id"], close_price, result)
                    update_daily_stats(sig["symbol"])

        if recovered > 0:
            await _send(format_system_alert("info", f"♻️ تم استرداد {recovered} صفقة بعد إعادة التشغيل"))

    except Exception as e:
        logger.error(f"Recovery error: {e}", exc_info=True)


async def _on_recovery_result(symbol, signal_id, entry_price, signal_type, entry_time):
    close_price = result_tracker.get_current_price(symbol)
    if close_price is None:
        await asyncio.sleep(5)
        close_price = result_tracker.get_current_price(symbol)
    if close_price is None:
        return

    entry_r = round(float(entry_price), config.PRICE_PRECISION)
    close_r = round(close_price, config.PRICE_PRECISION)
    result = "WIN" if (signal_type == "CALL" and close_r > entry_r) or \
                      (signal_type == "PUT" and close_r < entry_r) else "LOSS"

    update_signal_result(signal_id, close_price, result)
    update_daily_stats(symbol)
    await _send(format_result(symbol=symbol, entry_time_utc3=entry_time, result=result))


# ============================================================
# TELEGRAM COMMANDS
# ============================================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(format_startup_message())

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol = context.args[0].upper() if context.args else None
    if symbol:
        s = get_pair_stats(symbol)
        await update.message.reply_text(format_stats_message(s["wins"], s["losses"], s["win_rate"]))
    else:
        s = get_daily_stats()
        await update.message.reply_text(format_stats_message(s["wins"], s["losses"], s["win_rate"], pairs=s.get("pairs")))

async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = get_daily_stats()
    await update.message.reply_text(format_stats_message(s["wins"], s["losses"], s["win_rate"], pairs=s.get("pairs")))

async def cmd_weekly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(format_weekly_report(get_weekly_stats()))

async def cmd_monthly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    r = format_weekly_report(get_monthly_stats()).replace("الأسبوعي", "الشهري")
    await update.message.reply_text(r)

async def cmd_overall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = get_overall_stats(symbol=context.args[0].upper() if context.args else None)
    await update.message.reply_text(format_overall_stats(s))

async def cmd_recent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    recent = get_recent_signals(limit=10)
    if not recent:
        await update.message.reply_text("لا توجد إشارات حديثة.")
        return
    lines = ["📋 آخر الإشارات:\n"]
    for r in recent:
        emoji = "✅" if r["result"] == "WIN" else ("❌" if r["result"] == "LOSS" else "⏳")
        src = "📡" if "tradingview" in r.get("reasons", "") else "🔍"
        lines.append(f"{emoji} {r['symbol']} {r['signal_type']} {r['entry_time']} | {r['result']} {src}")
    await update.message.reply_text("\n".join(lines))

async def cmd_pipeline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    entries = pipeline.get_active_entries()
    if not entries:
        await update.message.reply_text("🔍 لا توجد إشارات نشطة.")
        return
    lines = ["🔍 حالة الـ Pipeline:\n"]
    for e in entries:
        src = "📡 TV" if e.get("source") == "tradingview" else "🔍 Scanner"
        lines.append(f"📊 {e['symbol']} {e['signal']} | {e['state']} | {src}")
    await update.message.reply_text("\n".join(lines))

async def cmd_health(update: Update, context: ContextTypes.DEFAULT_TYPE):
    h = result_tracker.get_health_status()
    await update.message.reply_text(format_health_status(h, len(pipeline.get_active_entries())))


# ============================================================
# MAIN
# ============================================================

def run_fastapi():
    """Run FastAPI - used only when NOT running under gunicorn."""
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="warning")


async def main():
    global telegram_application

    if not config.TELEGRAM_BOT_TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN not set! Add it as Environment Variable in Render.")
        logger.error("The bot will keep the web server running but Telegram features are disabled.")
        # Don't exit - keep web server alive for Render health check
    if not config.TELEGRAM_CHAT_ID:
        logger.error("❌ TELEGRAM_CHAT_ID not set! Add it as Environment Variable in Render.")

    init_db()

    application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    telegram_application = application

    # Commands
    for cmd, handler in [
        ("start", cmd_start), ("stats", cmd_stats), ("today", cmd_today),
        ("weekly", cmd_weekly), ("monthly", cmd_monthly), ("overall", cmd_overall),
        ("recent", cmd_recent), ("pipeline", cmd_pipeline), ("health", cmd_health),
    ]:
        application.add_handler(CommandHandler(cmd, handler))

    # Scheduled jobs
    jq = application.job_queue
    jq.run_repeating(check_pending_results, interval=config.RESULT_CHECK_INTERVAL, first=30)
    jq.run_repeating(keep_alive, interval=config.KEEP_ALIVE_INTERVAL, first=60)
    jq.run_repeating(send_daily_report, interval=3600, first=120)
    jq.run_repeating(send_weekly_report, interval=3600, first=180)
    jq.run_repeating(check_health, interval=config.HEALTH_CHECK_INTERVAL, first=60)

    # Internal scanner (backup) - every 2 minutes
    if config.ENABLE_INTERNAL_SCANNER:
        jq.run_repeating(run_internal_scanner, interval=config.SCAN_INTERVAL_SECONDS, first=30)

    # Start FastAPI in background thread
    threading.Thread(target=run_fastapi, daemon=True).start()

    logger.info("=" * 60)
    logger.info(f"ABOOD القناص {config.BOT_VERSION} - FREE Edition")
    logger.info(f"🆓 No paid indicators needed!")
    logger.info(f"Pairs: {', '.join(config.TRADING_PAIRS)}")
    logger.info(f"Signal Sources: TradingView Webhook + Internal Scanner")
    logger.info(f"Internal Scanner: {'ON' if config.ENABLE_INTERNAL_SCANNER else 'OFF'}")
    logger.info(f"Webhook: /webhook")
    logger.info(f"Keep-Alive: {config.KEEP_ALIVE_INTERVAL}s")
    logger.info("=" * 60)

    await application.initialize()
    await application.start()
    await application.updater.start_polling()

    await recover_from_crash()
    await _send(format_startup_message())
    log_health_event("STARTUP", f"Bot started - {config.BOT_VERSION} FREE")

    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        timer.shutdown()
        await application.updater.stop()
        await application.stop()
        await application.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
