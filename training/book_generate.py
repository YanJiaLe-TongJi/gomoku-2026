#!/usr/bin/env python3
"""Offline 12x12 freestyle opening recommendations, one CPU teacher process.

The book keys the entire board and side, never a move sequence or opponent ID.
Original Rapfi weights cover 13..22; this teacher enables experimental size 12.
"""
import argparse, collections, hashlib, heapq, json, pathlib, re, time
from label_teacher import Teacher

INITIAL = [(5, 6, 1), (5, 5, 2), (6, 5, 1), (6, 6, 2)]

def transform(p, t):
    r, c = divmod(p, 12)
    if t >= 4: c = 11-c
    for _ in range(t & 3): r, c = c, 11-r
    return r*12+c

def board_of(history):
    board = [0]*144
    for i, (r, c, s) in enumerate(history):
        p = r*12+c
        assert 0 <= r < 12 and 0 <= c < 12 and s == 1+i%2 and board[p] == 0
        board[p] = s
    return board

def pack(board):
    return bytes(sum(board[i+j] << (j*2) for j in range(4)) for i in range(0,144,4))

def canonical(history):
    variants = []
    for t in range(8):
        h = [(*divmod(transform(r*12+c,t),12),s) for r,c,s in history]
        variants.append((pack(board_of(h)), t, h))
    signature, t, hist = min(variants, key=lambda a:(a[0],a[1]))
    side = 1+len(hist)%2
    return signature.hex()+str(side), hist

def won(board, p, side):
    r,c=divmod(p,12)
    for dr,dc in ((0,1),(1,0),(1,1),(1,-1)):
        count=1
        for direction in (1,-1):
            y,x=r+direction*dr,c+direction*dc
            while 0<=y<12 and 0<=x<12 and board[y*12+x]==side:
                count+=1;y+=direction*dr;x+=direction*dc
        if count>=5:return True
    return False

def entry(history):
    b=board_of(history)
    return dict(board=[b[r:r+12]for r in range(0,144,12)],history=history,side=1+len(history)%2)

def search(teacher,e,nodes,ms):
    teacher.send(f'INFO MAX_NODE {nodes}\nINFO TIMEOUT_TURN {ms}\nINFO TIME_LEFT 100000000\nINFO SHOW_DETAIL 1\nBOARD\n'+
                 '\n'.join(f'{c},{r},{1 if s==e["side"] else 2}'for r,c,s in e['history'])+'\nDONE')
    details=[];start=time.monotonic()
    while True:
        line=teacher.q.get(timeout=max(10,ms/1000+5))
        if line is None or 'ERROR' in line or 'disabled:' in line or 'Failed to load' in line:
            raise RuntimeError(str(line))
        if line.startswith('MESSAGE Depth') or line.startswith('MESSAGE Speed'):details.append(line)
        if re.fullmatch(r'\d+,\d+',line):
            c,r=map(int,line.split(','));assert 0<=r<12 and 0<=c<12 and not e['board'][r][c]
            return r*12+c, dict(seconds=time.monotonic()-start,final=details[-1] if details else None)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--binary',default='build/teacher/pbrain-rapfi')
    ap.add_argument('--source',default='data/cloud_training/positions.jsonl')
    ap.add_argument('--output',default='data/opening_book/positions.jsonl')
    ap.add_argument('--max-positions',type=int,default=1200);ap.add_argument('--max-stones',type=int,default=12)
    ap.add_argument('--nodes',type=int,default=250000);ap.add_argument('--ms',type=int,default=700)
    ap.add_argument('--replies',type=int,default=4);a=ap.parse_args()
    out=pathlib.Path(a.output);out.parent.mkdir(parents=True,exist_ok=True)
    existing={e['key']:e for e in map(json.loads,out.read_text().splitlines())}if out.exists()else{}
    pending={};queue=[];counter=0;all_sources=collections.Counter()
    def enqueue(history,source):
        nonlocal counter
        if len(history)>a.max_stones:return
        b=board_of(history)
        if any(won(b,p,s)for p,s in enumerate(b)if s):return
        key,h=canonical(history);all_sources[source]+=1
        if key in pending:return
        pending[key]=(h,source)
        # Cover shallow responses before wide branches; recorded games win ties.
        priority=(len(h),0 if source=='recorded' else 1,counter);counter+=1
        heapq.heappush(queue,(priority,key))
    enqueue(INITIAL,'initial')
    b=board_of(INITIAL)
    for p in range(144):
        if not b[p]:enqueue(INITIAL+[(*divmod(p,12),1)],'all_first_black_moves')
    source_rows=list(map(json.loads,pathlib.Path(a.source).read_text().splitlines()))
    for e in source_rows:
        if len(e['history'])<=a.max_stones:enqueue(e['history'],'recorded')
    teacher=Teacher(a.binary);start=time.monotonic();processed=set()
    # Fail closed: require actual neural policy trace at 12x12 before generating.
    teacher.policy(entry(INITIAL))
    try:
        with out.open('a') as f:
            while queue and len(existing)<a.max_positions:
                _,key=heapq.heappop(queue)
                if key in processed:continue
                processed.add(key);h,source=pending[key];e=entry(h)
                if key in existing:record=existing[key]
                else:
                    nodes=a.nodes*(8 if len(h)==4 else 2 if len(h)<=6 else 1)
                    ms=a.ms*(6 if len(h)==4 else 2 if len(h)<=6 else 1)
                    move,details=search(teacher,e,nodes,ms)
                    h2=h+[(*divmod(move,12),e['side'])];b2=board_of(h2)
                    replies=[]
                    if len(h)+2<=a.max_stones and not won(b2,move,e['side']):
                        if len(h)==4:replies=[p for p in range(144)if not b2[p]]
                        else:
                            pol=teacher.policy(entry(h2))
                            # Always include the searched opponent main response.
                            opponent,_=search(teacher,entry(h2),a.nodes//4,min(200,a.ms))
                            replies=[opponent]+[p for p in sorted(range(144),key=lambda p:-pol[p]) if not b2[p] and p!=opponent][:a.replies-1]
                    record=dict(key=key,history=h,side=e['side'],move=move,opponent_replies=replies,
                                source=source,nodes_limit=nodes,time_limit_ms=ms,search=details)
                    f.write(json.dumps(record,separators=(',',':'))+'\n');f.flush();existing[key]=record
                    if len(existing)%25==0:
                        print(json.dumps(dict(positions=len(existing),queued=len(queue),seconds=round(time.monotonic()-start,2),stones=len(h))),flush=True)
                h2=h+[(*divmod(record['move'],12),e['side'])]
                for reply in record['opponent_replies']:
                    enqueue(h2+[(*divmod(reply,12),3-e['side'])],'teacher_expansion')
    finally:teacher.close()
    report=dict(positions=len(existing),elapsed_seconds=time.monotonic()-start,
                by_stones=dict(collections.Counter(len(e['history'])for e in existing.values())),
                by_source=dict(collections.Counter(e['source']for e in existing.values())),
                queued_unlabelled=len(set(pending)-set(existing)),source=a.source,
                teacher_sha256=hashlib.sha256(pathlib.Path(a.binary).read_bytes()).hexdigest(),
                model_sha256=hashlib.sha256(pathlib.Path(a.binary).parent.joinpath('mix9svqfreestyle_bsmix.bin.lz4').read_bytes()).hexdigest(),
                teacher_domain='Experimental 12x12 inference; original weights support 13..22',
                neural_policy_verified=True,workers=1,arguments=vars(a))
    out.with_suffix('.manifest.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
if __name__=='__main__':main()
