"""Compare exported submissions against the same opponent source and color."""
import argparse
import collections
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROUND_POINTS = {'win': 1.0, 'draw': 0.5, 'lose': 0.0}
MATCH_POINTS = {'win': 3, 'draw': 1, 'lose': 0}


def read_rounds(sid):
    rows = [json.loads(p.read_text()) for p in sorted((ROOT / 'data' / sid / 'rounds').glob('*.json'))]
    result = {}
    for row in rows:
        if row['result'] in ROUND_POINTS:
            key = (row['opponent_submission_url'], row['my_field'])
            result[key] = row
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--baseline', required=True)
    ap.add_argument('--challenger', required=True)
    args = ap.parse_args()
    old, new = read_rounds(args.baseline), read_rounds(args.challenger)
    shared = sorted(old.keys() & new.keys())
    transitions = collections.Counter()
    changes = []
    for key in shared:
        a, b = old[key], new[key]
        transitions[a['result'] + '->' + b['result']] += 1
        if a['result'] == b['result']:
            continue
        board = [r[:] for r in a['initial_board']]
        divergence = None
        for first, second in zip(a['moves'], b['moves']):
            if (first['row'], first['col']) != (second['row'], second['col']):
                divergence = dict(ply=first['ply'], side=first['field'], is_mine=first['is_mine'],
                                  board=board, old_move=[first['row'], first['col']],
                                  new_move=[second['row'], second['col']])
                break
            board[first['row']][first['col']] = first['field']
        changes.append(dict(opponent=a['opponent'], opponent_submission_url=key[0],
                            side=key[1], old_result=a['result'], new_result=b['result'],
                            point_delta=ROUND_POINTS[b['result']] - ROUND_POINTS[a['result']],
                            old_round=a['round_id'], new_round=b['round_id'],
                            first_divergence=divergence))
    # A match uses both colors, and the scoreboard awards 3/1/0 for it.
    def matches(sid):
        p = ROOT / 'data' / sid / 'index.json'
        if not p.exists():
            return {}
        return {e['opponent_submission_url']: e for e in json.loads(p.read_text())['matches']
                if e['result'] in MATCH_POINTS}
    am, bm = matches(args.baseline), matches(args.challenger)
    shared_matches = sorted(am.keys() & bm.keys())
    match_changes = [dict(opponent=am[k]['opponent'], opponent_submission_url=k,
                          old_result=am[k]['result'], new_result=bm[k]['result'],
                          point_delta=MATCH_POINTS[bm[k]['result']] - MATCH_POINTS[am[k]['result']])
                     for k in shared_matches if am[k]['result'] != bm[k]['result']]
    abnormal = []
    for b in new.values():
        reason = b.get('exit_reason') or ''
        who = re.search(r'Brain (\d+)', reason)
        if who and who.group(1) == b['my_brain_id']:
            abnormal.append(dict(round_id=b['round_id'], opponent=b['opponent'], reason=reason))
    report = dict(baseline=args.baseline, challenger=args.challenger,
                  shared_rounds=len(shared), transitions=dict(transitions),
                  round_point_delta=sum(e['point_delta'] for e in changes),
                  shared_matches=len(shared_matches),
                  match_score_delta=sum(e['point_delta'] for e in match_changes),
                  match_changes=match_changes, round_changes=changes,
                  challenger_own_abnormal_exits=abnormal,
                  challenger_max_response_ms=max((b.get('my_max_response_ms') or 0 for b in new.values()), default=0),
                  limitation='Only completed records with identical opponent submission and color are paired. Partial downloads may omit unfinished matches; score delta is not a live ranking.')
    out = ROOT / 'reports' / f'compare_{args.baseline}_{args.challenger}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('match_changes', 'round_changes')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
