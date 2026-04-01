"""
Message Formatter V2.0 - ABOOD "القناص" (Improved)
====================================================
Enhanced messages with better formatting, emojis, and statistics.
Added weekly/monthly report formatting.
"""

from datetime import datetime, timezone, timedelta

import config

UTC3 = timezone(timedelta(hours=config.UTC_OFFSET))
HEADER = config.BOT_DISPLAY_HEADER


def _now_utc3():
    return datetime.now(UTC3)


# ============================================================
# أ. رسالة الاستعداد (Pre-Alert)
# ============================================================

def format_pre_alert(symbol: str, signal_type: str, entry_time_utc3: str,
                     remaining_minutes: int,
                     wins: int, losses: int,
                     pair_wins: int, pair_losses: int) -> str:
    total = wins + losses
    win_rate = round((wins / total * 100)) if total > 0 else 0
    pair_total = pair_wins + pair_losses
    pair_rate = round((pair_wins / pair_total * 100)) if pair_total > 0 else 0

    direction_emoji = "🟢" if signal_type == "CALL" else "🔴"
    direction_arrow = "⬆️" if signal_type == "CALL" else "⬇️"

    return (
        f"》 ABOOD 15 M 《\n\n"
        f"📊  {symbol}\n"
        f"{direction_emoji}  {signal_type} {direction_arrow}\n"
        f"⌚  {entry_time_utc3}\n"
        f"⏳  {remaining_minutes} دقيقة\n\n"
        f"📈 Win: {wins} | Loss: {losses} ({win_rate}%)\n"
        f"📊 {symbol}: {pair_wins}W / {pair_losses}L ({pair_rate}%)"
    )


# ============================================================
# ب. رسالة التنفيذ (Execution)
# ============================================================

def format_execution(symbol: str, signal_type: str, entry_time_utc3: str) -> str:
    direction = "⬆️" if signal_type == "CALL" else "⬇️"

    return (
        f"{HEADER}\n"
        f"✅ 🔜 {symbol} {entry_time_utc3} {direction}"
    )


# ============================================================
# ج. رسالة الحصاد (Result)
# ============================================================

def format_result(symbol: str, entry_time_utc3: str, result: str) -> str:
    if result == "WIN":
        return (
            f"{HEADER}\n"
            f"✅ {symbol} {entry_time_utc3} 💎 WIN"
        )
    else:
        return (
            f"{HEADER}\n"
            f"❌ {symbol} {entry_time_utc3} 💀 LOSS"
        )


# ============================================================
# تقرير يومي (NEW!)
# ============================================================

def format_daily_report(stats: dict) -> str:
    total = stats["wins"] + stats["losses"]
    win_rate = stats.get("win_rate", 0)
    now = _now_utc3()

    lines = [
        f"📊 التقرير اليومي | {now.strftime('%Y-%m-%d')}",
        f"━━━━━━━━━━━━━━━━━━━━━━━",
        f"",
        f"🔢 إجمالي الصفقات: {total}",
        f"✅ رابحة: {stats['wins']}",
        f"❌ خاسرة: {stats['losses']}",
        f"📈 نسبة النجاح: {win_rate}%",
    ]

    if stats.get("pairs"):
        lines.append(f"\n📋 تفصيل الأزواج:")
        for p in stats["pairs"]:
            p_total = p["wins"] + p["losses"]
            emoji = "🟢" if p["win_rate"] >= 60 else ("🟡" if p["win_rate"] >= 50 else "🔴")
            lines.append(f"  {emoji} {p['symbol']}: {p['wins']}W / {p['losses']}L ({p['win_rate']}%)")

    # Performance indicator
    if total > 0:
        if win_rate >= 70:
            lines.append(f"\n🏆 أداء ممتاز! استمر! 💪")
        elif win_rate >= 55:
            lines.append(f"\n👍 أداء جيد")
        elif win_rate >= 40:
            lines.append(f"\n⚠️ أداء متوسط - مراجعة مطلوبة")
        else:
            lines.append(f"\n🚨 أداء ضعيف - يُنصح بالتوقف والمراجعة")

    lines.append(f"\n━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"🤖 ABOOD القناص {config.BOT_VERSION}")

    return "\n".join(lines)


# ============================================================
# تقرير أسبوعي (NEW!)
# ============================================================

def format_weekly_report(stats: dict) -> str:
    total = stats.get("total", 0)
    win_rate = stats.get("win_rate", 0)

    lines = [
        f"📊 التقرير الأسبوعي",
        f"━━━━━━━━━━━━━━━━━━━━━━━",
        f"📅 {stats.get('period', '')}",
        f"",
        f"🔢 إجمالي الصفقات: {total}",
        f"✅ رابحة: {stats['wins']}",
        f"❌ خاسرة: {stats['losses']}",
        f"📈 نسبة النجاح: {win_rate}%",
    ]

    if stats.get("pairs"):
        lines.append(f"\n📋 أداء الأزواج:")
        for p in stats["pairs"]:
            p_total = p["wins"] + p["losses"]
            p_rate = round((p["wins"] / p_total * 100), 1) if p_total > 0 else 0
            emoji = "🟢" if p_rate >= 60 else ("🟡" if p_rate >= 50 else "🔴")
            lines.append(f"  {emoji} {p['symbol']}: {p['wins']}W / {p['losses']}L ({p_rate}%)")

    # Best/worst pair
    if stats.get("pairs"):
        sorted_pairs = sorted(stats["pairs"],
                               key=lambda p: p["wins"] / max(p["wins"] + p["losses"], 1),
                               reverse=True)
        if sorted_pairs:
            best = sorted_pairs[0]
            best_rate = round(best["wins"] / max(best["wins"] + best["losses"], 1) * 100, 1)
            lines.append(f"\n🥇 أفضل زوج: {best['symbol']} ({best_rate}%)")
            if len(sorted_pairs) > 1:
                worst = sorted_pairs[-1]
                worst_rate = round(worst["wins"] / max(worst["wins"] + worst["losses"], 1) * 100, 1)
                lines.append(f"🥉 أضعف زوج: {worst['symbol']} ({worst_rate}%)")

    lines.append(f"\n━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"🤖 ABOOD القناص {config.BOT_VERSION}")

    return "\n".join(lines)


# ============================================================
# Utility Messages
# ============================================================

def format_stats_message(wins: int, losses: int, win_rate: float, pairs=None) -> str:
    total = wins + losses
    lines = [
        "📊 إحصائيات اليوم\n",
        f"✅ Win: {wins}",
        f"❌ Loss: {losses}",
        f"📈 Win Rate: {win_rate}%",
        f"🔢 Total: {total}",
    ]
    if pairs:
        lines.append("\n📋 تفصيل الأزواج:")
        for p in pairs:
            lines.append(f"  {p['symbol']}: {p['wins']}W / {p['losses']}L ({p['win_rate']}%)")
    return "\n".join(lines)


def format_overall_stats(stats: dict) -> str:
    return (
        f"🧮 الإحصائيات التراكمية\n\n"
        f"🔢 Total: {stats['total']}\n"
        f"✅ Win: {stats['wins']}\n"
        f"❌ Loss: {stats['losses']}\n"
        f"📈 Win Rate: {stats['win_rate']}%"
    )


def format_startup_message() -> str:
    now = _now_utc3()
    time_str = now.strftime("%Y-%m-%d %H:%M:%S")
    pairs = " | ".join(config.TRADING_PAIRS)

    return (
        f"📈 》 ABOOD القناص 《 {config.BOT_VERSION} 📈\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⏰ {time_str} (UTC+3)\n\n"
        f"✅ GainzAlgo V2 Webhook: جاهز\n"
        f"✅ LuxAlgo SMC Filter: {'مفعّل' if config.SMC_FILTER_ENABLED else 'معطّل'}\n"
        f"✅ 120s Stability Rule: مفعّل\n"
        f"✅ Wick Filter: {'مفعّل' if config.WICK_FILTER_ENABLED else 'معطّل'}\n"
        f"✅ Multi-Trade: {'مفعّل' if config.ALLOW_MULTI_PAIR_TRADES else 'معطّل'}\n"
        f"✅ Hybrid Mode: {'مفعّل' if config.ENABLE_HYBRID_MODE else 'معطّل'}\n"
        f"✅ قاعدة البيانات: متصلة\n"
        f"✅ Keep-Alive: مفعّل\n\n"
        f"📊 الأزواج: {pairs}\n"
        f"⏱ مدة الصفقات: 15 دقيقة (Fixed Time)\n"
        f"🎯 الدخول: عند إغلاق الشمعة (00:00:00)\n"
        f"🔍 Pipeline: 5 مراحل\n"
        f"🕐 ساعات العمل: 3:00 AM - 11:00 PM (UTC+3)\n"
        f"📅 أيام العمل: الاثنين - الجمعة\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 الأوامر:\n"
        f"/stats - إحصائيات اليوم\n"
        f"/weekly - تقرير أسبوعي\n"
        f"/monthly - تقرير شهري\n"
        f"/overall - الإحصائيات التراكمية\n"
        f"/recent - آخر 10 إشارات\n"
        f"/pipeline - حالة الـ Pipeline\n"
        f"/health - حالة النظام\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━"
    )


def format_health_status(health: dict, active_entries: int) -> str:
    """Format system health status message."""
    status_emoji = "🟢" if health["status"] == "healthy" else "🔴"
    now = _now_utc3()

    return (
        f"🏥 حالة النظام\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⏰ {now.strftime('%H:%M:%S')} (UTC+3)\n"
        f"{status_emoji} الحالة: {health['status']}\n"
        f"📊 صفقات نشطة: {active_entries}\n"
        f"⚠️ أخطاء متتالية: {health['consecutive_failures']}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━"
    )


def format_system_alert(alert_type: str, message: str) -> str:
    """Format system alert message."""
    emoji = "🚨" if alert_type == "critical" else "⚠️"
    now = _now_utc3()

    return (
        f"{emoji} تنبيه النظام {emoji}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⏰ {now.strftime('%H:%M:%S')} (UTC+3)\n"
        f"📝 {message}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━"
    )
