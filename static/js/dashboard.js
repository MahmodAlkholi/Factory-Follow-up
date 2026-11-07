/* ==========================================================================
   Chart helpers for the Factory Follow-up Dashboard.
   Every chart reads its data from a <script type="application/json"> block
   rendered by Django's json_script filter, so no inline data is ever built
   by string concatenation in the template.
   ========================================================================== */
(function () {
  "use strict";

  var PALETTE = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
                 "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"];

  var charts = {};

  function isRTL() {
    return document.documentElement.getAttribute("dir") === "rtl";
  }

  function readData(id) {
    if (!id) return [];
    var node = document.getElementById(id);
    if (!node) return [];
    try {
      var parsed = JSON.parse(node.textContent);
      return Array.isArray(parsed) ? parsed : [parsed];
    } catch (error) {
      console.warn("Could not parse chart data from", id, error);
      return [];
    }
  }

  function getCanvas(id) {
    var canvas = document.getElementById(id);
    if (!canvas || typeof Chart === "undefined") return null;
    if (charts[id]) {
      charts[id].destroy();
      delete charts[id];
    }
    return canvas;
  }

  function baseOptions(extra) {
    var options = {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: {
          display: true,
          position: "bottom",
          rtl: isRTL(),
          labels: { boxWidth: 12, font: { size: 11 } }
        },
        tooltip: { rtl: isRTL(), titleFont: { size: 12 }, bodyFont: { size: 12 } }
      }
    };
    if (extra) {
      Object.keys(extra).forEach(function (key) {
        options[key] = extra[key];
      });
    }
    return options;
  }

  function axisOptions(valueSuffix) {
    return {
      scales: {
        x: { grid: { display: false }, ticks: { font: { size: 10 } } },
        y: {
          beginAtZero: true,
          grid: { color: "rgba(148, 163, 184, .18)" },
          ticks: {
            font: { size: 10 },
            callback: function (value) {
              return value + (valueSuffix || "");
            }
          }
        }
      }
    };
  }

  /**
   * Mirror the axes in an RTL page.
   *
   * - the CATEGORY axis is reversed, so the items read right-to-left;
   * - on a vertical chart the VALUE axis only moves to the right-hand side
   *   (reversing it would make the bars grow downwards);
   * - on a horizontal chart the value axis grows right-to-left as well.
   */
  function mirrorForRTL(options, categoryKey, valueKey, horizontal) {
    if (!isRTL() || !options.scales) return options;
    var scales = options.scales;
    if (categoryKey && scales[categoryKey]) {
      scales[categoryKey].reverse = true;
    }
    if (valueKey && scales[valueKey]) {
      if (horizontal) {
        scales[valueKey].reverse = true;
      } else {
        scales[valueKey].position = "right";
      }
    }
    return options;
  }

  function line(canvasId, dataId, opts) {
    var canvas = getCanvas(canvasId);
    if (!canvas) return null;
    var rows = readData(dataId);
    opts = opts || {};
    var series = opts.series || [{ key: "value", label: "Value" }];

    var datasets = series.map(function (item, index) {
      return {
        label: item.label,
        data: rows.map(function (row) { return row[item.key]; }),
        borderColor: item.color || PALETTE[index % PALETTE.length],
        backgroundColor: (item.color || PALETTE[index % PALETTE.length]) + "22",
        borderWidth: 2,
        pointRadius: 3,
        pointHoverRadius: 5,
        tension: 0.3,
        fill: false
      };
    });

    var options = baseOptions();
    var axis = axisOptions(opts.ySuffix);
    axis.scales.x.ticks.maxRotation = 0;
    axis.scales.x.ticks.autoSkip = true;
    axis.scales.x.ticks.maxTicksLimit = 14;
    options.scales = axis.scales;
    mirrorForRTL(options, "x", "y", false);

    charts[canvasId] = new Chart(canvas, {
      type: "line",
      data: { labels: rows.map(function (row) { return row[opts.xKey || "label"]; }), datasets: datasets },
      options: options
    });
    return charts[canvasId];
  }

  function bar(canvasId, dataId, opts) {
    var canvas = getCanvas(canvasId);
    if (!canvas) return null;
    var rows = readData(dataId);
    opts = opts || {};
    var color = opts.color || PALETTE[0];

    var options = baseOptions();
    options.plugins.legend.display = false;
    options.scales = axisOptions(opts.ySuffix).scales;
    mirrorForRTL(options, "x", "y", false);

    charts[canvasId] = new Chart(canvas, {
      type: "bar",
      data: {
        labels: rows.map(function (row) { return row[opts.xKey || "label"]; }),
        datasets: [{
          label: opts.label || "",
          data: rows.map(function (row) { return row[opts.yKey || "value"]; }),
          backgroundColor: color + "cc",
          borderRadius: 5,
          maxBarThickness: 42
        }]
      },
      options: options
    });
    return charts[canvasId];
  }

  function horizontalBar(canvasId, dataId, opts) {
    var canvas = getCanvas(canvasId);
    if (!canvas) return null;
    var rows = readData(dataId);
    opts = opts || {};
    var color = opts.color || PALETTE[3];

    var options = baseOptions();
    options.indexAxis = "y";
    options.plugins.legend.display = false;
    // With indexAxis "y" the CATEGORY axis is y and the VALUE axis is x.
    // The tick callback must live on the value axis, otherwise it would
    // replace the category labels with their index.
    options.scales = {
      x: {
        beginAtZero: true,
        grid: { color: "rgba(148, 163, 184, .18)" },
        ticks: {
          font: { size: 10 },
          callback: function (value) {
            return value + (opts.ySuffix || "");
          }
        }
      },
      y: {
        grid: { display: false },
        ticks: { font: { size: 10 } }
      }
    };
    mirrorForRTL(options, "y", "x", true);

    charts[canvasId] = new Chart(canvas, {
      type: "bar",
      data: {
        labels: rows.map(function (row) { return row[opts.xKey || "label"]; }),
        datasets: [{
          label: opts.label || "",
          data: rows.map(function (row) { return row[opts.yKey || "value"]; }),
          backgroundColor: color + "cc",
          borderRadius: 5,
          maxBarThickness: 26
        }]
      },
      options: options
    });
    return charts[canvasId];
  }

  function doughnut(canvasId, dataId, opts) {
    var canvas = getCanvas(canvasId);
    if (!canvas) return null;
    opts = opts || {};

    var labels = opts.labels;
    var values = opts.values;
    if (!values && dataId) {
      var rows = readData(dataId);
      labels = rows.map(function (row) { return row[opts.labelKey || "label"]; });
      values = rows.map(function (row) { return row[opts.valueKey || "value"]; });
    }

    var options = baseOptions();
    options.cutout = "62%";
    options.plugins.legend.position = "bottom";

    charts[canvasId] = new Chart(canvas, {
      type: "doughnut",
      data: {
        labels: labels || [],
        datasets: [{
          data: values || [],
          backgroundColor: PALETTE,
          borderWidth: 2,
          borderColor: "#fff"
        }]
      },
      options: options
    });
    return charts[canvasId];
  }

  window.DashboardCharts = {
    line: line,
    bar: bar,
    horizontalBar: horizontalBar,
    doughnut: doughnut,
    palette: PALETTE,
    isRTL: isRTL
  };

  /* Redraw charts after an HTMX swap so they never keep stale sizes. */
  document.body.addEventListener("htmx:afterSwap", function () {
    Object.keys(charts).forEach(function (key) {
      if (charts[key]) charts[key].resize();
    });
  });
})();
