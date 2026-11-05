#!/usr/bin/env python3
"""Small, bounded self-play PPO experiment after supervised Rapfi distillation.

Terminal +/-1/0 rewards, frozen opponent league, KL and supervised anchors.
No search or hand-written board-value reward. Forced moves are deterministic
and excluded from policy-gradient updates, matching the submitted guard.
"""
import argparse,copy,json,pathlib,time,hashlib
import numpy as np
import torch
from torch.nn import functional as F
from train_policy import TinyPolicy,inputs,masked,metrics
from train_scaled_policy import objective

WINDOWS=np.array([[r*12+c+k*(dr*12+dc)for k in range(5)]
    for dr,dc in [(0,1),(1,0),(1,1),(1,-1)]for r in range(12)for c in range(12)
    if 0<=r+4*dr<12 and 0<=c+4*dc<12],dtype=np.int64)

def planes(boards,sides,device):
    s=np.asarray(sides).reshape(-1,1)
    x=np.stack([boards==s,(boards!=0)&(boards!=s),np.ones_like(boards)],1).astype(np.float32)
    return torch.tensor(x.reshape(-1,3,12,12),device=device)

def guard(boards,sides):
    legal=boards==0;values=boards[:,WINDOWS];free=values==0
    wins=[]
    for colors in [sides,3-sides]:
        four=((values==colors[:,None,None]).sum(2)==4)&(free.sum(2)==1)
        rows,windows=np.where(four);points=WINDOWS[windows,free[rows,windows].argmax(1)]
        flags=np.zeros_like(legal);flags[rows,points]=True;wins.append(flags)
    own,opp=wins;forced=own.any(1)|opp.any(1)
    target=np.where(own.any(1)[:,None],own,opp).argmax(1)
    legal[forced]=False;legal[np.where(forced)[0],target[forced]]=True
    return legal,forced

def openings(n,seed):
    rng=np.random.default_rng(seed);boards=np.zeros((n,144),dtype=np.int8)
    boards[:,[5*12+6,6*12+5]]=1;boards[:,[5*12+5,6*12+6]]=2
    for b in boards:
        for k in range(4):
            stones=np.where(b!=0)[0];empty=np.where(b==0)[0]
            nearby=(np.maximum(np.abs(empty[:,None]//12-stones[None,:]//12),np.abs(empty[:,None]%12-stones[None,:]%12))<=2).any(1)
            b[int(rng.choice(empty[nearby]))]=1+k%2
    return boards

def play(actor,opponents,n,seed,device,sample=True,collect=True):
    rng=np.random.default_rng(seed);boards=openings(n,seed);alive=np.ones(n,dtype=bool)
    winner=np.zeros(n,dtype=np.int8);roles=1+np.arange(n)%2;league=(np.arange(n)//2)%len(opponents)
    records=[];side=1;turns=0
    actor.eval()
    for net in opponents:net.eval()
    with torch.no_grad():
        while alive.any():
            ids=np.where(alive)[0];b=boards[ids];s=np.full(len(ids),side)
            legal,forced=guard(b,s);x=planes(b,s,device);logits=torch.empty((len(ids),144),device=device)
            learner=roles[ids]==side
            for network,mask in [(actor,learner)]+[(net,(~learner)&(league[ids]==i))for i,net in enumerate(opponents)]:
                chosen=np.where(mask)[0]
                if len(chosen):logits[torch.tensor(chosen,device=device)]=network(x[torch.tensor(chosen,device=device)])
            logits=logits.masked_fill(~torch.tensor(legal,device=device),-1e4)
            logprob=F.log_softmax(logits,1).cpu().numpy()
            if sample:
                cdf=np.exp(logprob).cumsum(1);cdf[:,-1]=1
                actions=(cdf>=rng.random(len(ids))[:,None]).argmax(1)
            else:actions=logprob.argmax(1)
            if collect:
                keep=learner&~forced;local=np.where(keep)[0]
                if len(local):records.append((b[local].copy(),s[local],actions[local],logprob[local,actions[local]],ids[local]))
            assert legal[np.arange(len(ids)),actions].all()
            boards[ids,actions]=side
            won=(boards[ids][:,WINDOWS]==side).all(2).any(1)
            winner[ids[won]]=side;alive[ids[won|np.all(boards[ids]!=0,axis=1)]]=False
            side=3-side;turns+=1
            assert turns<=136
    results=np.where(winner==0,0,np.where(winner==roles,1,-1)).astype(np.float32)
    stats=dict(games=n,wins=int((results==1).sum()),losses=int((results==-1).sum()),draws=int((results==0).sum()),score=float((results.mean()+1)/2),max_plies=turns)
    if not records:return None,stats
    b,s,a,lp,game=[np.concatenate([r[k]for r in records])for k in range(5)]
    return (b,s,a,lp,results[game]),stats

def export(net,entries,out,channels):
    out.mkdir(parents=True,exist_ok=True);net=copy.deepcopy(net).cpu().eval()
    x,y=inputs(entries);float_metrics,_=metrics(net,x,y);layers=[]
    with torch.no_grad():
        for layer in [*net.layers,net.head]:
            w=layer.weight;scale=w.abs().flatten(1).max(1).values.clamp_min(1e-8)/127
            q=(w/scale[:,None,None,None]).round().clamp(-127,127).to(torch.int8)
            layers.append(dict(shape=list(w.shape),dilation=layer.dilation[0],weights=q.flatten().tolist(),scales=scale.tolist(),bias=layer.bias.tolist()))
            layer.weight.copy_(q.float()*scale[:,None,None,None])
    quant_metrics,reference=metrics(net,x,y)
    model=dict(format='int8 per output channel; float32 activations',channels=channels,
               parameters=sum(p.numel()for p in net.parameters()),weight_bytes=sum(len(l['weights'])+4*(len(l['scales'])+len(l['bias']))for l in layers),layers=layers)
    (out/'tiny_policy.json').write_text(json.dumps(model))
    (out/'reference.json').write_text(json.dumps([dict(board=e['board'],side=e['side'],logits=reference[i].tolist())for i,e in enumerate(entries[:24])]))
    return dict(float_metrics=float_metrics,quant_metrics=quant_metrics)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--pretrained',required=True);ap.add_argument('--data',required=True);ap.add_argument('--out',required=True)
    ap.add_argument('--channels',type=int,default=168);ap.add_argument('--iterations',type=int,default=12);ap.add_argument('--games',type=int,default=256)
    ap.add_argument('--batch',type=int,default=1024);ap.add_argument('--epochs',type=int,default=3);ap.add_argument('--lr',type=float,default=3e-5);ap.add_argument('--device',default='musa');a=ap.parse_args()
    if a.device=='musa':import torch_musa
    device=torch.device(a.device);torch.set_num_threads(4);torch.manual_seed(309741);rng=np.random.default_rng(309741)
    out=pathlib.Path(a.out);out.mkdir(parents=True,exist_ok=True);assert not (out/'training_report.json').exists()
    entries=[json.loads(l)for l in pathlib.Path(a.data).read_text().splitlines()];train=[e for e in entries if e['split']=='train'];val=[e for e in entries if e['split']=='validation']
    xt,yt=inputs(train);xt=xt.to(device);yt=yt.to(device)
    net=TinyPolicy(a.channels).to(device);net.load_state_dict(torch.load(a.pretrained,map_location='cpu'))
    reference=copy.deepcopy(net).eval();snapshot=copy.deepcopy(net).eval()
    for frozen in [reference,snapshot]:
        for p in frozen.parameters():p.requires_grad_(False)
    opt=torch.optim.AdamW(net.parameters(),lr=a.lr,weight_decay=1e-4)
    history=[];best=-1.;best_iteration=0;start=time.time();total_games=0;total_steps=0
    for iteration in range(1,a.iterations+1):
        rollout,stats=play(net,[reference,snapshot],a.games,510000+iteration,device)
        total_games+=a.games
        b,s,actions,oldlp,returns=rollout
        snapshot.load_state_dict(net.state_dict())
        x=planes(b,s,device);actions=torch.tensor(actions,device=device);oldlp=torch.tensor(oldlp,device=device)
        with torch.no_grad():
            count=min(256,len(b));check=F.log_softmax(masked(net,x[:count]),1).gather(1,actions[:count,None]).squeeze(1)
            logprob_error=float((check-oldlp[:count]).abs().max())
            assert logprob_error<1e-3, ('on-policy log probability mismatch',logprob_error)
        # MUSA 1.3 lacks std.correction; outcomes already reside on CPU.
        adv=torch.tensor((returns-returns.mean())/max(float(returns.std(ddof=1)),.25),device=device)
        losses=[];net.train()
        for epoch in range(a.epochs):
            order=rng.permutation(len(b))
            for begin in range(0,len(order),a.batch):
                idx=torch.tensor(order[begin:begin+a.batch],device=device)
                pred=masked(net,x[idx]);logp=F.log_softmax(pred,1);selected=logp.gather(1,actions[idx,None]).squeeze(1)
                ratio=(selected-oldlp[idx]).exp()
                policy=-torch.minimum(ratio*adv[idx],ratio.clamp(.8,1.2)*adv[idx]).mean()
                entropy=-(logp.exp()*logp).sum(1).mean()
                with torch.no_grad():ref=F.softmax(masked(reference,x[idx]),1)
                kl=F.kl_div(logp,ref,reduction='batchmean')
                sample=torch.tensor(rng.integers(0,len(xt),size=min(256,len(idx))),device=device)
                anchor=objective(net,xt[sample],yt[sample])
                loss=policy+.03*kl-.005*entropy+.05*anchor
                opt.zero_grad(set_to_none=True);loss.backward();torch.nn.utils.clip_grad_norm_(net.parameters(),1);opt.step()
                losses.append(float(loss.detach()));total_steps+=1
        row=dict(iteration=iteration,selfplay=stats,transitions=len(b),loss=float(np.mean(losses)),rollout_logprob_error=logprob_error,seconds=time.time()-start)
        if iteration%2==0 or iteration==a.iterations:
            _,evaluation=play(net,[reference],96,92047,device,sample=False,collect=False);row['development_eval']=evaluation
            if evaluation['score']>best:
                best=evaluation['score'];best_iteration=iteration;torch.save({k:v.detach().cpu()for k,v in net.state_dict().items()},out/'tiny_policy.pt')
        history.append(row);print(json.dumps(row),flush=True);(out/'history.json').write_text(json.dumps(history,indent=2));(out/'progress.json').write_text(json.dumps(row,indent=2))
        torch.save({k:v.detach().cpu()for k,v in net.state_dict().items()},out/'last_policy.pt')
    net.load_state_dict(torch.load(out/'tiny_policy.pt',map_location=device))
    _,final=play(net,[reference],128,92419,device,sample=False,collect=False)
    validation=export(net,val,out,a.channels)
    report=dict(config=vars(a),pretrained_sha256=hashlib.sha256(pathlib.Path(a.pretrained).read_bytes()).hexdigest(),
                algorithm='clipped PPO on terminal outcomes, frozen pretrain/previous-iteration opponents, KL and supervised anchors; no value head',
                total_selfplay_games=total_games,optimizer_steps=total_steps,best_iteration=best_iteration,development_score=best,
                heldout_eval_vs_pretrain=final,seconds=time.time()-start,history=history,**validation,
                limits='bounded initial RL experiment, not convergence; development openings used for checkpoint selection, separate final seed used once; teacher remains 12-board extrapolation')
    (out/'training_report.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items()if k!='history'}),flush=True)
if __name__=='__main__':main()
