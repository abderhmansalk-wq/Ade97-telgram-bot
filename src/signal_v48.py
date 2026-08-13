from dataclasses import dataclass, asdict, field
import numpy as np
import pandas as pd
from .agents import prepare
from .signal_v44 import _trade_pnl_r
from .signal_v45 import _range_signal
from .signal_v46 import classify_regime, _atr_pct_series

FROZEN_SETUP={'symbol':'BTC','timeframe':'4h','regime':'RANGE','side':'LONG','rr':2.0,'min_score':2,'horizon':12}

@dataclass
class OverlayResult:
    name: str
    trades: int
    win_rate: float
    expectancy_r: float
    profit_factor: float
    max_drawdown_r: float
    longest_losing_streak: int
    monte_carlo_mdd_p95: float
    status: str
    reason: str

@dataclass
class V48Result:
    symbol: str
    status: str
    best_overlay: str
    overlays: list[dict]=field(default_factory=list)


def _signal(x,i,atr_cutoff):
    if i<210 or classify_regime(x,i,atr_cutoff)!='RANGE': return False
    side,score=_range_signal(x,i)
    return side=='LONG' and score>=FROZEN_SETUP['min_score']


def _mdd(vals):
    if not vals: return 0.0
    a=np.asarray(vals,float); eq=np.cumsum(a); curve=np.r_[0.0,eq]; peak=np.maximum.accumulate(curve)
    return float(np.max(peak-curve))


def _pf(vals):
    if not vals: return 0.0
    a=np.asarray(vals,float); gains=float(a[a>0].sum()); losses=float(-a[a<0].sum())
    return gains/losses if losses>0 else (99.0 if gains>0 else 0.0)


def _longest_losing_streak(vals):
    best=cur=0
    for v in vals:
        if v<0: cur+=1; best=max(best,cur)
        else: cur=0
    return best


def _mc_mdd_p95(vals,seed=48):
    if len(vals)<2: return _mdd(vals)
    rng=np.random.default_rng(seed); a=np.asarray(vals,float); mdds=[]
    for _ in range(2000):
        s=rng.permutation(a)
        mdds.append(_mdd(list(s)))
    return float(np.quantile(mdds,.95))


def _fold_ranges(n,horizon):
    train_end=max(420,int(n*.55)); remaining=n-train_end
    if remaining<360: return train_end,[]
    fold_size=remaining//3; embargo=max(horizon,12); folds=[]
    for k in range(3):
        rs=train_end+k*fold_size; re=n if k==2 else train_end+(k+1)*fold_size
        s=rs+embargo; e=re-embargo
        if e-s>=80: folds.append((s,e))
    return train_end,folds


def _raw_candidates(x,folds,atr_cutoff,cost_bps=8.0):
    out=[]
    for fold_id,(start,end) in enumerate(folds):
        for i in range(start,min(end,len(x)-FROZEN_SETUP['horizon'])):
            if not _signal(x,i,atr_cutoff): continue
            pnl=_trade_pnl_r(x,i,'LONG',FROZEN_SETUP['rr'],1.0,FROZEN_SETUP['horizon'],cost_bps)
            if pnl is None: continue
            atr_pct=float(x.atr.iloc[i]/x.close.iloc[i]*100) if float(x.close.iloc[i]) else 0.0
            out.append({'i':i,'fold':fold_id,'pnl':float(pnl),'atr_pct':atr_pct})
    return out


def _apply_overlay(cands,name):
    vals=[]; last_i=-10_000; consec_losses=0; equity=0.0; peak=0.0; paused_until=-1
    for c in cands:
        i=c['i']
        if name in ('cooldown','combo') and i-last_i<6: continue
        if name in ('loss_cooldown','combo') and consec_losses>=2 and i<paused_until: continue
        if name in ('vol_extreme','combo') and c['atr_pct']>2.4: continue
        dd=peak-equity
        scale=1.0
        if name in ('dd_brake','combo'):
            if dd>=8.0: continue
            if dd>=5.0: scale=.5
        pnl=c['pnl']*scale
        vals.append(pnl); last_i=i; equity+=pnl; peak=max(peak,equity)
        if pnl<0:
            consec_losses+=1
            if consec_losses>=2: paused_until=i+12
        else:
            consec_losses=0
    return vals


def validate_v48(df:pd.DataFrame,symbol='BTC')->V48Result:
    symbol=symbol.upper()
    if symbol!='BTC': return V48Result(symbol,'NO_SETUP','-',[])
    x=prepare(df).reset_index(drop=True)
    if len(x)<1050: return V48Result(symbol,'INSUFFICIENT_DATA','-',[])
    train_end,folds=_fold_ranges(len(x),FROZEN_SETUP['horizon'])
    if len(folds)!=3: return V48Result(symbol,'INSUFFICIENT_DATA','-',[])
    atrp=_atr_pct_series(x).iloc[210:train_end].dropna()
    if len(atrp)<300: return V48Result(symbol,'INSUFFICIENT_DATA','-',[])
    atr_cutoff=float(atrp.quantile(.80))
    cands=_raw_candidates(x,folds,atr_cutoff,8.0)
    overlays=[]
    for name in ('baseline','cooldown','loss_cooldown','dd_brake','vol_extreme','combo'):
        vals=_apply_overlay(cands,name)
        n=len(vals); wr=100*sum(v>0 for v in vals)/n if n else 0.0; ev=float(np.mean(vals)) if vals else 0.0
        pf=_pf(vals); mdd=_mdd(vals); lls=_longest_losing_streak(vals); mc=_mc_mdd_p95(vals,48+len(name))
        gates=[n>=35,ev>=.10,pf>=1.20,mdd<=10.0,mc<=14.0]
        status='PAPER_READY' if all(gates) else 'HOLD'
        failed=[]
        for ok,label in zip(gates,['trades>=35','EV>=0.10R','PF>=1.20','MDD<=10R','MC95<=14R']):
            if not ok: failed.append(label)
        overlays.append(OverlayResult(name,n,round(wr,2),round(ev,4),round(pf,3),round(mdd,3),lls,round(mc,3),status,'Passed risk overlay gates' if status=='PAPER_READY' else 'Failed: '+', '.join(failed)))
    ready=[o for o in overlays if o.status=='PAPER_READY']
    if ready:
        best=max(ready,key=lambda o:(o.expectancy_r,-o.max_drawdown_r,o.trades))
        status='PAPER_READY'; best_name=best.name
    else:
        best=min(overlays,key=lambda o:(o.max_drawdown_r,-o.expectancy_r)) if overlays else None
        status='HOLD'; best_name=best.name if best else '-'
    return V48Result(symbol,status,best_name,[asdict(o) for o in overlays])
