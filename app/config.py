TIMEFRAMES = [
    {"id": "5m", "label": "۵ دقیقه", "seconds": 5 * 60},
    {"id": "15m", "label": "۱۵ دقیقه", "seconds": 15 * 60},
    {"id": "30m", "label": "۳۰ دقیقه", "seconds": 30 * 60},
    {"id": "1h", "label": "۱ ساعت", "seconds": 60 * 60},
    {"id": "3h", "label": "۳ ساعت", "seconds": 3 * 60 * 60},
    {"id": "1d", "label": "۱ روز", "seconds": 24 * 60 * 60},
    {"id": "1w", "label": "۱ هفته", "seconds": 7 * 24 * 60 * 60},
]

TIMEFRAME_IDS = [tf["id"] for tf in TIMEFRAMES]

HORIZON_FA = {tf["id"]: f"{tf['label']} آینده" for tf in TIMEFRAMES}

DEFAULT_SYMBOL = "BTCUSDT"
KLINE_LIMIT = 400
CACHE_TTL_TICKER = 8
CACHE_TTL_KLINES = 20
CACHE_TTL_MARKETS = 30
CACHE_TTL_NEWS = 120
HTTP_TIMEOUT = 12.0
