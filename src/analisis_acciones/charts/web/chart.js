// Drawing layer only: every value shown here comes from Python (chart_widget.py).
// No calculations, no network access.
"use strict";

(function () {
  const LWC = window.LightweightCharts;
  const container = document.getElementById("chart");
  const legendTitle = document.getElementById("legend-title");
  const legendValues = document.getElementById("legend-values");
  const legendIndicators = document.getElementById("legend-indicators");

  const state = {
    chart: null,
    priceSeries: null,
    volumeSeries: null,
    indicatorSeries: [],
    bandFills: [],
    overlays: {},
    overlaySeries: [],
    overlayLines: [],
    drawings: [],
    drawingSeries: [],
    drawingLines: [],
    drawingMarkers: null,
    drawMode: null,
    drawPoints: [],
    drawHints: {},
    indicators: [],
    payload: null,
    chartType: "candles",
    theme: null,
    locale: "es-ES",
    labels: { open: "A", high: "Máx", low: "Mín", close: "C", volume: "Vol" },
    priceFormat: null,
    volumeFormat: null,
  };

  function safeLocale(tag) {
    try {
      if (tag && Intl.NumberFormat.supportedLocalesOf([tag]).length) return tag;
    } catch (e) {
      console.warn("Unsupported locale " + tag);
    }
    return "es-ES";
  }

  function numberFormat(decimals) {
    return new Intl.NumberFormat(state.locale, {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    });
  }

  function chartOptions() {
    const t = state.theme;
    return {
      autoSize: true,
      layout: {
        background: { type: "solid", color: t.surface },
        textColor: t.text_muted,
        fontSize: 11,
        attributionLogo: true, // required attribution (Apache-2.0 NOTICE)
        panes: { separatorColor: t.border, separatorHoverColor: t.border },
      },
      grid: {
        vertLines: { color: t.grid },
        horzLines: { color: t.grid },
      },
      crosshair: { mode: LWC.CrosshairMode.Normal },
      rightPriceScale: { borderColor: t.border },
      timeScale: { borderColor: t.border, rightOffset: 3, minBarSpacing: 0.5 },
      localization: { locale: state.locale, dateFormat: "dd/MM/yyyy" },
    };
  }

  function ensureChart() {
    if (!state.chart) {
      state.chart = LWC.createChart(container, chartOptions());
      state.chart.subscribeCrosshairMove(onCrosshairMove);
      state.chart.subscribeClick(onClick);
    }
    return state.chart;
  }

  function removeSeries() {
    if (!state.chart) return;
    if (state.priceSeries) state.chart.removeSeries(state.priceSeries);
    if (state.volumeSeries) state.chart.removeSeries(state.volumeSeries);
    for (const s of state.indicatorSeries) state.chart.removeSeries(s);
    state.bandFills = [];
    for (const s of state.drawingSeries) state.chart.removeSeries(s);
    for (const s of state.overlaySeries) state.chart.removeSeries(s);
    state.overlaySeries = [];
    state.overlayLines = [];
    state.drawingSeries = [];
    state.drawingLines = [];
    state.drawingMarkers = null;
    state.priceSeries = null;
    state.volumeSeries = null;
    state.indicatorSeries = [];
  }

  // Shaded area between two lines of one indicator (Ichimoku cloud). Drawn
  // behind the series; colour flips where the lines cross.
  class BandFill {
    constructor(points, upColor, downColor) {
      this.points = points;
      this.upColor = upColor;
      this.downColor = downColor;
      const self = this;
      this._view = { zOrder: () => "bottom", renderer: () => ({ draw: (t) => self.draw(t) }) };
    }
    attached({ chart, series }) { this.chart = chart; this.series = series; }
    detached() { this.chart = null; this.series = null; }
    updateAllViews() {}
    paneViews() { return [this._view]; }
    draw(target) {
      if (!this.chart || !this.series || this.points.length < 2) return;
      const ts = this.chart.timeScale();
      const xy = [];
      for (const p of this.points) {
        const x = ts.timeToCoordinate(p.time);
        const ya = this.series.priceToCoordinate(p.a);
        const yb = this.series.priceToCoordinate(p.b);
        xy.push(x === null || ya === null || yb === null ? null : { x, ya, yb, up: p.a >= p.b });
      }
      target.useBitmapCoordinateSpace(({ context: ctx, horizontalPixelRatio: hr,
                                         verticalPixelRatio: vr }) => {
        const quad = (x0, a0, b0, x1, a1, b1, up) => {
          ctx.fillStyle = up ? this.upColor : this.downColor;
          ctx.beginPath();
          ctx.moveTo(x0 * hr, a0 * vr); ctx.lineTo(x1 * hr, a1 * vr);
          ctx.lineTo(x1 * hr, b1 * vr); ctx.lineTo(x0 * hr, b0 * vr);
          ctx.closePath(); ctx.fill();
        };
        for (let i = 1; i < xy.length; i++) {
          const p = xy[i - 1];
          const q = xy[i];
          if (!p || !q) continue;
          if (p.up === q.up) {
            quad(p.x, p.ya, p.yb, q.x, q.ya, q.yb, p.up);
          } else {
            // Lines cross between the two bars: split at the intersection.
            const d0 = p.ya - p.yb;
            const d1 = q.ya - q.yb;
            const f = d0 / (d0 - d1);
            const xc = p.x + f * (q.x - p.x);
            const yc = p.ya + f * (q.ya - p.ya);
            quad(p.x, p.ya, p.yb, xc, yc, yc, p.up);
            quad(xc, yc, yc, q.x, q.ya, q.yb, q.up);
          }
        }
      });
    }
  }

  function addIndicators(firstFreePane) {
    const chart = state.chart;
    let nextPane = firstFreePane;
    for (const ind of state.indicators) {
      const pane = ind.placement === "overlay" ? 0 : nextPane++;
      const nf = numberFormat(ind.decimals);
      const priceFormat = {
        type: "custom", minMove: Math.pow(10, -ind.decimals), formatter: (v) => nf.format(v),
      };
      let first = null;
      const byKey = {};
      for (const out of ind.outputs) {
        const common = { priceFormat, priceLineVisible: false, lastValueVisible: true,
                         title: "" };
        const series = out.style === "histogram"
          ? chart.addSeries(LWC.HistogramSeries, { ...common, color: out.color }, pane)
          : chart.addSeries(LWC.LineSeries, {
              ...common, color: out.color, lineWidth: 1, crosshairMarkerVisible: false,
            }, pane);
        series.setData(out.points);
        state.indicatorSeries.push(series);
        byKey[out.key] = { series, points: out.points };
        if (!first) first = series;
      }
      for (const fill of ind.fills || []) {
        const a = byKey[fill.a];
        const b = byKey[fill.b];
        if (!a || !b) continue;
        const bValues = new Map(b.points.filter((p) => "value" in p).map((p) => [p.time, p.value]));
        const band = [];
        for (const p of a.points) {
          if ("value" in p && bValues.has(p.time)) band.push({ time: p.time, a: p.value, b: bValues.get(p.time) });
        }
        const primitive = new BandFill(band, fill.upColor, fill.downColor);
        a.series.attachPrimitive(primitive);
        state.bandFills.push(primitive);
      }
      if (first) {
        for (const level of ind.levels) {
          first.createPriceLine({
            price: level, color: ind.levelColor, lineWidth: 1, lineStyle: LWC.LineStyle.Dashed,
            axisLabelVisible: true, title: "",
          });
        }
      }
    }
    const panes = chart.panes();
    panes.forEach((p, i) => p.setStretchFactor(i === 0 ? 3 : 1));
  }

  function buildSeries() {
    const p = state.payload;
    const t = state.theme;
    const chart = ensureChart();
    removeSeries();
    const fmt = state.priceFormat;
    const priceFormat = {
      type: "custom", minMove: Math.pow(10, -p.decimals), formatter: (v) => fmt.format(v),
    };
    const compact = new Intl.NumberFormat(state.locale, {
      notation: "compact", maximumFractionDigits: 1,
    });
    if (state.chartType === "line") {
      state.priceSeries = chart.addSeries(LWC.LineSeries, {
        color: t.accent, lineWidth: 2, priceFormat,
      }, 0);
      state.priceSeries.setData(p.candles.map((c) => ({ time: c.time, value: c.close })));
    } else {
      state.priceSeries = chart.addSeries(LWC.CandlestickSeries, {
        upColor: t.up, downColor: t.down, borderUpColor: t.up, borderDownColor: t.down,
        wickUpColor: t.up, wickDownColor: t.down, priceFormat,
      }, 0);
      state.priceSeries.setData(p.candles);
    }
    if (p.volume) {
      state.volumeSeries = chart.addSeries(LWC.HistogramSeries, {
        priceFormat: { type: "custom", minMove: 1, formatter: (v) => compact.format(v) },
        priceLineVisible: false, lastValueVisible: false,
      }, 1);
      state.volumeSeries.setData(p.volume);
    }
    addIndicators(p.volume ? 2 : 1);
    renderDrawings();
    renderOverlays();
  }

  // Overlays (projections, wave counts): computed in Python, drawn here --------
  function renderOverlays() {
    if (!state.chart || !state.priceSeries) return;
    for (const s of state.overlaySeries) state.chart.removeSeries(s);
    for (const l of state.overlayLines) state.priceSeries.removePriceLine(l);
    state.overlaySeries = [];
    state.overlayLines = [];
    for (const items of Object.values(state.overlays)) {
      for (const item of items) {
        if (item.kind === "line" && item.points.length >= 2) {
          const s = state.chart.addSeries(LWC.LineSeries, {
            color: item.color, lineWidth: item.width || 1, lineStyle: item.style || 0,
            priceLineVisible: false, lastValueVisible: !!item.lastValue,
            crosshairMarkerVisible: false, title: item.title || "",
          }, 0);
          s.setData(item.points);
          state.overlaySeries.push(s);
          if (item.labels && item.labels.length) {
            LWC.createSeriesMarkers(s, item.labels.map((l) => ({
              time: l.time, position: l.position || "aboveBar", color: l.color || item.color,
              shape: "circle", size: 0, text: l.text,
            })));
          }
        } else if (item.kind === "level") {
          state.overlayLines.push(state.priceSeries.createPriceLine({
            price: item.price, color: item.color, lineWidth: 1, lineStyle: item.style || 2,
            axisLabelVisible: true, title: item.title || "",
          }));
        }
      }
    }
  }

  // When an overlay reaches past the last bar and the user is looking at the
  // latest bars, widen the view so the projected part is visible.
  function revealFuture(items) {
    const candles = state.payload ? state.payload.candles : [];
    if (!state.chart || !candles.length) return;
    const lastTime = candles[candles.length - 1].time;
    let extra = 0;
    for (const item of items) {
      if (item.kind !== "line") continue;
      extra = Math.max(extra, item.points.filter((p) => p.time > lastTime).length);
    }
    const ts = state.chart.timeScale();
    const range = ts.getVisibleLogicalRange();
    const lastIndex = candles.length - 1;
    if (!extra || !range || range.to < lastIndex - 1) return;
    ts.setVisibleLogicalRange({ from: range.from + extra / 2, to: lastIndex + extra + 3 });
  }

  // Drawings -------------------------------------------------------------------
  function timeKey(t) {
    if (typeof t === "string") return t;
    if (t && typeof t === "object" && "year" in t) {
      const mm = String(t.month).padStart(2, "0");
      const dd = String(t.day).padStart(2, "0");
      return `${t.year}-${mm}-${dd}`;
    }
    return null;
  }

  // Map a date onto the bars on screen (weekly/monthly bars start on other dates).
  function snapTime(day) {
    const c = state.payload ? state.payload.candles : [];
    if (!c.length) return null;
    let best = c[0].time;
    for (const bar of c) {
      if (bar.time <= day) best = bar.time; else break;
    }
    return best;
  }

  function clearDrawingArtifacts() {
    if (!state.chart) return;
    for (const s of state.drawingSeries) state.chart.removeSeries(s);
    if (state.priceSeries) for (const l of state.drawingLines) state.priceSeries.removePriceLine(l);
    if (state.drawingMarkers) state.drawingMarkers.setMarkers([]);
    state.drawingSeries = [];
    state.drawingLines = [];
  }

  function renderDrawings() {
    if (!state.chart || !state.priceSeries || !state.theme) return;
    clearDrawingArtifacts();
    const t = state.theme;
    const markers = [];
    for (const d of state.drawings) {
      if (d.kind === "hline") {
        state.drawingLines.push(state.priceSeries.createPriceLine({
          price: d.points[0].price, color: t.accent, lineWidth: 1,
          lineStyle: LWC.LineStyle.Solid, axisLabelVisible: true, title: "",
        }));
      } else if (d.kind === "fib") {
        for (const level of d.levels) {
          state.drawingLines.push(state.priceSeries.createPriceLine({
            price: level.price, color: "#d4a017", lineWidth: 1,
            lineStyle: LWC.LineStyle.Dotted, axisLabelVisible: true,
            title: `${(level.ratio * 100).toFixed(1)} %`,
          }));
        }
      } else if (d.kind === "trend") {
        const pts = d.points
          .map((p) => ({ time: snapTime(p.time), value: p.price }))
          .sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0));
        if (pts[0].time === pts[1].time) continue;
        const s = state.chart.addSeries(LWC.LineSeries, {
          color: t.accent, lineWidth: 2, priceLineVisible: false, lastValueVisible: false,
          crosshairMarkerVisible: false,
        }, 0);
        s.setData(pts);
        state.drawingSeries.push(s);
      } else if (d.kind === "note") {
        markers.push({
          time: snapTime(d.points[0].time), position: "aboveBar", color: "#d4a017",
          shape: "arrowDown", text: d.text,
        });
      }
    }
    markers.sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0));
    if (!state.drawingMarkers) state.drawingMarkers = LWC.createSeriesMarkers(state.priceSeries, []);
    state.drawingMarkers.setMarkers(markers);
  }

  const POINTS_NEEDED = { hline: 1, trend: 2, fib: 2, note: 1 };

  function showHint(text) {
    const hint = document.getElementById("draw-hint");
    hint.textContent = text || "";
    hint.style.display = text ? "block" : "none";
    if (state.theme) {
      hint.style.background = state.theme.surface_alt;
      hint.style.color = state.theme.text;
    }
  }

  function onClick(param) {
    if (!state.drawMode || !param || !param.point || param.time === undefined) return;
    if (!state.priceSeries) return;
    const price = state.priceSeries.coordinateToPrice(param.point.y);
    const day = timeKey(param.time);
    if (price === null || !day) return;
    state.drawPoints.push({ time: day, price: price });
    const needed = POINTS_NEEDED[state.drawMode];
    if (state.drawPoints.length >= needed) {
      const message = JSON.stringify({ kind: state.drawMode, points: state.drawPoints });
      state.drawMode = null;
      state.drawPoints = [];
      showHint("");
      if (window.bridge) window.bridge.drawingCreated(message);
    } else {
      showHint(state.drawHints.second || "");
    }
  }

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && state.drawMode) {
      state.drawMode = null;
      state.drawPoints = [];
      showHint("");
      if (window.bridge) window.bridge.drawingCancelled();
    }
  });

  if (window.QWebChannel && window.qt && window.qt.webChannelTransport) {
    new QWebChannel(window.qt.webChannelTransport, (channel) => {
      window.bridge = channel.objects.bridge;
    });
  }

  function showInitialRange() {
    const n = state.payload.candles.length;
    const ts = state.chart.timeScale();
    if (n > state.payload.initialBars) {
      ts.setVisibleLogicalRange({ from: n - state.payload.initialBars, to: n + 2 });
    } else {
      ts.fitContent();
    }
  }

  function span(key, text, color) {
    const s = document.createElement("span");
    const k = document.createElement("span");
    k.className = "k";
    k.textContent = key;
    s.appendChild(k);
    s.appendChild(document.createTextNode(text));
    if (color) s.style.color = color;
    return s;
  }

  function renderLegend(index) {
    const p = state.payload;
    if (!p || !p.candles.length) {
      legendTitle.textContent = "";
      legendValues.textContent = "";
      return;
    }
    const i = Math.max(0, Math.min(index, p.candles.length - 1));
    const bar = p.candles[i];
    const prev = i > 0 ? p.candles[i - 1].close : null;
    const fmt = state.priceFormat;
    const t = state.theme;
    legendTitle.textContent = p.title;
    legendTitle.style.color = t.text;
    legendValues.replaceChildren();
    const L = state.labels;
    legendValues.appendChild(span(L.open, fmt.format(bar.open)));
    legendValues.appendChild(span(L.high, fmt.format(bar.high)));
    legendValues.appendChild(span(L.low, fmt.format(bar.low)));
    legendValues.appendChild(span(L.close, fmt.format(bar.close)));
    if (prev !== null && prev !== 0) {
      const ch = bar.close - prev;
      const pct = (ch / prev) * 100;
      const sign = ch > 0 ? "+" : "";
      const color = ch > 0 ? t.up : ch < 0 ? t.down : t.text_muted;
      legendValues.appendChild(
        span("", `${sign}${fmt.format(ch)} (${sign}${numberFormat(2).format(pct)} %)`, color));
    }
    const vol = p.volumeByIndex ? p.volumeByIndex[i] : null;
    if (vol !== null && vol !== undefined) {
      legendValues.appendChild(span(L.volume, state.volumeFormat.format(vol)));
    }
    legendValues.style.color = t.text_muted;

    legendIndicators.replaceChildren();
    for (const ind of state.indicators) {
      const row = document.createElement("div");
      const sw = document.createElement("span");
      sw.className = "swatch";
      sw.style.background = ind.outputs[ind.outputs.length - 1].color;
      row.appendChild(sw);
      const nf = numberFormat(ind.decimals);
      const vals = ind.outputs.map((o) => {
        const v = o.byIndex[i];
        return v === null || v === undefined ? "—" : nf.format(v);
      });
      row.appendChild(document.createTextNode(`${ind.label}  ${vals.join(" / ")}`));
      row.style.color = t.text_muted;
      legendIndicators.appendChild(row);
    }
  }

  function onCrosshairMove(param) {
    if (!state.payload) return;
    const last = state.payload.candles.length - 1;
    if (param === undefined || param.time === undefined || param.logical === undefined) {
      renderLegend(last);
      return;
    }
    renderLegend(Math.round(param.logical));
  }

  window.chartApp = {
    configure(options) {
      state.theme = options.theme;
      state.locale = safeLocale(options.locale);
      state.labels = Object.assign(state.labels, options.labels || {});
      state.volumeFormat = new Intl.NumberFormat(state.locale, { maximumFractionDigits: 0 });
      document.body.style.background = state.theme.surface;
      if (state.chart) state.chart.applyOptions(chartOptions());
      if (state.payload) {
        buildSeries();
        renderLegend(state.payload.candles.length - 1);
      }
    },
    setData(payload) {
      const keep = payload.keepRange && state.chart && state.payload
        && state.payload.symbol === payload.symbol
        ? state.chart.timeScale().getVisibleLogicalRange() : null;
      state.payload = payload;
      state.indicators = payload.indicators || [];
      state.priceFormat = numberFormat(payload.decimals);
      ensureChart();
      buildSeries();
      if (keep) state.chart.timeScale().setVisibleLogicalRange(keep);
      else {
        showInitialRange();
        // Re-apply once layout has settled (the first size may still be provisional).
        requestAnimationFrame(() => { if (state.payload === payload) showInitialRange(); });
      }
      renderLegend(payload.candles.length - 1);
    },
    setIndicators(indicators) {
      state.indicators = indicators || [];
      if (state.payload) {
        const range = state.chart.timeScale().getVisibleLogicalRange();
        buildSeries();
        if (range) state.chart.timeScale().setVisibleLogicalRange(range);
        renderLegend(state.payload.candles.length - 1);
      }
    },
    setOverlay(group, items) {
      if (items && items.length) state.overlays[group] = items;
      else delete state.overlays[group];
      renderOverlays();
      revealFuture(items || []);
    },
    setDrawings(drawings) {
      state.drawings = drawings || [];
      renderDrawings();
    },
    setDrawMode(mode, hints) {
      state.drawMode = POINTS_NEEDED[mode] ? mode : null;
      state.drawPoints = [];
      state.drawHints = hints || {};
      showHint(state.drawMode ? state.drawHints.first : "");
    },
    // Test hook: simulate a click at a date/price (bypasses pixel coordinates).
    simulateDrawClick(day, price) {
      if (!state.drawMode) return false;
      state.drawPoints.push({ time: day, price: price });
      if (state.drawPoints.length >= POINTS_NEEDED[state.drawMode]) {
        const message = JSON.stringify({ kind: state.drawMode, points: state.drawPoints });
        state.drawMode = null;
        state.drawPoints = [];
        showHint("");
        if (window.bridge) window.bridge.drawingCreated(message);
      }
      return true;
    },
    setChartType(type) {
      state.chartType = type === "line" ? "line" : "candles";
      if (state.payload) {
        const range = state.chart.timeScale().getVisibleLogicalRange();
        buildSeries();
        if (range) state.chart.timeScale().setVisibleLogicalRange(range);
      }
    },
    clear() {
      removeSeries();
      state.payload = null;
      renderLegend(0);
    },
    // Introspection used by automated tests.
    state() {
      const range = state.chart ? state.chart.timeScale().getVisibleLogicalRange() : null;
      return {
        bars: state.payload ? state.payload.candles.length : 0,
        chartType: state.chartType,
        priceSeriesType: state.priceSeries ? state.priceSeries.seriesType() : null,
        hasVolume: !!state.volumeSeries,
        indicators: state.indicators.map((i) => i.label),
        drawings: state.drawings.length,
        overlayGroups: Object.fromEntries(Object.entries(state.overlays).map(([k, v]) => [k, v.length])),
        overlaySeries: state.overlaySeries.length,
        overlayLines: state.overlayLines.length,
        drawingLines: state.drawingLines.length,
        drawingSeries: state.drawingSeries.length,
        drawMode: state.drawMode,
        bridge: !!window.bridge,
        indicatorSeries: state.indicatorSeries.length,
        bandFills: state.bandFills.length,
        panes: state.chart ? state.chart.panes().length : 0,
        legend: legendTitle.textContent + " | " + legendValues.textContent,
        indicatorLegend: legendIndicators.textContent,
        visibleFrom: range ? range.from : null,
        visibleTo: range ? range.to : null,
        background: document.body.style.background,
      };
    },
  };
})();
