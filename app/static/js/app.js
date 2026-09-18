const TIMEFRAMES = [
  { id: "5m", label: "۵ دقیقه" },
  { id: "15m", label: "۱۵ دقیقه" },
  { id: "30m", label: "۳۰ دقیقه" },
  { id: "1h", label: "۱ ساعت" },
  { id: "3h", label: "۳ ساعت" },
  { id: "1d", label: "۱ روز" },
  { id: "1w", label: "۱ هفته" },
];

function initialRefreshMs() {
  const raw = localStorage.getItem("ca_refresh");
  if (raw == null) return 8000;
  const n = Number(raw);
  if (n === 30000) return 8000;
  return n;
}

const state = {
  symbol: localStorage.getItem("ca_symbol") || "BTCUSDT",
  interval: localStorage.getItem("ca_interval") || "5m",
  pendingInterval: null,
  coins: [],
  analysis: null,
  chartType: "candles",
  indicators: { sma: true, ema: false, boll: false, macd: false, rsi: false, volume: true },
  watchlist: JSON.parse(localStorage.getItem("ca_watch") || "[]"),
  showForecast: localStorage.getItem("ca_forecast") !== "0",
  refreshMs: initialRefreshMs(),
  page: "dashboard",
  alertSound: localStorage.getItem("ca_alert_sound") !== "0",
  alertMinOdds: Number(localStorage.getItem("ca_alert_min") || 50),
};

const PAGE_TITLE = "CryptoAnalyzer";
let mainChart, extraChart, bigChart;
let candleSeries, lineSeries, volumeSeries, extraSeries;
const overlaySeries = {};
let forecastSeries = null;
let priceTimer = null;
let analysisTimer = null;
let alertWatchTimer = null;
let analysisSeq = 0;
let lastPrice = null;
let chartKey = "";
let audioCtx = null;
let alertArmed = localStorage.getItem("ca_alert_arm") === "1";
let audioUnlocked = false;
let lastAlertNotify = {};
try { lastAlertNotify = JSON.parse(sessionStorage.getItem("ca_alert_fired") || "{}"); } catch (_) { lastAlertNotify = {}; }

/** Tiny WAV beep as HTMLAudio fallback when WebAudio is blocked. */
const ALERT_BEEP_WAV = (() => {
  const sampleRate = 22050;
  const duration = 0.45;
  const n = Math.floor(sampleRate * duration);
  const dataSize = n * 2;
  const buf = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buf);
  const writeStr = (off, s) => { for (let i = 0; i < s.length; i++) view.setUint8(off + i, s.charCodeAt(i)); };
  writeStr(0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeStr(36, "data");
  view.setUint32(40, dataSize, true);
  const freqs = [880, 1175, 1568];
  for (let i = 0; i < n; i++) {
    const t = i / sampleRate;
    const seg = Math.min(2, Math.floor(t / 0.14));
    const local = t - seg * 0.14;
    const env = local < 0.02 ? local / 0.02 : Math.max(0, 1 - (local - 0.02) / 0.12);
    const sample = Math.sin(2 * Math.PI * freqs[seg] * t) * env * 0.55;
    view.setInt16(44 + i * 2, sample * 32767, true);
  }
  const bytes = new Uint8Array(buf);
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return "data:audio/wav;base64," + btoa(binary);
})();

const $ = (id) => document.getElementById(id);

function toast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.hidden = false;
  setTimeout(() => { el.hidden = true; }, 2800);
}

async function api(path) {
  const joiner = path.includes("?") ? "&" : "?";
  const res = await fetch(`${path}${joiner}_=${Date.now()}`, { cache: "no-store" });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || "خطای سرور");
  }
  return res.json();
}

function formatPrice(n, ticker) {
  if (n == null || Number.isNaN(n)) return "—";
  const prefix = ticker && ticker.price_prefix !== undefined ? ticker.price_prefix : "$";
  const abs = Math.abs(n);
  let num;
  if (abs >= 1000) num = n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  else if (abs >= 50) num = n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 3 });
  else if (abs >= 1) num = n.toLocaleString("en-US", { minimumFractionDigits: 4, maximumFractionDigits: 5 });
  else num = n.toLocaleString("en-US", { minimumFractionDigits: 5, maximumFractionDigits: 8 });
  return prefix + num;
}

function mtPrice(n) {
  if (n == null || n === "" || Number.isNaN(Number(n))) return "";
  const v = Number(n);
  const abs = Math.abs(v);
  if (abs >= 1000) return v.toFixed(2);
  if (abs >= 50) return v.toFixed(3);
  if (abs >= 1) return v.toFixed(5);
  return v.toFixed(6);
}

function mtSymbol(symbol) {
  if (!symbol) return "";
  return symbol.endsWith("USDT") ? symbol.slice(0, -4) + "USD" : symbol;
}

function mtNumHtml(value) {
  const txt = mtPrice(value);
  if (!txt) return `<code class="mt-num">—</code>`;
  return `<code class="mt-num" data-copy="${txt}">${txt}</code>`;
}

function mtOrderText(symbol, side, price, sl, tp) {
  const p = mtPrice(price), s = mtPrice(sl), t = mtPrice(tp);
  if (!p) return "";
  return `${mtSymbol(symbol)}\n${side}\nPrice ${p}\nSL ${s}\nTP ${t}`;
}

function mtLevelsHtml(a, side) {
  const buy = side !== "sell";
  const price = buy ? (a.buy_at || a.entry) : (a.sell_at || a.entry);
  const sl = buy ? (a.buy_sl || a.stop_loss) : (a.sell_sl || a.stop_loss);
  const tp = buy ? (a.buy_tp || a.tp1) : (a.sell_tp || a.tp1);
  const label = buy ? "Buy" : "Sell";
  const p = mtPrice(price), s = mtPrice(sl), t = mtPrice(tp);
  if (!p) return "";
  const sym = a.mt_symbol || mtSymbol(a.symbol);
  return `
    <div class="mt-levels ${buy ? "buy" : "sell"}" data-mt-symbol="${sym}" data-mt-side="${label}" data-mt-price="${p}" data-mt-sl="${s}" data-mt-tp="${t}">
      <div class="mt-levels-head">
        <b>${sym}</b>
        <span>${label}</span>
        <button type="button" class="mt-copy-btn">کپی سفارش</button>
      </div>
      <div class="mt-levels-nums">
        <span>Price ${mtNumHtml(price)}</span>
        <span>SL ${mtNumHtml(sl)}</span>
        <span>TP ${mtNumHtml(tp)}</span>
      </div>
    </div>`;
}

function setMtNum(id, value) {
  const el = $(id);
  if (!el) return;
  const txt = mtPrice(value);
  el.textContent = txt || "—";
  el.dataset.copy = txt;
}

function fillMtCopy(plan) {
  setMtNum("mtBuyAt", plan.buy_at);
  setMtNum("mtBuySl", plan.buy_sl);
  setMtNum("mtBuyTp", plan.buy_tp);
  setMtNum("mtSellAt", plan.sell_at);
  setMtNum("mtSellSl", plan.sell_sl);
  setMtNum("mtSellTp", plan.sell_tp);
  const pair = $("mtPair");
  if (pair) {
    const txt = mtSymbol(state.symbol);
    pair.textContent = txt || "—";
    pair.dataset.copy = txt;
  }
}

function mtCopyText() {
  const plan = (state.analysis && state.analysis.prediction && state.analysis.prediction.plan) || {};
  return [
    mtOrderText(state.symbol, "Buy", plan.buy_at, plan.buy_sl, plan.buy_tp),
    mtOrderText(state.symbol, "Sell", plan.sell_at, plan.sell_sl, plan.sell_tp),
  ].filter(Boolean).join("\n\n");
}

function handleMtClick(e) {
  const btn = e.target.closest(".mt-copy-btn");
  if (btn) {
    e.preventDefault();
    e.stopPropagation();
    const box = btn.closest("[data-mt-price]");
    if (box) copyText(mtOrderText(box.dataset.mtSymbol, box.dataset.mtSide, box.dataset.mtPrice, box.dataset.mtSl, box.dataset.mtTp));
    return true;
  }
  const num = e.target.closest(".mt-num");
  if (num && num.dataset.copy) {
    e.preventDefault();
    e.stopPropagation();
    copyText(num.dataset.copy);
    return true;
  }
  return false;
}

async function copyText(text) {
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    toast(text.includes("\n") ? "اعداد متاتریدر کپی شد" : ("کپی شد: " + text));
  } catch (_) {
    toast("کپی نشد؛ عدد را دستی انتخاب کن");
  }
}

function formatCompact(n) {
  if (!n) return "—";
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  if (abs >= 1e12) return sign + "$" + (abs / 1e12).toFixed(2) + "T";
  if (abs >= 1e9) return sign + "$" + (abs / 1e9).toFixed(2) + "B";
  if (abs >= 1e6) return sign + "$" + (abs / 1e6).toFixed(2) + "M";
  if (abs >= 1e3) return sign + "$" + (abs / 1e3).toFixed(2) + "K";
  return sign + "$" + abs.toFixed(2);
}

function formatQty(n, base) {
  if (!n) return "—";
  if (n >= 1e6) return (n / 1e6).toFixed(2) + "M " + base;
  if (n >= 1e3) return (n / 1e3).toFixed(2) + "K " + base;
  return n.toLocaleString("en-US", { maximumFractionDigits: 2 }) + " " + base;
}

function pctClass(v) {
  return v > 0 ? "up pos" : v < 0 ? "down neg" : "";
}

function pctText(v) {
  if (v == null) return "—";
  const sign = v > 0 ? "+" : "";
  return sign + v.toFixed(2) + "%";
}

function chartColors() {
  const light = document.documentElement.getAttribute("data-theme") === "light";
  return {
    bg: "transparent",
    text: light ? "#334155" : "#94a3b8",
    grid: light ? "rgba(15,23,42,0.06)" : "rgba(148,163,184,0.08)",
    up: "#22c55e",
    down: "#ef4444",
    cross: light ? "#64748b" : "#64748b",
  };
}

function applyTheme(dark) {
  document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
  $("themeToggle").checked = dark;
  localStorage.setItem("ca_theme", dark ? "dark" : "light");
  if (state.analysis) renderCharts(state.analysis);
}

function setWatchButton() {
  $("watchToggle").classList.toggle("on", state.watchlist.includes(state.symbol));
}

function toggleWatch() {
  const set = new Set(state.watchlist);
  if (set.has(state.symbol)) set.delete(state.symbol);
  else set.add(state.symbol);
  state.watchlist = [...set];
  localStorage.setItem("ca_watch", JSON.stringify(state.watchlist));
  setWatchButton();
}

function buildTimeframes() {
  const row = $("tfRow");
  row.innerHTML = "";
  TIMEFRAMES.forEach((tf) => {
    const b = document.createElement("button");
    b.textContent = tf.label;
    const pending = state.pendingInterval === tf.id;
    const active = tf.id === state.interval && !state.pendingInterval;
    b.className = [active ? "active" : "", pending ? "pending" : ""].filter(Boolean).join(" ");
    b.onclick = () => setTimeframe(tf.id);
    row.appendChild(b);
  });
}

function setTimeframe(id) {
  if (state.pendingInterval === id) return;
  state.pendingInterval = id;
  localStorage.setItem("ca_interval", id);
  buildTimeframes();
  const label = TIMEFRAMES.find((t) => t.id === id)?.label || id;
  loadAnalysis({
    reason: "interval",
    message: `مدل در حال بررسی بازه ${label} است...`,
  });
}

function renderPairButton(ticker) {
  $("pairIcon").src = ticker.icon || ticker.image;
  $("pairIcon").style.visibility = "visible";
  $("pairIcon").onerror = () => { $("pairIcon").style.visibility = "hidden"; };
  if (ticker.category === "macro") {
    $("pairTitle").textContent = ticker.name_en;
    $("pairSymbol").textContent = ticker.symbol === "DXY" ? "DXY · شاخص دلار" : `${ticker.base} / ${ticker.quote}`;
  } else {
    $("pairTitle").textContent = `${ticker.name_en} / Tether`;
    $("pairSymbol").textContent = `${ticker.base} / USDT`;
  }
}

function setLiveStatus(kind, text) {
  const el = $("liveStatus");
  if (!el) return;
  el.className = "live-status " + (kind || "");
  const span = el.querySelector("span");
  if (span) span.textContent = text;
}

function renderPrices(ticker) {
  const next = ticker.price;
  $("livePrice").textContent = formatPrice(next, ticker);
  if (lastPrice != null && next != null && next !== lastPrice) {
    $("livePrice").classList.remove("tick-up", "tick-down");
    $("livePrice").classList.add(next > lastPrice ? "tick-up" : "tick-down");
    setTimeout(() => $("livePrice").classList.remove("tick-up", "tick-down"), 700);
  }
  lastPrice = next;
  $("liveChange").textContent = pctText(ticker.change_24h) + " (24H)";
  $("liveChange").className = "live-change " + pctClass(ticker.change_24h);
  $("railIcon").src = ticker.image || ticker.icon;
  $("railName").textContent = `${ticker.name_en} (${ticker.base})`;
  $("railNameFa").textContent = ticker.name_fa;
  $("railPrice").textContent = formatPrice(ticker.price, ticker);
  $("railChange").textContent = pctText(ticker.change_24h);
  $("railChange").className = "rail-change " + pctClass(ticker.change_24h);
  const stats = [
    ["بالاترین ۲۴ ساعت", formatPrice(ticker.high_24h, ticker)],
    ["پایین‌ترین ۲۴ ساعت", formatPrice(ticker.low_24h, ticker)],
  ];
  if (ticker.category === "macro") {
    stats.push(["بازار", ticker.market_label || "بازار جهانی"]);
    if (ticker.volume_24h) stats.push(["حجم", formatCompact(ticker.volume_24h)]);
  } else {
    stats.push(["حجم ۲۴ ساعت", formatCompact(ticker.volume_24h)]);
    stats.push(["ارزش بازار", formatCompact(ticker.market_cap)]);
    stats.push(["عرضه در گردش", formatQty(ticker.circulating_supply, ticker.base)]);
  }
  $("statsList").innerHTML = stats.map(([k, v]) => `<li><span>${k}</span><b>${v}</b></li>`).join("");
  const received = Date.now() / 1000;
  const asof = Number(ticker.as_of) || received;
  const age = Math.max(0, received - asof);
  let src = ticker.market_label || ticker.quote_source || "صرافی";
  if (ticker.category === "macro") src = ticker.market_label || "بازار جهانی";
  if (ticker.category !== "macro") src = "صرافی زنده";
  if (state.pendingInterval) setLiveStatus("busy", "در حال تصمیم‌گیری...");
  else if (age > 45) setLiveStatus("lag", `در حال همگام‌سازی با ${src}`);
  else setLiveStatus("ok", `زنده · ${src}`);
}

function renderPerformance(perf) {
  $("perfList").innerHTML = TIMEFRAMES.map((tf) => {
    const v = perf[tf.id] ?? 0;
    return `<li><span>${tf.label}</span><b class="${pctClass(v)}">${pctText(v)}</b></li>`;
  }).join("");
}

function addPlanLines(series, pred) {
  const p = pred && pred.plan;
  if (!series || !p) return;
  const rows = [
    [p.buy_at, "#22c55e", "بخر"],
    [p.sell_at, "#ef4444", "بفروش"],
  ];
  if (p.action === "buy") {
    rows.push([p.buy_sl, "#f97316", "حد ضرر"], [p.buy_tp, "#38bdf8", "هدف"]);
  } else if (p.action === "sell") {
    rows.push([p.sell_sl, "#f97316", "حد ضرر"], [p.sell_tp, "#38bdf8", "هدف"]);
  }
  rows.forEach(([price, color, title]) => {
    if (!price) return;
    try {
      series.createPriceLine({
        price,
        color,
        lineWidth: 2,
        lineStyle: 2,
        axisLabelVisible: true,
        title,
      });
    } catch (_) { /* ignore */ }
  });
}

function renderPrediction(pred) {
  const ticker = state.analysis && state.analysis.ticker;
  const plan = pred.plan || {};
  const action = plan.action || pred.direction || "wait";
  const verb = action === "buy" ? "بخر" : action === "sell" ? "بفروش" : "بدون معامله";
  if ($("signalVerb")) {
    $("signalVerb").textContent = verb;
    $("signalVerb").dataset.dir = action === "buy" || action === "sell" ? action : "wait";
  }
  if ($("signalNow")) $("signalNow").textContent = plan.now_text || pred.no_trade_reason || pred.horizon || "";
  if ($("signalCmd")) $("signalCmd").textContent = plan.command || pred.summary || "";
  if ($("signalQuality")) {
    const q = pred.quality_fa || "";
    const ev = pred.evidence || {};
    const oos = ev.oos || {};
    const bits = [
      q ? `کیفیت: ${q}` : "",
      pred.primary_strategy_fa ? `استراتژی: ${pred.primary_strategy_fa}` : "",
      oos.expectancy != null ? `EV خارج‌نمونه: ${oos.expectancy}R` : "",
      oos.trades != null ? `${oos.trades} معامله OOS` : "",
      pred.holding_period ? `نگهداری: ${pred.holding_period}` : "",
    ].filter(Boolean);
    $("signalQuality").textContent = bits.join(" · ");
  }
  if ($("signalInvalid")) {
    $("signalInvalid").textContent = pred.invalidation ? `ابطال: ${pred.invalidation}` : (pred.no_trade_reason || "");
  }
  const points = document.querySelector(".signal-points");
  if (points) points.classList.toggle("is-watch", action === "wait");
  const buySmall = document.querySelector(".point.buy small");
  const sellSmall = document.querySelector(".point.sell small");
  if (buySmall) buySmall.textContent = action === "wait" ? "سطح دیده‌بان خرید" : "از این نقطه بخر";
  if (sellSmall) sellSmall.textContent = action === "wait" ? "سطح دیده‌بان فروش" : "از این نقطه بفروش";
  if ($("buyAt")) $("buyAt").textContent = plan.buy_at ? formatPrice(plan.buy_at, ticker) : "—";
  if ($("sellAt")) $("sellAt").textContent = plan.sell_at ? formatPrice(plan.sell_at, ticker) : "—";
  if ($("buySl")) $("buySl").textContent = plan.buy_sl ? formatPrice(plan.buy_sl, ticker) : "—";
  if ($("sellSl")) $("sellSl").textContent = plan.sell_sl ? formatPrice(plan.sell_sl, ticker) : "—";
  if ($("buyTp")) $("buyTp").textContent = plan.buy_tp ? formatPrice(plan.buy_tp, ticker) : "—";
  if ($("sellTp")) $("sellTp").textContent = plan.sell_tp ? formatPrice(plan.sell_tp, ticker) : "—";
  if ($("buyOdds")) $("buyOdds").textContent = plan.buy_success != null ? plan.buy_success + "٪" : "—";
  if ($("sellOdds")) $("sellOdds").textContent = plan.sell_success != null ? plan.sell_success + "٪" : "—";
  if ($("signalOdds")) {
    const odds = action === "wait" ? (pred.confidence != null ? pred.confidence : "—") : (plan.success_pct != null ? plan.success_pct : pred.probability);
    $("signalOdds").textContent = (odds != null ? odds : "—") + "٪";
  }
  if ($("signalRR")) {
    if (action === "wait") $("signalRR").textContent = "سیگنال فعال نیست";
    else {
      const rr = action === "sell" ? (plan.sell_rr || plan.min_rr) : (plan.buy_rr || plan.min_rr);
      $("signalRR").textContent = `حداقل سود ${rr || 2} برابر حد ضرر`;
    }
  }
  if ($("signalNote")) $("signalNote").textContent = plan.disclaimer || pred.disclaimer || "سیگنال آموزشی است؛ قطعی نیست.";
  fillMtCopy(plan);
  $("predLabel").textContent = pred.label;
  $("predHorizon").textContent = pred.horizon;
  $("predConfLevel").textContent = pred.confidence_fa ? `اطمینان ${pred.confidence_fa} (${pred.confidence}٪)` : "";
  $("predProb").textContent = (pred.probability != null ? pred.probability : pred.confidence) + "٪";
  $("predTarget").textContent = formatPrice(pred.target_price, ticker);
  $("predChange").textContent = pctText(pred.change_pct);
  $("predChange").className = pctClass(pred.change_pct);
  const zone = pred.entry_zone || [];
  $("predEntry").textContent = zone.length === 2 ? `${formatPrice(zone[0], ticker)} – ${formatPrice(zone[1], ticker)}` : "—";
  $("predSl").textContent = pred.stop_loss ? formatPrice(pred.stop_loss, ticker) : "—";
  $("predTp").textContent = pred.tp1 ? `${formatPrice(pred.tp1, ticker)} / ${formatPrice(pred.tp2, ticker)}` : "—";
  const dirEl = document.querySelector(".pred-dir");
  if (dirEl) dirEl.dataset.dir = pred.direction;
  const chips = [];
  if (pred.quality_fa) chips.push(pred.quality_fa);
  if (pred.regime_fa) chips.push(`رژیم: ${pred.regime_fa}`);
  if (pred.volatility_fa) chips.push(`نوسان: ${pred.volatility_fa}`);
  if (pred.session) chips.push(`سشن: ${pred.session}`);
  if (pred.structure && pred.structure.trend) chips.push(`ساختار: ${pred.structure.trend}`);
  if (pred.news_risk) chips.push(`ریسک خبر: ${pred.news_risk === "high" ? "بالا" : pred.news_risk === "medium" ? "متوسط" : "پایین"}`);
  if (pred.ml && pred.ml.hit_rate != null) chips.push(`ML hit-rate: ${pred.ml.hit_rate}٪`);
  if (pred.risk_reward) chips.push(`R/R ${pred.risk_reward}`);
  if (pred.evidence && pred.evidence.has_edge === false) chips.push("بدون لبه OOS");
  $("predChips").innerHTML = chips.map((c) => `<i>${c}</i>`).join("");
  const layerNames = {
    structure: "ساختار",
    indicators: "تکنیکال",
    candles: "کندل",
    volume: "حجم",
    stats: "آمار",
    ml: "ML",
    mtf: "چندبازه",
    session: "سشن",
    sentiment: "احساسات",
  };
  const layers = pred.layers || {};
  $("layerBars").innerHTML = Object.keys(layerNames).filter((k) => layers[k] != null).map((k) => `
    <div><b><span>${layerNames[k]}</span><span>${layers[k]}٪</span></b><u><i style="width:${layers[k]}%"></i></u></div>
  `).join("");
  $("predReasons").innerHTML = (pred.reasons || []).slice(0, 8).map((r) => `<li class="${r.bias || ""}">${r.text}</li>`).join("");
  $("predRisks").textContent = (pred.risks || []).join(" · ");
  $("predSummary").textContent = `${pred.summary || ""} ${pred.volume_note || ""} ${pred.disclaimer || ""}`;
}

function gaugeSvg(pct, signal) {
  const color = signal === "buy" ? "#22c55e" : signal === "sell" ? "#ef4444" : "#eab308";
  const r = 46;
  const c = Math.PI * r;
  const dash = (Math.max(4, Math.min(100, pct)) / 100) * c;
  return `
    <svg viewBox="0 0 120 72">
      <path d="M14 62 A 46 46 0 0 1 106 62" fill="none" stroke="rgba(148,163,184,0.18)" stroke-width="10" stroke-linecap="round"/>
      <path d="M14 62 A 46 46 0 0 1 106 62" fill="none" stroke="${color}" stroke-width="10" stroke-linecap="round"
        stroke-dasharray="${dash} ${c}" />
    </svg>`;
}

function fmtInd(v) {
  if (v == null) return "—";
  if (Math.abs(v) >= 1000) return v.toLocaleString("en-US", { maximumFractionDigits: 2 });
  if (Math.abs(v) >= 1) return v.toLocaleString("en-US", { maximumFractionDigits: 2 });
  return v.toLocaleString("en-US", { maximumFractionDigits: 4 });
}

function renderGauges(ind) {
  const items = [
    { key: "rsi", title: "RSI (14)", value: ind.rsi?.value, signal: ind.rsi?.signal, label: ind.rsi?.label, gauge: ind.rsi?.gauge },
    { key: "macd", title: "MACD (12, 26)", value: ind.macd?.value, signal: ind.macd?.signal, label: ind.macd?.label, gauge: ind.macd?.gauge },
    { key: "ma50", title: "MA (50)", value: ind.ma50?.value, signal: ind.ma50?.signal, label: ind.ma50?.label, gauge: ind.ma50?.gauge },
    { key: "ma200", title: "MA (200)", value: ind.ma200?.value, signal: ind.ma200?.signal, label: ind.ma200?.label, gauge: ind.ma200?.gauge },
    { key: "boll", title: "BOLL", value: ind.boll?.label, signal: ind.boll?.signal, label: ind.boll?.label, gauge: ind.boll?.gauge, skipVal: true },
  ];
  $("gauges").innerHTML = items.map((it) => `
    <article class="gauge">
      ${gaugeSvg(it.gauge ?? 50, it.signal || "neutral")}
      <div class="g-title">${it.title}</div>
      ${it.skipVal ? "" : `<div class="g-val">${fmtInd(it.value)}</div>`}
      <div class="g-lab ${it.signal || "neutral"}">${it.label || "خنثی"}</div>
    </article>
  `).join("");
}

function destroyChart(ch) {
  if (ch) {
    try { ch.remove(); } catch (_) { /* ignore */ }
  }
}

function createChart(el, height) {
  const c = chartColors();
  return LightweightCharts.createChart(el, {
    layout: { background: { type: "solid", color: "transparent" }, textColor: c.text, fontFamily: "Vazirmatn, sans-serif" },
    grid: { vertLines: { color: c.grid }, horzLines: { color: c.grid } },
    rightPriceScale: { borderColor: c.grid },
    timeScale: { borderColor: c.grid, timeVisible: true, secondsVisible: false },
    crosshair: { vertLine: { color: c.cross }, horzLine: { color: c.cross } },
    width: el.clientWidth,
    height: height || el.clientHeight || 360,
  });
}

function renderCharts(data) {
  const host = $("mainChart");
  const extra = $("extraChart");
  destroyChart(mainChart);
  destroyChart(extraChart);
  overlaySeries.sma = overlaySeries.ema = overlaySeries.bollU = overlaySeries.bollM = overlaySeries.bollL = null;
  forecastSeries = candleSeries = lineSeries = volumeSeries = extraSeries = null;

  const showExtra = state.indicators.rsi || state.indicators.macd;
  extra.hidden = !showExtra;
  host.style.height = showExtra ? "280px" : "360px";

  mainChart = createChart(host, host.clientHeight);
  const c = chartColors();

  if (state.chartType === "line") {
    lineSeries = mainChart.addLineSeries({ color: "#6d7cff", lineWidth: 2 });
    lineSeries.setData(data.candles.map((k) => ({ time: k.time, value: k.close })));
    addPlanLines(lineSeries, data.prediction);
  } else {
    candleSeries = mainChart.addCandlestickSeries({
      upColor: c.up, downColor: c.down, borderVisible: false,
      wickUpColor: c.up, wickDownColor: c.down,
    });
    candleSeries.setData(data.candles);
    addPlanLines(candleSeries, data.prediction);
  }

  if (state.indicators.volume) {
    volumeSeries = mainChart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "vol",
    });
    mainChart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.78, bottom: 0 } });
    volumeSeries.setData(data.volume);
  }

  const ov = data.overlays || {};
  if (state.indicators.sma) {
    overlaySeries.sma = mainChart.addLineSeries({ color: "#60a5fa", lineWidth: 1, priceLineVisible: false });
    overlaySeries.sma.setData(ov.sma50 || []);
  }
  if (state.indicators.ema) {
    overlaySeries.ema = mainChart.addLineSeries({ color: "#f59e0b", lineWidth: 1, priceLineVisible: false });
    overlaySeries.ema.setData(ov.ema21 || []);
  }
  if (state.indicators.boll) {
    overlaySeries.bollU = mainChart.addLineSeries({ color: "#a78bfa", lineWidth: 1, priceLineVisible: false, lineStyle: 2 });
    overlaySeries.bollM = mainChart.addLineSeries({ color: "#818cf8", lineWidth: 1, priceLineVisible: false });
    overlaySeries.bollL = mainChart.addLineSeries({ color: "#a78bfa", lineWidth: 1, priceLineVisible: false, lineStyle: 2 });
    overlaySeries.bollU.setData(ov.bb_upper || []);
    overlaySeries.bollM.setData(ov.bb_mid || []);
    overlaySeries.bollL.setData(ov.bb_lower || []);
  }

  if (state.showForecast && data.prediction?.forecast?.length) {
    forecastSeries = mainChart.addLineSeries({
      color: "#c084fc", lineWidth: 2, lineStyle: 2, priceLineVisible: false, lastValueVisible: true,
    });
    forecastSeries.setData(data.prediction.forecast);
  }

  mainChart.timeScale().fitContent();

  if (showExtra) {
    extraChart = createChart(extra, 120);
    if (state.indicators.rsi) {
      extraSeries = extraChart.addLineSeries({ color: "#22d3ee", lineWidth: 2 });
      extraSeries.setData(ov.rsi || []);
      extraSeries.createPriceLine({ price: 70, color: "#ef4444", lineStyle: 2, lineWidth: 1, axisLabelVisible: true, title: "70" });
      extraSeries.createPriceLine({ price: 30, color: "#22c55e", lineStyle: 2, lineWidth: 1, axisLabelVisible: true, title: "30" });
    } else {
      extraSeries = extraChart.addHistogramSeries({ color: "#6d7cff" });
      extraSeries.setData(ov.macd_hist || []);
      const macdLine = extraChart.addLineSeries({ color: "#60a5fa", lineWidth: 1, priceLineVisible: false });
      macdLine.setData(ov.macd || []);
    }
    extraChart.timeScale().fitContent();
    mainChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (range) extraChart.timeScale().setVisibleLogicalRange(range);
    });
  }

  if (state.page === "charts") renderBigChart(data);
}

function renderBigChart(data) {
  const el = $("bigChart");
  if (!el) return;
  destroyChart(bigChart);
  bigChart = createChart(el, el.clientHeight);
  const c = chartColors();
  const s = bigChart.addCandlestickSeries({
    upColor: c.up, downColor: c.down, borderVisible: false,
    wickUpColor: c.up, wickDownColor: c.down,
  });
  s.setData(data.candles || []);
  const v = bigChart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "vol" });
  bigChart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
  v.setData(data.volume || []);
  bigChart.timeScale().fitContent();
}

function refreshChartData(data) {
  const candles = data.candles || [];
  try {
    if (state.chartType === "line" && lineSeries) {
      lineSeries.setData(candles.map((k) => ({ time: k.time, value: k.close })));
    } else if (candleSeries) {
      candleSeries.setData(candles);
    } else {
      renderCharts(data);
      return;
    }
    if (volumeSeries && data.volume) volumeSeries.setData(data.volume);
    const ov = data.overlays || {};
    if (overlaySeries.sma) overlaySeries.sma.setData(ov.sma50 || []);
    if (overlaySeries.ema) overlaySeries.ema.setData(ov.ema21 || []);
    if (overlaySeries.bollU) overlaySeries.bollU.setData(ov.bb_upper || []);
    if (overlaySeries.bollM) overlaySeries.bollM.setData(ov.bb_mid || []);
    if (overlaySeries.bollL) overlaySeries.bollL.setData(ov.bb_lower || []);
    if (forecastSeries && data.prediction?.forecast) forecastSeries.setData(data.prediction.forecast);
    if (extraSeries) {
      if (state.indicators.rsi) extraSeries.setData(ov.rsi || []);
      else extraSeries.setData(ov.macd_hist || []);
    }
  } catch (_) {
    renderCharts(data);
  }
}

function showDecision(title, text) {
  const el = $("decisionOverlay");
  if (!el) return;
  if ($("decisionTitle")) $("decisionTitle").textContent = title || "در حال تصمیم‌گیری";
  if ($("decisionText")) $("decisionText").textContent = text || "اندیکاتورها و مدل در حال جمع‌بندی هستند...";
  el.hidden = false;
  $("predBanner")?.classList.add("is-thinking");
  setLiveStatus("busy", title || "در حال تصمیم‌گیری");
}

function hideDecision() {
  const el = $("decisionOverlay");
  if (el) el.hidden = true;
  $("predBanner")?.classList.remove("is-thinking");
}

function patchLastCandle(price) {
  if (price == null || !state.analysis?.candles?.length) return;
  const last = { ...state.analysis.candles[state.analysis.candles.length - 1] };
  last.close = price;
  last.high = Math.max(last.high, price);
  last.low = Math.min(last.low, price);
  state.analysis.candles[state.analysis.candles.length - 1] = last;
  try {
    if (candleSeries) candleSeries.update(last);
    if (lineSeries) lineSeries.update({ time: last.time, value: last.close });
  } catch (_) { /* ignore */ }
}

function syncChartToTicker(data) {
  const price = data?.ticker?.price;
  if (price == null || !data?.candles?.length) return data;
  const last = { ...data.candles[data.candles.length - 1] };
  last.close = price;
  last.high = Math.max(last.high, price);
  last.low = Math.min(last.low, price);
  data.candles[data.candles.length - 1] = last;
  return data;
}

function applyLivePrice(ticker) {
  if (!ticker || (ticker.symbol && ticker.symbol !== state.symbol)) return;
  renderPrices(ticker);
  if (state.analysis) {
    state.analysis.ticker = { ...state.analysis.ticker, ...ticker };
    patchLastCandle(ticker.price);
  }
}

async function loadAnalysis(opts = {}) {
  const silent = !!opts.silent;
  const reason = opts.reason || "refresh";
  const interval = state.pendingInterval || state.interval;
  const symbol = state.symbol;
  const seq = ++analysisSeq;
  if (!silent) {
    const label = TIMEFRAMES.find((t) => t.id === interval)?.label || interval;
    showDecision(
      reason === "interval" ? "در حال تصمیم‌گیری" : "در حال به‌روزرسانی",
      opts.message || `مدل در حال بررسی بازه ${label} است...`
    );
    $("refreshBtn")?.classList.add("spinning");
  }
  try {
    const data = await api(`/api/analysis?symbol=${encodeURIComponent(symbol)}&interval=${interval}`);
    if (seq !== analysisSeq || symbol !== state.symbol) return;
    state.interval = interval;
    if (state.pendingInterval === interval) state.pendingInterval = null;
    state.analysis = data;
    lastPrice = data.ticker?.price ?? lastPrice;
    renderPairButton(data.ticker);
    renderPrices(data.ticker);
    renderPerformance(data.performance);
    renderPrediction(data.prediction);
    renderGauges(data.indicators);
    syncChartToTicker(data);
    const key = `${symbol}:${interval}:${state.chartType}:${document.documentElement.getAttribute("data-theme")}`;
    if (silent && key === chartKey && mainChart) refreshChartData(data);
    else {
      chartKey = key;
      renderCharts(data);
    }
    setWatchButton();
    buildTimeframes();
  } catch (err) {
    if (seq !== analysisSeq) return;
    toast(err.message);
    setLiveStatus("lag", err.message);
    if (state.pendingInterval === interval) state.pendingInterval = null;
    buildTimeframes();
  } finally {
    if (seq === analysisSeq) {
      hideDecision();
      $("refreshBtn")?.classList.remove("spinning");
    }
  }
}

function renderPairList(filter = "") {
  const q = filter.trim().toLowerCase();
  const list = $("pairList");
  const match = (c) => {
    const blob = `${c.base} ${c.name_en} ${c.name_fa} ${c.symbol} ${c.keywords || ""}`.toLowerCase();
    return !q || blob.includes(q);
  };
  const macros = state.coins.filter((c) => c.category === "macro" && match(c));
  const rest = state.coins.filter((c) => c.category !== "macro" && match(c)).slice(0, 80);
  const itemHtml = (c) => `
    <button class="pair-item ${c.symbol === state.symbol ? "active" : ""}" data-symbol="${c.symbol}">
      <img src="${c.icon}" alt="" onerror="this.style.visibility='hidden'" />
      <span>${c.name_fa} · ${c.name_en}</span>
      <small>${c.base}</small>
    </button>`;
  let html = "";
  if (macros.length) html += `<div class="pair-group">بازارهای جهانی</div>` + macros.map(itemHtml).join("");
  if (rest.length) html += `<div class="pair-group">رمزارز</div>` + rest.map(itemHtml).join("");
  list.innerHTML = html || `<p class="muted" style="padding:8px">موردی پیدا نشد</p>`;
  list.querySelectorAll(".pair-item").forEach((btn) => {
    btn.onclick = () => selectSymbol(btn.dataset.symbol);
  });
}

function selectSymbol(symbol) {
  $("pairMenu").hidden = true;
  if (symbol !== state.symbol) {
    state.symbol = symbol;
    localStorage.setItem("ca_symbol", symbol);
    chartKey = "";
    lastPrice = null;
  }
  loadAnalysis({ reason: "symbol", message: "در حال بارگذاری نماد و تصمیم‌گیری..." });
  if (state.page === "analysis") loadPredictions();
  if (state.page === "outlook") loadOutlook();
}

async function loadCoins() {
  try {
    state.coins = await api("/api/coins");
    renderPairList();
  } catch (err) {
    toast(err.message);
  }
}

async function loadMarkets() {
  try {
    const rows = await api("/api/markets");
    const q = ($("marketSearch").value || "").toLowerCase();
    const filtered = rows.filter((r) => `${r.base} ${r.name_en} ${r.name_fa}`.toLowerCase().includes(q));
    $("marketBody").innerHTML = filtered.slice(0, 80).map((r) => `
      <tr data-symbol="${r.symbol}">
        <td><div class="coin-cell"><img src="${r.icon}" onerror="this.style.visibility='hidden'" /><span>${r.name_fa} <small>${r.base}</small></span></div></td>
        <td>${formatPrice(r.price, r)}</td>
        <td class="${pctClass(r.change_24h)}">${pctText(r.change_24h)}</td>
        <td>${formatCompact(r.volume_24h)}</td>
        <td>${formatCompact(r.market_cap)}</td>
      </tr>
    `).join("");
    $("marketBody").querySelectorAll("tr").forEach((tr) => {
      tr.onclick = () => {
        selectSymbol(tr.dataset.symbol);
        goPage("dashboard");
      };
    });
  } catch (err) {
    toast(err.message);
  }
}

let alertLoadInFlight = null;

async function loadAlerts(opts) {
  const silent = !!(opts && opts.silent);
  const live = $("alertLive");
  if (alertLoadInFlight) {
    try {
      await alertLoadInFlight;
    } catch (_) { /* continue */ }
    if (silent) return;
  }
  if (!silent) {
    $("alertHeadline").textContent = "در حال اسکن طلا، یورو، دلار و ارزهای اصلی...";
    if (live) live.textContent = "اسکن جدید...";
  } else if (live) {
    live.textContent = "بروزرسانی خودکار...";
  }
  const extra = (state.watchlist || []).join(",");
  const min = Number(state.alertMinOdds) || 50;
  const run = (async () => {
    const data = await api(`/api/alerts?extra=${encodeURIComponent(extra)}&min_odds=${encodeURIComponent(min)}`);
    renderAlertBoard(data);
    processHotAlerts(data);
    if (live) {
      const t = new Date();
      const hh = String(t.getHours()).padStart(2, "0");
      const mm = String(t.getMinutes()).padStart(2, "0");
      const ss = String(t.getSeconds()).padStart(2, "0");
      const n = (data.buys || []).length + (data.sells || []).length;
      live.textContent = `آخرین بروزرسانی ${hh}:${mm}:${ss} · فیلتر ≥${min}٪ · پیشنهاد فعال: ${n}`;
    }
    return data;
  })();
  alertLoadInFlight = run;
  try {
    await run;
  } catch (err) {
    $("alertHeadline").textContent = err.message;
    if (live) live.textContent = "خطا در اسکن — دوباره تلاش می‌شود";
    if (!silent) toast(err.message);
  } finally {
    if (alertLoadInFlight === run) alertLoadInFlight = null;
  }
}

function renderAlertBoard(data) {
  if (!$("alertHeadline")) return;
  $("alertHeadline").textContent = data.headline || "";
  $("alertNote").textContent = data.disclaimer || "";
  const heroes = [data.best_buy, data.best_sell].filter(Boolean);
  $("alertHeroes").innerHTML = heroes.map(alertHeroHtml).join("") || "<p class='muted'>الان پیشنهاد فعالی بالای فیلترت نیست. دیده‌بان و رتبه‌بندی پایین را ببین.</p>";
  $("alertBuys").innerHTML = (data.buys || []).map(alertRowHtml).join("") || "<p class='muted'>خرید فعالی بالای فیلتر نیست.</p>";
  $("alertSells").innerHTML = (data.sells || []).map(alertRowHtml).join("") || "<p class='muted'>فروش فعالی بالای فیلتر نیست.</p>";
  if ($("alertWaits")) {
    $("alertWaits").innerHTML = (data.watched || []).map(alertRowHtml).join("") || "<p class='muted'>موردی در دیده‌بان نیست.</p>";
  }
  if ($("alertResearch")) {
    $("alertResearch").innerHTML = (data.research || []).map(alertRowHtml).join("") || "<p class='muted'>—</p>";
  }
  if ($("alertNoTrade")) {
    $("alertNoTrade").innerHTML = (data.no_trade || []).map(alertRowHtml).join("") || "";
  }
}

function collectHotAlerts(data) {
  const min = Number(state.alertMinOdds) || 50;
  const rows = [...(data.buys || []), ...(data.sells || [])];
  return rows.filter((a) =>
    (a.action === "buy" || a.action === "sell") &&
    Number(a.success_pct || a.probability || 0) >= min
  );
}

function processHotAlerts(data, opts) {
  const hot = collectHotAlerts(data);
  const force = !!(opts && opts.force);
  const dot = $("alertNavDot");
  if (dot) dot.hidden = !hot.length;
  syncAlertArmUi(hot);
  if (document.hidden && hot.length) document.title = "🔔 هشدار معامله";
  else if (!document.hidden) document.title = PAGE_TITLE;
  if (!alertArmed || !state.alertSound || !hot.length) return;
  const now = Date.now();
  const due = [];
  hot.forEach((a) => {
    const key = `${a.symbol}:${a.action}`;
    if (force) delete lastAlertNotify[key];
    const prev = lastAlertNotify[key];
    const pct = Number(a.success_pct || 0);
    if (prev && now - prev.at < 3 * 60 * 1000 && pct < prev.pct + 5) return;
    due.push(a);
  });
  due.sort((a, b) => Number(b.success_pct) - Number(a.success_pct));
  if (!due.length) return;
  // One clear beep burst, then notifications.
  playAlertSound();
  due.slice(0, 3).forEach((a) => {
    lastAlertNotify[`${a.symbol}:${a.action}`] = { at: now, pct: Number(a.success_pct || 0) };
    showTradeNotification(a);
  });
  sessionStorage.setItem("ca_alert_fired", JSON.stringify(lastAlertNotify));
}

function ensureAudio() {
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) return null;
  if (!audioCtx) audioCtx = new AC();
  return audioCtx;
}

async function unlockAudio() {
  audioUnlocked = true;
  const ctx = ensureAudio();
  if (ctx && ctx.state === "suspended") {
    try { await ctx.resume(); } catch (_) { /* fallback below */ }
  }
  return ctx;
}

async function playWebBeep() {
  const ctx = await unlockAudio();
  if (!ctx) throw new Error("no-webaudio");
  if (ctx.state === "suspended") await ctx.resume();
  const now = ctx.currentTime + 0.02;
  [880, 1175, 1568].forEach((freq, i) => {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    const t0 = now + i * 0.15;
    osc.frequency.setValueAtTime(freq, t0);
    gain.gain.setValueAtTime(0.001, t0);
    gain.gain.linearRampToValueAtTime(0.28, t0 + 0.025);
    gain.gain.linearRampToValueAtTime(0.001, t0 + 0.28);
    osc.connect(gain).connect(ctx.destination);
    osc.start(t0);
    osc.stop(t0 + 0.3);
  });
}

function playHtmlBeep() {
  return new Promise((resolve, reject) => {
    try {
      const audio = new Audio(ALERT_BEEP_WAV);
      audio.volume = 0.85;
      audio.onended = () => resolve(true);
      audio.onerror = () => reject(new Error("html-audio-fail"));
      const p = audio.play();
      if (p && p.then) p.then(() => {}).catch(reject);
    } catch (err) {
      reject(err);
    }
  });
}

async function playAlertSound() {
  try {
    await playWebBeep();
    return true;
  } catch (_) {
    try {
      await playHtmlBeep();
      return true;
    } catch (err2) {
      console.warn("alert sound blocked", err2);
      toast("مرورگر صدا را مسدود کرد — روی «تست صدا» یا فعال‌سازی کلیک کن");
      return false;
    }
  }
}

async function testAlertSound() {
  state.alertSound = true;
  if ($("alertSoundOn")) $("alertSoundOn").checked = true;
  localStorage.setItem("ca_alert_sound", "1");
  const ok = await playAlertSound();
  if (ok) toast("اگر شنیدی، صدا آماده است");
}

async function toggleAlertArm() {
  if (alertArmed) {
    alertArmed = false;
    localStorage.setItem("ca_alert_arm", "0");
    syncAlertArmUi();
    toast("هشدار صوتی خاموش شد");
    return;
  }
  const ok = await playAlertSound();
  if ("Notification" in window && Notification.permission !== "granted") {
    try {
      const perm = await Notification.requestPermission();
      if (perm !== "granted") toast("نوتیفیکیشن سیستم فعال نشد؛ صدا روی همین تب کار می‌کند.");
    } catch (_) { /* ignore */ }
  }
  if (!ok) {
    syncAlertArmUi();
    return;
  }
  alertArmed = true;
  localStorage.setItem("ca_alert_arm", "1");
  lastAlertNotify = {};
  sessionStorage.removeItem("ca_alert_fired");
  syncAlertArmUi();
  toast("هشدار صوتی فعال شد");
  try {
    await loadAlerts({ silent: true });
  } catch (_) { /* next poll */ }
}

function showTradeNotification(a) {
  const verb = a.action === "buy" ? "Buy" : "Sell";
  const title = `${verb} ${a.mt_symbol || mtSymbol(a.symbol)}`;
  const body = [
    `احتمال ${a.success_pct}٪`,
    a.entry ? `Price ${mtPrice(a.entry)}` : "",
    a.stop_loss ? `SL ${mtPrice(a.stop_loss)}` : "",
    a.tp1 ? `TP ${mtPrice(a.tp1)}` : "",
  ].filter(Boolean).join(" · ");
  if (!("Notification" in window) || Notification.permission !== "granted") {
    toast(`${title} · ${body}`);
    return;
  }
  const note = new Notification(title, {
    body,
    tag: "trendix-" + a.symbol,
    dir: "rtl",
    lang: "fa",
    requireInteraction: true,
  });
  note.onclick = () => {
    window.focus();
    selectSymbol(a.symbol);
    goPage("dashboard");
    note.close();
  };
}

function syncAlertArmUi(hot) {
  const btn = $("alertArmBtn");
  if (btn) {
    btn.classList.toggle("on", alertArmed);
    btn.textContent = alertArmed ? "هشدار صوتی فعال است" : "فعال کردن هشدار صوتی";
  }
  const status = $("alertArmStatus");
  if (!status) return;
  const min = state.alertMinOdds || 50;
  if (!alertArmed) {
    status.textContent = "صدا خاموش است. «فعال کردن هشدار صوتی» یا «تست صدا» را بزن.";
    return;
  }
  if (!state.alertSound) {
    status.textContent = "هشدار روشن است ولی تیک «صدا» خاموش است.";
    return;
  }
  if (hot && hot.length) {
    status.textContent = "آمادهٔ پخش: " + hot.map((a) => `${a.name_fa} ${a.success_pct}٪ ${a.action === "buy" ? "بخر" : "بفروش"}`).join(" · ");
    return;
  }
  status.textContent = `صدا فعال است — الان پیشنهاد فعالی ≥ ${min}٪ نیست؛ با آمدن پیشنهاد بوق می‌زند.`;
}

async function tickAlertWatch() {
  try {
    await loadAlerts({ silent: true });
  } catch (_) { /* next pass */ }
  const delay = document.hidden ? 45000 : 20000;
  alertWatchTimer = setTimeout(tickAlertWatch, delay);
}

async function loadAutotrade() {
  if (!$("atStatusBox")) return;
  $("atStatusBox").innerHTML = "<p class='muted'>در حال خواندن وضعیت...</p>";
  try {
    const data = await api("/api/autotrade/status");
    const cfg = data.config || {};
    if ($("atEnabled")) $("atEnabled").checked = !!cfg.enabled;
    if ($("atLogin") && !$("atLogin").value) $("atLogin").value = cfg.login || "";
    if ($("atServer")) $("atServer").value = cfg.server || "Alpari-MT5-Demo";
    if ($("atPath") && cfg.terminal_path) $("atPath").value = cfg.terminal_path;
    if ($("atMode")) $("atMode").value = cfg.mode || "intraday";
    if ($("atRisk")) $("atRisk").value = cfg.risk_percent ?? 0.5;
    if ($("atMaxPos")) $("atMaxPos").value = cfg.max_positions ?? 3;
    if ($("atMinOdds")) $("atMinOdds").value = cfg.min_odds ?? 50;
    const acc = data.account || (data.connection && data.connection.account);
    const lines = [
      `<p><b>کتابخانه MT5:</b> ${data.mt5_library ? "نصب است" : "نیست (روی این سیستم معامله اجرا نمی‌شود)"}</p>`,
      `<p><b>ذخیره رمز:</b> ${cfg.has_password ? "بله (محلی)" : "خیر"} · مسیر: <code>${cfg.store_path || "—"}</code></p>`,
      data.note ? `<p class="muted">${data.note}</p>` : "",
    ];
    if (acc) {
      lines.push(
        `<p><b>اکانت:</b> ${acc.login} @ ${acc.server} · موجودی ${Number(acc.balance).toFixed(2)} ${acc.currency} · `
        + `equity ${Number(acc.equity).toFixed(2)} · سود شناور ${Number(acc.profit).toFixed(2)}</p>`
      );
      lines.push(`<p><b>معامله مجاز:</b> ${acc.trade_allowed ? "بله" : "خیر"} · Expert: ${acc.trade_expert ? "بله" : "خیر"}</p>`);
    } else if (data.connection && data.connection.error) {
      lines.push(`<p class="warn">${data.connection.error}</p>`);
    }
    $("atStatusBox").innerHTML = lines.join("");
    renderAtPositions(data.open_positions || []);
    renderAtDeals(data.deals || []);
    renderAtLog(data.log || []);
  } catch (err) {
    $("atStatusBox").innerHTML = `<p class="warn">${err.message}</p>`;
  }
}

function renderAtPositions(rows) {
  const el = $("atPositions");
  if (!el) return;
  if (!rows.length) {
    el.innerHTML = "<p class='muted'>پوزیشن بازی از Trendix نیست.</p>";
    return;
  }
  el.innerHTML = `<table class="autotrade-table"><thead><tr>
    <th>تیکت</th><th>نماد</th><th>جهت</th><th>حجم</th><th>ورود</th><th>سود</th><th>سواپ</th>
  </tr></thead><tbody>${rows.map((p) => `<tr>
    <td>${p.ticket}</td><td>${p.symbol}</td><td>${p.type}</td><td>${p.volume}</td>
    <td>${p.price_open}</td><td class="${p.profit >= 0 ? "up" : "down"}">${Number(p.profit).toFixed(2)}</td>
    <td>${Number(p.swap).toFixed(2)}</td>
  </tr>`).join("")}</tbody></table>`;
}

function renderAtDeals(rows) {
  const el = $("atDeals");
  if (!el) return;
  if (!rows.length) {
    el.innerHTML = "<p class='muted'>هنوز معامله‌ای با magic ترندیکس نیست. در دمو، کمیسیون ممکن است صفر و اسپرد در قیمت باشد.</p>";
    return;
  }
  el.innerHTML = `<table class="autotrade-table"><thead><tr>
    <th>زمان</th><th>نماد</th><th>نوع</th><th>حجم</th><th>قیمت</th><th>سود</th><th>کمیسیون</th><th>سواپ</th>
  </tr></thead><tbody>${rows.map((d) => {
    const t = d.time ? new Date(d.time * 1000).toLocaleString("fa-IR") : "—";
    return `<tr>
      <td>${t}</td><td>${d.symbol}</td><td>${d.type}</td><td>${d.volume}</td><td>${d.price}</td>
      <td class="${Number(d.profit) >= 0 ? "up" : "down"}">${Number(d.profit).toFixed(2)}</td>
      <td>${Number(d.commission).toFixed(2)}</td><td>${Number(d.swap).toFixed(2)}</td>
    </tr>`;
  }).join("")}</tbody></table>`;
}

function renderAtLog(rows) {
  const el = $("atLog");
  if (!el) return;
  if (!rows.length) {
    el.innerHTML = "<p class='muted'>لاگ خالی است.</p>";
    return;
  }
  el.innerHTML = `<table class="autotrade-table"><thead><tr>
    <th>زمان</th><th>نماد</th><th>جهت</th><th>لات</th><th>نتیجه</th>
  </tr></thead><tbody>${rows.map((r) => {
    const t = r.ts ? new Date(r.ts * 1000).toLocaleString("fa-IR") : "—";
    const ok = r.result && r.result.ok;
    return `<tr>
      <td>${t}</td><td>${r.mt_symbol || r.trendix}</td><td>${r.side}</td><td>${r.lot ?? "—"}</td>
      <td class="${ok ? "up" : "down"}">${ok ? "OK" : (r.result && r.result.error) || "—"}</td>
    </tr>`;
  }).join("")}</tbody></table>`;
}

async function saveAutotradeConfig() {
  const payload = {
    enabled: !!($("atEnabled") && $("atEnabled").checked),
    login: ($("atLogin") && $("atLogin").value.trim()) || "",
    password: ($("atPassword") && $("atPassword").value) || "",
    server: ($("atServer") && $("atServer").value.trim()) || "Alpari-MT5-Demo",
    terminal_path: ($("atPath") && $("atPath").value.trim()) || "",
    mode: ($("atMode") && $("atMode").value) || "intraday",
    risk_percent: Number($("atRisk") && $("atRisk").value) || 0.5,
    max_positions: Number($("atMaxPos") && $("atMaxPos").value) || 3,
    min_odds: Number($("atMinOdds") && $("atMinOdds").value) || 50,
  };
  const res = await fetch("/api/autotrade/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || "ذخیره نشد");
  if ($("atPassword")) $("atPassword").value = "";
  toast("تنظیمات ذخیره شد");
  await loadAutotrade();
}

async function testAutotrade() {
  toast("در حال تست اتصال...");
  const res = await fetch("/api/autotrade/test", { method: "POST" });
  const body = await res.json().catch(() => ({}));
  if (body.ok) toast(`وصل شد · equity ${(body.account && body.account.equity) || "—"}`);
  else toast(body.error || "اتصال ناموفق");
  await loadAutotrade();
}

async function runAutotradeOnce() {
  toast("یک دور اسکن و معامله...");
  const res = await fetch("/api/autotrade/run", { method: "POST" });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || "اجرا نشد");
  const n = (body.placed || []).length;
  toast(body.ok ? `انجام شد · معاملات جدید: ${n}` : (body.error || body.reason || "رد شد"));
  await loadAutotrade();
}

async function loadBacktest() {
  const ticker = (state.analysis && state.analysis.ticker) || {};
  if ($("btPair")) $("btPair").textContent = ticker.name_fa ? `${ticker.name_fa} · ${state.interval}` : state.symbol;
  if ($("btStats")) $("btStats").innerHTML = "<p class='muted'>در حال اجرای استراتژی روی کندل‌های قبلی با هزینه معامله...</p>";
  if ($("btTrades")) $("btTrades").innerHTML = "";
  if ($("btEquity")) $("btEquity").innerHTML = "";
  if ($("btVerdict")) $("btVerdict").textContent = "";
  try {
    const data = await api(`/api/backtest?symbol=${encodeURIComponent(state.symbol)}&interval=${state.interval}`);
    const s = data.stats || {};
    const oos = data.out_of_sample || {};
    const ins = data.in_sample || {};
    if ($("btPair")) $("btPair").textContent = `${(data.ticker || ticker).name_fa || state.symbol} · ${data.horizon || state.interval}`;
    if (!data.ok) {
      $("btStats").innerHTML = `<p class="muted">${data.error || "بک‌تست انجام نشد"}</p>`;
      return;
    }
    if ($("btVerdict")) {
      $("btVerdict").textContent = data.verdict || "";
      $("btVerdict").dataset.edge = data.has_edge ? "yes" : (data.retired ? "no" : "weak");
    }
    const cell = (label, value, cls) => `<div><span>${label}</span><b class="${cls || ""}">${value ?? "—"}</b></div>`;
    $("btStats").innerHTML = [
      cell("معامله‌ها", s.trades ?? 0),
      cell("برد", s.win_rate != null ? s.win_rate + "٪" : "—"),
      cell("امید ریاضی", s.expectancy, (s.expectancy || 0) >= 0 ? "up" : "down"),
      cell("ضریب سود", s.profit_factor ?? "—"),
      cell("شارپ", s.sharpe ?? "—"),
      cell("سورتینو", s.sortino ?? "—"),
      cell("حداکثر افت", (s.max_dd_r ?? "—") + " R"),
      cell("ریکاوری", s.recovery_factor ?? "—"),
      cell("میانگین برد", s.avg_win ?? "—"),
      cell("میانگین باخت", s.avg_loss ?? "—"),
      cell("باخت متوالی", s.consecutive_losses ?? "—"),
      cell("زمان در معامله", s.exposure_pct != null ? s.exposure_pct + "٪" : "—"),
      cell("OOS معامله", oos.trades ?? 0),
      cell("OOS امید", oos.expectancy, (oos.expectancy || 0) >= 0 ? "up" : "down"),
      cell("IS امید", ins.expectancy, (ins.expectancy || 0) >= 0 ? "up" : "down"),
    ].join("") + `<p class="hint">${data.disclaimer || ""}</p>`
      + ((data.walk_forward || []).length
        ? `<p class="hint">Walk-forward: ${(data.walk_forward || []).map((f) => `${f.from_pct}–${f.to_pct}٪ EV ${f.expectancy}R (${f.trades} معامله)`).join(" · ")}</p>`
        : "");
    const eq = data.equity || [];
    const max = Math.max(1, ...eq.map((v) => Math.abs(v)));
    $("btEquity").innerHTML = eq.map((v) => {
      const h = Math.max(6, Math.round((Math.abs(v) / max) * 80));
      const color = v >= 0 ? "var(--green)" : "var(--red)";
      return `<i style="height:${h}px;background:${color}"></i>`;
    }).join("");
    $("btTrades").innerHTML = (data.trades || []).slice().reverse().map((t) => `
      <article>
        <div>
          <strong>${t.side_fa}</strong>
          <small> ورود ${t.entry} → خروج ${t.exit} · ${t.result_fa}${t.strategy ? " · " + t.strategy : ""}</small>
        </div>
        <b class="${t.win ? "win" : "loss"}">${t.pnl_r} R</b>
      </article>
    `).join("") || "<p class='muted'>معامله‌ای ثبت نشد — این هم نتیجه معتبر است.</p>";
  } catch (err) {
    if ($("btStats")) $("btStats").innerHTML = `<p class="muted">${err.message}</p>`;
    toast(err.message);
  }
}

function alertHeroHtml(a) {
  const odds = a.success_pct != null ? a.success_pct : a.probability;
  const hot = (a.action === "buy" || a.action === "sell") && (a.status === "alert" || a.quality === "high_conviction" || a.quality === "strong" || a.quality === "moderate");
  const side = a.action === "sell" ? "sell" : a.action === "buy" ? "buy" : "wait";
  const levels = a.action === "wait" ? "" : mtLevelsHtml(a, side);
  const live = mtPrice(a.price);
  const tier = a.quality === "high_conviction" ? "🔥 قانع‌کننده" : a.quality === "strong" ? "قوی" : (a.quality_fa || a.strength || "");
  const align = a.mtf_conflict ? "تضاد بازه‌ها" : (a.mtf_aligned ? "هم‌جهت HTF" : "");
  return `
    <article class="alert-hero ${a.action}${hot ? " hot" : ""}${a.mtf_conflict ? " conflict" : ""}" data-alert-symbol="${a.symbol}">
      <header>
        <img src="${a.icon}" alt="" onerror="this.style.visibility='hidden'" />
        <div>
          <strong>${a.name_fa}</strong>
          <small>${a.mt_symbol || mtSymbol(a.symbol)} · ${a.interval_fa || ""} · <code class="mt-num" data-copy="${live}">${live || "—"}</code></small>
        </div>
        <span class="badge">${tier} · ${odds ?? "—"}٪${align ? " · " + align : ""}</span>
      </header>
      <div class="cmd">${a.command}</div>
      <p>${a.detail}</p>
      ${tfStackHtml(a)}
      ${levels}
      <p class="alert-meta">R:R ۱ به ${a.rr || a.min_rr || 2} · ${a.holding_period || a.horizon || ""} · ${a.regime || "—"} · EV ${a.expectancy ?? "—"}R · ${a.primary_strategy || ""}</p>
      ${a.invalidation ? `<p class="alert-meta">ابطال: ${a.invalidation}</p>` : ""}
      <ul>${(a.reasons || []).map((r) => `<li>${r}</li>`).join("")}</ul>
    </article>`;
}

function tfStackHtml(a) {
  const stack = a.tf_stack || [];
  if (stack.length) {
    return `<div class="tf-stack">${stack.map((s) => {
      const lean = (s.side === "buy" || s.side === "sell") ? s.side : (s.lean || "wait");
      const cls = lean === "buy" ? "buy" : lean === "sell" ? "sell" : "wait";
      const edge = s.has_edge ? " edge" : "";
      const label = s.side === "buy" || s.side === "sell" ? s.side_fa : (s.lean_fa || s.side_fa || "صبر");
      const soft = (s.side !== "buy" && s.side !== "sell" && lean !== "wait") ? " soft" : "";
      return `<i class="${cls}${edge}${soft}" title="${s.regime || ""} ${s.strategy || ""}">${s.interval_fa} ${label}</i>`;
    }).join("")}</div>`;
  }
  if (a.setup_map) return `<p class="alert-meta setup-map">${a.setup_map}</p>`;
  return "";
}

function alertRowHtml(a) {
  const odds = a.success_pct != null ? a.success_pct : a.probability;
  const side = a.action === "sell" ? "sell" : a.action === "buy" ? "buy" : "";
  const levels = side && a.action !== "wait" ? mtLevelsHtml(a, side) : "";
  const act = a.action === "buy" ? "BUY" : a.action === "sell" ? "SELL" : (a.status === "edge_wait" ? "WAIT" : "NO TRADE");
  const evNum = a.expectancy != null ? Number(a.expectancy) : null;
  const evTxt = evNum != null ? ` · EV ${evNum >= 0 ? "+" : ""}${a.expectancy}R` : "";
  const align = a.mtf_conflict ? " · تضاد بازه‌ها" : (a.mtf_aligned ? " · هم‌جهت HTF" : "");
  return `
    <article class="alert-row ${a.action}${a.mtf_conflict ? " conflict" : ""}" data-alert-symbol="${a.symbol}">
      <img src="${a.icon}" alt="" />
      <div class="alert-row-body">
        <div class="alert-row-top">
          <strong>${a.name_fa}</strong>
          <span class="act">${act}</span>
        </div>
        <small>${a.mt_symbol || mtSymbol(a.symbol)} · ${a.interval_fa || "—"} · ${a.quality_fa || a.strength || ""}${evTxt}${align}${odds ? " · " + odds + "٪" : ""}</small>
        <small>${a.detail || ""}</small>
        ${tfStackHtml(a)}
        ${levels}
      </div>
    </article>`;
}

async function loadOutlook() {
  const ticker = (state.analysis && state.analysis.ticker) || {};
  $("outlookPair").textContent = ticker.name_fa ? `${ticker.name_fa} · ${state.symbol}` : state.symbol;
  $("briefHero").innerHTML = "<p class='muted'>در حال نوشتن خلاصه از همهٔ بازه‌ها...</p>";
  $("briefGrid").innerHTML = "";
  $("briefScenarios").innerHTML = "";
  $("briefWatch").innerHTML = "";
  try {
    const data = await api(`/api/predictions?symbol=${state.symbol}`);
    const b = data.brief || {};
    const t = data.ticker || ticker;
    $("outlookPair").textContent = `${t.name_fa || t.base || state.symbol} · ${formatPrice(t.price, t)}`;
    $("briefHero").innerHTML = `
      <h2>${b.headline || "چشم‌انداز"}</h2>
      <p class="lead">${b.overall || ""}</p>
      <div class="brief-meta">
        <i class="${data.consensus || ""}">اجماع: ${data.consensus_label || "—"}</i>
        <i>خرید ${data.buy_count ?? 0} از ۷ بازه</i>
        <i>فروش ${data.sell_count ?? 0} از ۷ بازه</i>
      </div>
      <p>${b.conflicts || ""}</p>
      <p class="muted">${b.disclaimer || ""}</p>
    `;
    const blocks = [b.short_term, b.intraday, b.swing].filter(Boolean);
    $("briefGrid").innerHTML = blocks.map((s) => `
      <article class="brief-card">
        <div class="tag ${s.bias || "neutral"}">${s.bias_fa || "—"} · احتمال ${s.probability || "—"}٪</div>
        <h3>${s.title}</h3>
        <p>${s.text || ""}</p>
      </article>
    `).join("");
    const sc = b.scenarios || {};
    $("briefScenarios").innerHTML = `
      <h3>دو سناریوی پیش‌رو</h3>
      <p><strong>اگر خریداران قوی باشند:</strong> ${sc.up || ""}</p>
      <p><strong>اگر فروشندگان مسلط شوند:</strong> ${sc.down || ""}</p>
    `;
    $("briefWatch").innerHTML = `
      <h3>چه چیزی را زیر نظر بگیرید</h3>
      <ul>${(b.watch || []).map((w) => `<li>${w}</li>`).join("")}</ul>
    `;
  } catch (err) {
    $("briefHero").innerHTML = `<p class="muted">${err.message}</p>`;
    toast(err.message);
  }
}

async function loadPredictions() {
  $("analysisPair").textContent = state.symbol;
  try {
    const data = await api(`/api/predictions?symbol=${state.symbol}`);
    $("consensusBox").innerHTML = `
      <strong>اجماع بازه‌ها: ${data.consensus_label}</strong>
      <p class="muted">خرید ${data.buy_count} · فروش ${data.sell_count} · منبع: ${data.source || "—"}</p>
    `;
    $("tfGrid").innerHTML = data.timeframes.map((row) => {
      const p = row.prediction || {};
      const tf = TIMEFRAMES.find((t) => t.id === row.interval);
      return `
        <article class="tf-card">
          <h4>${tf ? tf.label : row.interval}</h4>
          <div class="dir ${p.direction || ""}">${p.label || "—"}</div>
          <p>هدف ${formatPrice(p.target_price, data.ticker)}</p>
          <p class="${pctClass(p.change_pct)}">${pctText(p.change_pct)} · احتمال ${p.probability || p.confidence || 0}٪</p>
          <p class="muted">${p.regime_fa || ""} ${p.volatility_fa ? "· نوسان " + p.volatility_fa : ""}</p>
        </article>`;
    }).join("");
    const first = data.timeframes.find((t) => t.interval === state.interval) || data.timeframes[0];
    const reasons = first?.prediction?.reasons || [];
    $("reasonsCard").innerHTML = `<h3>توضیح مدل (${TIMEFRAMES.find((t) => t.id === (first?.interval))?.label || ""})</h3>
      <ul>${reasons.map((r) => `<li>${r.text}</li>`).join("") || "<li>دلیلی ثبت نشد</li>"}</ul>
      ${(first?.prediction?.risks || []).map((x) => `<p class="warn">${x}</p>`).join("")}`;
  } catch (err) {
    toast(err.message);
  }
}

async function loadNews() {
  try {
    const items = await api("/api/news");
    if (!items.length) {
      $("newsGrid").innerHTML = "<p class='muted'>خبری دریافت نشد.</p>";
      return;
    }
    $("newsGrid").innerHTML = items.map((n) => `
      <a class="news-card" href="${n.url}" target="_blank" rel="noopener">
        ${n.image ? `<img src="${n.image}" alt="" />` : ""}
        <div>
          <h3>${n.title}</h3>
          <p>${n.body || ""}</p>
          <small>${n.source}</small>
        </div>
      </a>
    `).join("");
  } catch (err) {
    toast(err.message);
  }
}

async function loadWatchlist() {
  if (!state.watchlist.length) {
    $("watchGrid").innerHTML = "<p class='muted'>ارزی به لیست پیگیری اضافه نشده. از ستاره بالای داشبورد استفاده کنید.</p>";
    return;
  }
  const cards = await Promise.all(state.watchlist.map(async (sym) => {
    try {
      const t = await api(`/api/ticker?symbol=${sym}`);
      return `<article class="watch-card" data-symbol="${t.symbol}">
        <img src="${t.image || t.icon}" alt="" />
        <div>
          <strong>${t.name_fa} (${t.base})</strong>
          <div>${formatPrice(t.price, t)} <span class="${pctClass(t.change_24h)}">${pctText(t.change_24h)}</span></div>
        </div>
      </article>`;
    } catch {
      return "";
    }
  }));
  $("watchGrid").innerHTML = cards.join("");
  $("watchGrid").querySelectorAll(".watch-card").forEach((el) => {
    el.onclick = () => { selectSymbol(el.dataset.symbol); goPage("dashboard"); };
  });
}

function goPage(page) {
  state.page = page;
  document.querySelectorAll(".page").forEach((p) => p.classList.toggle("active", p.id === "page-" + page));
  document.querySelectorAll(".nav-item[data-page]").forEach((b) => b.classList.toggle("active", b.dataset.page === page));
  document.querySelector(".app").classList.toggle("no-rail", page !== "dashboard");
  $("rail").style.display = page === "dashboard" ? "" : "none";
  if (page === "markets") loadMarkets();
  if (page === "alerts") loadAlerts();
  if (page === "outlook") loadOutlook();
  if (page === "analysis") loadPredictions();
  if (page === "charts" && state.analysis) renderBigChart(state.analysis);
  if (page === "news") loadNews();
  if (page === "watchlist") loadWatchlist();
  if (page === "backtest") loadBacktest();
  if (page === "autotrade") loadAutotrade();
}

async function tickPrice() {
  const symbol = state.symbol;
  try {
    const t = await api(`/api/ticker?symbol=${encodeURIComponent(symbol)}`);
    if (symbol === state.symbol) applyLivePrice(t);
  } catch (_) { /* keep last price */ }
  priceTimer = setTimeout(tickPrice, 2500);
}

async function tickAnalysis() {
  if (!state.refreshMs) return;
  if (!state.pendingInterval) {
    const page = state.page;
    try {
      if (page === "dashboard" || page === "charts") await loadAnalysis({ silent: true });
      else if (page === "outlook") await loadOutlook();
      else if (page === "analysis") await loadPredictions();
      else if (page === "markets") await loadMarkets();
      else if (page === "watchlist") await loadWatchlist();
    } catch (_) { /* next tick */ }
  }
  if (state.refreshMs) analysisTimer = setTimeout(tickAnalysis, state.refreshMs);
}

function scheduleRefresh() {
  if (priceTimer) clearTimeout(priceTimer);
  if (analysisTimer) clearTimeout(analysisTimer);
  tickPrice();
  tickAnalysis();
}

function bind() {
  document.querySelectorAll(".nav-item[data-page]").forEach((btn) => {
    btn.onclick = () => goPage(btn.dataset.page);
  });
  $("themeToggle").onchange = (e) => applyTheme(e.target.checked);
  $("pairBtn").onclick = () => {
    const menu = $("pairMenu");
    menu.hidden = !menu.hidden;
    if (!menu.hidden) $("pairSearch").focus();
  };
  $("pairSearch").oninput = (e) => renderPairList(e.target.value);
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".pair-wrap")) $("pairMenu").hidden = true;
  });
  $("watchToggle").onclick = toggleWatch;
  $("refreshBtn").onclick = () => loadAnalysis({ reason: "manual", message: "در حال به‌روزرسانی قیمت و نتیجه..." });
  if ($("btRun")) $("btRun").onclick = loadBacktest;
  $("chartType").querySelectorAll("button").forEach((b) => {
    b.onclick = () => {
      $("chartType").querySelectorAll("button").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      state.chartType = b.dataset.type;
      chartKey = "";
      if (state.analysis) renderCharts(state.analysis);
    };
  });
  $("indToggles").querySelectorAll("button").forEach((b) => {
    b.classList.toggle("active", !!state.indicators[b.dataset.ind]);
    b.onclick = () => {
      state.indicators[b.dataset.ind] = !state.indicators[b.dataset.ind];
      b.classList.toggle("active", state.indicators[b.dataset.ind]);
      chartKey = "";
      if (state.analysis) renderCharts(state.analysis);
    };
  });
  $("fullscreenBtn").onclick = () => {
    const el = document.querySelector(".chart-card");
    if (!document.fullscreenElement) el.requestFullscreen?.();
    else document.exitFullscreen?.();
  };
  $("marketSearch").oninput = loadMarkets;
  $("showForecast").checked = state.showForecast;
  $("showForecast").onchange = (e) => {
    state.showForecast = e.target.checked;
    localStorage.setItem("ca_forecast", e.target.checked ? "1" : "0");
    if (state.analysis) renderCharts(state.analysis);
  };
  $("refreshInterval").value = String(state.refreshMs / 1000);
  $("refreshInterval").onchange = (e) => {
    state.refreshMs = Number(e.target.value) * 1000;
    localStorage.setItem("ca_refresh", String(state.refreshMs));
    scheduleRefresh();
  };
  if ($("alertArmBtn")) $("alertArmBtn").onclick = toggleAlertArm;
  if ($("alertTestBtn")) $("alertTestBtn").onclick = testAlertSound;
  if ($("atSaveBtn")) $("atSaveBtn").onclick = () => saveAutotradeConfig().catch((e) => toast(e.message));
  if ($("atTestBtn")) $("atTestBtn").onclick = () => testAutotrade().catch((e) => toast(e.message));
  if ($("atRunBtn")) $("atRunBtn").onclick = () => runAutotradeOnce().catch((e) => toast(e.message));
  if ($("atRefreshBtn")) $("atRefreshBtn").onclick = () => loadAutotrade().catch((e) => toast(e.message));
  if ($("alertSoundOn")) {
    $("alertSoundOn").checked = state.alertSound;
    $("alertSoundOn").onchange = (e) => {
      state.alertSound = e.target.checked;
      localStorage.setItem("ca_alert_sound", e.target.checked ? "1" : "0");
      if (e.target.checked) testAlertSound();
    };
  }
  if ($("alertOddsMin")) {
    $("alertOddsMin").value = String(state.alertMinOdds);
    $("alertOddsMin").onchange = (e) => {
      state.alertMinOdds = Number(e.target.value);
      localStorage.setItem("ca_alert_min", String(state.alertMinOdds));
      lastAlertNotify = {};
      sessionStorage.removeItem("ca_alert_fired");
      loadAlerts({ silent: false });
    };
  }
  syncAlertArmUi();
  if ($("page-alerts")) {
    $("page-alerts").addEventListener("click", (e) => {
      if (handleMtClick(e)) return;
      if (e.target.closest(".alert-arm")) return;
      const card = e.target.closest("[data-alert-symbol]");
      if (card) {
        selectSymbol(card.dataset.alertSymbol);
        goPage("dashboard");
      }
    });
  }
  document.addEventListener("click", (e) => { handleMtClick(e); });
  if ($("mtCopyAll")) $("mtCopyAll").onclick = () => copyText(mtCopyText());
  document.addEventListener("click", () => { if (alertArmed || audioUnlocked) unlockAudio(); });
  document.addEventListener("keydown", () => { if (alertArmed || audioUnlocked) unlockAudio(); });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      document.title = PAGE_TITLE;
      if (alertArmed) unlockAudio();
    }
  });
  window.addEventListener("resize", resizeCharts);
  document.addEventListener("fullscreenchange", () => {
    resizeCharts();
    if (state.analysis) renderCharts(state.analysis);
  });
}

function resizeCharts() {
  if (mainChart) mainChart.applyOptions({ width: $("mainChart").clientWidth, height: $("mainChart").clientHeight });
  if (extraChart) extraChart.applyOptions({ width: $("extraChart").clientWidth });
  if (bigChart) bigChart.applyOptions({ width: $("bigChart").clientWidth, height: $("bigChart").clientHeight });
}

async function init() {
  const dark = (localStorage.getItem("ca_theme") || "dark") === "dark";
  applyTheme(dark);
  buildTimeframes();
  bind();
  await loadCoins();
  await loadAnalysis();
  scheduleRefresh();
  tickAlertWatch();
}

init();
