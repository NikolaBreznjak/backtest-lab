(function () {
  "use strict";

  const state = {
    dashboard: null,
    barsData: null,
    detailCache: new Map(),
    selectedStrategyId: null,
    selectedMarket: "MSFT",
    zoomBars: "all",
    replayCursor: 0,
    isPlaying: false,
    playTimer: null,
    hoverBarIdx: null,
  };

  const els = {
    metaLastRun: document.getElementById("meta-last-run"),
    metaDataThrough: document.getElementById("meta-data-through"),
    kpiTotal: document.getElementById("kpi-total"),
    kpiTotalSub: document.getElementById("kpi-total-sub"),
    kpiSurvivors: document.getElementById("kpi-survivors"),
    kpiDead: document.getElementById("kpi-dead"),
    kpiDeadRate: document.getElementById("kpi-dead-rate"),
    kpiTopSharpe: document.getElementById("kpi-top-sharpe"),
    kpiTopName: document.getElementById("kpi-top-name"),
    kpiNearMiss: document.getElementById("kpi-nearmiss"),
    kpiNearMissSub: document.getElementById("kpi-nearmiss-sub"),
    strategySelect: document.getElementById("strategy-select"),
    marketTabs: document.getElementById("market-tabs"),
    btnReset: document.getElementById("btn-reset"),
    btnStepBack: document.getElementById("btn-step-back"),
    btnPlay: document.getElementById("btn-play"),
    btnStepFwd: document.getElementById("btn-step-fwd"),
    btnEnd: document.getElementById("btn-end"),
    speedSelect: document.getElementById("speed-select"),
    zoomSelect: document.getElementById("zoom-select"),
    replaySlider: document.getElementById("replay-slider"),
    hudDate: document.getElementById("hud-date"),
    hudOpen: document.getElementById("hud-open"),
    hudHigh: document.getElementById("hud-high"),
    hudLow: document.getElementById("hud-low"),
    hudClose: document.getElementById("hud-close"),
    hudPos: document.getElementById("hud-pos"),
    hudStratEq: document.getElementById("hud-strat-eq"),
    hudBhEq: document.getElementById("hud-bh-eq"),
    hudTrades: document.getElementById("hud-trades"),
    hudIndWrap: document.getElementById("hud-ind-wrap"),
    hudInd: document.getElementById("hud-ind"),
    canvas: document.getElementById("terminal-canvas"),
    tooltip: document.getElementById("chart-tooltip"),
    stressSubtitle: document.getElementById("stress-subtitle"),
    stressVerdictBadge: document.getElementById("stress-verdict-badge"),
    stressBody: document.getElementById("stress-body"),
    survivorsCountBadge: document.getElementById("survivors-count-badge"),
    survivorsBody: document.getElementById("survivors-body"),
    matrixTable: document.getElementById("matrix-table"),
    leaderboardTable: document.getElementById("leaderboard-table"),
    journalTable: document.getElementById("journal-table"),
    journalSearch: document.getElementById("journal-search"),
    journalFilter: document.getElementById("journal-filter"),
  };

  function fmtPct(v, showPlus = true) {
    if (v === null || v === undefined || Number.isNaN(v)) return "--";
    const s = v.toFixed(2) + "%";
    return showPlus && v > 0 ? "+" + s : s;
  }

  function fmtNum(v, d = 2) {
    if (v === null || v === undefined || Number.isNaN(v)) return "--";
    return Number(v).toFixed(d);
  }

  function clsRet(v) {
    if (v > 0) return "txt-green";
    if (v < 0) return "txt-red";
    return "txt-muted";
  }

  async function init() {
    const [dashResp, barsResp] = await Promise.all([
      fetch("data/dashboard.json"),
      fetch("data/bars.json"),
    ]);
    if (!dashResp.ok || !barsResp.ok) {
      throw new Error("Failed to load dashboard or bars JSON");
    }
    state.dashboard = await dashResp.json();
    state.barsData = await barsResp.json();

    const lb = state.dashboard.leaderboard || [];
    if (lb.length > 0) {
      // Pick first strategy with >=2 tests passed or top sharpe
      const best = lb[0];
      state.selectedStrategyId = best.id;
    }
    const univ = state.dashboard.meta.universe || ["MSFT", "AAPL", "NVDA", "^GSPC"];
    state.selectedMarket = univ[0];

    renderTopbarAndKpis();
    renderControls();
    renderSurvivors();
    renderMatrix();
    renderLeaderboard();
    renderJournal();
    bindEvents();

    if (state.selectedStrategyId) {
      await selectStrategy(state.selectedStrategyId, state.selectedMarket, true);
    }
  }

  function renderTopbarAndKpis() {
    const d = state.dashboard;
    const run = d.meta.last_run;
    els.metaLastRun.textContent = run.run_at_ljubljana || run.run_at_utc;
    const mMeta = d.meta.universe_meta;
    const dates = Object.values(mMeta).map((x) => x.last_date).sort();
    els.metaDataThrough.textContent = dates[dates.length - 1] || "--";

    els.kpiTotal.textContent = d.stats.total_ideas;
    els.kpiTotalSub.textContent = `Last run: +${run.new_ideas_tested} ideas (${run.elapsed_seconds}s)`;
    els.kpiSurvivors.textContent = d.stats.survivors_count;
    els.kpiDead.textContent = d.stats.graveyard_count;
    const deadPct = d.stats.total_ideas > 0
      ? ((d.stats.graveyard_count / d.stats.total_ideas) * 100).toFixed(0) + "% rejected by strict gates"
      : "--";
    els.kpiDeadRate.textContent = deadPct;

    const lb = d.leaderboard;
    if (lb.length > 0) {
      const topSharpe = [...lb].sort((a, b) => b.summary.mean_sharpe - a.summary.mean_sharpe)[0];
      els.kpiTopSharpe.textContent = fmtNum(topSharpe.summary.mean_sharpe, 3);
      els.kpiTopName.textContent = `${topSharpe.name} (${fmtPct(topSharpe.summary.mean_return_pct)})`;

      const near = lb[0];
      els.kpiNearMiss.textContent = `${near.tests_passed_count}/4 GATES`;
      els.kpiNearMissSub.textContent = near.name;
    }
  }

  function renderControls() {
    const lb = state.dashboard.leaderboard;
    els.strategySelect.innerHTML = "";
    lb.forEach((s) => {
      const opt = document.createElement("option");
      opt.value = s.id;
      const tag = s.verdict === "PASS" ? "[PASS]" : `[${s.tests_passed_count}/4]`;
      opt.textContent = `${tag} ${s.name} — Ret ${fmtPct(s.summary.mean_return_pct)} | Sh ${fmtNum(s.summary.mean_sharpe, 2)}`;
      els.strategySelect.appendChild(opt);
    });
    els.strategySelect.value = state.selectedStrategyId;

    const univ = state.dashboard.meta.universe;
    els.marketTabs.innerHTML = "";
    univ.forEach((sym) => {
      const btn = document.createElement("button");
      btn.className = "mkt-tab" + (sym === state.selectedMarket ? " active" : "");
      btn.textContent = sym;
      btn.dataset.sym = sym;
      btn.addEventListener("click", () => {
        state.selectedMarket = sym;
        updateMarketTabStyles();
        resetCursorToEnd();
        drawChart();
      });
      els.marketTabs.appendChild(btn);
    });
  }

  function updateMarketTabStyles() {
    els.marketTabs.querySelectorAll(".mkt-tab").forEach((b) => {
      b.classList.toggle("active", b.dataset.sym === state.selectedMarket);
    });
  }

  async function loadStrategyDetail(id) {
    if (state.detailCache.has(id)) return state.detailCache.get(id);
    const resp = await fetch(`data/details/${id}.json`);
    if (!resp.ok) throw new Error(`Failed to load strategy detail ${id}`);
    const data = await resp.json();
    state.detailCache.set(id, data);
    return data;
  }

  async function selectStrategy(id, market = null, jumpToEnd = true) {
    stopReplay();
    state.selectedStrategyId = id;
    if (market) state.selectedMarket = market;
    els.strategySelect.value = id;
    updateMarketTabStyles();

    // Highlight selected rows
    document.querySelectorAll("[data-strategy-id]").forEach((tr) => {
      tr.classList.toggle("selected-row", tr.dataset.strategyId === id);
    });

    await loadStrategyDetail(id);
    if (jumpToEnd) resetCursorToEnd();
    renderStressInspector();
    drawChart();
  }

  function getActiveMarketData() {
    const bars = state.barsData.bars[state.selectedMarket];
    const detail = state.detailCache.get(state.selectedStrategyId);
    const mDetail = detail ? detail.markets[state.selectedMarket] : null;
    return { bars, mDetail };
  }

  function resetCursorToEnd() {
    const { bars, mDetail } = getActiveMarketData();
    if (!bars || !mDetail) return;
    els.replaySlider.min = mDetail.start_idx;
    els.replaySlider.max = mDetail.end_idx;
    state.replayCursor = mDetail.end_idx;
    els.replaySlider.value = state.replayCursor;
  }

  function stopReplay() {
    state.isPlaying = false;
    if (state.playTimer) {
      clearInterval(state.playTimer);
      state.playTimer = null;
    }
    els.btnPlay.innerHTML = "&#9654; REPLAY";
  }

  function toggleReplay() {
    if (state.isPlaying) {
      stopReplay();
      return;
    }
    const { mDetail } = getActiveMarketData();
    if (!mDetail) return;
    if (state.replayCursor >= mDetail.end_idx) {
      state.replayCursor = mDetail.start_idx;
    }
    state.isPlaying = true;
    els.btnPlay.innerHTML = "&#10074;&#10074; PAUSE";
    const stepLoop = () => {
      if (!state.isPlaying) return;
      const speed = Number(els.speedSelect.value) || 5;
      const stepBars = speed >= 30 ? 4 : speed >= 15 ? 2 : 1;
      const delay = speed >= 30 ? 25 : speed >= 15 ? 35 : speed >= 5 ? 45 : 140;
      state.replayCursor = Math.min(mDetail.end_idx, state.replayCursor + stepBars);
      els.replaySlider.value = state.replayCursor;
      drawChart();
      if (state.replayCursor >= mDetail.end_idx) {
        stopReplay();
        return;
      }
      state.playTimer = setTimeout(stepLoop, delay);
    };
    stepLoop();
  }

  function drawChart() {
    const { bars, mDetail } = getActiveMarketData();
    if (!bars || !mDetail) return;

    const canvas = els.canvas;
    const rect = canvas.parentElement.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const W = Math.max(rect.width, 320);
    const H = Math.max(rect.height, 420);
    canvas.width = Math.floor(W * dpr);
    canvas.height = Math.floor(H * dpr);
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    // Clear
    ctx.fillStyle = "#090d13";
    ctx.fillRect(0, 0, W, H);

    const endIdx = mDetail.end_idx;
    const startIdx = mDetail.start_idx;
    const cursor = Math.max(startIdx, Math.min(endIdx, state.replayCursor));

    // Visible slice according to zoom
    let visStart = 0;
    if (state.zoomBars !== "all") {
      const win = Number(state.zoomBars);
      visStart = Math.max(0, bars.length - win);
    }
    const visEnd = bars.length - 1;
    const visCount = visEnd - visStart + 1;

    const padLeft = 14;
    const padRight = 64;
    const padTop = 14;
    const padBottom = 24;
    const plotW = W - padLeft - padRight;

    // 3 Panes: Price (54%), Indicator/Volume (20%), Equity (26%)
    const totalPlotH = H - padTop - padBottom;
    const gap = 10;
    const priceH = Math.floor(totalPlotH * 0.54);
    const midH = Math.floor(totalPlotH * 0.19);
    const eqH = totalPlotH - priceH - midH - gap * 2;

    const priceTop = padTop;
    const midTop = priceTop + priceH + gap;
    const eqTop = midTop + midH + gap;

    const xForBar = (idx) => padLeft + ((idx - visStart + 0.5) / visCount) * plotW;
    const barW = Math.max(1.2, Math.min(10, (plotW / visCount) * 0.68));

    // Visible price range up to bars.length (or full range so axes don't jump wildly during replay)
    let pMin = Infinity, pMax = -Infinity;
    for (let i = visStart; i <= visEnd; i++) {
      if (bars[i].low < pMin) pMin = bars[i].low;
      if (bars[i].high > pMax) pMax = bars[i].high;
    }
    if (mDetail.indicators.pane === "price") {
      for (const s of mDetail.indicators.series) {
        for (let i = visStart; i <= cursor; i++) {
          const v = s.values[i];
          if (v !== null && v !== undefined) {
            if (v < pMin) pMin = v;
            if (v > pMax) pMax = v;
          }
        }
      }
    }
    const pPad = (pMax - pMin) * 0.06 || 1;
    pMin -= pPad;
    pMax += pPad;
    const yPrice = (p) => priceTop + ((pMax - p) / (pMax - pMin)) * priceH;

    // Helper gridlines
    ctx.strokeStyle = "#141d29";
    ctx.lineWidth = 1;
    for (let g = 0; g <= 4; g++) {
      const py = priceTop + (priceH * g) / 4;
      ctx.beginPath();
      ctx.moveTo(padLeft, py);
      ctx.lineTo(W - padRight, py);
      ctx.stroke();

      const val = pMax - ((pMax - pMin) * g) / 4;
      ctx.fillStyle = "#6b7d96";
      ctx.font = "10px JetBrains Mono, monospace";
      ctx.fillText(val.toFixed(val > 500 ? 0 : 2), W - padRight + 6, py + 3);
    }

    // Train vs Unseen split line (60%)
    const splitIdx = Math.max(startIdx + 60, Math.floor(bars.length * 0.6));
    if (splitIdx >= visStart && splitIdx <= visEnd) {
      const sx = xForBar(splitIdx);
      ctx.save();
      ctx.fillStyle = "rgba(56, 189, 248, 0.03)";
      ctx.fillRect(sx, priceTop, W - padRight - sx, totalPlotH);
      ctx.strokeStyle = "rgba(56, 189, 248, 0.35)";
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(sx, priceTop);
      ctx.lineTo(sx, eqTop + eqH);
      ctx.stroke();
      ctx.fillStyle = "#38bdf8";
      ctx.font = "10px JetBrains Mono, monospace";
      ctx.fillText("UNSEEN OOS (40%)", sx + 6, priceTop + 12);
      ctx.restore();
    }

    // Position shading (up to cursor)
    for (let i = Math.max(visStart, startIdx + 1); i <= Math.min(visEnd, cursor); i++) {
      const posActive = mDetail.signals[i - 1] === 1;
      if (posActive) {
        const x = xForBar(i) - barW * 0.65;
        ctx.fillStyle = "rgba(0, 211, 149, 0.055)";
        ctx.fillRect(x, priceTop, Math.max(barW * 1.3, 1.5), priceH);
      }
    }

    // Draw candles (up to cursor normally; future bars dimmed as ghost outline if replaying)
    for (let i = visStart; i <= visEnd; i++) {
      const b = bars[i];
      const x = xForBar(i);
      const isFuture = i > cursor;
      const up = b.close >= b.open;
      const color = isFuture
        ? "rgba(84, 100, 122, 0.16)"
        : up ? "#00d395" : "#ff4d6a";

      const yh = yPrice(b.high);
      const yl = yPrice(b.low);
      const yo = yPrice(b.open);
      const yc = yPrice(b.close);

      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, yh);
      ctx.lineTo(x, yl);
      ctx.stroke();

      const bodyTop = Math.min(yo, yc);
      const bodyH = Math.max(1.2, Math.abs(yc - yo));
      ctx.fillStyle = color;
      ctx.fillRect(x - barW / 2, bodyTop, barW, bodyH);
    }

    // Price overlay indicators (up to cursor)
    if (mDetail.indicators.pane === "price") {
      for (const s of mDetail.indicators.series) {
        ctx.strokeStyle = s.color;
        ctx.lineWidth = 1.4;
        ctx.beginPath();
        let started = false;
        for (let i = visStart; i <= Math.min(visEnd, cursor); i++) {
          const v = s.values[i];
          if (v === null || v === undefined) {
            started = false;
            continue;
          }
          const x = xForBar(i);
          const y = yPrice(v);
          if (!started) {
            ctx.moveTo(x, y);
            started = true;
          } else {
            ctx.lineTo(x, y);
          }
        }
        ctx.stroke();
      }
    }

    // Entry / Exit markers (up to cursor)
    let tradesUpToCursor = 0;
    for (const t of mDetail.trades) {
      if (t.entry_idx <= cursor) {
        tradesUpToCursor++;
        if (t.entry_idx >= visStart && t.entry_idx <= visEnd) {
          const x = xForBar(t.entry_idx);
          const y = yPrice(bars[t.entry_idx].low) + 9;
          ctx.fillStyle = "#00d395";
          ctx.beginPath();
          ctx.moveTo(x, y - 6);
          ctx.lineTo(x - 4.5, y + 2);
          ctx.lineTo(x + 4.5, y + 2);
          ctx.closePath();
          ctx.fill();
        }
      }
      if (!t.open && t.exit_idx <= cursor && t.exit_idx >= visStart && t.exit_idx <= visEnd) {
        const x = xForBar(t.exit_idx);
        const y = yPrice(bars[t.exit_idx].high) - 9;
        ctx.fillStyle = t.return_pct >= 0 ? "#38bdf8" : "#ff4d6a";
        ctx.beginPath();
        ctx.moveTo(x, y + 6);
        ctx.lineTo(x - 4.5, y - 2);
        ctx.lineTo(x + 4.5, y - 2);
        ctx.closePath();
        ctx.fill();
      }
    }

    // ---------------- MIDDLE PANE (SUB-INDICATOR OR VOLUME) ----------------
    ctx.strokeStyle = "#1b2636";
    ctx.strokeRect(padLeft, midTop, plotW, midH);

    if (mDetail.indicators.pane === "sub") {
      let sMin = Infinity, sMax = -Infinity;
      for (const s of mDetail.indicators.series) {
        for (let i = visStart; i <= cursor; i++) {
          const v = s.values[i];
          if (v !== null && v !== undefined) {
            if (v < sMin) sMin = v;
            if (v > sMax) sMax = v;
          }
        }
      }
      for (const lv of (mDetail.indicators.levels || [])) {
        if (lv < sMin) sMin = lv;
        if (lv > sMax) sMax = lv;
      }
      if (!Number.isFinite(sMin)) { sMin = 0; sMax = 100; }
      const sPad = (sMax - sMin) * 0.1 || 1;
      sMin -= sPad;
      sMax += sPad;
      const ySub = (v) => midTop + ((sMax - v) / (sMax - sMin)) * midH;

      // Levels
      ctx.save();
      ctx.strokeStyle = "rgba(130, 148, 173, 0.35)";
      ctx.setLineDash([3, 3]);
      for (const lv of (mDetail.indicators.levels || [])) {
        const ly = ySub(lv);
        ctx.beginPath();
        ctx.moveTo(padLeft, ly);
        ctx.lineTo(W - padRight, ly);
        ctx.stroke();
      }
      ctx.restore();

      for (const s of mDetail.indicators.series) {
        ctx.strokeStyle = s.color;
        ctx.lineWidth = 1.3;
        ctx.beginPath();
        let started = false;
        for (let i = visStart; i <= Math.min(visEnd, cursor); i++) {
          const v = s.values[i];
          if (v === null || v === undefined) { started = false; continue; }
          const x = xForBar(i);
          const y = ySub(v);
          if (!started) { ctx.moveTo(x, y); started = true; } else { ctx.lineTo(x, y); }
        }
        ctx.stroke();
      }
      ctx.fillStyle = "#8294ad";
      ctx.font = "10px JetBrains Mono, monospace";
      ctx.fillText(mDetail.indicators.label || "INDICATOR", padLeft + 6, midTop + 12);
      ctx.fillText(sMax.toFixed(1), W - padRight + 6, midTop + 10);
      ctx.fillText(sMin.toFixed(1), W - padRight + 6, midTop + midH - 3);
    } else {
      // Volume bars
      let vMax = 1;
      for (let i = visStart; i <= visEnd; i++) {
        if (bars[i].volume > vMax) vMax = bars[i].volume;
      }
      for (let i = visStart; i <= Math.min(visEnd, cursor); i++) {
        const b = bars[i];
        const vh = (b.volume / vMax) * (midH - 14);
        const x = xForBar(i);
        ctx.fillStyle = b.close >= b.open ? "rgba(0, 211, 149, 0.35)" : "rgba(255, 77, 106, 0.35)";
        ctx.fillRect(x - barW / 2, midTop + midH - vh, barW, vh);
      }
      ctx.fillStyle = "#8294ad";
      ctx.font = "10px JetBrains Mono, monospace";
      ctx.fillText("VOLUME + OVERLAY", padLeft + 6, midTop + 12);
    }

    // ---------------- BOTTOM PANE (EQUITY CURVE VS BUY & HOLD) ----------------
    ctx.strokeStyle = "#1b2636";
    ctx.strokeRect(padLeft, eqTop, plotW, eqH);

    const eqArr = mDetail.equity_curve;
    const bhArr = mDetail.bh_curve;
    let eMin = 1.0, eMax = 1.0;
    const relStart = Math.max(0, visStart - startIdx);
    const relCursor = Math.max(0, cursor - startIdx);
    for (let k = relStart; k <= Math.min(eqArr.length - 1, relCursor); k++) {
      eMin = Math.min(eMin, eqArr[k], bhArr[k]);
      eMax = Math.max(eMax, eqArr[k], bhArr[k]);
    }
    const ePad = (eMax - eMin) * 0.08 || 0.05;
    eMin -= ePad;
    eMax += ePad;
    const yEq = (v) => eqTop + ((eMax - v) / (eMax - eMin)) * eqH;

    // 0% baseline
    const yZero = yEq(1.0);
    ctx.strokeStyle = "rgba(130, 148, 173, 0.25)";
    ctx.beginPath();
    ctx.moveTo(padLeft, yZero);
    ctx.lineTo(W - padRight, yZero);
    ctx.stroke();

    // B&H dashed curve
    ctx.save();
    ctx.strokeStyle = "#f5a623";
    ctx.lineWidth = 1.3;
    ctx.setLineDash([4, 3]);
    ctx.beginPath();
    let bStarted = false;
    for (let i = Math.max(visStart, startIdx); i <= Math.min(visEnd, cursor); i++) {
      const k = i - startIdx;
      const x = xForBar(i);
      const y = yEq(bhArr[k]);
      if (!bStarted) { ctx.moveTo(x, y); bStarted = true; } else { ctx.lineTo(x, y); }
    }
    ctx.stroke();
    ctx.restore();

    // Strategy equity curve
    ctx.strokeStyle = "#38bdf8";
    ctx.lineWidth = 1.8;
    ctx.beginPath();
    let eStarted = false;
    for (let i = Math.max(visStart, startIdx); i <= Math.min(visEnd, cursor); i++) {
      const k = i - startIdx;
      const x = xForBar(i);
      const y = yEq(eqArr[k]);
      if (!eStarted) { ctx.moveTo(x, y); eStarted = true; } else { ctx.lineTo(x, y); }
    }
    ctx.stroke();

    ctx.fillStyle = "#8294ad";
    ctx.font = "10px JetBrains Mono, monospace";
    ctx.fillText("EQUITY: STRAT (CYAN) vs BUY & HOLD (AMBER)", padLeft + 6, eqTop + 12);
    ctx.fillText(fmtPct((eMax - 1) * 100), W - padRight + 6, eqTop + 10);
    ctx.fillText(fmtPct((eMin - 1) * 100), W - padRight + 6, eqTop + eqH - 3);

    // Date axis ticks
    ctx.fillStyle = "#6b7d96";
    const tickCount = 6;
    for (let t = 0; t <= tickCount; t++) {
      const bIdx = Math.min(visEnd, Math.round(visStart + ((visEnd - visStart) * t) / tickCount));
      const x = xForBar(bIdx);
      ctx.fillText(bars[bIdx].date, Math.min(W - padRight - 62, Math.max(padLeft, x - 26)), H - 6);
    }

    // Replay cursor vertical line
    if (cursor >= visStart && cursor <= visEnd) {
      const cx = xForBar(cursor);
      ctx.save();
      ctx.strokeStyle = "rgba(226, 232, 240, 0.35)";
      ctx.setLineDash([2, 2]);
      ctx.beginPath();
      ctx.moveTo(cx, priceTop);
      ctx.lineTo(cx, eqTop + eqH);
      ctx.stroke();
      ctx.restore();
    }

    // Hover crosshair
    if (state.hoverBarIdx !== null && state.hoverBarIdx >= visStart && state.hoverBarIdx <= visEnd) {
      const hx = xForBar(state.hoverBarIdx);
      ctx.save();
      ctx.strokeStyle = "rgba(56, 189, 248, 0.45)";
      ctx.beginPath();
      ctx.moveTo(hx, priceTop);
      ctx.lineTo(hx, eqTop + eqH);
      ctx.stroke();
      ctx.restore();
    }

    // Update HUD Readout for cursor bar
    const curBar = bars[cursor];
    const relC = Math.max(0, cursor - startIdx);
    const curEq = eqArr[relC] !== undefined ? (eqArr[relC] - 1) * 100 : 0;
    const curBh = bhArr[relC] !== undefined ? (bhArr[relC] - 1) * 100 : 0;
    const isLong = cursor > startIdx && mDetail.signals[cursor - 1] === 1;

    els.hudDate.textContent = curBar.date;
    els.hudOpen.textContent = fmtNum(curBar.open);
    els.hudHigh.textContent = fmtNum(curBar.high);
    els.hudLow.textContent = fmtNum(curBar.low);
    els.hudClose.textContent = fmtNum(curBar.close);
    els.hudPos.textContent = isLong ? "LONG" : "FLAT";
    els.hudPos.className = isLong ? "tag-long" : "tag-flat";
    els.hudStratEq.textContent = fmtPct(curEq);
    els.hudStratEq.className = clsRet(curEq);
    els.hudBhEq.textContent = fmtPct(curBh);
    els.hudBhEq.className = clsRet(curBh);
    els.hudTrades.textContent = tradesUpToCursor;

    const indSummary = mDetail.indicators.series
      .map((s) => {
        const v = s.values[cursor];
        return v !== null && v !== undefined ? `${s.name.split("(")[0]}:${v.toFixed(1)}` : null;
      })
      .filter(Boolean)
      .join(" ");
    els.hudInd.textContent = indSummary || "--";

    // Store geometry for mousemove hover
    canvas._chartGeom = { visStart, visEnd, visCount, padLeft, padRight, plotW, W, bars, mDetail };
  }

  function renderStressInspector() {
    const s = state.dashboard.leaderboard.find((x) => x.id === state.selectedStrategyId);
    if (!s) return;
    els.stressSubtitle.textContent = `${s.name} · Family: ${s.family} · Origin: ${s.origin}`;
    els.stressVerdictBadge.textContent = s.verdict === "PASS" ? "SURVIVOR (4/4)" : `DEAD (${s.tests_passed_count}/4)`;
    els.stressVerdictBadge.className = "verdict-pill " + (s.verdict === "PASS" ? "verdict-pass" : "verdict-fail");

    const st = s.stress_tests;
    const feeRows = st.fee_sweep.tiers
      .map(
        (t) => `<tr>
          <td>${t.fee_bps} bps</td>
          <td class="num ${clsRet(t.mean_return_pct)}">${fmtPct(t.mean_return_pct)}</td>
          <td class="num">${fmtPct(t.mean_cagr_pct)}</td>
          <td class="num">${fmtNum(t.mean_sharpe, 3)}</td>
          <td class="num">${t.beats_bh_count}/4</td>
        </tr>`
      )
      .join("");

    const oosRows = Object.entries(st.train_vs_unseen.per_market)
      .map(
        ([sym, r]) => `<tr>
          <td>${sym}</td>
          <td class="num">${fmtNum(r.train_sharpe, 2)}</td>
          <td class="num ${r.unseen_sharpe >= r.unseen_bh_sharpe ? "txt-green" : ""}">${fmtNum(r.unseen_sharpe, 2)}</td>
          <td class="num">${fmtNum(r.unseen_bh_sharpe, 2)}</td>
        </tr>`
      )
      .join("");

    const randRows = Object.entries(st.random_baseline.per_market)
      .map(
        ([sym, r]) => `<tr>
          <td>${sym}</td>
          <td class="num">${fmtNum(r.strategy_sharpe, 2)}</td>
          <td class="num">${fmtNum(r.random_p50_sharpe, 2)}</td>
          <td class="num">${fmtNum(r.random_p75_sharpe, 2)}</td>
          <td class="num ${r.percentile_rank >= 75 ? "txt-green" : "txt-red"}">${r.percentile_rank.toFixed(0)}%</td>
        </tr>`
      )
      .join("");

    const deathBlock =
      s.verdict === "PASS"
        ? `<div class="death-box pass"><strong>VERDICT: SURVIVED ALL 4 STRESS TESTS</strong> &mdash; Promoted to paper-trading watchlist.</div>`
        : `<div class="death-box fail"><strong>DEATH REASONS (GRAVEYARD):</strong><ul>${s.death_reasons
            .map((r) => `<li>${r}</li>`)
            .join("")}</ul></div>`;

    els.stressBody.innerHTML = `
      <div class="stress-grid">
        <div class="gate-card">
          <div class="gate-head">
            <span class="gate-title">1. FEE SWEEP (2&ndash;20 BPS)</span>
            <span class="gate-badge ${st.fee_sweep.passed ? "gate-pass" : "gate-fail"}">${st.fee_sweep.passed ? "PASS" : "FAIL"}</span>
          </div>
          <table class="mini-table">
            <thead><tr><th>FEE</th><th class="num">RET</th><th class="num">CAGR</th><th class="num">SHARPE</th><th class="num">B&amp;H</th></tr></thead>
            <tbody>${feeRows}</tbody>
          </table>
        </div>

        <div class="gate-card">
          <div class="gate-head">
            <span class="gate-title">2. EVERY START DATE (ROLLING)</span>
            <span class="gate-badge ${st.rolling_starts.passed ? "gate-pass" : "gate-fail"}">${st.rolling_starts.passed ? "PASS" : "FAIL"}</span>
          </div>
          <table class="mini-table">
            <tbody>
              <tr><td>Rolling Windows Tested</td><td class="num">${st.rolling_starts.windows_tested}</td></tr>
              <tr><td>Positive Windows (&ge;65%)</td><td class="num ${st.rolling_starts.pct_positive >= 65 ? "txt-green" : "txt-red"}">${st.rolling_starts.pct_positive}%</td></tr>
              <tr><td>Beat B&amp;H Windows (&ge;50%)</td><td class="num ${st.rolling_starts.pct_beat_bh >= 50 ? "txt-green" : "txt-red"}">${st.rolling_starts.pct_beat_bh}%</td></tr>
              <tr><td>Median / Worst / Best</td><td class="num">${fmtPct(st.rolling_starts.median_return_pct)} / ${fmtPct(st.rolling_starts.worst_return_pct)} / ${fmtPct(st.rolling_starts.best_return_pct)}</td></tr>
            </tbody>
          </table>
        </div>

        <div class="gate-card">
          <div class="gate-head">
            <span class="gate-title">3. TRAIN vs UNSEEN (60/40 SPLIT)</span>
            <span class="gate-badge ${st.train_vs_unseen.passed ? "gate-pass" : "gate-fail"}">${st.train_vs_unseen.passed ? "PASS" : "FAIL"}</span>
          </div>
          <table class="mini-table">
            <thead><tr><th>MKT</th><th class="num">TRAIN SH</th><th class="num">OOS SH</th><th class="num">OOS B&amp;H</th></tr></thead>
            <tbody>${oosRows}</tbody>
          </table>
          <div style="margin-top:6px;font-family:var(--font-mono);font-size:10.5px;color:var(--muted);">
            Mean OOS Sharpe: <strong>${fmtNum(st.train_vs_unseen.unseen_mean_sharpe, 3)}</strong> &middot;
            Retention: <strong>${fmtNum(st.train_vs_unseen.sharpe_retention, 2)}</strong>
          </div>
        </div>

        <div class="gate-card">
          <div class="gate-head">
            <span class="gate-title">4. RANDOM BASELINE (${st.random_baseline.trials_per_market} MC)</span>
            <span class="gate-badge ${st.random_baseline.passed ? "gate-pass" : "gate-fail"}">${st.random_baseline.passed ? "PASS" : "FAIL"}</span>
          </div>
          <table class="mini-table">
            <thead><tr><th>MKT</th><th class="num">STRAT</th><th class="num">P50</th><th class="num">P75</th><th class="num">RANK</th></tr></thead>
            <tbody>${randRows}</tbody>
          </table>
          <div style="margin-top:6px;font-family:var(--font-mono);font-size:10.5px;color:var(--muted);">
            Mean Percentile Rank: <strong>${st.random_baseline.mean_percentile_rank}%</strong> (need &ge;75%)
          </div>
        </div>
      </div>
      ${deathBlock}
    `;
  }

  function renderSurvivors() {
    const survivors = state.dashboard.survivors || [];
    els.survivorsCountBadge.textContent = `${survivors.length} ACTIVE`;
    if (survivors.length === 0) {
      const nearMisses = state.dashboard.leaderboard.slice(0, 3);
      const rows = nearMisses
        .map(
          (s) => `<tr data-strategy-id="${s.id}" onclick="window.__selectStrat('${s.id}')">
            <td><strong>${s.name}</strong></td>
            <td class="num">${s.tests_passed_count}/4</td>
            <td class="num ${clsRet(s.summary.mean_return_pct)}">${fmtPct(s.summary.mean_return_pct)}</td>
            <td class="num">${fmtNum(s.summary.mean_sharpe, 2)}</td>
            <td class="num">${fmtNum(s.stress_tests.train_vs_unseen.unseen_mean_sharpe, 2)}</td>
          </tr>`
        )
        .join("");

      els.survivorsBody.innerHTML = `
        <div class="empty-survivors">
          <h4>0 SURVIVORS IN PAPER WATCHLIST</h4>
          <p>Most strategies fail the 4 stress tests &mdash; that is the point of rejecting by default. Any strategy passing all 4 gates in future daily runs will enter this paper-trading list and track live forward bars.</p>
        </div>
        <div style="margin-top:12px;">
          <div class="ctrl-label" style="margin-bottom:6px;">TOP NEAR-MISSES (CLICK TO INSPECT)</div>
          <table class="mini-table">
            <thead><tr><th>STRATEGY</th><th class="num">GATES</th><th class="num">RET</th><th class="num">SHARPE</th><th class="num">OOS SH</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      `;
      return;
    }

    const rows = survivors
      .map((s) => {
        const fwd = s.forward ? s.forward.mean_forward_return_pct : 0;
        const fwdBh = s.forward ? s.forward.mean_forward_bh_return_pct : 0;
        return `<tr data-strategy-id="${s.id}" onclick="window.__selectStrat('${s.id}')">
          <td><strong>${s.name}</strong><br><span class="txt-muted" style="font-size:10px;">Since ${s.discovered_at}</span></td>
          <td class="num ${clsRet(s.summary.mean_return_pct)}">${fmtPct(s.summary.mean_return_pct)}</td>
          <td class="num">${fmtNum(s.summary.mean_sharpe, 2)}</td>
          <td class="num ${clsRet(fwd)}">${fmtPct(fwd)}</td>
          <td class="num">${fmtPct(fwdBh)}</td>
        </tr>`;
      })
      .join("");

    els.survivorsBody.innerHTML = `
      <table class="mini-table">
        <thead><tr><th>SURVIVOR</th><th class="num">IS RET</th><th class="num">SHARPE</th><th class="num">FWD PAPER</th><th class="num">FWD B&amp;H</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    `;
  }

  function renderMatrix() {
    const univ = state.dashboard.meta.universe;
    const lb = state.dashboard.leaderboard;
    const thead = els.matrixTable.querySelector("thead");
    const tbody = els.matrixTable.querySelector("tbody");

    thead.innerHTML = `<tr>
      <th>STRATEGY</th>
      ${univ.map((u) => `<th>${u}</th>`).join("")}
      <th class="num">UNIVERSE AVG</th>
      <th class="num">GATES</th>
    </tr>`;

    tbody.innerHTML = lb
      .map((s) => {
        const cells = univ
          .map((sym) => {
            const pm = s.per_market[sym];
            const beat = pm.beats_bh_return;
            return `<td>
              <div class="matrix-cell ${beat ? "matrix-beat" : "matrix-miss"}"
                   onclick="event.stopPropagation(); window.__selectStrat('${s.id}', '${sym}')">
                <div class="matrix-top ${beat ? "txt-green" : clsRet(pm.total_return_pct)}">${fmtPct(pm.total_return_pct)}</div>
                <div class="matrix-sub">vs ${fmtPct(pm.bh_return_pct)} &middot; Sh ${fmtNum(pm.sharpe, 2)}</div>
              </div>
            </td>`;
          })
          .join("");
        return `<tr data-strategy-id="${s.id}" onclick="window.__selectStrat('${s.id}')">
          <td class="mono" style="font-size:11.5px;"><strong>${s.name}</strong></td>
          ${cells}
          <td class="num ${clsRet(s.summary.mean_excess_return_pct)}">
            ${fmtPct(s.summary.mean_return_pct)}<br>
            <span class="txt-muted" style="font-size:10px;">vs ${fmtPct(s.summary.mean_bh_return_pct)}</span>
          </td>
          <td class="num mono">${s.tests_passed_count}/4</td>
        </tr>`;
      })
      .join("");
  }

  function renderLeaderboard() {
    const lb = state.dashboard.leaderboard;
    const tbody = els.leaderboardTable.querySelector("tbody");
    tbody.innerHTML = lb
      .map((s, idx) => {
        const st = s.stress_tests;
        const pills = [
          { lbl: "FEE", ok: st.fee_sweep.passed },
          { lbl: "ROLL", ok: st.rolling_starts.passed },
          { lbl: "OOS", ok: st.train_vs_unseen.passed },
          { lbl: "RAND", ok: st.random_baseline.passed },
        ]
          .map((p) => `<span class="pill ${p.ok ? "pill-ok" : "pill-no"}">${p.lbl}</span>`)
          .join("");

        return `<tr data-strategy-id="${s.id}" onclick="window.__selectStrat('${s.id}')">
          <td class="mono txt-muted">${idx + 1}</td>
          <td><span class="verdict-pill ${s.verdict === "PASS" ? "verdict-pass" : "verdict-fail"}">${s.verdict}</span></td>
          <td><strong>${s.name}</strong></td>
          <td class="mono txt-muted">${s.family}</td>
          <td class="num ${clsRet(s.summary.mean_return_pct)}">${fmtPct(s.summary.mean_return_pct)}</td>
          <td class="num txt-muted">${fmtPct(s.summary.mean_bh_return_pct)}</td>
          <td class="num ${clsRet(s.summary.mean_excess_return_pct)}">${fmtPct(s.summary.mean_excess_return_pct)}</td>
          <td class="num">${fmtNum(s.summary.mean_sharpe, 3)}</td>
          <td class="num">${fmtNum(st.train_vs_unseen.unseen_mean_sharpe, 3)}</td>
          <td class="num txt-red">${fmtPct(s.summary.mean_max_dd_pct, false)}</td>
          <td class="num">${s.summary.mean_trades.toFixed(1)}</td>
          <td class="num">${s.summary.mean_exposure_pct.toFixed(1)}%</td>
          <td><div class="pill-row">${pills}</div></td>
        </tr>`;
      })
      .join("");
  }

  function renderJournal() {
    const q = (els.journalSearch.value || "").toLowerCase().trim();
    const filter = els.journalFilter.value;
    const entries = state.dashboard.journal.filter((e) => {
      if (filter === "PASS" && e.verdict !== "PASS") return false;
      if (filter === "FAIL" && e.verdict !== "FAIL") return false;
      if (filter === "nearmiss" && e.tests_passed_count < 1) return false;
      if (q) {
        const hay = `${e.name} ${e.family} ${e.death_reasons.join(" ")}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    const tbody = els.journalTable.querySelector("tbody");
    tbody.innerHTML = entries
      .map((e) => {
        const reason = e.death_reasons.length > 0 ? e.death_reasons.join(" · ") : "Passed all 4 stress gates";
        return `<tr data-strategy-id="${e.id}" onclick="window.__selectStrat('${e.id}')">
          <td class="mono txt-muted">${e.run_id}</td>
          <td><span class="verdict-pill ${e.verdict === "PASS" ? "verdict-pass" : "verdict-fail"}">${e.verdict}</span></td>
          <td><strong>${e.name}</strong></td>
          <td class="num ${clsRet(e.summary.mean_return_pct)}">${fmtPct(e.summary.mean_return_pct)}</td>
          <td class="num">${fmtNum(e.summary.mean_sharpe, 3)}</td>
          <td class="num">${e.summary.beats_bh_markets}/4</td>
          <td class="num mono">${e.tests_passed_count}/4</td>
          <td style="font-size:11.5px;color:${e.verdict === "PASS" ? "var(--green)" : "#d5dce6"};">${reason}</td>
        </tr>`;
      })
      .join("");
  }

  function bindEvents() {
    window.__selectStrat = (id, mkt = null) => {
      selectStrategy(id, mkt, true);
      window.scrollTo({ top: 0, behavior: "smooth" });
    };

    els.strategySelect.addEventListener("change", (e) => {
      selectStrategy(e.target.value, null, true);
    });

    els.btnPlay.addEventListener("click", toggleReplay);

    els.btnReset.addEventListener("click", () => {
      stopReplay();
      const { mDetail } = getActiveMarketData();
      if (!mDetail) return;
      state.replayCursor = mDetail.start_idx;
      els.replaySlider.value = state.replayCursor;
      drawChart();
    });

    els.btnEnd.addEventListener("click", () => {
      stopReplay();
      resetCursorToEnd();
      drawChart();
    });

    els.btnStepBack.addEventListener("click", () => {
      stopReplay();
      const { mDetail } = getActiveMarketData();
      if (!mDetail) return;
      state.replayCursor = Math.max(mDetail.start_idx, state.replayCursor - 1);
      els.replaySlider.value = state.replayCursor;
      drawChart();
    });

    els.btnStepFwd.addEventListener("click", () => {
      stopReplay();
      const { mDetail } = getActiveMarketData();
      if (!mDetail) return;
      state.replayCursor = Math.min(mDetail.end_idx, state.replayCursor + 1);
      els.replaySlider.value = state.replayCursor;
      drawChart();
    });

    els.replaySlider.addEventListener("input", (e) => {
      stopReplay();
      state.replayCursor = Number(e.target.value);
      drawChart();
    });

    els.zoomSelect.addEventListener("change", (e) => {
      state.zoomBars = e.target.value;
      drawChart();
    });

    els.journalSearch.addEventListener("input", renderJournal);
    els.journalFilter.addEventListener("change", renderJournal);

    els.canvas.addEventListener("mousemove", (e) => {
      const g = els.canvas._chartGeom;
      if (!g) return;
      const rect = els.canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;
      if (mx < g.padLeft || mx > g.W - g.padRight) {
        state.hoverBarIdx = null;
        els.tooltip.classList.add("hidden");
        drawChart();
        return;
      }
      const frac = (mx - g.padLeft) / g.plotW;
      const idx = Math.max(g.visStart, Math.min(g.visEnd, Math.floor(g.visStart + frac * g.visCount)));
      state.hoverBarIdx = idx;
      const b = g.bars[idx];
      const rel = idx - g.mDetail.start_idx;
      const eq = rel >= 0 && g.mDetail.equity_curve[rel] ? fmtPct((g.mDetail.equity_curve[rel] - 1) * 100) : "--";
      const bh = rel >= 0 && g.mDetail.bh_curve[rel] ? fmtPct((g.mDetail.bh_curve[rel] - 1) * 100) : "--";

      els.tooltip.innerHTML = `
        <div><strong>${b.date}</strong></div>
        <div>O: ${fmtNum(b.open)} &nbsp; H: ${fmtNum(b.high)}</div>
        <div>L: ${fmtNum(b.low)} &nbsp; C: ${fmtNum(b.close)}</div>
        <div>Strat: ${eq} &nbsp; B&amp;H: ${bh}</div>
      `;
      els.tooltip.style.left = Math.min(g.W - 210, mx + 14) + "px";
      els.tooltip.style.top = Math.max(10, my - 20) + "px";
      els.tooltip.classList.remove("hidden");
      drawChart();
    });

    els.canvas.addEventListener("mouseleave", () => {
      state.hoverBarIdx = null;
      els.tooltip.classList.add("hidden");
      drawChart();
    });

    window.addEventListener("resize", drawChart);
  }

  init().catch((err) => {
    console.error(err);
    document.body.insertAdjacentHTML(
      "afterbegin",
      `<div style="background:#3a1018;color:#ffb3bf;padding:12px 20px;font-family:monospace;">Dashboard Error: ${err.message}</div>`
    );
  });
})();
