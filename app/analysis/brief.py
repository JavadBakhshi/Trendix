"""Persian market outlook briefing from multi-timeframe ensemble results."""

from __future__ import annotations

from app.config import TIMEFRAMES

TF_LABEL = {tf["id"]: tf["label"] for tf in TIMEFRAMES}

SHORT = {"5m", "15m", "30m"}
MID = {"1h", "3h"}
LONG = {"1d", "1w"}

DIR_FA = {"buy": "صعودی", "sell": "نزولی", "neutral": "خنثی / رنج"}


def build_brief(ticker: dict, rows: list[dict], consensus: str, consensus_label: str) -> dict:
    parsed = []
    for row in rows:
        pred = row.get("prediction") or {}
        if row.get("error") or not pred:
            continue
        parsed.append(
            {
                "interval": row["interval"],
                "label": TF_LABEL.get(row["interval"], row["interval"]),
                "direction": pred.get("direction") or "neutral",
                "dir_fa": DIR_FA.get(pred.get("direction") or "neutral", "خنثی"),
                "name": pred.get("label") or "خنثی",
                "prob": pred.get("probability") or pred.get("confidence") or 50,
                "conf": pred.get("confidence") or 0,
                "move": pred.get("change_pct") or 0,
                "target": pred.get("target_price"),
                "regime": pred.get("regime_fa") or "",
                "vol": pred.get("volatility_fa") or "",
                "structure": (pred.get("structure") or {}).get("trend") or "",
                "news": pred.get("news_risk") or "low",
                "reasons": [r.get("text") for r in (pred.get("reasons") or []) if r.get("text")][:3],
                "risks": pred.get("risks") or [],
                "sl": pred.get("stop_loss"),
                "tp1": pred.get("tp1"),
            }
        )
    name = ticker.get("name_fa") or ticker.get("base") or ticker.get("symbol")
    symbol = ticker.get("symbol") or ""
    price = ticker.get("price")
    short = _bucket(parsed, SHORT)
    mid = _bucket(parsed, MID)
    long = _bucket(parsed, LONG)
    headline = _headline(name, consensus, short, mid, long)
    overall = _overall(name, symbol, price, consensus_label, short, mid, long, parsed)
    return {
        "headline": headline,
        "overall": overall,
        "short_term": _section("کوتاه‌مدت (۵ تا ۳۰ دقیقه)", short, "در دقایق و نیم‌ساعت آینده"),
        "intraday": _section("میان‌مدت (۱ تا ۳ ساعت)", mid, "در افق ساعتی"),
        "swing": _section("بلندمدت‌تر (روز و هفته)", long, "در افق روزانه و هفتگی"),
        "scenarios": _scenarios(name, parsed, long, mid),
        "watch": _watch(parsed, long, mid),
        "conflicts": _conflicts(short, mid, long),
        "disclaimer": "این متن خلاصهٔ مدل است، نه توصیهٔ خرید و فروش. بازار می‌تواند خلاف این سناریو حرکت کند.",
    }


def _bucket(parsed: list[dict], ids: set[str]) -> dict:
    items = [p for p in parsed if p["interval"] in ids]
    if not items:
        return {"bias": "neutral", "bias_fa": "نامشخص", "items": [], "avg_prob": 50, "avg_move": 0, "text": "برای این افق داده کافی نبود."}
    buys = sum(1 for p in items if p["direction"] == "buy")
    sells = sum(1 for p in items if p["direction"] == "sell")
    if buys > sells:
        bias = "buy"
    elif sells > buys:
        bias = "sell"
    else:
        bias = "neutral"
    avg_prob = sum(p["prob"] for p in items) / len(items)
    avg_move = sum(p["move"] for p in items) / len(items)
    regimes = [p["regime"] for p in items if p["regime"]]
    regime = max(set(regimes), key=regimes.count) if regimes else ""
    lines = []
    for p in items:
        move = p["move"]
        move_txt = f"{move:+.2f}٪" if move else "تقریباً بدون تغییر"
        lines.append(
            f"در بازهٔ {p['label']} مدل حالت «{p['name']}» می‌بیند "
            f"(احتمال حدود {int(p['prob'])}٪) و انتظار حرکت حدود {move_txt} را دارد."
        )
        if p["reasons"]:
            lines.append(f"دلیل اصلی این بازه: {p['reasons'][0]}.")
    if bias == "buy":
        lead = f"جمع‌بندی این افق بیشتر به سمت صعود متمایل است."
    elif bias == "sell":
        lead = f"جمع‌بندی این افق بیشتر به سمت نزول یا اصلاح متمایل است."
    else:
        lead = f"در این افق سیگنال‌ها مخلوط یا خنثی‌اند؛ بازار ممکن است رنج بزند یا منتظر محرک بماند."
    if regime:
        lead += f" رژیم غالب: {regime}."
    return {
        "bias": bias,
        "bias_fa": DIR_FA[bias],
        "items": items,
        "avg_prob": round(avg_prob),
        "avg_move": round(avg_move, 3),
        "text": lead + " " + " ".join(lines),
    }


def _headline(name: str, consensus: str, short: dict, mid: dict, long: dict) -> str:
    if consensus == "buy" and long.get("bias") == "buy":
        return f"چشم‌انداز {name}: تمایل صعودی، به‌ویژه در افق بالاتر"
    if consensus == "sell" and long.get("bias") == "sell":
        return f"چشم‌انداز {name}: فشار نزولی در چند افق هم‌زمان"
    if short.get("bias") != long.get("bias") and short.get("bias") != "neutral" and long.get("bias") != "neutral":
        return f"چشم‌انداز {name}: کوتاه‌مدت و بلندمدت هم‌جهت نیستند"
    if consensus == "buy":
        return f"چشم‌انداز {name}: سوگیری ملایم صعودی"
    if consensus == "sell":
        return f"چشم‌انداز {name}: سوگیری ملایم نزولی"
    return f"چشم‌انداز {name}: بازار بدون جهت قوی؛ نیاز به تأیید بیشتر"


def _overall(name, symbol, price, consensus_label, short, mid, long, parsed) -> str:
    price_txt = _fmt(price)
    parts = [
        f"خلاصهٔ مدل برای {name} ({symbol}) در قیمت حدود {price_txt} این است که اجماع بازه‌ها «{consensus_label}» است."
    ]
    parts.append(
        f"کوتاه‌مدت {short['bias_fa']}، میان‌مدت {mid['bias_fa']} و افق روز/هفته {long['bias_fa']} دیده می‌شود."
    )
    if short["bias"] == mid["bias"] == long["bias"] != "neutral":
        parts.append("چون چند افق با هم هم‌جهت‌اند، این سوگیری نسبت به وقتی فقط یک تایم‌فریم سیگنال بدهد قابل‌اعتمادتر است — نه تضمینی.")
    elif short["bias"] != long["bias"] and "neutral" not in {short["bias"], long["bias"]}:
        parts.append(
            "اختلاف کوتاه‌مدت با افق بالاتر معمولاً یعنی پولبک داخل روند بزرگ‌تر، یا شروع چرخش؛ تا وقتی Daily تأیید نکند نباید حرکت دقیقه‌ای را روند جدید فرض کرد."
        )
    else:
        parts.append("هم‌جهتی کامل بین بازه‌ها نیست؛ سناریوی محتمل‌تر نوسان حول سطوح و انتظار برای شکست معتبر است.")
    news_high = any(p["news"] == "high" for p in parsed)
    if news_high:
        parts.append("نزدیک خبر مهم، اعتبار سیگنال‌ها کمتر است و مدل توصیه می‌کند عجله نکنید.")
    return " ".join(parts)


def _section(title: str, bucket: dict, horizon: str) -> dict:
    return {
        "title": title,
        "horizon": horizon,
        "bias": bucket["bias"],
        "bias_fa": bucket["bias_fa"],
        "text": bucket["text"],
        "probability": bucket["avg_prob"],
        "expected_move": bucket["avg_move"],
    }


def _scenarios(name: str, parsed: list[dict], long: dict, mid: dict) -> dict:
    ref = next((p for p in parsed if p["interval"] == "1d"), None) or (long["items"][-1] if long.get("items") else None)
    up = f"اگر {name} بتواند مقاومت نزدیک را با حجم و بسته‌شدن معتبر بشکند، ادامهٔ مسیر با سوگیری صعودی میان‌مدت هم‌خوان است."
    down = f"اگر حمایت معتبر از دست برود، اصلاح عمیق‌تر با سوگیری نزولی مدل در بعضی بازه‌ها سازگار می‌شود."
    if ref:
        if ref.get("tp1"):
            up += f" هدف اولیهٔ مدل حدود {_fmt(ref['tp1'])} است."
        if ref.get("sl"):
            down += f" نقض سناریوی صعودی می‌تواند حوالی {_fmt(ref['sl'])} دیده شود."
    if mid.get("bias") == "buy":
        up += " تأیید ساعتی فعلاً به نفع خریداران است."
    if mid.get("bias") == "sell":
        down += " فشار فروش در تایم ساعتی این سناریو را تقویت می‌کند."
    return {"up": up, "down": down}


def _watch(parsed: list[dict], long: dict, mid: dict) -> list[str]:
    items = []
    ref = next((p for p in parsed if p["interval"] in {"1h", "1d"}), None)
    if ref and ref.get("structure"):
        items.append(f"ساختار {ref['label']}: {ref['structure']}")
    if long.get("bias_fa"):
        items.append(f"جهت افق بالاتر را ملاک اصلی بگذارید: {long['bias_fa']}")
    if mid.get("items"):
        items.append("برای ورود، هم‌خوانی ۱ ساعت با ۱۵ دقیقه مهم‌تر از سیگنال تنها در ۵ دقیقه است.")
    items.append("اگر خبر پرریسک منتشر شد، این خلاصه را تا آرام شدن نوسان کنار بگذارید.")
    return items[:4]


def _conflicts(short: dict, mid: dict, long: dict) -> str:
    dirs = {short["bias"], mid["bias"], long["bias"]}
    if len(dirs) == 1:
        return "در حال حاضر تضاد جدی بین افق‌ها دیده نمی‌شود."
    bits = []
    if short["bias"] != long["bias"] and short["bias"] != "neutral" and long["bias"] != "neutral":
        bits.append(f"کوتاه‌مدت {short['bias_fa']} است ولی افق روز/هفته {long['bias_fa']}؛ این می‌تواند پولبک یا تله باشد.")
    if mid["bias"] != long["bias"] and "neutral" not in {mid["bias"], long["bias"]}:
        bits.append(f"تایم ساعتی با Daily یکی نیست ({mid['bias_fa']} در برابر {long['bias_fa']}).")
    return " ".join(bits) or "اختلاف جزئی بین بازه‌ها هست؛ تا هم‌جهتی بیشتر صبر منطقی‌تر است."


def _fmt(value) -> str:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "—"
    if abs(n) >= 1000:
        return f"{n:,.2f}"
    if abs(n) >= 50:
        return f"{n:.3f}"
    if abs(n) >= 1:
        return f"{n:.5f}"
    return f"{n:.6f}"
