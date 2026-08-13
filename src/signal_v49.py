from dataclasses import dataclass, asdict, field
import numpy as np
import pandas as pd
from .agents import prepare
from .signal_v44 import _trade_pnl_r
from .signal_v45 import _range_signal
from .signal_v46 import classify_regime, _atr_pct_series

# Frozen after V4.8.1. No tuning is allowed in this module.
SETUP={'symbol':'BTC','timeframe':'4h','regime':'RANGE','side':'LONG','rr':2.0,'min_score':2,'horizon':12}
LOSS_COOLDOWN_AFTER=2
LOSS_COOLDOWN_BARS=12

@dataclass
class CostMetrics:
    cost_bps: float
    trades: int
    win_rate: float
    expectancy_r: float
    profit_factor: float
    max_drawdown_r: float
    longest_losing_streak: int
    monte_carlo_mdd_p95: float
    bootstrap_low_r: float
    bootstrap_high_r: float
    positive_folds: int
    folds: int

@dataclass
class V49Result:
    symbol: str
    status: str
    sample_bars: int
    atr_cutoff_pct: float
    costs: list[dict]=field(default_factory=list)
    reason: str=''


def _signal(x,i,atr_cutoff):
    if i<210 or classify_regime(x,i,atr_cutoff)!='RANGE':
        return False
    side,score=_range_signal(x,i)
    return side=='LONG' and score>=SETUP['min_score']


def _mdd(vals):
    if not vals: return 0.0
    a=np.asarray(vals,float); eq=np.cumsum(a); curve=np.r_[0.0,eq]; peak=np.maximum.accumulate(curve)
    return float(np.max(peak-curve))


def _pf(vals):
    if not vals: return 0.0
    a=np.asarray(vals,float); gains=float(a[a>0].sum()); losses=float(-a[a<0].sum())
    return gains/losses if losses>0 else (99.0 if gains>0 else 0.0)


def _lls(vals):
    best=cur=0
    for v in vals:
        if v<0: cur+=1; best=max(best,cur)
        else: cur=0
    return best


def _mc95(vals,seed=49):
    if len(vals)<2: return _mdd(vals)
    rng=np.random.default_rng(seed); a=np.asarray(vals,float); out=[]
    for _ in range(3000):
        out.append(_mdd(list(rng.permutation(a))))
    return float(np.quantile(out,.95))


def _bootstrap(vals,seed=149):
    if len(vals)<2:
        v=float(vals[0]) if vals else 0.0
        return v,v
    rng=np.random.default_rng(seed); a=np.asarray(vals,float)
    sims=rng.choice(a,size=(3000,len(a)),replace=True).mean(axis=1)
    lo,hi=np.quantile(sims,[.05,.95])
    return float(lo),float(hi)


def _fold_ranges(n,horizon):
    # Extended robustness: 50% calibration-only history, 50% split into 4 purged OOS folds.
    train_end=max(480,int(n*.50))
    remaining=n-train_end
    if remaining<520: return train_end,[]
    fold_size=remaining//4; embargo=max(horizon,12); folds=[]
    for k in range(4):
        rs=train_end+k*fold_size
        re=n if k==3 else train_end+(k+1)*fold_size
        s=rs+embargo; e=re-embargo
        if e-s>=90: folds.append((s,e))
    return train_end,folds


def _raw_fold(x,start,end,atr_cutoff,cost_bps):
    rows=[]
    for i in range(start,min(end,len(x)-SETUP['horizon'])):
        if not _signal(x,i,atr_cutoff): continue
        pnl=_trade_pnl_r(x,i,'LONG',SETUP['rr'],1.0,SETUP['horizon'],cost_bps)
        if pnl is not None: rows.append((i,float(pnl)))
    return rows


def _apply_loss_cooldown(rows):
    vals=[]; consec=0; paused_until=-1
    for i,pnl in rows:
        if consec>=LOSS_COOLDOWN_AFTER and i<paused_until:
            continue
        vals.append(pnl)
        if pnl<0:
            consec+=1
            if consec>=LOSS_COOLDOWN_AFTER:
                paused_until=i+LOSS_COOLDOWN_BARS
        else:
            consec=0
    return vals


def _metrics(x,folds,atr_cutoff,cost_bps):
    all_vals=[]; fold_vals=[]
    for start,end in folds:
        vals=_apply_loss_cooldown(_raw_fold(x,start,end,atr_cutoff,cost_bps))
        fold_vals.append(vals); all_vals.extend(vals)
    n=len(all_vals)
    wr=100*sum(v>0 for v in all_vals)/n if n else 0.0
    ev=float(np.mean(all_vals)) if all_vals else 0.0
    pf=_pf(all_vals); mdd=_mdd(all_vals); lls=_lls(all_vals); mc=_mc95(all_vals,49+int(cost_bps))
    lo,hi=_bootstrap(all_vals,149+int(cost_bps))
    pos=sum(1 for vals in fold_vals if vals and float(np.mean(vals))>0)
    return CostMetrics(cost_bps,n,round(wr,2),round(ev,4),round(pf,3),round(mdd,3),lls,round(mc,3),round(lo,4),round(hi,4),pos,len(fold_vals))


def validate_v49(df:pd.DataFrame,symbol='BTC')->V49Result:
    symbol=symbol.upper()
    if symbol!='BTC': return V49Result(symbol,'NO_SETUP',len(df),0.0,[],'V4.9 freezes only BTC 4h RANGE LONG + loss_cooldown')
    x=prepare(df).reset_index(drop=True)
    if len(x)<1650: return V49Result(symbol,'INSUFFICIENT_DATA',len(x),0.0,[],'Need >=1650 4h bars for 4 purged folds')
    train_end,folds=_fold_ranges(len(x),SETUP['horizon'])
    if len(folds)!=4: return V49Result(symbol,'INSUFFICIENT_DATA',len(x),0.0,[],'Need 4 complete purged OOS folds')
    atrp=_atr_pct_series(x).iloc[210:train_end].dropna()
    if len(atrp)<350: return V49Result(symbol,'INSUFFICIENT_DATA',len(x),0.0,[],'ATR calibration history too short')
    atr_cutoff=float(atrp.quantile(.80))
    costs=[_metrics(x,folds,atr_cutoff,c) for c in (8.0,12.0,16.0)]
    base=costs[0]; stress=costs[-1]
    gates=[base.trades>=35,base.positive_folds>=3 and base.folds==4,base.expectancy_r>=.10,base.profit_factor>=1.20,base.max_drawdown_r<=10.0,base.monte_carlo_mdd_p95<=14.0,base.bootstrap_low_r>0.0,stress.expectancy_r>=.05,stress.profit_factor>=1.10]
    names=['trades>=35','3/4 positive folds','EV8>=0.10R','PF8>=1.20','MDD<=10R','MC95<=14R','bootstrap5%>0','EV16>=0.05R','PF16>=1.10']
    failed=[name for ok,name in zip(gates,names) if not ok]
    if all(gates):
        status='FORWARD_TEST_READY'; reason='Passed extended historical confirmation; proceed only to live paper/forward testing'
    else:
        status='HOLD'; reason='Failed: '+', '.join(failed)
    return V49Result(symbol,status,len(x),round(atr_cutoff,3),[asdict(c) for c in costs],reason)
