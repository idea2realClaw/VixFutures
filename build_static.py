#!/usr/bin/env python3
"""Build a self-contained static VIX futures snapshot.

Two data sources:
  * default : fetch from a running local server (--source http://127.0.0.1:8765)
  * --direct: import server.py and query CBOE / volchart.io directly (no HTTP
              service needed). This is what the Longzhu node uses.

Usage:
  python build_static.py --source http://127.0.0.1:8765 --out dist/vixfutures.html
  python build_static.py --direct --out D:\\DragonServer\\www\\vixfutures.html
"""
import argparse
import datetime
import json
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, 'static')
MAX_BACK_DAYS = 20


def get_json(base, path):
    url = base.rstrip('/') + path
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.loads(response.read().decode('utf-8'))


def read(name):
    with open(os.path.join(STATIC, name), encoding='utf-8') as handle:
        return handle.read()


def replace_once(text, old, new, label):
    if text.count(old) != 1:
        raise RuntimeError('%s: expected exactly one occurrence, found %d' % (label, text.count(old)))
    return text.replace(old, new)


def build_js(raw_js):
    load_start = raw_js.index('  function load(index, force) {')
    load_end = raw_js.index("  byId('refreshBtn').addEventListener", load_start)
    new_load = """  function load(index, force) {
    var key = state.dates[index] || SNAPSHOT.dates[0];
    state.data = SNAPSHOT.curves[key] || SNAPSHOT.curves[SNAPSHOT.dates[0]];
    if (!state.data) {
      var box = byId('errorBox');
      box.textContent = '快照数据缺失，请返回广播站首页。';
      box.classList.remove('hidden');
      return;
    }
    renderAll();
    byId('errorBox').classList.add('hidden');
    var button = byId('refreshBtn');
    button.disabled = true;
    button.textContent = '静态快照';
  }

"""
    js = raw_js[:load_start] + new_load + raw_js[load_end:]

    js = replace_once(
        js,
        "  byId('refreshBtn').addEventListener('click', function () { load(state.dateIndex, true); });\n",
        '',
        'refresh listener',
    )

    init_start = js.index("  fetch('/api/dates'")
    init_end = js.index('  window.setInterval(function () {', init_start)
    new_init = """  state.dates = SNAPSHOT.dates.slice(0, MAX_BACK_DAYS + 1);
  var requested = new URLSearchParams(window.location.search).get('date');
  var found = state.dates.indexOf(requested);
  if (found > 0 && found <= MAX_BACK_DAYS) state.dateIndex = found;
  load(state.dateIndex, false);

"""
    js = js[:init_start] + new_init + js[init_end:]

    timer_start = js.index('  window.setInterval(function () {')
    timer_end = js.index('})();', timer_start)
    js = js[:timer_start] + js[timer_end:]

    if 'fetch(' in js:
        raise RuntimeError('static JS still contains fetch()')
    return js


def load_payloads_http(source):
    dates_payload = get_json(source, '/api/dates')
    if not dates_payload.get('ok') or not dates_payload.get('dates'):
        raise RuntimeError('/api/dates returned no dates')
    dates = dates_payload['dates'][: MAX_BACK_DAYS + 1]

    curves = {}
    for date in dates:
        # The newest trading day must use the live endpoint: the historical
        # endpoint intentionally has no previous settlement / volume / OI.
        path = '/api/curve' if date == dates[0] else '/api/curve?date=' + urllib.request.quote(date)
        payload = get_json(source, path)
        if not payload.get('ok'):
            raise RuntimeError('failed to load curve for ' + date)
        curves[date] = payload
    return dates, curves


def load_payloads_direct():
    """Query upstream directly by importing server.py (no HTTP service needed)."""
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    import server  # zero third-party dependencies

    dates = server.fetch_trading_dates()[: MAX_BACK_DAYS + 1]
    if not dates:
        raise RuntimeError('no trading dates available')

    curves = {}
    for date in dates:
        # force=True avoids the 60s payload cache returning stale data.
        payload = server.build_payload(None if date == dates[0] else date, force=True)
        if not payload.get('ok'):
            raise RuntimeError('failed to load curve for ' + date)
        curves[date] = payload
    return dates, curves


def render_snapshot(dates, curves, generated_at=None):
    if generated_at is None:
        generated_at = datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=8))
        ).isoformat(timespec='seconds')

    snapshot = {
        'generatedAt': generated_at,
        'dates': dates,
        'curves': curves,
    }
    snapshot_json = json.dumps(snapshot, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')

    html = read('index.html')
    css = read('style.css')
    css += '\n.hit-counter { display: inline-block; vertical-align: middle; height: 20px; width: auto; }\n'

    js = build_js(read('app.js'))

    marker = '  <link rel="stylesheet" href="/static/style.css">'
    html = replace_once(html, marker, '  <style>\n' + css + '\n  </style>', 'css link')

    marker = '<div class="meta-item"><span class="meta-label">数据源</span><span class="meta-value">CBOE / SquawkFlow</span></div>'
    snapshot_item = (
        marker
        + '\n      <div class="meta-item"><span class="meta-label">页面模式</span>'
        + '<span class="meta-value">静态快照 · 生成于 ' + generated_at + ' · 共 '
        + str(len(dates)) + ' 个交易日</span></div>'
    )
    html = replace_once(html, marker, snapshot_item, 'meta bar')

    html = html.replace('<title>VIX Futures Curve · 期限结构</title>',
                        '<title>VIX期货结构曲线 · 静态快照</title>')

    counter_url = (
        'https://hits.sh/weworkwos.tailf2b74d.ts.net/vixfutures.svg'
        '?label=visits&amp;color=2563eb&amp;labelColor=64748b&amp;style=flat-square'
    )
    counter_img = (
        '        <img class="hit-counter" src="' + counter_url + '"'
        ' alt="访问次数" title="由 hits.sh 统计的真实请求数">\n'
    )
    html = replace_once(
        html,
        '      <div class="top-actions">\n',
        '      <div class="top-actions">\n' + counter_img,
        'top actions',
    )

    marker = '  <script src="/static/app.js"></script>'
    html = replace_once(
        html,
        marker,
        '  <script>\nvar SNAPSHOT = ' + snapshot_json + ';\n' + js + '\n  </script>',
        'script tag',
    )
    return html, generated_at


def write_snapshot(html, out_path, dates, generated_at):
    out_path = os.path.abspath(out_path)
    parent = os.path.dirname(out_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write(html)
    print('OUT=' + out_path)
    print('BYTES=' + str(os.path.getsize(out_path)))
    print('DATES=' + str(len(dates)) + ' FIRST=' + dates[0] + ' LAST=' + dates[-1])
    print('GENERATED_AT=' + generated_at)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', default='http://127.0.0.1:8765')
    parser.add_argument('--direct', action='store_true', help='query upstream directly, no local service')
    parser.add_argument('--out', default=os.path.join(ROOT, 'dist', 'vixfutures.html'))
    args = parser.parse_args()

    if args.direct:
        dates, curves = load_payloads_direct()
    else:
        dates, curves = load_payloads_http(args.source)

    html, generated_at = render_snapshot(dates, curves)
    write_snapshot(html, args.out, dates, generated_at)


if __name__ == '__main__':
    main()
