"""Known coin metadata (English + Persian names, CoinGecko ids)."""

COINS = {
    "BTC": {"en": "Bitcoin", "fa": "بیت‌کوین", "gecko": "bitcoin"},
    "ETH": {"en": "Ethereum", "fa": "اتریوم", "gecko": "ethereum"},
    "BNB": {"en": "BNB", "fa": "بی‌ان‌بی", "gecko": "binancecoin"},
    "SOL": {"en": "Solana", "fa": "سولانا", "gecko": "solana"},
    "XRP": {"en": "XRP", "fa": "ریپل", "gecko": "ripple"},
    "ADA": {"en": "Cardano", "fa": "کاردانو", "gecko": "cardano"},
    "DOGE": {"en": "Dogecoin", "fa": "دوج‌کوین", "gecko": "dogecoin"},
    "TRX": {"en": "TRON", "fa": "ترون", "gecko": "tron"},
    "TON": {"en": "Toncoin", "fa": "تون‌کوین", "gecko": "the-open-network"},
    "AVAX": {"en": "Avalanche", "fa": "آوالانچ", "gecko": "avalanche-2"},
    "SHIB": {"en": "Shiba Inu", "fa": "شیبا اینو", "gecko": "shiba-inu"},
    "DOT": {"en": "Polkadot", "fa": "پولکادات", "gecko": "polkadot"},
    "LINK": {"en": "Chainlink", "fa": "چین‌لینک", "gecko": "chainlink"},
    "BCH": {"en": "Bitcoin Cash", "fa": "بیت‌کوین کش", "gecko": "bitcoin-cash"},
    "NEAR": {"en": "NEAR", "fa": "نیر", "gecko": "near"},
    "LTC": {"en": "Litecoin", "fa": "لایت‌کوین", "gecko": "litecoin"},
    "MATIC": {"en": "Polygon", "fa": "پالیگان", "gecko": "matic-network"},
    "POL": {"en": "Polygon", "fa": "پالیگان", "gecko": "polygon-ecosystem-token"},
    "UNI": {"en": "Uniswap", "fa": "یونی‌سواپ", "gecko": "uniswap"},
    "ICP": {"en": "Internet Computer", "fa": "اینترنت کامپیوتر", "gecko": "internet-computer"},
    "APT": {"en": "Aptos", "fa": "آپتوس", "gecko": "aptos"},
    "ATOM": {"en": "Cosmos", "fa": "کازموس", "gecko": "cosmos"},
    "FIL": {"en": "Filecoin", "fa": "فایل‌کوین", "gecko": "filecoin"},
    "ETC": {"en": "Ethereum Classic", "fa": "اتریوم کلاسیک", "gecko": "ethereum-classic"},
    "XLM": {"en": "Stellar", "fa": "استلار", "gecko": "stellar"},
    "HBAR": {"en": "Hedera", "fa": "هدرا", "gecko": "hedera-hashgraph"},
    "ARB": {"en": "Arbitrum", "fa": "آربیتروم", "gecko": "arbitrum"},
    "OP": {"en": "Optimism", "fa": "آپتیمیسم", "gecko": "optimism"},
    "INJ": {"en": "Injective", "fa": "اینجکتیو", "gecko": "injective-protocol"},
    "SUI": {"en": "Sui", "fa": "سویی", "gecko": "sui"},
    "PEPE": {"en": "Pepe", "fa": "پپه", "gecko": "pepe"},
    "RENDER": {"en": "Render", "fa": "رندر", "gecko": "render-token"},
    "IMX": {"en": "Immutable", "fa": "ایمیوتبل", "gecko": "immutable-x"},
    "VET": {"en": "VeChain", "fa": "وی‌چین", "gecko": "vechain"},
    "MKR": {"en": "Maker", "fa": "میکر", "gecko": "maker"},
    "GRT": {"en": "The Graph", "fa": "گراف", "gecko": "the-graph"},
    "AAVE": {"en": "Aave", "fa": "آوه", "gecko": "aave"},
    "ALGO": {"en": "Algorand", "fa": "الگورند", "gecko": "algorand"},
    "FTM": {"en": "Fantom", "fa": "فانتوم", "gecko": "fantom"},
    "SAND": {"en": "The Sandbox", "fa": "سندباکس", "gecko": "the-sandbox"},
    "AXS": {"en": "Axie Infinity", "fa": "اکسی اینفینیتی", "gecko": "axie-infinity"},
    "MANA": {"en": "Decentraland", "fa": "دیسنترالند", "gecko": "decentraland"},
    "XMR": {"en": "Monero", "fa": "مونرو", "gecko": "monero"},
    "EGLD": {"en": "MultiversX", "fa": "مولتی‌ورس‌ایکس", "gecko": "elrond-erd-2"},
    "THETA": {"en": "Theta", "fa": "تتا", "gecko": "theta-token"},
    "RUNE": {"en": "THORChain", "fa": "تورچین", "gecko": "thorchain"},
    "QNT": {"en": "Quant", "fa": "کوانت", "gecko": "quant-network"},
    "FLOW": {"en": "Flow", "fa": "فلو", "gecko": "flow"},
    "EOS": {"en": "EOS", "fa": "ایاس", "gecko": "eos"},
    "XTZ": {"en": "Tezos", "fa": "تزوس", "gecko": "tezos"},
    "NEO": {"en": "NEO", "fa": "نئو", "gecko": "neo"},
    "IOTA": {"en": "IOTA", "fa": "آیوتا", "gecko": "iota"},
    "ZEC": {"en": "Zcash", "fa": "زی‌کش", "gecko": "zcash"},
    "DASH": {"en": "Dash", "fa": "دش", "gecko": "dash"},
    "CHZ": {"en": "Chiliz", "fa": "چیلیز", "gecko": "chiliz"},
    "ENS": {"en": "ENS", "fa": "ای‌ان‌اس", "gecko": "ethereum-name-service"},
    "CRV": {"en": "Curve", "fa": "کرو", "gecko": "curve-dao-token"},
    "LDO": {"en": "Lido DAO", "fa": "لیدو", "gecko": "lido-dao"},
    "STX": {"en": "Stacks", "fa": "استکس", "gecko": "blockstack"},
    "WLD": {"en": "Worldcoin", "fa": "ورلدکوین", "gecko": "worldcoin-wld"},
    "SEI": {"en": "Sei", "fa": "سی", "gecko": "sei-network"},
    "TIA": {"en": "Celestia", "fa": "سلستیا", "gecko": "celestia"},
    "JUP": {"en": "Jupiter", "fa": "ژوپیتر", "gecko": "jupiter-exchange-solana"},
    "WIF": {"en": "dogwifhat", "fa": "داگ‌ویف‌هت", "gecko": "dogwifcoin"},
    "FET": {"en": "Fetch.ai", "fa": "فچ", "gecko": "fetch-ai"},
    "TAO": {"en": "Bittensor", "fa": "بیتنسور", "gecko": "bittensor"},
    "ORDI": {"en": "ORDI", "fa": "اوردی", "gecko": "ordinals"},
    "BONK": {"en": "Bonk", "fa": "بونک", "gecko": "bonk"},
    "FLOKI": {"en": "FLOKI", "fa": "فلوکی", "gecko": "floki"},
    "GALA": {"en": "Gala", "fa": "گالا", "gecko": "gala"},
    "CAKE": {"en": "PancakeSwap", "fa": "پنکیک‌سواپ", "gecko": "pancakeswap-token"},
    "COMP": {"en": "Compound", "fa": "کامپاند", "gecko": "compound-governance-token"},
    "SNX": {"en": "Synthetix", "fa": "سینتتیکس", "gecko": "havven"},
    "DYDX": {"en": "dYdX", "fa": "دی‌وای‌دی‌ایکس", "gecko": "dydx-chain"},
    "BLUR": {"en": "Blur", "fa": "بلر", "gecko": "blur"},
    "APE": {"en": "ApeCoin", "fa": "ایپ‌کوین", "gecko": "apecoin"},
    "GMT": {"en": "STEPN", "fa": "استپن", "gecko": "stepn"},
    "CFX": {"en": "Conflux", "fa": "کانفلاکس", "gecko": "conflux-token"},
    "KAS": {"en": "Kaspa", "fa": "کاسپا", "gecko": "kaspa"},
    "NOT": {"en": "Notcoin", "fa": "نات‌کوین", "gecko": "notcoin"},
    "ENA": {"en": "Ethena", "fa": "اتنا", "gecko": "ethena"},
    "ONDO": {"en": "Ondo", "fa": "اوندو", "gecko": "ondo-finance"},
    "PENDLE": {"en": "Pendle", "fa": "پندل", "gecko": "pendle"},
    "STRK": {"en": "Starknet", "fa": "استارک‌نت", "gecko": "starknet"},
    "ZK": {"en": "ZKsync", "fa": "زی‌کی‌سینک", "gecko": "zksync"},
    "EIGEN": {"en": "EigenLayer", "fa": "آیگن‌لایر", "gecko": "eigenlayer"},
    "OM": {"en": "MANTRA", "fa": "مانترا", "gecko": "mantra-dao"},
    "PYTH": {"en": "Pyth", "fa": "پایت", "gecko": "pyth-network"},
    "JTO": {"en": "Jito", "fa": "جیتو", "gecko": "jito-governance-token"},
    "W": {"en": "Wormhole", "fa": "ورم‌هول", "gecko": "wormhole"},
    "BEAM": {"en": "Beam", "fa": "بیم", "gecko": "beam-2"},
    "ROSE": {"en": "Oasis", "fa": "اوسیس", "gecko": "oasis-network"},
    "KAVA": {"en": "Kava", "fa": "کاوا", "gecko": "kava"},
    "ZIL": {"en": "Zilliqa", "fa": "زیلیکا", "gecko": "zilliqa"},
    "BAT": {"en": "Basic Attention", "fa": "بت", "gecko": "basic-attention-token"},
    "1INCH": {"en": "1inch", "fa": "وان‌اینچ", "gecko": "1inch"},
    "SUSHI": {"en": "SushiSwap", "fa": "سوشی", "gecko": "sushi"},
    "YFI": {"en": "yearn.finance", "fa": "یرن", "gecko": "yearn-finance"},
    "GMX": {"en": "GMX", "fa": "جی‌ام‌ایکس", "gecko": "gmx"},
    "EUR": {"en": "Euro", "fa": "یورو تتر", "gecko": None},
    "PAXG": {"en": "PAX Gold", "fa": "طلای توکن", "gecko": "pax-gold"},
}

MACRO_ASSETS = [
    {
        "symbol": "XAUUSD",
        "base": "XAU",
        "quote": "USD",
        "name_en": "Gold (Ounce)",
        "name_fa": "طلا (انس جهانی)",
        "yahoo": "GC=F",
        "binance": "PAXGUSDT",
        "prefer_spot": True,
        "live_feeds": [
            {"kind": "bybit_linear", "id": "XAUUSDT"},
            {"kind": "okx_swap", "id": "XAU-USDT-SWAP"},
            {"kind": "binance", "id": "PAXGUSDT"},
        ],
        "icon": "/static/img/gold.svg",
        "price_prefix": "$",
        "market_label": "بازار جهانی طلا",
        "keywords": "طلا انس طلای جهانی gold ounce xau xauusd",
    },
    {
        "symbol": "EURUSD",
        "base": "EUR",
        "quote": "USD",
        "name_en": "Euro / Dollar",
        "name_fa": "یورو / دلار",
        "yahoo": "EURUSD=X",
        "binance": "EURUSDT",
        "prefer_spot": True,
        "icon": "/static/img/eur.svg",
        "price_prefix": "",
        "market_label": "بازار جهانی فارکس",
        "keywords": "یورو یورو دلار euro eurusd eur",
    },
    {
        "symbol": "DXY",
        "base": "DXY",
        "quote": "USD",
        "name_en": "US Dollar Index",
        "name_fa": "دلار (شاخص DXY)",
        "yahoo": "DX-Y.NYB",
        "yahoo_alt": "DX=F",
        "binance": None,
        "icon": "/static/img/usd.svg",
        "price_prefix": "",
        "market_label": "شاخص دلار آمریکا",
        "keywords": "دلار شاخص دلار dollar dxy usd",
    },
]

_MACRO_BY_SYMBOL = {a["symbol"]: a for a in MACRO_ASSETS}
_MACRO_ALIASES = {
    "GOLD": "XAUUSD",
    "XAU": "XAUUSD",
    "XAUUSDT": "XAUUSD",
    "XAUUSD": "XAUUSD",
    "GC": "XAUUSD",
    "EUR": "EURUSD",
    "EURUSD": "EURUSD",
    "USD": "DXY",
    "DOLLAR": "DXY",
    "DXY": "DXY",
    "DXYUSD": "DXY",
}


def meta_for(base: str) -> dict:
    info = COINS.get(base.upper())
    if info:
        return {
            "en": info["en"],
            "fa": info["fa"],
            "gecko": info.get("gecko"),
        }
    return {"en": base.upper(), "fa": base.upper(), "gecko": None}


def gecko_ids_for(bases: list[str]) -> list[str]:
    ids = []
    seen = set()
    for base in bases:
        gid = COINS.get(base.upper(), {}).get("gecko")
        if gid and gid not in seen:
            ids.append(gid)
            seen.add(gid)
    return ids


def icon_url(base: str) -> str:
    spec = _MACRO_BY_SYMBOL.get(base.upper())
    if spec:
        return spec["icon"]
    return f"https://cdn.jsdelivr.net/gh/spothq/cryptocurrency-icons@master/128/color/{base.lower()}.png"


def normalize_symbol(symbol: str) -> str:
    raw = (symbol or "").upper().replace("-", "").replace("/", "").replace("=", "").replace(" ", "")
    return _MACRO_ALIASES.get(raw, raw)


def macro_spec(symbol: str) -> dict | None:
    return _MACRO_BY_SYMBOL.get(normalize_symbol(symbol))


def pack_macro(spec: dict) -> dict:
    return {
        "symbol": spec["symbol"],
        "base": spec["base"],
        "quote": spec["quote"],
        "name_en": spec["name_en"],
        "name_fa": spec["name_fa"],
        "icon": spec["icon"],
        "category": "macro",
        "keywords": spec.get("keywords", ""),
        "price_prefix": spec.get("price_prefix", "$"),
        "market_label": spec.get("market_label", "بازار جهانی"),
    }
