# -*- coding: utf-8 -*-
r"""Clean an Odoo filesystem session store.

Odoo keeps sessions as files under ``<data_dir>/sessions``. Two things fill
that directory up with rubbish:

* ``FilesystemSessionStore.save()`` writes a temp file and renames it into
  place, and swallows any OSError while doing so. A failed rename leaves a
  ``tmp*.__wz_sess`` orphan behind and the session is silently never written.
* ``HttpCase`` leaks one session file per test (see README).

Left alone the directory grows without limit, and a crowded shared store is
what made the test suite nondeterministic in the first place.

Usage::

    python clean-sessions.py <sessions-dir> [--keep-db DBNAME] [--max-age-days N]
    python clean-sessions.py C:\odoo-dev\filestore\pilates\sessions --keep-db yoleyva_fitness_v2
    python clean-sessions.py C:\odoo-dev\testdata\sessions --max-age-days 0

Sessions belonging to ``--keep-db`` and younger than ``--max-age-days`` are
kept, so running this against a live server's store does not log anybody out.
Everything else goes: orphaned temp files, sessions from other databases
(test runs), and anything past the age limit.
"""
import argparse
import json
import os
import time


def clean(path, keep_db=None, max_age_days=1.0, dry_run=False):
    cutoff = time.time() - (max_age_days * 86400)
    removed = {'orphaned temp saves': 0, 'sessions from other databases': 0,
               'sessions past the age limit': 0, 'unreadable and expired': 0}
    kept = 0
    freed = 0

    for root, _dirs, files in os.walk(path):
        for name in files:
            fp = os.path.join(root, name)
            try:
                mtime = os.path.getmtime(fp)
                size = os.path.getsize(fp)
            except OSError:
                continue

            why = None
            if name.startswith('tmp') and name.endswith('__wz_sess'):
                why = 'orphaned temp saves'
            elif mtime < cutoff:
                why = 'sessions past the age limit'
            elif keep_db:
                try:
                    with open(fp, encoding='utf-8') as fh:
                        db = (json.load(fh) or {}).get('db')
                except Exception:
                    why = 'unreadable and expired' if mtime < cutoff else None
                else:
                    if db != keep_db:
                        why = 'sessions from other databases'

            if why is None:
                kept += 1
                continue
            if not dry_run:
                try:
                    os.unlink(fp)
                except OSError:
                    continue
            removed[why] += 1
            freed += size

    # prune the bucket directories left empty behind them
    empty = 0
    if not dry_run:
        for root, dirs, _f in os.walk(path, topdown=False):
            for d in dirs:
                p = os.path.join(root, d)
                try:
                    if not os.listdir(p):
                        os.rmdir(p)
                        empty += 1
                except OSError:
                    pass

    print('%s %s' % ('would remove' if dry_run else 'removed', path))
    for reason, count in sorted(removed.items()):
        print('   %-32s %d' % (reason, count))
    if not dry_run:
        print('   %-32s %d' % ('empty bucket directories', empty))
    print('   %-32s %d' % ('kept', kept))
    print('   %-32s %.1f MB' % ('freed', freed / 1048576.0))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('sessions_dir')
    ap.add_argument('--keep-db', default=None,
                    help='keep recent sessions belonging to this database, so a '
                         'running server does not lose its logins')
    ap.add_argument('--max-age-days', type=float, default=1.0)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    if not os.path.isdir(args.sessions_dir):
        raise SystemExit('not a directory: %s' % args.sessions_dir)
    clean(args.sessions_dir, args.keep_db, args.max_age_days, args.dry_run)


if __name__ == '__main__':
    main()
