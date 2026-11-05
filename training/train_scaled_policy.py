#!/usr/bin/env python3
"""Wider students: GPU-resident D4 views, large batches, train/validation convergence logs."""
import argparse,json,math,pathlib,time,random,hashlib
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
from train_policy import TinyPolicy,inputs,masked,augment,metrics


def synchronize(device):
 if device.type=='musa':torch.musa.synchronize()
 elif device.type=='cuda':torch.cuda.synchronize()


def objective(net,x,target):
 pred=masked(net,x)
 soft=F.softmax(target/2,1)
 return -(soft*F.log_softmax(pred/2,1)).sum(1).mean()*4+.25*F.cross_entropy(pred,target.argmax(1))


def evaluate(net,x,y):return metrics(net,x,y)[0]


def main():
 ap=argparse.ArgumentParser()
 ap.add_argument('--data',default='data/cloud_training/labels.jsonl')
 ap.add_argument('--channels',type=int,required=True)
 ap.add_argument('--batch-size',type=int,default=1024)
 ap.add_argument('--steps',type=int,default=4000)
 ap.add_argument('--min-steps',type=int,default=1200)
 ap.add_argument('--eval-every',type=int,default=100)
 ap.add_argument('--patience',type=int,default=6,help='validation checks, not batches')
 ap.add_argument('--lr',type=float,default=.0015)
 ap.add_argument('--out',required=True)
 ap.add_argument('--device',default='musa')
 ap.add_argument('--benchmark',action='store_true')
 a=ap.parse_args()
 if a.device=='musa':import torch_musa
 device=torch.device(a.device)
 torch.set_num_threads(4);torch.manual_seed(20261104);random.seed(20261104);np.random.seed(20261104)
 out=pathlib.Path(a.out);out.mkdir(parents=True,exist_ok=True)
 if (out/'training_report.json').exists() and not a.benchmark:raise RuntimeError('Completed output exists; choose a new --out directory')
 data=pathlib.Path(a.data).read_bytes();entries=[json.loads(l)for l in data.splitlines()]
 train=[e for e in entries if e['split']=='train'];val=[e for e in entries if e['split']=='validation']
 assert set(e['key']for e in train).isdisjoint(e['key']for e in val)
 assert set(e['group']for e in train).isdisjoint(e['group']for e in val)
 xt_cpu,yt_cpu=inputs(train);xv_cpu,yv_cpu=inputs(val)
 xt,yt=xt_cpu.to(device),yt_cpu.to(device);xv,yv=xv_cpu.to(device),yv_cpu.to(device)
 augmented=[augment(xt,yt,k)for k in range(8)]
 xa=torch.cat([v[0]for v in augmented]);ya=torch.cat([v[1]for v in augmented]);del augmented
 net=TinyPolicy(a.channels).to(device)
 if a.benchmark:
  benchmarks=[]
  for batch in [256,1024,2048,4096]:
   opt=torch.optim.AdamW(net.parameters(),lr=a.lr)
   x,y=xa[:batch],ya[:batch]
   for _ in range(5):
    opt.zero_grad(set_to_none=True);loss=objective(net,x,y);loss.backward();opt.step()
   synchronize(device);start=time.perf_counter()
   for _ in range(20):
    opt.zero_grad(set_to_none=True);loss=objective(net,x,y);loss.backward();opt.step()
   synchronize(device);seconds=time.perf_counter()-start
   result={'channels':a.channels,'batch_size':batch,'step_ms':seconds/20*1000,'examples_per_second':20*batch/seconds,'allocated_mib':torch.musa.memory_allocated()/1048576 if device.type=='musa' else None}
   benchmarks.append(result);print(json.dumps(result),flush=True)
  (out/'benchmark.json').write_text(json.dumps(benchmarks,indent=2));return
 opt=torch.optim.AdamW(net.parameters(),lr=a.lr,weight_decay=.0001)
 scheduler=torch.optim.lr_scheduler.ReduceLROnPlateau(opt,mode='min',factor=.5,patience=2,threshold=1e-4,threshold_mode='abs',min_lr=3e-5)
 params=sum(p.numel()for p in net.parameters());history=[];best=float('inf');best_state=None;stale=0;best_step=0;stop_reason='step_limit';loss_acc=0.;start=time.time()
 print(json.dumps({'event':'start','channels':a.channels,'parameters':params,'device':str(device),'batch_size':a.batch_size,'train_unique':len(train),'train_d4_views':len(xa),'validation_unique':len(val),'max_steps':a.steps,'min_steps':a.min_steps}),flush=True)
 rng=np.random.default_rng(20261104);order=rng.permutation(len(xa));cursor=0
 for step in range(1,a.steps+1):
  net.train()
  if cursor+a.batch_size>len(order):order=rng.permutation(len(xa));cursor=0
  idx=torch.tensor(order[cursor:cursor+a.batch_size],device=device);cursor+=a.batch_size
  if step<=50:
   for g in opt.param_groups:g['lr']=a.lr*(.1+.9*step/50)
  opt.zero_grad(set_to_none=True);loss=objective(net,xa[idx],ya[idx]);loss.backward();nn.utils.clip_grad_norm_(net.parameters(),5);opt.step();loss_acc+=loss.detach()
  if step%a.eval_every==0 or step==a.steps:
   train_metrics=evaluate(net,xt,yt);val_metrics=evaluate(net,xv,yv)
   row={'step':step,'equivalent_unique_data_passes':step*a.batch_size/len(train),'train_loss':float(loss_acc/a.eval_every),'train':train_metrics,'validation':val_metrics,'lr':opt.param_groups[0]['lr'],'seconds':time.time()-start}
   history.append(row);loss_acc=0.
   metric=val_metrics['kl_T2']
   if metric<best-1e-4:
    best=metric;best_step=step;best_state={k:v.detach().cpu().clone()for k,v in net.state_dict().items()};stale=0;torch.save(best_state,out/'tiny_policy.pt')
   else:stale+=1
   scheduler.step(metric);row['best_step']=best_step;row['stale_checks']=stale
   (out/'progress.json').write_text(json.dumps(row,indent=2));(out/'history.json').write_text(json.dumps(history,indent=2));print(json.dumps(row),flush=True)
   if step>=a.min_steps and stale>=a.patience:stop_reason='validation_early_stop';break
 synchronize(device);training_seconds=time.time()-start
 last_train=evaluate(net,xt,yt);last_val=evaluate(net,xv,yv)
 net=TinyPolicy(a.channels);net.load_state_dict(best_state)
 best_train,_=metrics(net,xt_cpu,yt_cpu);float_metrics,_=metrics(net,xv_cpu,yv_cpu)
 layers=[]
 with torch.no_grad():
  for layer in [*net.layers,net.head]:
   w=layer.weight;scale=w.abs().flatten(1).max(1).values.clamp_min(1e-8)/127
   q=(w/scale[:,None,None,None]).round().clamp(-127,127).to(torch.int8)
   layers.append({'shape':list(w.shape),'dilation':layer.dilation[0],'weights':q.flatten().tolist(),'scales':scale.tolist(),'bias':layer.bias.tolist()})
   layer.weight.copy_(q.float()*scale[:,None,None,None])
 quant_metrics,reference=metrics(net,xv_cpu,yv_cpu)
 model={'format':'int8 weights per output channel; float32 activations/scales/bias','channels':a.channels,'architecture':f'3x12x12 -> {a.channels} channels x4 conv3 dilation 1,2,3,1 ReLU -> conv1 policy','parameters':params,'weight_bytes':sum(len(l['weights'])+4*(len(l['scales'])+len(l['bias']))for l in layers),'layers':layers}
 (out/'tiny_policy.json').write_text(json.dumps(model));(out/'reference.json').write_text(json.dumps([{'board':e['board'],'side':e['side'],'logits':reference[i].tolist()}for i,e in enumerate(val[:24])]))
 teacher='Rapfi 600-node search move (70%) and mix9svq policy T=2 (30%)' if 'teacher_search_move' in entries[0] else 'Rapfi mix9svq policy'
 report={'channels':a.channels,'parameters':params,'weight_bytes':model['weight_bytes'],'batch_size':a.batch_size,'device':str(device),'device_name':torch.musa.get_device_name(0)if device.type=='musa'else str(device),'torch':torch.__version__,'musa':torch_musa.__version__ if device.type=='musa' else None,'seed':20261104,'train_positions':len(train),'train_augmented_views':len(xa),'validation_positions':len(val),'data_sha256':hashlib.sha256(data).hexdigest(),'best_step':best_step,'stopped_step':step,'stop_reason':stop_reason,'training_seconds':training_seconds,'total_seconds':time.time()-start,'train_at_best':best_train,'float_metrics':float_metrics,'quant_metrics':quant_metrics,'last_train':last_train,'last_validation':last_val,'history':history,'teacher':teacher+', experimental 12x12 extrapolation from 13..22 weights','validation_use':'checkpoint and architecture development selection; no independent final test','training_config':vars(a)}
 (out/'training_report.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items()if k!='history'}),flush=True)
if __name__=='__main__':main()
