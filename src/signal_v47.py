from dataclasses import dataclass, asdict, field
import math
import numpy as np
import pandas as pd
from .agents import prepare
from .signal_v44 import _trade_pnl_r
from .signal_v45 import _trend_signal, _range_signal
from .signal_v46 import classify_regime, _atr_pct_series

# V4.7 intentionally freezes the two BTC 4h candidates discovered in V4.6.
# No RR/regime/side optimization is allowed inside the final robustness gate.
FROZEN_SETUPS = [
    {'symbol':'BTC','timeframe':'4h','regime':'RANGE','side':'LONG','rr':2.0,'min_score':2,'horizon':12},
    {'symbol':'BTC','timeframe':'4h','regime':'TREND','side':'SHORT','rr':1.5,'min_score':2,'horizon':12},
]

@dataclass
class CostResult:
    cost_bps: float
    trades: int
    win_rate: float
    expectancy_r: float
    profit_factor: float
    max_drawdown_r: float
    positive_folds: int
    folds: int
    bootstrap_low_r: float
    bootstrap_high_r: float

@dataclass
class SetupResult:
    timeframe: str
    regime: str
    side: str
    rr: float
    atr_cutoff_pct: float
    status: str
    reason: str
    costs: list[dict] = field(default_factory=list)

@dataclass
class V47Result:
    symbol: str
    status: str
    paper_ready_count: int
    setups: list[dict] = field(default_factory=list)


def _signal(x, i, regime, side, atr_cutoff, min_score):
    if i < 210 or classify_regime(x, i, atr_cutoff) != regime:
        return False
    if regime == 'RANGE': s, score = _range_signal(x, i)
    elif regime == 'TREND': s, score = _trend_signal(x, i)
    else: return False
    return s == side and score >= min_score


def _fold_ranges(n, horizon):
    # First 55% is untouched calibration history. Last 45% is final OOS only.
    train_end = max(420, int(n * 0.55))
    remaining = n - train_end
    if remaining < 360:
        return train_end, []
    fold_size = remaining // 3
    embargo = max(horizon, 12)
    folds=[]
    for k in range(3):
        raw_start = train_end + k * fold_size
        raw_end = n if k == 2 else train_end + (k + 1) * fold_size
        start = raw_start + embargo
        end = raw_end - embargo
        if end - start >= 80:
            folds.append((start, end))
    return train_end, folds


def _trade_series(x, folds, setup, cost_bps, atr_cutoff):
    all_vals=[]; per_fold=[]
    for start,end in folds:
        vals=[]
        for i in range(start, min(end, len(x)-setup['horizon'])):
            if not _signal(x,i,setup['regime'],setup['side'],atr_cutoff,setup['min_score']):
                continue
            pnl=_trade_pnl_r(x,i,setup['side'],setup['rr'],1.0,setup['horizon'],cost_bps)
            if pnl is not None:
                vals.append(float(pnl)); all_vals.append(float(pnl))
        per_fold.append(vals)
    return all_vals, per_fold


def _metrics(vals, per_fold, seed=47):
    if not vals:
        return dict(trades=0, win_rate=0.0, expectancy=0.0, pf=0.0, mdd=0.0, pos=0, folds=len(per_fold), low=0.0, high=0.0)
    a=np.asarray(vals,dtype=float)
    trades=len(a); wr=float((a>0).mean()*100); ev=float(a.mean())
    gains=float(a[a>0].sum()); losses=float(-a[a<0].sum())
    pf=(gains/losses) if losses>0 else (99.0 if gains>0 else 0.0)
    eq=np.cumsum(a); peak=np.maximum.accumulate(np.r_[0.0,eq]); curve=np.r_[0.0,eq]
    mdd=float(np.max(peak-curve))
    pos=sum(1 for f in per_fold if f and (sum(f)/len(f))>0)
    rng=np.random.default_rng(seed)
    if trades >= 2:
        sims=rng.choice(a,size=(2000,trades),replace=True).mean(axis=1)
        low,high=np.quantile(sims,[0.05,0.95])
    else:
        low=high=ev
    return dict(trades=trades,win_rate=wr,expectancy=ev,pf=float(pf),mdd=mdd,pos=pos,folds=len(per_fold),low=float(low),high=float(high))


def validate_setup(df: pd.DataFrame, setup: dict) -> SetupResult:
    x=prepare(df).reset_index(drop=True)
    if len(x) < 1050:
        return SetupResult(setup['timeframe'],setup['regime'],setup['side'],setup['rr'],0.0,'INSUFFICIENT_DATA','Need >=1050 bars',[])
    train_end,folds=_fold_ranges(len(x),setup['horizon'])
    if len(folds) != 3:
        return SetupResult(setup['timeframe'],setup['regime'],setup['side'],setup['rr'],0.0,'INSUFFICIENT_DATA','Need 3 purged OOS folds',[])
    atrp=_atr_pct_series(x).iloc[210:train_end].dropna()
    if len(atrp)<300:
        return SetupResult(setup['timeframe'],setup['regime'],setup['side'],setup['rr'],0.0,'INSUFFICIENT_DATA','ATR train history too short',[])
    atr_cutoff=float(atrp.quantile(.80))
    cost_rows=[]
    for cost in (8.0,12.0,16.0):
        vals,per_fold=_trade_series(x,folds,setup,cost,atr_cutoff)
        m=_metrics(vals,per_fold,seed=47+int(cost))
        cost_rows.append(CostResult(cost,m['trades'],round(m['win_rate'],2),round(m['expectancy'],4),round(m['pf'],3),round(m['mdd'],3),m['pos'],m['folds'],round(m['low'],4),round(m['high'],4)))
    base=cost_rows[0]; stress=cost_rows[-1]
    gates=[
        base.trades>=35,
        base.positive_folds>=2 and base.folds==3,
        base.expectancy_r>=0.10,
        base.profit_factor>=1.20,
        base.max_drawdown_r<=10.0,
        base.bootstrap_low_r>0.0,
        stress.expectancy_r>=0.05,
        stress.profit_factor>=1.10,
    ]
    if all(gates):
        status='PAPER_READY'; reason='Passed frozen OOS, bootstrap, drawdown and 16bps stress gates'
    else:
        status='HOLD';
        failed=[]
        names=['trades>=35','2/3 positive folds','EV8>=0.10R','PF8>=1.20','MDD<=10R','bootstrap5%>0','EV16>=0.05R','PF16>=1.10']
        for ok,name in zip(gates,names):
            if not ok: failed.append(name)
        reason='Failed: '+', '.join(failed)
    return SetupResult(setup['timeframe'],setup['regime'],setup['side'],setup['rr'],round(atr_cutoff,3),status,reason,[asdict(c) for c in cost_rows])


def validate_v47(symbol: str, frames: dict[str,pd.DataFrame]) -> V47Result:
    symbol=symbol.upper()
    setups=[]
    for setup in FROZEN_SETUPS:
        if setup['symbol'] != symbol: continue
        df=frames.get(setup['timeframe'])
        if df is None: continue
        setups.append(validate_setup(df,setup))
    ready=sum(1 for s in setups if s.status=='PAPER_READY')
    status='PAPER_READY' if ready else ('NO_FROZEN_SETUP' if not setups else 'HOLD')
    return V47Result(symbol,status,ready,[asdict(s) for s in setups])
