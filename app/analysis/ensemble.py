"""Weighted ensemble: regime-aware layers, risk, explainable output."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.analysis.candles import analyze_candles
from app.analysis.costs import asset_class, market_name
from app.analysis.evidence import evaluate, holding_label, quality_tier
from app.analysis.indicator_votes import score_indicators
from app.analysis.layers import analyze_regime, analyze_session, analyze_stats, analyze_volume
from app.analysis.ml_models import score_ml
from app.analysis.structure import analyze_structure
from app.config import HORIZON_FA, MAX_CALIBRATED_PROB, MIN_RR, TIMEFRAMES


BASE_WEIGHTS = {
    "structure": 0.22,
    "indicators": 0.16,
    "candles": 0.09,
    "volume": 0.08,
    "stats": 0.10,
    "ml": 0.16,
    "mtf": 0.11,
    "session": 0.04,
    "sentiment": 0.04,
}


def combine(
    df: pd.DataFrame,
    interval: str,
    symbol: str,
    volume_source: str | None,
    mtf: dict | None = None,
    sentiment: dict | None = None,
    news: dict | None = None,
) -> dict:
    if df.empty or len(df) < 30:
        return empty_prediction(interval)

    # Forming candle is incomplete — decide on last closed bar only.
    work = df.iloc[:-1].copy() if len(df) > 80 else df
    if work.empty or len(work) < 30:
        return empty_prediction(interval)

    price = float(work["close"].iloc[-1])
    atr = float(work["atr"].iloc[-1]) if "atr" in work.columns and pd.notna(work["atr"].iloc[-1]) else price * 0.008
    regime = analyze_regime(work)
    structure = analyze_structure(work)
    candles = analyze_candles(work)
    volume = analyze_volume(work, volume_source)
    stats = analyze_stats(work)
    indicators = score_indicators(work, regime.get("family") or regime["regime"])
    ml = score_ml(work)
    session = analyze_session(interval, symbol)
    mtf_score, mtf_reasons = _mtf_score(mtf)
    evidence = evaluate(work, interval, symbol)

    weights = dict(BASE_WEIGHTS)
    family = regime.get("family") or "ranging"
    if family == "trending":
        weights["structure"] += 0.06
        weights["indicators"] += 0.03
        weights["stats"] -= 0.04
        weights["candles"] -= 0.02
    elif family == "ranging":
        weights["stats"] += 0.05
        weights["indicators"] += 0.03
        weights["structure"] -= 0.04
        weights["ml"] -= 0.02
    if news and news.get("level") == "high":
        for k in weights:
            weights[k] *= 0.85
        weights["session"] += 0.05

    layers = {
        "structure": structure["score"],
        "indicators": indicators["score"],
        "candles": candles["score"],
        "volume": volume["score"],
        "stats": stats["score"],
        "ml": ml["score"],
        "mtf": mtf_score,
        "session": session["score"],
        "sentiment": (sentiment or {}).get("score") or 0.0,
    }
    wsum = sum(weights.values()) or 1
    final = sum(layers[k] * weights[k] for k in layers) / wsum
    news_pen = (news or {}).get("score") or 0.0
    final = float(np.clip(final + news_pen * 0.35, -100, 100))

    agreement = _agreement(layers)
    core = evidence.get("core") or {}
    news_level = (news or {}).get("level", "low")
    mtf_dir = _mtf_direction(mtf)
    layers_agree = (np.sign(final) == 1 and core.get("side") == "buy") or (np.sign(final) == -1 and core.get("side") == "sell")
    action, no_trade_why = _gate_action(final, core, evidence, news_level, mtf_dir, ml)

    p_hat = float(evidence.get("calibrated_p") or 0.5)
    if action == "buy":
        p_hat = float(evidence.get("p_buy") or p_hat)
    elif action == "sell":
        p_hat = float(evidence.get("p_sell") or p_hat)
    probability = int(np.clip(round(p_hat * 100), 22, MAX_CALIBRATED_PROB))
    if action == "wait":
        probability = int(np.clip(round(50 + (p_hat - 0.5) * 20), 28, 62))

    oos = evidence.get("out_of_sample") or {}
    n_oos = int(oos.get("trades") or 0)
    shrink = min(1.0, n_oos / 16.0)
    confidence = int(np.clip(50 + (probability - 50) * shrink + (agreement - 0.5) * 8, 18, MAX_CALIBRATED_PROB))
    if news_level == "high":
        confidence = max(18, confidence - 12)
    if ml.get("hit_rate") is not None and ml["hit_rate"] < 52:
        confidence = max(18, confidence - 4)

    tier, tier_fa = quality_tier(action, evidence, agreement, news_level, bool(core.get("extended")), layers_agree)
    if tier in {"avoid", "moderate", "no_trade"} and action in {"buy", "sell"}:
        if tier == "avoid":
            action = "wait"
            no_trade_why = no_trade_why or evidence.get("verdict") or "لبه آماری کافی نیست"
        elif tier == "moderate" and core.get("extended"):
            action = "wait"
            no_trade_why = no_trade_why or "ستاپ هست اما قیمت کشیده است؛ ورود الان کیفیت هشدار ندارد"

    if action == "buy":
        direction, label = "buy", "بخر"
    elif action == "sell":
        direction, label = "sell", "بفروش"
    else:
        direction, label = "wait", "صبر کن / بدون معامله"

    conf_level = "HIGH" if confidence >= 64 and tier == "high_conviction" else "MEDIUM" if confidence >= 52 else "LOW"
    conf_fa = {"HIGH": "بالا", "MEDIUM": "متوسط", "LOW": "پایین"}[conf_level]

    expected = ml["expected_return"] if ml.get("ok") else final / 9000
    if regime["volatility"] == "high":
        expected *= 1.15
    elif regime["volatility"] == "low":
        expected *= 0.7
    if direction == "sell" and expected > 0:
        expected = -abs(expected)
    if direction == "buy" and expected < 0:
        expected = abs(expected)
    if direction == "wait":
        expected *= 0.15

    target = price * (1 + expected)
    change_pct = (target - price) / price * 100
    oos_ev = float(oos.get("expectancy") or 0)
    buy_p = int(round(float(evidence.get("p_buy") or 0.5) * 100))
    sell_p = int(round(float(evidence.get("p_sell") or 0.5) * 100))
    plan = make_trade_plan(
        price,
        atr,
        structure.get("levels") or {},
        action=action,
        buy_success=buy_p,
        sell_success=sell_p,
        no_trade_why=no_trade_why,
        strategy=core.get("strategy_fa") or core.get("strategy"),
        expectancy=oos_ev,
    )
    if plan["action"] == "buy":
        risk = {"entry_zone": [plan["buy_at"], plan["buy_at"]], "stop_loss": plan["buy_sl"], "tp1": plan["buy_tp"], "tp2": plan["buy_tp2"], "rr": plan["buy_rr"]}
    elif plan["action"] == "sell":
        risk = {"entry_zone": [plan["sell_at"], plan["sell_at"]], "stop_loss": plan["sell_sl"], "tp1": plan["sell_tp"], "tp2": plan["sell_tp2"], "rr": plan["sell_rr"]}
    else:
        risk = {"entry_zone": [plan["buy_at"], plan["sell_at"]], "stop_loss": None, "tp1": None, "tp2": None, "rr": plan.get("min_rr")}
    seconds = next((tf["seconds"] for tf in TIMEFRAMES if tf["id"] == interval), 3600)
    last_ts = int(work.iloc[-1]["time"].timestamp())
    forecast = _forecast(price, expected, last_ts, seconds)

    reasons = []
    for block in (
        structure.get("reasons"),
        indicators.get("reasons"),
        candles.get("reasons"),
        volume.get("reasons"),
        stats.get("reasons"),
        ml.get("reasons"),
        mtf_reasons,
        session.get("reasons"),
        (sentiment or {}).get("reasons"),
        (news or {}).get("reasons"),
        regime.get("reasons"),
    ):
        reasons.extend(block or [])
    reasons = [r for r in reasons if r.get("bias") != "neutral"][:8] + [r for r in reasons if r.get("bias") == "neutral"][:4]
    if evidence.get("verdict"):
        reasons.insert(0, {
            "id": "evidence",
            "text": evidence["verdict"],
            "bias": action if action in {"buy", "sell"} else "neutral",
        })

    risks = []
    if news and news.get("level") in {"high", "medium"}:
        risks.append((news["reasons"] or [{}])[0].get("text") or "ریسک خبر")
    if regime["volatility"] == "high":
        risks.append("نوسان بالاست؛ استاپ ATR را بزرگ‌تر در نظر بگیرید")
    if agreement < 0.35:
        risks.append("لایه‌های مدل با هم هم‌جهت نیستند")
    if not evidence.get("has_edge"):
        risks.append(evidence.get("verdict") or "لبه خارج از نمونه تأیید نشد")
    if not risks:
        risks.append("ریسک معمولی بازار؛ این خروجی توصیه سرمایه‌گذاری نیست")

    layer_pct = {k: int(np.clip(50 + v * 0.45, 5, 95)) for k, v in layers.items()}
    invalidation = _invalidation(action, plan, structure)
    if action == "wait":
        summary = f"بدون معامله. {no_trade_why or evidence.get('verdict') or 'ستاپ معتبر با امید ریاضی مثبت دیده نشد.'}"
    else:
        summary = (
            f"{label} با احتمال کالیبره‌شده {probability}٪ (از {n_oos} معامله خارج از نمونه). "
            f"رژیم: {regime['regime_fa']} · استراتژی: {core.get('strategy_fa') or '—'}. "
            f"{reasons[0]['text'] if reasons else ''}"
        )

    return {
        "direction": direction,
        "label": label,
        "probability": probability,
        "confidence": confidence,
        "confidence_level": conf_level,
        "confidence_fa": conf_fa,
        "quality": tier,
        "quality_fa": tier_fa,
        "no_trade_reason": None if action in {"buy", "sell"} else (no_trade_why or evidence.get("verdict")),
        "target_price": _round_price(target),
        "change_pct": round(change_pct, 3),
        "expected_move": round(change_pct, 3),
        "horizon": HORIZON_FA.get(interval, interval),
        "holding_period": holding_label(interval),
        "interval": interval,
        "market": market_name(symbol),
        "asset_class": asset_class(symbol),
        "entry_zone": risk["entry_zone"],
        "stop_loss": risk["stop_loss"],
        "tp1": risk["tp1"],
        "tp2": risk["tp2"],
        "risk_reward": risk["rr"],
        "plan": plan,
        "primary_strategy": core.get("strategy"),
        "primary_strategy_fa": core.get("strategy_fa"),
        "invalidation": invalidation,
        "evidence": {
            "has_edge": evidence.get("has_edge"),
            "edge_nearby": evidence.get("edge_nearby"),
            "retired": evidence.get("retired"),
            "verdict": evidence.get("verdict"),
            "oos": oos,
            "in_sample": evidence.get("in_sample"),
            "walk_forward": evidence.get("walk_forward"),
            "costs": evidence.get("costs"),
            "n_oos": n_oos,
            "calibrated_p": round(p_hat, 3),
            "best_strategy": evidence.get("best_strategy"),
            "strategy_oos": evidence.get("strategy_oos"),
            "core": core,
            "regime_breakdown": evidence.get("regime_breakdown"),
        },
        "regime": regime["regime"],
        "regime_fa": regime["regime_fa"],
        "volatility": regime["volatility"],
        "volatility_fa": regime["volatility_fa"],
        "structure": {
            "trend": structure["trend_label"],
            "bos": structure["bos"],
            "choch": structure["choch"],
            "pattern": structure.get("pattern"),
            "support": structure["levels"].get("nearest_support"),
            "resistance": structure["levels"].get("nearest_resistance"),
            "support_strength": structure["levels"].get("support_strength"),
            "resistance_strength": structure["levels"].get("resistance_strength"),
            "liquidity": structure.get("liquidity"),
        },
        "candles": candles.get("patterns"),
        "layers": layer_pct,
        "layer_scores": {k: round(v, 1) for k, v in layers.items()},
        "ml": {
            "up_prob": ml.get("up_prob"),
            "down_prob": ml.get("down_prob"),
            "hit_rate": ml.get("hit_rate"),
            "ok": ml.get("ok"),
        },
        "session": session.get("session_fa"),
        "sentiment": sentiment or {},
        "news_risk": news_level,
        "news_events": (news or {}).get("events") or [],
        "volume_note": volume.get("source_note"),
        "reasons": reasons[:10],
        "risks": risks[:4],
        "summary": summary,
        "forecast": forecast,
        "ta_score": round(indicators["score"], 1),
        "ml_ok": bool(ml.get("ok")),
        "disclaimer": "احتمال از بک‌تست خارج از نمونه پس از هزینه است، نه فرمول تزئینی. توصیه مالی نیست.",
    }


def _mtf_score(mtf: dict | None) -> tuple[float, list[dict]]:
    if not mtf:
        return 0.0, []
    votes = []
    reasons = []
    for tf, info in mtf.items():
        d = info.get("direction")
        if d == "buy":
            votes.append(1)
        elif d == "sell":
            votes.append(-1)
        else:
            votes.append(0)
        reasons.append({"id": "mtf", "text": f"{tf}: {info.get('label', d)}", "bias": d or "neutral"})
    if not votes:
        return 0.0, []
    mean = float(np.mean(votes))
    # higher TFs already listed first if caller orders them
    score = mean * 70
    if abs(mean) >= 0.6:
        reasons.insert(0, {"id": "confluence", "text": "هم‌جهتی تایم‌فریم‌ها (Confluence) برقرار است", "bias": "buy" if mean > 0 else "sell"})
    return float(np.clip(score, -100, 100)), reasons[:6]


def _agreement(layers: dict) -> float:
    signs = [np.sign(v) for v in layers.values() if abs(v) >= 6]
    if len(signs) < 2:
        return 0.4
    maj = np.sign(np.mean(signs))
    return float(np.mean([1 if s == maj else 0 for s in signs]))


def _mtf_direction(mtf: dict | None) -> str | None:
    if not mtf:
        return None
    votes = []
    for info in mtf.values():
        d = info.get("direction")
        if d == "buy":
            votes.append(1)
        elif d == "sell":
            votes.append(-1)
    if not votes:
        return None
    mean = float(np.mean(votes))
    if mean >= 0.5:
        return "buy"
    if mean <= -0.5:
        return "sell"
    return None


def _gate_action(final: float, core: dict, evidence: dict, news_level: str, mtf_dir: str | None, ml: dict) -> tuple[str, str | None]:
    """NO TRADE unless the tested core setup exists and OOS expectancy is positive after costs."""
    if news_level == "high":
        return "wait", "ریسک خبر بالاست؛ معامله اجباری نیست"
    side = core.get("side") or "wait"
    if side == "wait":
        if evidence.get("edge_nearby") or evidence.get("has_edge"):
            return "wait", evidence.get("verdict") or "لبه تاریخی نزدیک است؛ الان ستاپ ورودی نیست"
        return "wait", evidence.get("verdict") or "ستاپ آزمایش‌شده در این رژیم دیده نشد"
    if evidence.get("retired") or not evidence.get("has_edge"):
        return "wait", evidence.get("verdict") or "امید ریاضی خارج از نمونه پس از هزینه کافی نیست"
    # Soft MTF: only block when HTF conflicts AND ensemble also fights the setup.
    if mtf_dir and mtf_dir != side:
        if (side == "buy" and final <= -8) or (side == "sell" and final >= 8):
            return "wait", "تضاد تایم‌فریم بالاتر همراه با لایه‌های مخالف"
    if side == "buy" and final <= -28:
        return "wait", "ستاپ هست اما لایه‌های دیگر خلاف جهت‌اند"
    if side == "sell" and final >= 28:
        return "wait", "ستاپ هست اما لایه‌های دیگر خلاف جهت‌اند"
    hit = ml.get("hit_rate")
    ml_score = float(ml.get("score") or 0)
    if hit is not None and hit < 45 and abs(ml_score) >= 18:
        if side == "buy" and ml_score < 0:
            return "wait", "مدل آماری خلاف جهت خرید است"
        if side == "sell" and ml_score > 0:
            return "wait", "مدل آماری خلاف جهت فروش است"
    return side, None


def _invalidation(action: str, plan: dict, structure: dict) -> str:
    if action == "buy":
        sl = plan.get("buy_sl")
        support = (structure.get("levels") or {}).get("nearest_support")
        extra = f" یا شکست تأییدشده زیر { _fmt(support)}" if support else ""
        return f"بسته شدن زیر حد ضرر {_fmt(sl) if sl else '—'}{extra}."
    if action == "sell":
        sl = plan.get("sell_sl")
        resist = (structure.get("levels") or {}).get("nearest_resistance")
        extra = f" یا شکست تأییدشده بالای { _fmt(resist)}" if resist else ""
        return f"بسته شدن بالای حد ضرر {_fmt(sl) if sl else '—'}{extra}."
    return "بدون معامله فعال؛ ابطال موضوعیت ندارد تا ستاپ معتبر تشکیل شود."


def make_trade_plan(
    price: float,
    atr: float,
    levels: dict,
    action: str = "wait",
    buy_success: int = 50,
    sell_success: int = 50,
    no_trade_why: str | None = None,
    strategy: str | None = None,
    expectancy: float = 0.0,
) -> dict:
    """Levels only. Action is decided by evidence gating, never by proximity to S/R."""
    atr = max(float(atr or 0), price * 0.0015)
    sl_dist = max(atr * 1.3, price * 0.0018)
    support = levels.get("nearest_support")
    resist = levels.get("nearest_resistance")
    buy_at = price
    sell_at = price
    if support and support < price:
        buy_sl = min(price - sl_dist, float(support) - atr * 0.15)
    else:
        buy_sl = price - sl_dist
    if resist and resist > price:
        sell_sl = max(price + sl_dist, float(resist) + atr * 0.15)
    else:
        sell_sl = price + sl_dist
    buy_r = abs(buy_at - buy_sl) or sl_dist
    sell_r = abs(sell_sl - sell_at) or sl_dist
    buy_tp, buy_tp2 = buy_at + buy_r * MIN_RR, buy_at + buy_r * (MIN_RR + 1)
    sell_tp, sell_tp2 = sell_at - sell_r * MIN_RR, sell_at - sell_r * (MIN_RR + 1)
    watch_buy = float(support) if support and support < price else price - atr * 0.55
    watch_sell = float(resist) if resist and resist > price else price + atr * 0.55
    if action == "buy":
        success = buy_success
        command = (
            f"الان از {_fmt(price)} بخر · حد ضرر {_fmt(buy_sl)} · هدف {_fmt(buy_tp)} "
            f"· R:R ۱:{MIN_RR:g} · احتمال کالیبره {success}٪"
        )
        now_text = f"استراتژی: {strategy or 'core'} · امید ریاضی OOS {expectancy:+.2f}R"
    elif action == "sell":
        success = sell_success
        command = (
            f"الان از {_fmt(price)} بفروش · حد ضرر {_fmt(sell_sl)} · هدف {_fmt(sell_tp)} "
            f"· R:R ۱:{MIN_RR:g} · احتمال کالیبره {success}٪"
        )
        now_text = f"استراتژی: {strategy or 'core'} · امید ریاضی OOS {expectancy:+.2f}R"
    else:
        success = 0
        command = no_trade_why or "بدون معامله — لبه آماری کافی نیست"
        now_text = "NO TRADE"
        buy_at, sell_at = watch_buy, watch_sell
        buy_sl = buy_at - sl_dist
        sell_sl = sell_at + sl_dist
        buy_tp, buy_tp2 = buy_at + sl_dist * MIN_RR, buy_at + sl_dist * (MIN_RR + 1)
        sell_tp, sell_tp2 = sell_at - sl_dist * MIN_RR, sell_at - sl_dist * (MIN_RR + 1)
        buy_r = sl_dist
        sell_r = sl_dist
    return {
        "action": action,
        "command": command,
        "now_text": now_text,
        "success_pct": success,
        "buy_success": buy_success,
        "sell_success": sell_success,
        "min_rr": MIN_RR,
        "buy_at": _round_price(buy_at),
        "sell_at": _round_price(sell_at),
        "buy_sl": _round_price(buy_sl),
        "sell_sl": _round_price(sell_sl),
        "buy_tp": _round_price(buy_tp),
        "buy_tp2": _round_price(buy_tp2),
        "sell_tp": _round_price(sell_tp),
        "sell_tp2": _round_price(sell_tp2),
        "buy_rr": round(abs((buy_tp - buy_at) / buy_r), 2) if buy_r else MIN_RR,
        "sell_rr": round(abs((sell_at - sell_tp) / sell_r), 2) if sell_r else MIN_RR,
        "disclaimer": "احتمال از معاملات خارج از نمونه پس از هزینه است؛ تضمین سود نیست.",
    }


def _fmt(value: float) -> str:
    v = _round_price(value)
    if abs(v) >= 100:
        return f"{v:,.2f}"
    if abs(v) >= 1:
        return f"{v:.4f}"
    return f"{v:.6f}"


def _forecast(price: float, expected: float, last_ts: int, step: int) -> list[dict]:
    pts = [{"time": last_ts, "value": price}]
    value = price
    for i in range(1, 9):
        value *= 1 + expected * (0.72 ** (i - 1))
        pts.append({"time": last_ts + step * i, "value": round(value, 8)})
    return pts


def _round_price(value: float) -> float:
    abs_v = abs(value)
    if abs_v >= 1000:
        return round(value, 2)
    if abs_v >= 50:
        return round(value, 3)
    if abs_v >= 1:
        return round(value, 5)
    return round(value, 6)


def empty_prediction(interval: str) -> dict:
    return {
        "direction": "wait",
        "label": "بدون معامله",
        "probability": 50,
        "confidence": 0,
        "confidence_level": "LOW",
        "confidence_fa": "پایین",
        "quality": "no_trade",
        "quality_fa": "بدون معامله",
        "no_trade_reason": "داده کافی نیست",
        "target_price": 0,
        "change_pct": 0,
        "expected_move": 0,
        "horizon": HORIZON_FA.get(interval, interval),
        "holding_period": None,
        "interval": interval,
        "entry_zone": [0, 0],
        "stop_loss": 0,
        "tp1": 0,
        "tp2": 0,
        "risk_reward": None,
        "plan": {
            "action": "wait",
            "command": "داده کافی نیست",
            "now_text": "NO TRADE",
            "success_pct": 0,
            "buy_success": 0,
            "sell_success": 0,
            "min_rr": 2,
            "buy_at": 0,
            "sell_at": 0,
            "buy_sl": 0,
            "sell_sl": 0,
            "buy_tp": 0,
            "sell_tp": 0,
            "disclaimer": "این پیش‌بینی آموزشی است.",
        },
        "primary_strategy": None,
        "invalidation": None,
        "evidence": {"has_edge": False, "retired": False, "verdict": "داده کافی نیست"},
        "regime": "unknown",
        "regime_fa": "نامشخص",
        "volatility": "normal",
        "volatility_fa": "متوسط",
        "structure": {},
        "candles": [],
        "layers": {},
        "layer_scores": {},
        "ml": {},
        "session": None,
        "sentiment": {},
        "news_risk": "low",
        "news_events": [],
        "volume_note": None,
        "reasons": [],
        "risks": [],
        "summary": "داده کافی برای پیش‌بینی وجود ندارد.",
        "forecast": [],
        "ta_score": 0,
        "ml_ok": False,
        "disclaimer": "این پیش‌بینی آموزشی است و توصیه مالی نیست.",
    }
