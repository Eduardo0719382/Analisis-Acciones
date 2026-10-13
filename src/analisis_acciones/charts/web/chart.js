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
    }
    return state.chart;
  }

  function removeSeries() {
    if (!state.chart) return;
    if (state.priceSeries) state.chart.removeSeries(state.priceSeries);
    if (state.volumeSeries) state.chart.removeSeries(state.volumeSeries);
    for (const s of state.indicatorSeries) state.chart.removeSeries(s);
    state.priceSeries = null;
    state.volumeSeries = null;
    state.indicatorSeries = [];
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
        if (!first) first = series;
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
      else showInitialRange();
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
        indicatorSeries: state.indicatorSeries.length,
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
