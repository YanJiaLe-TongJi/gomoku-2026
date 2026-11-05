"""Replay an explicitly saved opening set with paired colors and checkpoint each game."""
import argparse
import collections
import hashlib
import json
import pathlib
import time
from arena import game


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--openings', required=True)
    ap.add_argument('--baseline', required=True)
    ap.add_argument('--challenger', required=True)
    ap.add_argument('--ms', type=int, default=1100)
    ap.add_argument('--output', required=True)
    args = ap.parse_args()
    source = json.loads(pathlib.Path(args.openings).read_text())
    openings = source.get('openings')
    if not isinstance(openings, list):
        openings = source.get('opening_details')
    if not isinstance(openings, list) or not openings:
        raise ValueError('No saved openings in source report')
    report = dict(baseline=args.baseline, challenger=args.challenger,
                  binary_sha256={k: hashlib.sha256(pathlib.Path(v).read_bytes()).hexdigest()
                                 for k, v in [('baseline', args.baseline),
                                              ('challenger', args.challenger)]},
                  budget_ms=args.ms, openings=openings, results=[], completed=False,
                  limitation='Small local development comparison, paired colors; same openings as prior experiment; not online score.')
    started = time.monotonic()
    for opening in openings:
        for side in (1, 2):
            report['results'].append(game(args.baseline, args.challenger, opening, side, args.ms))
            report['counts'] = dict(collections.Counter(r['result'] for r in report['results']))
            report['seconds'] = time.monotonic() - started
            report['max_move_ms'] = max(m['ms'] for r in report['results'] for m in r['moves'])
            report['completed'] = len(report['results']) == len(openings) * 2
            pathlib.Path(args.output).write_text(json.dumps(report, indent=2) + '\n')
            print(len(report['results']), report['counts'], round(report['seconds'], 1), flush=True)


if __name__ == '__main__':
    main()
