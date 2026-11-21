(function () {
  'use strict';

  var SVG_NS = 'http://www.w3.org/2000/svg';
  var W = 1000;
  var H = 420;
  var PAD = { left: 62, right: 24, top: 24, bottom: 48 };

  var state = {
    data: null,
    dates: [],
    dateIndex: 0,
    axisMode: 'auto',
    showPrevious: true,
    showLabels: true
  };

  var MAX_BACK_DAYS = 20;

  function byId(id) { return document.getElementById(id); }

  function svgEl(tag, attrs, text) {
    var node = document.createElementNS(SVG_NS, tag);
    Object.keys(attrs || {}).forEach(function (key) {
      node.setAttribute(key, String(attrs[key]));
    });
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function fmt(value, digits) {
    return value === null || value === undefined ? '—' : Number(value).toFixed(digits === undefined ? 2 : digits);
  }

  function signed(value, digits) {
    if (value === null || value === undefined) return '—';
    var n = Number(value);
    return (n > 0 ? '+' : '') + n.toFixed(digits === undefined ? 2 : digits);
  }

  function trendClass(value) {
    if (value === null || value === undefined || value === 0) return 'flat';
    return value > 0 ? 'up' : 'down';
  }

  function formatTime(iso) {
    if (!iso) return '—';
    var date = new Date(iso);
    if (isNaN(date.getTime())) return iso;
    return date.toLocaleString('zh-CN', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hour12: false
    });
  }

  function smoothPath(points) {
    if (!points.length) return '';
    if (points.length === 1) return 'M' + points[0].x + ',' + points[0].y;
    var d = 'M' + points[0].x.toFixed(2) + ',' + points[0].y.toFixed(2);
    for (var i = 0; i < points.length - 1; i++) {
      var p0 = points[i - 1] || points[i];
      var p1 = points[i];
      var p2 = points[i + 1];
      var p3 = points[i + 2] || p2;
      var c1x = p1.x + (p2.x - p0.x) / 6;
      var c1y = p1.y + (p2.y - p0.y) / 6;
      var c2x = p2.x - (p3.x - p1.x) / 6;
      var c2y = p2.y - (p3.y - p1.y) / 6;
      d += ' C' + c1x.toFixed(2) + ',' + c1y.toFixed(2) +
           ' ' + c2x.toFixed(2) + ',' + c2y.toFixed(2) +
           ' ' + p2.x.toFixed(2) + ',' + p2.y.toFixed(2);
    }
    return d;
  }

  function yDomain(contracts, mode, withPrevious, spotPrice) {
    var values = contracts.map(function (c) { return c.settlement; });
    if (withPrevious) {
      contracts.forEach(function (c) {
        if (c.previousSettlement !== null && c.previousSettlement !== undefined) {
          values.push(c.previousSettlement);
        }
      });
    }
    if (spotPrice && spotPrice > 0) values.push(spotPrice);
    var min = Math.min.apply(null, values);
    var max = Math.max.apply(null, values);
    if (mode === 'narrow') {
      var pad = Math.max((max - min) * 0.18, 0.25);
      return [min - pad, max + pad];
    }
    var low = Math.max(0, Math.floor((min - 2) / 5) * 5);
    var high = Math.ceil((max + 2) / 5) * 5;
    return [low, Math.max(high, low + 5)];
  }

  function renderChart() {
    var svg = byId('curveChart');
    var contracts = state.data ? state.data.contracts : [];
    var empty = byId('chartEmpty');
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    if (!contracts.length) {
      empty.classList.remove('hidden');
      return;
    }
    empty.classList.add('hidden');

    var plotWidth = W - PAD.left - PAD.right;
    var plotHeight = H - PAD.top - PAD.bottom;
    var spot = state.data.spot || {};
    var domain = yDomain(contracts, state.axisMode, state.showPrevious, spot.price);
    var xAt = function (index) {
      return PAD.left + (contracts.length === 1 ? plotWidth / 2 : index * plotWidth / (contracts.length - 1));
    };
    var yAt = function (value) {
      return PAD.top + (domain[1] - value) / (domain[1] - domain[0]) * plotHeight;
    };

    var ticks = 5;
    for (var t = 0; t <= ticks; t++) {
      var value = domain[0] + (domain[1] - domain[0]) * t / ticks;
      var y = yAt(value);
      svg.appendChild(svgEl('line', {
        x1: PAD.left, x2: W - PAD.right, y1: y, y2: y,
        stroke: t === 0 ? '#cbd5e1' : '#eef2f7', 'stroke-width': 1
      }));
      svg.appendChild(svgEl('text', {
        x: PAD.left - 10, y: y + 4, 'text-anchor': 'end',
        fill: '#94a3b8', 'font-size': 11
      }, value.toFixed(state.axisMode === 'narrow' ? 1 : 0)));
    }

    contracts.forEach(function (contract, index) {
      svg.appendChild(svgEl('text', {
        x: xAt(index), y: H - 18, 'text-anchor': 'middle',
        fill: '#64748b', 'font-size': 11
      }, contract.shortLabel));
      svg.appendChild(svgEl('text', {
        x: xAt(index), y: H - 4, 'text-anchor': 'middle',
        fill: '#cbd5e1', 'font-size': 9
      }, contract.label));
    });

    if (state.showPrevious) {
      var previousPoints = contracts
        .filter(function (c) { return c.previousSettlement !== null && c.previousSettlement !== undefined; })
        .map(function (c) { return { x: xAt(c.month - 1), y: yAt(c.previousSettlement) }; });
      if (previousPoints.length > 1) {
        svg.appendChild(svgEl('path', {
          d: smoothPath(previousPoints), fill: 'none', stroke: '#94a3b8',
          'stroke-width': 1.8, 'stroke-dasharray': '5 4', 'stroke-linecap': 'round'
        }));
      }
    }

    var mainPoints = contracts.map(function (c) {
      return { x: xAt(c.month - 1), y: yAt(c.settlement) };
    });
    svg.appendChild(svgEl('path', {
      d: smoothPath(mainPoints), fill: 'none', stroke: '#2563eb',
      'stroke-width': 2.6, 'stroke-linecap': 'round', 'stroke-linejoin': 'round'
    }));

    mainPoints.forEach(function (point, index) {
      svg.appendChild(svgEl('circle', {
        cx: point.x, cy: point.y, r: 4.2,
        fill: '#ffffff', stroke: '#2563eb', 'stroke-width': 2
      }));
      if (state.showLabels) {
        svg.appendChild(svgEl('text', {
          x: point.x, y: point.y - 12, 'text-anchor': 'middle',
          fill: '#475569', 'font-size': 10.5, 'font-weight': 600
        }, fmt(contracts[index].settlement, 2)));
      }
    });

    if (spot.price && spot.price > 0) {
      var spotY = yAt(spot.price);
      svg.appendChild(svgEl('line', {
        x1: PAD.left, x2: W - PAD.right, y1: spotY, y2: spotY,
        stroke: '#16a34a', 'stroke-width': 1.8, 'stroke-dasharray': '8 5'
      }));
      svg.appendChild(svgEl('text', {
        x: W - PAD.right - 4, y: spotY - 7, 'text-anchor': 'end',
        fill: '#16a34a', 'font-size': 11, 'font-weight': 600
      }, 'VIX 现货 ' + fmt(spot.price, 2)));
    }

    var hoverGroup = svgEl('g', { opacity: 0, 'pointer-events': 'none' });
    var hoverLine = svgEl('line', {
      x1: 0, x2: 0, y1: PAD.top, y2: H - PAD.bottom,
      stroke: '#94a3b8', 'stroke-width': 1, 'stroke-dasharray': '3 3'
    });
    var hoverDot = svgEl('circle', {
      cx: 0, cy: 0, r: 7, fill: '#2563eb', 'fill-opacity': 0.18,
      stroke: '#2563eb', 'stroke-width': 1.5
    });
    hoverGroup.appendChild(hoverLine);
    hoverGroup.appendChild(hoverDot);
    svg.appendChild(hoverGroup);

    var hitArea = svgEl('rect', {
      x: PAD.left, y: PAD.top, width: plotWidth, height: plotHeight, fill: 'transparent'
    });
    svg.appendChild(hitArea);

    var tooltip = byId('tooltip');

    function onMove(event) {
      var rect = svg.getBoundingClientRect();
      var viewX = (event.clientX - rect.left) * W / rect.width;
      var nearest = 0;
      var bestDistance = Infinity;
      for (var i = 0; i < mainPoints.length; i++) {
        var distance = Math.abs(mainPoints[i].x - viewX);
        if (distance < bestDistance) { bestDistance = distance; nearest = i; }
      }
      var point = mainPoints[nearest];
      var contract = contracts[nearest];
      var pair = state.data.pairs[nearest - 1];

      hoverGroup.setAttribute('opacity', '1');
      hoverLine.setAttribute('x1', point.x);
      hoverLine.setAttribute('x2', point.x);
      hoverDot.setAttribute('cx', point.x);
      hoverDot.setAttribute('cy', point.y);

      var rows = [
        ['到期日', contract.expiration],
        ['结算价', fmt(contract.settlement, 4)],
        ['前结算', fmt(contract.previousSettlement, 4)],
        ['涨跌', signed(contract.change, 4)],
        ['对上月', pair ? signed(pair.percent, 2) + '%' : '—']
      ];
      var html = '<div class="tooltip-title">' + contract.label + ' · ' + contract.symbol + '</div>';
      rows.forEach(function (row) {
        html += '<div class="tooltip-row"><span>' + row[0] + '</span><b>' + row[1] + '</b></div>';
      });
      tooltip.innerHTML = html;
      tooltip.classList.remove('hidden');

      var wrapRect = byId('chartWrap').getBoundingClientRect();
      var px = point.x / W * rect.width + (rect.left - wrapRect.left);
      var py = point.y / H * rect.height + (rect.top - wrapRect.top);
      tooltip.style.left = Math.max(4, Math.min(px + 14, wrapRect.width - 205)) + 'px';
      tooltip.style.top = Math.max(4, py - 12) + 'px';
    }

    function onLeave() {
      hoverGroup.setAttribute('opacity', '0');
      tooltip.classList.add('hidden');
    }

    hitArea.addEventListener('mousemove', onMove);
    hitArea.addEventListener('mouseleave', onLeave);
  }

  function renderSummary() {
    var data = state.data;
    var metrics = data.metrics;
    var contracts = data.contracts;
    var front = contracts[0];

    var badge = byId('regimeBadge');
    var isContango = metrics.regime === 'contango';
    var isBackwardation = metrics.regime === 'backwardation';
    badge.className = 'badge badge-' + (isContango || isBackwardation ? metrics.regime : 'neutral');
    badge.textContent = isContango ? 'Contango 正向' : isBackwardation ? 'Backwardation 逆向' : 'Flat';

    byId('settleTime').textContent = formatTime(data.source.cboeLastUpdate);
    byId('fetchTime').textContent = formatTime(data.source.fetchedAt);
    var check = data.source.crossCheck || {};
    byId('crossCheck').textContent = check.status === 'ok'
      ? '一致 · 最大差 ' + fmt(check.maxAbsDiff, 4)
      : check.status === 'unavailable' ? '备用源不可用' : '无重叠合约';

    byId('kpiFront').textContent = fmt(front.settlement, 2);
    var frontSub = byId('kpiFrontSub');
    frontSub.textContent = '较前结算 ' + signed(front.change, 2) + ' (' + signed(front.changePct, 2) + '%)';
    frontSub.className = 'kpi-sub ' + trendClass(front.change);

    var secondValue = byId('kpiSecond');
    secondValue.textContent = signed(metrics.frontSecondSpreadPct, 2) + '%';
    secondValue.className = 'kpi-value ' + trendClass(metrics.frontSecondSpreadPct);
    byId('kpiSecondSub').textContent = 'M2 ' + fmt(metrics.second, 2) + ' · 价差 ' + signed(metrics.second - metrics.front, 2);

    var backValue = byId('kpiBack');
    var backLabel = contracts[contracts.length - 1].label;
    backValue.textContent = signed(metrics.frontBackSpreadPct, 2) + '%';
    backValue.className = 'kpi-value ' + trendClass(metrics.frontBackSpreadPct);
    byId('kpiBackSub').textContent = backLabel + ' ' + fmt(metrics.back, 2) + ' · 价差 ' + signed(metrics.frontBackSpread, 2);

    var regimeValue = byId('kpiRegime');
    regimeValue.textContent = isContango ? 'Contango' : isBackwardation ? 'Backwardation' : 'Flat';
    regimeValue.className = 'kpi-value kpi-text ' + (isContango ? 'up' : isBackwardation ? 'down' : 'flat');
    byId('kpiRegimeSub').textContent = '近月 ' + fmt(metrics.front, 2) + ' → 远月 ' + fmt(metrics.back, 2) + ' · ' + metrics.contractCount + ' 个合约';

    var display = byId('dateDisplay');
    while (display.firstChild) display.removeChild(display.firstChild);
    var prefix = document.createElement('span');
    prefix.textContent = '当前日期：';
    var day = document.createElement('b');
    day.textContent = data.date || '—';
    display.appendChild(prefix);
    display.appendChild(day);
    if (state.dateIndex > 0) {
      var offset = document.createElement('span');
      offset.className = 'spot-note';
      offset.textContent = '回溯 ' + state.dateIndex + ' 个交易日';
      display.appendChild(offset);
    }
    var spot = data.spot || {};
    var spotNote = document.createElement('span');
    spotNote.className = 'spot-note';
    spotNote.textContent = spot.price
      ? 'VIX 现货 ' + fmt(spot.price, 2) + ' · ' + (spot.source || '') + (spot.currentOnly ? '（仅当前值）' : '')
      : 'VIX 现货不可用';
    display.appendChild(spotNote);

    var limit = Math.min(MAX_BACK_DAYS, Math.max(0, state.dates.length - 1));
    byId('prevDay').disabled = state.dateIndex >= limit;
    byId('nextDay').disabled = state.dateIndex <= 0;
    byId('todayBtn').disabled = state.dateIndex <= 0;
    byId('todayBtn').classList.toggle('active', state.dateIndex === 0);
  }

  function renderPairs() {
    var grid = byId('pairGrid');
    grid.textContent = '';
    state.data.pairs.forEach(function (pair) {
      var card = document.createElement('div');
      card.className = 'pair-card ' + trendClass(pair.percent);
      var name = document.createElement('div');
      name.className = 'pair-name';
      name.textContent = pair.from + ' → ' + pair.to;
      var pct = document.createElement('div');
      pct.className = 'pair-pct ' + trendClass(pair.percent);
      pct.textContent = signed(pair.percent, 2) + '%';
      var diff = document.createElement('div');
      diff.className = 'pair-diff';
      diff.textContent = signed(pair.difference, 3) + ' pts';
      card.appendChild(name);
      card.appendChild(pct);
      card.appendChild(diff);
      grid.appendChild(card);
    });
  }

  function renderTable() {
    var body = byId('contractRows');
    body.textContent = '';
    state.data.contracts.forEach(function (contract, index) {
      var pair = state.data.pairs[index - 1];
      var row = document.createElement('tr');
      var cells = [
        { text: contract.label, cls: 'month-cell' },
        { text: contract.symbol },
        { text: contract.expiration },
        { text: fmt(contract.settlement, 4), num: true },
        { text: fmt(contract.previousSettlement, 4), num: true },
        { text: signed(contract.change, 4), num: true, cls: trendClass(contract.change) },
        { text: signed(contract.changePct, 2) + '%', num: true, cls: trendClass(contract.changePct) },
        { text: contract.volume === null || contract.volume === undefined ? '—' : contract.volume.toLocaleString('en-US'), num: true },
        { text: contract.openInterest === null || contract.openInterest === undefined ? '—' : contract.openInterest.toLocaleString('en-US'), num: true },
        { text: pair ? signed(pair.percent, 2) + '%' : '—', num: true, cls: pair ? trendClass(pair.percent) : '' }
      ];
      cells.forEach(function (cell) {
        var td = document.createElement('td');
        if (cell.num) td.className = 'num';
        if (cell.cls) td.className = (td.className ? td.className + ' ' : '') + cell.cls;
        td.textContent = cell.text;
        row.appendChild(td);
      });
      body.appendChild(row);
    });
    byId('tableSummary').textContent = '结算价单位：VIX 点数 · 成交量/持仓量来自 CBOE';
  }

  function renderAll() {
    renderSummary();
    renderChart();
    renderPairs();
    renderTable();
  }

  function load(index, force) {
    var button = byId('refreshBtn');
    button.disabled = true;
    button.textContent = '加载中…';
    var query = [];
    if (force) query.push('refresh=1');
    if (index > 0 && state.dates[index]) query.push('date=' + encodeURIComponent(state.dates[index]));
    var url = '/api/curve' + (query.length ? '?' + query.join('&') : '');
    return fetch(url, { cache: 'no-store' })
      .then(function (response) {
        return response.json().then(function (data) { return { response: response, data: data }; });
      })
      .then(function (result) {
        if (!result.response.ok || !result.data.ok) {
          throw new Error(result.data.error || ('HTTP ' + result.response.status));
        }
        state.data = result.data;
        renderAll();
        byId('errorBox').classList.add('hidden');
      })
      .catch(function (error) {
        var box = byId('errorBox');
        box.textContent = '数据加载失败：' + error.message + ' 请确认 server.py 正在运行，或点击刷新重试。';
        box.classList.remove('hidden');
      })
      .then(function () {
        button.disabled = false;
        button.textContent = '刷新数据';
      });
  }

  byId('refreshBtn').addEventListener('click', function () { load(state.dateIndex, true); });
  function goToDate(index) {
    state.dateIndex = index;
    var next = index > 0 && state.dates[index]
      ? '?date=' + encodeURIComponent(state.dates[index])
      : window.location.pathname;
    window.history.replaceState(null, '', next);
    load(index, false);
  }

  byId('prevDay').addEventListener('click', function () {
    var limit = Math.min(MAX_BACK_DAYS, Math.max(0, state.dates.length - 1));
    if (state.dateIndex < limit) goToDate(state.dateIndex + 1);
  });
  byId('nextDay').addEventListener('click', function () {
    if (state.dateIndex > 0) goToDate(state.dateIndex - 1);
  });
  byId('todayBtn').addEventListener('click', function () { goToDate(0); });
  byId('axisMode').addEventListener('click', function (event) {
    var target = event.target;
    if (target.tagName !== 'BUTTON') return;
    state.axisMode = target.getAttribute('data-mode');
    Array.prototype.forEach.call(this.querySelectorAll('button'), function (button) {
      button.classList.toggle('active', button === target);
    });
    renderChart();
  });
  byId('showPrevious').addEventListener('change', function (event) {
    state.showPrevious = event.target.checked;
    renderChart();
  });
  byId('showLabels').addEventListener('change', function (event) {
    state.showLabels = event.target.checked;
    renderChart();
  });

  fetch('/api/dates', { cache: 'no-store' })
    .then(function (response) { return response.json(); })
    .then(function (data) {
      if (data.ok && Array.isArray(data.dates)) {
        state.dates = data.dates;
        var requested = new URLSearchParams(window.location.search).get('date');
        var found = state.dates.indexOf(requested);
        if (found > 0 && found <= MAX_BACK_DAYS) state.dateIndex = found;
      }
    })
    .catch(function () {})
    .then(function () { return load(state.dateIndex, false); });

  window.setInterval(function () {
    if (document.visibilityState === 'visible') load(state.dateIndex, false);
  }, 60000);
})();
