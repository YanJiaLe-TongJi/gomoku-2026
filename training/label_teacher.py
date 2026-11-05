#!/usr/bin/env python3
"""Rapfi neural policy distillation labels, fail closed on classical fallback."""
import argparse,json,pathlib,subprocess,queue,threading,re,time,hashlib
class Teacher:
 def __init__(self,binary):
  self.p=subprocess.Popen([str(pathlib.Path(binary).resolve())],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,universal_newlines=True,bufsize=1)
  self.q=queue.Queue();self.thread=threading.Thread(target=self._read,daemon=True);self.thread.start()
  self.send('START 12\nINFO RULE 0\nINFO THREAD_NUM 1\nINFO PONDERING 0\nABOUT')
  self.until_about()
 def _read(self):
  for line in self.p.stdout:self.q.put(line.rstrip())
  self.q.put(None)
 def send(self,s):self.p.stdin.write(s+'\n');self.p.stdin.flush()
 def until_about(self):
  lines=[]
  while True:
   try:line=self.q.get(timeout=30)
   except queue.Empty:raise RuntimeError('teacher timeout')
   if line is None:raise RuntimeError('teacher exited: '+'\n'.join(lines))
   if 'disabled:' in line or 'ERROR' in line or 'Failed to load' in line:raise RuntimeError(line)
   lines.append(line)
   if line.startswith('name='):return lines
 def policy(self,e):
  rows=['YXBOARD']+[f'{c},{r},{1 if color==e["side"] else 2}' for r,c,color in e['history']]+['DONE','TRACEBOARD','ABOUT']
  self.send('\n'.join(rows));lines=self.until_about()
  header=next((i for i,s in enumerate(lines) if 'Policy------Self' in s),None)
  if header is None:raise RuntimeError('No neural policy in TRACEBOARD; refusing classical labels: '+'\n'.join(lines[:12]))
  vals=[]
  for y,line in enumerate(lines[header+1:header+13]):
   tokens=re.findall(r'\[[^\]]+\]|-?\d+',line[len('MESSAGE '):] if line.startswith('MESSAGE ') else line)
   if len(tokens)!=13 or int(tokens[-1])!=y+1:raise RuntimeError('invalid policy row '+line)
   for x,token in enumerate(tokens[:-1]):
    if e['board'][y][x]:
     if not token.startswith('['):raise RuntimeError('occupied cell mismatch')
     vals.append(-1e9)
    else:
     if token.startswith('['):raise RuntimeError('empty cell mismatch')
     vals.append(int(token)/32.0)
  return vals
 def close(self):
  if self.p.poll() is None:self.send('END');self.p.wait(timeout=5)

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--binary',default='build/teacher/pbrain-rapfi');ap.add_argument('--input',default='data/cloud_training/positions.jsonl');ap.add_argument('--output',default='data/cloud_training/labels.jsonl');ap.add_argument('--limit',type=int,default=0);a=ap.parse_args()
 entries=[json.loads(l) for l in open(a.input)];entries=entries[:a.limit or None]
 target=pathlib.Path(a.output);done={json.loads(l)['key'] for l in target.open()} if target.exists() else set()
 teacher=Teacher(a.binary);start=time.time()
 try:
  with target.open('a') as f:
   for i,e in enumerate(entries):
    if e['key'] in done:continue
    logits=teacher.policy(e)
    f.write(json.dumps({**e,'teacher_logits':logits},ensure_ascii=False)+'\n');f.flush()
    if (i+1)%100==0:print(f'labelled {i+1}/{len(entries)} {time.time()-start:.1f}s',flush=True)
 finally:teacher.close()
 print('labels finished',len(entries),flush=True)
if __name__=='__main__':main()
