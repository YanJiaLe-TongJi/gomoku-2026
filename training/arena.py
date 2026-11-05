#!/usr/bin/env python3
"""Paired-colour probe matches from recorded validation openings, equal wall-time budgets."""
import argparse,concurrent.futures,json,pathlib,random,subprocess,time,collections,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tests'))
from match import wins
class Probe:
 def __init__(self,path):self.p=subprocess.Popen([str(path)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
 def move(self,b,s,ms):
  self.p.stdin.write(f's {s} {ms} '+' '.join(str(v) for row in b for v in row)+'\n');self.p.stdin.flush();return json.loads(self.p.stdout.readline())
 def close(self):self.p.stdin.close();self.p.wait(timeout=5)
def game(base,new,opening,new_side,ms):
 b=[r[:]for r in opening['board']];side=opening['side'];probes={new_side:Probe(new),3-new_side:Probe(base)};moves=[];winner=0
 try:
  for _ in range(sum(v==0 for r in b for v in r)):
   result=probes[side].move(b,side,ms);p=result['pos'];y,x=divmod(p,12)
   if not(0<=p<144) or b[y][x]:raise RuntimeError('illegal arena move')
   b[y][x]=side;moves.append({'side':side,**result})
   if wins(b,y,x,side):winner=side;break
   side=3-side
 finally:
  for p in probes.values():p.close()
 return {'opening':opening['key'],'new_side':new_side,'winner':winner,'result':'draw'if winner==0 else 'win'if winner==new_side else 'lose','moves':moves}
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--baseline',default=str(ROOT/'build/probe_baseline'));ap.add_argument('--challenger',required=True);ap.add_argument('--pairs',type=int,default=12);ap.add_argument('--ms',type=int,default=150);ap.add_argument('--workers',type=int,default=2);ap.add_argument('--output',required=True);a=ap.parse_args()
 data=[json.loads(l)for l in (ROOT/'data/cloud_training/positions.jsonl').read_text().splitlines()]
 candidates=[e for e in data if e['split']=='validation' and 9<=sum(v!=0 for r in e['board']for v in r)<=18]
 rng=random.Random(20261104);rng.shuffle(candidates);openings=[];groups=collections.Counter()
 # Distribute selected opening positions across validation opponents.
 for limit in range(1,a.pairs+1):
  for e in candidates:
   if groups[e['group']]<limit and e not in openings:openings.append(e);groups[e['group']]+=1
   if len(openings)==a.pairs:break
  if len(openings)==a.pairs:break
 jobs=[(e,s)for e in openings for s in [1,2]];results=[];start=time.time()
 with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers)as pool:
  futures=[pool.submit(game,a.baseline,a.challenger,e,s,a.ms)for e,s in jobs]
  for f in concurrent.futures.as_completed(futures):
   r=f.result();results.append(r);print(len(results),dict(collections.Counter(x['result']for x in results)),round(time.time()-start,1),flush=True)
 summary={'baseline':a.baseline,'challenger':a.challenger,'budget_ms':a.ms,'pairs':a.pairs,'workers':a.workers,'counts':dict(collections.Counter(x['result']for x in results)),'seconds':time.time()-start,'max_move_ms':max(m['ms']for r in results for m in r['moves']),'results':results,'limitation':'small development comparison; opening group held out of training but validation used for checkpoint selection; wall-clock/host noise; not online judge score'}
 pathlib.Path(a.output).write_text(json.dumps(summary,indent=2));print(json.dumps({k:v for k,v in summary.items()if k!='results'}))
if __name__=='__main__':main()
