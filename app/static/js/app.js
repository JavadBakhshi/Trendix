const TIMEFRAMES = [
  { id: "5m", label: "۵ دقیقه" },
  { id: "15m", label: "۱۵ دقیقه" },
  { id: "30m", label: "۳۰ دقیقه" },
  { id: "1h", label: "۱ ساعت" },
  { id: "3h", label: "۳ ساعت" },
  { id: "1d", label: "۱ روز" },
  { id: "1w", label: "۱ هفته" },
];

const state = {
  symbol: localStorage.getItem("ca_symbol") || "BTCUSDT",
  interval: localStorage.getItem("ca_interval") || "5m",
  coins: [],
  analysis: null,
  chartType: "candles",
  indicators: { sma: true, ema: false, boll: false, macd: false, rsi: false, volume: true },
  watchlist: JSON.parse(localStorage.getItem("ca_watch") || "[]"),
  showForecast: localStorage.getItem("ca_forecast") !== "0",
  refreshMs: Number(localStorage.getItem("ca_refresh") || 30000),
  page: "dashboard",
};

let mainChart, extraChart, bigChart;
let candleSeries, lineSeries, volumeSeries, extraSeries;
const overlaySeries = {};
let forecastSeries = null;
let timer = null;

const $ = (id) => document.getElementById(id);

function toast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.hidden = false;
  setTimeout(() => { el.hidden = true; }, 2800);
}

async function api(path) {
  const res = await fetch(path);
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
    b.className = tf.id === state.interval ? "active" : "";
    b.onclick = () => {
      state.interval = tf.id;
      localStorage.setItem("ca_interval", tf.id);
      buildTimeframes();
      loadAnalysis();
    };
    row.appendChild(b);
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

function renderPrices(ticker) {
  $("livePrice").textContent = formatPrice(ticker.price, ticker);
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
}

function renderPerformance(perf) {
  $("perfList").innerHTML = TIMEFRAMES.map((tf) => {
    const v = perf[tf.id] ?? 0;
    return `<li><span>${tf.label}</span><b class="${pctClass(v)}">${pctText(v)}</b></li>`;
  }).join("");
}

function renderPrediction(pred) {
  const ticker = state.analysis && state.analysis.ticker;
  $("predLabel").textContent = pred.label;
  $("predHorizon").textContent = pred.horizon;
  $("predConfLevel").textContent = pred.confidence_fa ? `اطمینان ${pred.confidence_fa} (${pred.confidence}٪)` : "";
  $("predProb").textContent = (pred.probability != null ? pred.probability : pred.confidence) + "٪";
  $("predTarget").textContent = formatPrice(pred.target_price, ticker);
  $("predChange").textContent = pctText(pred.change_pct);
  $("predChange").className = pctClass(pred.change_pct);
  const zone = pred.entry_zone || [];
  const trade = pred.direction === "buy" || pred.direction === "sell";
  $("predEntry").textContent = trade && zone.length === 2 ? `${formatPrice(zone[0], ticker)} – ${formatPrice(zone[1], ticker)}` : "—";
  $("predSl").textContent = trade && pred.stop_loss ? formatPrice(pred.stop_loss, ticker) : "—";
  $("predTp").textContent = trade && pred.tp1 ? `${formatPrice(pred.tp1, ticker)} / ${formatPrice(pred.tp2, ticker)}` : "—";
  document.querySelector(".pred-dir").dataset.dir = pred.direction;
  const chips = [];
  if (pred.regime_fa) chips.push(`رژیم: ${pred.regime_fa}`);
  if (pred.volatility_fa) chips.push(`نوسان: ${pred.volatility_fa}`);
  if (pred.session) chips.push(`سشن: ${pred.session}`);
  if (pred.structure && pred.structure.trend) chips.push(`ساختار: ${pred.structure.trend}`);
  if (pred.news_risk) chips.push(`ریسک خبر: ${pred.news_risk === "high" ? "بالا" : pred.news_risk === "medium" ? "متوسط" : "پایین"}`);
  if (pred.ml && pred.ml.hit_rate != null) chips.push(`ML hit-rate: ${pred.ml.hit_rate}٪`);
  if (pred.risk_reward) chips.push(`R/R ${pred.risk_reward}`);
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
  } else {
    candleSeries = mainChart.addCandlestickSeries({
      upColor: c.up, downColor: c.down, borderVisible: false,
      wickUpColor: c.up, wickDownColor: c.down,
    });
    candleSeries.setData(data.candles);
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

async function loadAnalysis() {
  try {
    const data = await api(`/api/analysis?symbol=${state.symbol}&interval=${state.interval}`);
    state.analysis = data;
    renderPairButton(data.ticker);
    renderPrices(data.ticker);
    renderPerformance(data.performance);
    renderPrediction(data.prediction);
    renderGauges(data.indicators);
    renderCharts(data);
    setWatchButton();
  } catch (err) {
    toast(err.message);
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
  state.symbol = symbol;
  localStorage.setItem("ca_symbol", symbol);
  $("pairMenu").hidden = true;
  loadAnalysis();
  if (state.page === "analysis") loadPredictions();
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

async function loadAlerts() {
  $("alertHeadline").textContent = "در حال اسکن طلا، یورو، دلار و ارزهای اصلی...";
  $("alertHeroes").innerHTML = "";
  $("alertBuys").innerHTML = "";
  $("alertSells").innerHTML = "";
  if ($("alertWaits")) $("alertWaits").innerHTML = "";
  const extra = (state.watchlist || []).join(",");
  try {
    const data = await api(`/api/alerts?extra=${encodeURIComponent(extra)}`);
    $("alertHeadline").textContent = data.headline || "";
    $("alertNote").textContent = data.disclaimer || "";
    const heroes = [data.best_buy, data.best_sell].filter(Boolean);
    $("alertHeroes").innerHTML = heroes.map(alertHeroHtml).join("") || "<p class='muted'>الان مورد قوی نیست.</p>";
    $("alertBuys").innerHTML = (data.buys || []).map(alertRowHtml).join("") || "<p class='muted'>هشدار خرید فعالی نیست.</p>";
    $("alertSells").innerHTML = (data.sells || []).map(alertRowHtml).join("") || "<p class='muted'>هشدار فروش فعالی نیست.</p>";
    if ($("alertWaits")) {
      $("alertWaits").innerHTML = (data.watched || []).map(alertRowHtml).join("") || "";
    }
    document.querySelectorAll("[data-alert-symbol]").forEach((el) => {
      el.onclick = () => { selectSymbol(el.dataset.alertSymbol); goPage("dashboard"); };
    });
  } catch (err) {
    $("alertHeadline").textContent = err.message;
    toast(err.message);
  }
}

function alertHeroHtml(a) {
  const ticker = { price_prefix: a.price_prefix };
  const zone = (a.entry_zone || []).filter(Boolean);
  return `
    <article class="alert-hero ${a.action}" data-alert-symbol="${a.symbol}">
      <header>
        <img src="${a.icon}" alt="" onerror="this.style.visibility='hidden'" />
        <div><strong>${a.name_fa}</strong><small> ${formatPrice(a.price, ticker)}</small></div>
        <span class="badge">${a.strength} · ${a.confidence}٪</span>
      </header>
      <div class="cmd">${a.command}</div>
      <p>${a.detail}</p>
      <p>انتظار ${pctText(a.expected_move)} در ${a.horizon || "۱ ساعت"} · رژیم ${a.regime || "—"}</p>
      ${a.action !== "wait" && zone.length === 2 ? `<p>ورود ${formatPrice(zone[0], ticker)} تا ${formatPrice(zone[1], ticker)} · حد ضرر ${formatPrice(a.stop_loss, ticker)} · هدف ${formatPrice(a.tp1, ticker)}</p>` : ""}
      <ul>${(a.reasons || []).map((r) => `<li>${r}</li>`).join("")}</ul>
    </article>`;
}

function alertRowHtml(a) {
  const ticker = { price_prefix: a.price_prefix };
  return `
    <article class="alert-row ${a.action}" data-alert-symbol="${a.symbol}">
      <img src="${a.icon}" alt="" />
      <div>
        <strong>${a.name_fa}</strong>
        <small>${a.strength} · احتمال ${a.probability}٪ · ${pctText(a.expected_move)}</small>
      </div>
      <span class="act">${a.action === "buy" ? "بخر" : a.action === "sell" ? "بفروش" : "صبر"}</span>
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
}

function scheduleRefresh() {
  if (timer) clearInterval(timer);
  if (!state.refreshMs) return;
  timer = setInterval(() => {
    if (state.page === "dashboard" || state.page === "charts") loadAnalysis();
  }, state.refreshMs);
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
  $("refreshBtn").onclick = loadAnalysis;
  $("chartType").querySelectorAll("button").forEach((b) => {
    b.onclick = () => {
      $("chartType").querySelectorAll("button").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      state.chartType = b.dataset.type;
      if (state.analysis) renderCharts(state.analysis);
    };
  });
  $("indToggles").querySelectorAll("button").forEach((b) => {
    b.classList.toggle("active", !!state.indicators[b.dataset.ind]);
    b.onclick = () => {
      state.indicators[b.dataset.ind] = !state.indicators[b.dataset.ind];
      b.classList.toggle("active", state.indicators[b.dataset.ind]);
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
}

init();
