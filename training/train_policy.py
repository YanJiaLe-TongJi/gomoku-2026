#!/usr/bin/env python3
"""Small policy-only CNN distilled from Rapfi logits. Run on cloud, not local Mac."""
import argparse,copy,json,pathlib,random,time,platform
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

class TinyPolicy(nn.Module):
 def __init__(self,channels=16):
  super().__init__();self.layers=nn.ModuleList([nn.Conv2d(i,o,3,padding=d,dilation=d) for i,o,d in [(3,channels,1),(channels,channels,2),(channels,channels,3),(channels,channels,1)]])
  self.head=nn.Conv2d(channels,1,1)
 def forward(self,x):
  for layer in self.layers:x=F.relu(layer(x))
  return self.head(x).flatten(1)

def inputs(entries):
 b=np.array([e['board'] for e in entries],dtype=np.int64);s=np.array([e['side'] for e in entries])[:,None,None]
 return torch.tensor(np.stack([b==s,(b!=s)&(b!=0),np.ones_like(b)],1),dtype=torch.float32),torch.tensor(np.array([e['teacher_logits'] for e in entries]),dtype=torch.float32)

def masked(net,x):
 empty=(x[:,0]+x[:,1]).flatten(1)==0
 return net(x).masked_fill(~empty,-1e4)

def augment(x,t,k):
 x=torch.rot90(x,k%4,(-2,-1));t=torch.rot90(t.reshape(-1,12,12),k%4,(-2,-1))
 if k//4:x=x.flip(-1);t=t.flip(-1)
 return x.contiguous(),t.reshape(-1,144).contiguous()

def metrics(net,x,t):
 net.eval();out=[]
 with torch.no_grad():
  for start in range(0,len(x),256):out.append(masked(net,x[start:start+256]).cpu())
 pred=torch.cat(out);t=t.cpu();best=t.argmax(1);top=pred.topk(20,1).indices
 soft=F.softmax(t/2,1)
 kl=F.kl_div(F.log_softmax(pred/2,1),soft,reduction='batchmean').item()
 return {'kl_T2':kl,**{f'top{k}':(top[:,:k]==best[:,None]).any(1).float().mean().item() for k in [1,5,8,12,20]}},pred

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--data',default='data/cloud_training/labels.jsonl');ap.add_argument('--epochs',type=int,default=100);ap.add_argument('--device',default='musa');ap.add_argument('--out',default='models');a=ap.parse_args()
 if a.device=='musa':import torch_musa
 torch.set_num_threads(4);torch.manual_seed(20261104);random.seed(20261104);np.random.seed(20261104)
 device=torch.device(a.device)
 entries=[json.loads(l)for l in open(a.data)];train=[e for e in entries if e['split']=='train'];val=[e for e in entries if e['split']=='validation']
 assert set(e['key'] for e in train).isdisjoint(e['key']for e in val)
 assert set(e['group'] for e in train).isdisjoint(e['group']for e in val)
 xt,yt=inputs(train);xv,yv=inputs(val);xt=xt.to(device);yt=yt.to(device);xv=xv.to(device);yv=yv.to(device)
 net=TinyPolicy().to(device);opt=torch.optim.AdamW(net.parameters(),lr=.002,weight_decay=.0001)
 sch=torch.optim.lr_scheduler.CosineAnnealingLR(opt,T_max=a.epochs,eta_min=.0001)
 out=pathlib.Path(a.out);out.mkdir(exist_ok=True);best=float('inf');best_state=None;stale=0;history=[];start=time.time()
 print(json.dumps({'device':str(device),'torch':torch.__version__,'parameters':sum(p.numel() for p in net.parameters()),'train':len(train),'validation':len(val)},ensure_ascii=False),flush=True)
 for epoch in range(1,a.epochs+1):
  net.train();order=np.random.permutation(len(xt));losses=[]
  for begin in range(0,len(order),256):
   idx=torch.tensor(order[begin:begin+256],device=device);x,t=augment(xt[idx],yt[idx],random.randrange(8));pred=masked(net,x)
   soft=F.softmax(t/2,1);loss=-(soft*F.log_softmax(pred/2,1)).sum(1).mean()*4+.25*F.cross_entropy(pred,t.argmax(1))
   opt.zero_grad(set_to_none=True);loss.backward();nn.utils.clip_grad_norm_(net.parameters(),5);opt.step();losses.append(loss.item())
  sch.step();m,_=metrics(net,xv,yv);row={'epoch':epoch,'loss':sum(losses)/len(losses),**m,'seconds':round(time.time()-start,2)};history.append(row);print(json.dumps(row),flush=True)
  if m['kl_T2']<best-1e-5:
   best=m['kl_T2'];best_state={k:v.detach().cpu().clone() for k,v in net.state_dict().items()};best_epoch=epoch;stale=0;torch.save(best_state,out/'tiny_policy.pt')
  else:stale+=1
  if stale>=20:break
 net=TinyPolicy();net.load_state_dict(best_state);xvc,yvc=inputs(val);float_metrics,_=metrics(net,xvc,yvc)
 exported=[]
 with torch.no_grad():
  for layer in [*net.layers,net.head]:
   w=layer.weight;scales=w.abs().reshape(w.shape[0],-1).max(1).values.clamp_min(1e-8)/127
   q=(w/scales[:,None,None,None]).round().clamp(-127,127).to(torch.int8)
   exported.append({'shape':list(w.shape),'dilation':layer.dilation[0],'weights':q.flatten().tolist(),'scales':scales.tolist(),'bias':layer.bias.tolist()})
   layer.weight.copy_(q.float()*scales[:,None,None,None])
 quant_metrics,reference=metrics(net,xvc,yvc)
 model={'format':'int8 weights per output channel; float32 activations/scales/bias','architecture':'3x12x12 -> 16 channels x4 conv3 dilation 1,2,3,1 ReLU -> conv1 policy','parameters':sum(p.numel()for p in net.parameters()),'weight_bytes':sum(len(l['weights'])+4*(len(l['scales'])+len(l['bias']))for l in exported),'layers':exported}
 (out/'tiny_policy.json').write_text(json.dumps(model))
 (out/'reference.json').write_text(json.dumps([{'board':e['board'],'side':e['side'],'logits':reference[i].tolist()} for i,e in enumerate(val[:24])]))
 report={'device':a.device,'device_name':torch.musa.get_device_name(0) if a.device=='musa' else str(device),'torch':torch.__version__,'musa':getattr(torch_musa,'__version__',None) if a.device=='musa' else None,'train_positions':len(train),'validation_positions':len(val),'best_epoch':best_epoch,'seconds':time.time()-start,'float_metrics':float_metrics,'quant_metrics':quant_metrics,'teacher':'Rapfi mix9svq freestyle policy; experimental 12-board extrapolation from weights declaring 13..22','history':history,'parameters':model['parameters'],'weight_bytes':model['weight_bytes'],'validation_use':'checkpoint selection; not an independent playing-strength test'}
 (out/'training_report.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items()if k!='history'}),flush=True)
if __name__=='__main__':main()
