#!/usr/bin/env python3
"""One-shot updater for the Longzhu node.

Flow:
  1. git pull --ff-only origin main
  2. import server.py, query CBOE / volchart.io / Yahoo directly
  3. render a self-contained snapshot and write it to D:\\DragonServer\\www
  4. add the /vixfutures.html link to index.html if it is missing

Zero third-party dependencies. Exit code 0 on success, 1 on failure.
"""
import argparse
import datetime
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import build_static  # noqa: E402

DEFAULT_TARGET = r'D:\DragonServer\www'


def log(message):
    stamp = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
    print('[%s] %s' % (stamp, message), flush=True)


def git_pull():
    log('git pull --ff-only origin main')
    result = subprocess.run(
        ['git', 'pull', '--ff-only', 'origin', 'main'],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    log(result.stdout.strip() or '(no output)')
    return result.returncode == 0


def patch_index(index_path, dry_run=False):
    if not os.path.exists(index_path):
        log('INDEX_MISSING ' + index_path)
        return False

    data = open(index_path, 'rb').read()
    if b'/vixfutures.html' in data:
        log('INDEX_ALREADY_LINKED')
        return True

    eol = b'\r\n' if b'\r\n' in data else b'\n'
    link = '    <li><a href="/vixfutures.html" title="VIX期货结构曲线（静态快照）">VIX期货结构</a></li>'.encode('utf-8')

    nav = data.find(b'<ul class="nav-links"')
    if nav < 0:
        raise RuntimeError('nav-links not found in index.html')
    end = data.find(b'</ul>', nav)
    if end < 0:
        raise RuntimeError('</ul> not found after nav-links')

    patched = data[:end] + link + eol + data[end:]
    if dry_run:
        log('DRY_RUN index patch: would add VIX link')
    else:
        with open(index_path, 'wb') as handle:
            handle.write(patched)
        log('INDEX_PATCHED ' + index_path)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='build into dist/, do not write www or git pull')
    parser.add_argument('--no-pull', action='store_true', help='skip git pull')
    parser.add_argument('--target', default=DEFAULT_TARGET, help='website root (default D:\\DragonServer\\www)')
    args = parser.parse_args()

    log('START root=' + ROOT + ' dry_run=' + str(args.dry_run))

    if not args.dry_run and not args.no_pull:
        if not git_pull():
            log('GIT_PULL_FAILED')
            return 1

    dates, curves = build_static.load_payloads_direct()
    log('DATA_OK dates=%d first=%s last=%s' % (len(dates), dates[0], dates[-1]))

    html, generated_at = build_static.render_snapshot(dates, curves)
    if args.dry_run:
        out_path = os.path.join(ROOT, 'dist', 'vixfutures_dryrun.html')
    else:
        out_path = os.path.join(args.target, 'vixfutures.html')
    build_static.write_snapshot(html, out_path, dates, generated_at)

    patch_index(os.path.join(args.target, 'index.html'), dry_run=args.dry_run)
    log('DONE')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - report any failure with exit code 1
        log('ERROR ' + type(exc).__name__ + ': ' + str(exc))
        sys.exit(1)
