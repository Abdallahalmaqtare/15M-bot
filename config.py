"""
ABOOD "القناص" V3.0 Configuration
====================================
🆓 100% FREE - No paid indicators needed!
Uses TradingView Plus (free alerts + webhooks) with custom Pine Script.
Also has internal scanner as backup.
"""
import os

# ============================================================
# TELEGRAM (🔐 Secured)
# ============================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ============================================================
# TRADING PAIRS
# ============================================================
TRADING_PAIRS = ["EURUSD", "GBPUSD", "AUDUSD"]

YF_SYMBOL_MAP = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "AUDUSD": "AUDUSD=X",
}

# ============================================================
# TIMEFRAME & TRADE
# ============================================================
TIMEFRAME = "15m"
TRADE_DURATION = 15
CANDLE_INTERVAL = 15

# ============================================================
# TIMEZONE
# ============================================================
UTC_OFFSET = 3

# ============================================================
# SIGNAL SOURCE: TradingView Webhook (PRIMARY) + Internal Scanner (BACKUP)
# ============================================================
# TradingView webhook is the primary source (real-time, better data)
# Internal scanner runs as backup if no webhook received

# Internal scanner settings (backup)
ENABLE_INTERNAL_SCANNER = os.getenv("ENABLE_INTERNAL_SCANNER", "true").lower() == "true"
SCAN_INTERVAL_SECONDS = 120

# Indicator toggles (for internal scanner)
ENABLE_BOLLINGER = True
ENABLE_RSI = True
ENABLE_EMA = True
ENABLE_STOCHASTIC = True
ENABLE_ADX = True
ENABLE_CANDLE_PATTERNS = True
ENABLE_MOMENTUM = True

# Indicator parameters
BB_PERIOD = 20
BB_STD = 2.0
RSI_PERIOD = 14
RSI_OVERBOUGHT = 65
RSI_OVERSOLD = 35
EMA_FAST = 9
EMA_SLOW = 21
STOCH_K = 14
STOCH_SMOOTH = 3
STOCH_OVERBOUGHT = 80
STOCH_OVERSOLD = 20
ADX_PERIOD = 14
ADX_THRESHOLD = 25

# Scoring thresholds
MIN_SIGNAL_SCORE = 3.5
MIN_CONFIRMING_INDICATORS = 3
CONFLICT_THRESHOLD = 1.0
MIN_SIGNAL_INTERVAL = 15

# ============================================================
# FREE SMC ORDER BLOCK DETECTION (for internal scanner)
# ============================================================
ENABLE_SMC_FILTER = True
OB_LOOKBACK = 10
OB_MIN_IMPULSE_ATR = 1.5
OB_PROXIMITY_ATR = 0.5

# ============================================================
# PIPELINE SETTINGS
# ============================================================
STABILITY_WINDOW_SECONDS = 120
CONFIRMATION_ENABLED = True
RESULT_CHECK_DELAY_SECONDS = 1
PRICE_PRECISION = 5

# ============================================================
# WICK FILTER
# ============================================================
WICK_FILTER_ENABLED = True
WICK_BODY_RATIO_MAX = 0.40

# ============================================================
# ANTI-FLICKER
# ============================================================
MIN_SIGNAL_INTERVAL_SECONDS = 900

# ============================================================
# MULTI-TRADE
# ============================================================
ALLOW_MULTI_PAIR_TRADES = True
MAX_CONCURRENT_TRADES = 3

# ============================================================
# WEBHOOK SECURITY
# ============================================================
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "abood_v3_secret")

# ============================================================
# TRADING HOURS (UTC)
# ============================================================
ENABLE_TRADING_HOURS = os.getenv("ENABLE_TRADING_HOURS", "true").lower() == "true"
TRADING_START_HOUR_UTC = int(os.getenv("TRADING_START_HOUR", "0"))
TRADING_END_HOUR_UTC = int(os.getenv("TRADING_END_HOUR", "20"))

# ============================================================
# TRADING DAYS
# ============================================================
ENABLE_TRADING_DAYS = os.getenv("ENABLE_TRADING_DAYS", "true").lower() == "true"
TRADING_DAYS = [0, 1, 2, 3, 4]

# ============================================================
# HOSTING
# ============================================================
PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "0.0.0.0")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "")
KEEP_ALIVE_INTERVAL = 300

# ============================================================
# DISPLAY
# ============================================================
BOT_NAME = "ABOOD TRADING"
BOT_VERSION = "V3.0"
BOT_DISPLAY_HEADER = "abood Trading 15M POCKETOPTION BOT 🔵"

# ============================================================
# TELEGRAM RETRY
# ============================================================
TELEGRAM_RETRY_ATTEMPTS = 3
TELEGRAM_RETRY_DELAY = 2

# ============================================================
# AUTO REPORTS
# ============================================================
ENABLE_DAILY_REPORT = os.getenv("ENABLE_DAILY_REPORT", "true").lower() == "true"
DAILY_REPORT_HOUR_UTC3 = 23
ENABLE_WEEKLY_REPORT = os.getenv("ENABLE_WEEKLY_REPORT", "true").lower() == "true"
WEEKLY_REPORT_DAY = 4

# ============================================================
# HEALTH
# ============================================================
ENABLE_HEALTH_ALERTS = True
HEALTH_CHECK_INTERVAL = 300
MAX_PRICE_FETCH_FAILURES = 5

# ============================================================
# RESULT CHECK FALLBACK
# ============================================================
RESULT_CHECK_INTERVAL = 30
