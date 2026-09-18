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
KLINE_LIMIT = 1000
CACHE_TTL_TICKER = 2
CACHE_TTL_KLINES = 8
CACHE_TTL_MARKETS = 20
CACHE_TTL_NEWS = 120
YAHOO_QUOTE_TTL = 3
YAHOO_CHART_TTL = 10
HTTP_TIMEOUT = 12.0

# One position hold, in bars. Used by the tested core signal and backtests.
HOLD_BARS = {
    "5m": 16,
    "15m": 12,
    "30m": 12,
    "1h": 14,
    "3h": 10,
    "1d": 10,
    "1w": 6,
}

# Conservative one-way cost components in basis points of price.
# Round-trip cost = 2 * (spread/2 + commission + slippage).
COST_BPS = {
    "crypto": {"spread_bps": 5.0, "commission_bps": 5.0, "slippage_bps": 4.0},
    "fx": {"spread_bps": 1.5, "commission_bps": 0.0, "slippage_bps": 0.5},
    "gold": {"spread_bps": 3.0, "commission_bps": 0.0, "slippage_bps": 1.0},
    "index": {"spread_bps": 2.5, "commission_bps": 0.5, "slippage_bps": 1.0},
}

# Edge gate: stress costs in the simulator so "edge" survives worse fills.
COST_STRESS = 1.35

# Professional floors — small-sample "EV > 0" is noise, not an edge.
MIN_OOS_TRADES = 12
MIN_EXPECTANCY_R = 0.05
MIN_PROFIT_FACTOR = 1.15
MIN_SIDE_TRADES = 8
MIN_WF_POSITIVE_FOLDS = 2
MAX_CALIBRATED_PROB = 72
MIN_RR = 2.0
ATR_STOP_MULT = 1.3
