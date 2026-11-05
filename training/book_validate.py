#!/usr/bin/env python3
"""Verify packed C++ lookup against all D4 boards and measure recorded coverage."""
import argparse,collections,json,pathlib,random,subprocess,time
from book_generate import INITIAL,board_of,canonical,transform

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input',default='data/opening_book/positions.jsonl')
    ap.add_argument('--probe',default='data/opening_book/book_probe')
    ap.add_argument('--source',default='data/cloud_training/positions.jsonl')
    ap.add_argument('--report',default='reports/opening_book_validation.json');a=ap.parse_args()
    records={e['key']:e for e in map(json.loads,pathlib.Path(a.input).read_text().splitlines())}
    p=subprocess.Popen([a.probe],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    timings=[];queries=0
    def query(b,side):
        nonlocal queries
        p.stdin.write(str(side)+' '+' '.join(map(str,b))+'\n');p.stdin.flush()
        move,us=p.stdout.readline().split();queries+=1;timings.append(float(us));return int(move)
    checks=collections.Counter();start=time.monotonic()
    try:
        for e in records.values():
            original=board_of(e['history'])
            for t in range(8):
                h=[(*divmod(transform(r*12+c,t),12),s)for r,c,s in e['history']]
                b=board_of(h);key,ch=canonical(h)
                # Canonicalization may choose an equivalent symmetry in symmetric boards.
                expected=records[key]['move'];candidate=query(b,e['side'])
                assert candidate>=0 and b[candidate]==0
                accepted=False
                for ct in range(8):
                    cb=[0]*144
                    for index,value in enumerate(b):cb[transform(index,ct)]=value
                    if cb==board_of(ch) and transform(candidate,ct)==expected:accepted=True
                assert accepted,(e['key'],t,candidate,expected)
                checks['all_eight_symmetry_hits']+=1
            assert query(original,3-e['side'])==-1
            checks['wrong_side_rejected']+=1
        # Non-book valid boards must miss rather than collide with a recommendation.
        rng=random.Random(20261104)
        for _ in range(500):
            h=list(INITIAL);b=board_of(h)
            for i in range(rng.randrange(1,12)):
                pos=rng.choice([j for j,x in enumerate(b)if x==0]);side=1+len(h)%2
                b[pos]=side;h.append((*divmod(pos,12),side))
            key,_=canonical(h);move=query(b,1+len(h)%2)
            if key not in records:assert move==-1;checks['unknown_board_misses']+=1
            else:assert move>=0 and b[move]==0
        black_first=0;initial=board_of(INITIAL)
        for move in range(144):
            if initial[move]:continue
            h=INITIAL+[(*divmod(move,12),1)];b=board_of(h)
            assert query(b,2)>=0;black_first+=1
        checks['all_legal_first_black_moves_covered']=black_first
        first=query(initial,1);assert first>=0
        first_board=board_of(INITIAL+[(*divmod(first,12),1)])
        for reply in range(144):
            if first_board[reply]:continue
            b=first_board[:];b[reply]=2
            assert query(b,1)>=0
            checks['all_replies_to_recommended_first_move_covered']+=1
    finally:p.stdin.close();assert p.wait(timeout=10)==0
    coverage=collections.defaultdict(collections.Counter)
    for e in map(json.loads,pathlib.Path(a.source).read_text().splitlines()):
        stones=len(e['history']);key,_=canonical(e['history'])
        coverage[stones]['positions']+=1;coverage[stones]['hits']+=key in records
    result=dict(positions=len(records),queries=queries,checks=dict(checks),
                max_lookup_us=max(timings),median_lookup_us=sorted(timings)[len(timings)//2],
                seconds=time.monotonic()-start,coverage_by_stones=dict(coverage),
                limitation='Recorded-source coverage is in-sample and does not establish win-rate improvement.')
    pathlib.Path(a.report).write_text(json.dumps(result,indent=2));print(json.dumps(result))
if __name__=='__main__':main()
