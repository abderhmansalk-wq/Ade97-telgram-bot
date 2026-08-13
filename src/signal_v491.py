from dataclasses import dataclass, asdict, field
import numpy as np
import pandas as pd
from .agents import prepare
from .signal_v49 import SETUP, LOSS_COOLDOWN_AFTER, LOSS_COOLDOWN_BARS, _fold_ranges, _raw_fold
from .signal_v46 import _atr_pct_series

@dataclass
class FoldDiagnostic:
    fold: int
    start: str
    end: str
    raw_candidates: int
    executed_trades: int
    win_rate: float
    expectancy_r: float
    profit_factor: float
    max_drawdown_r: float
    one_position_trades: int
    one_position_win_rate: float
    one_position_expectancy_r: float
    one_position_profit_factor: float
    one_position_max_drawdown_r: float
    positive: bool
    one_position_positive: bool

@dataclass
class V491Result:
    symbol: str
    status: str
    sample_bars: int
    atr_cutoff_pct: float
    total_trades: int
    positive_folds: int
    one_position_total_trades: int
    one_position_positive_folds: int
    overlap_removed: int
    folds: list[dict]=field(default_factory=list)
    diagnosis: str=''


def _mdd(vals):
    if not vals: return 0.0
    a=np.asarray(vals,float)
    curve=np.r_[0.0,np.cumsum(a)]
    peak=np.maximum.accumulate(curve)
    return float(np.max(peak-curve))


def _pf(vals):
    if not vals: return 0.0
    a=np.asarray(vals,float)
    gains=float(a[a>0].sum()); losses=float(-a[a<0].sum())
    return gains/losses if losses>0 else (99.0 if gains>0 else 0.0)


def _stats(vals):
    n=len(vals)
    if not n: return (0,0.0,0.0,0.0,0.0)
    wr=100*sum(v>0 for v in vals)/n
    return (n,wr,float(np.mean(vals)),_pf(vals),_mdd(vals))


def _apply_loss_cooldown_rows(rows, one_position=False):
    accepted=[]
    consec=0
    paused_until=-1
    occupied_until=-1
    for i,pnl in rows:
        if one_position and i < occupied_until:
            continue
        if consec>=LOSS_COOLDOWN_AFTER and i<paused_until:
            continue
        accepted.append((i,pnl))
        if one_position:
            # Conservative execution audit: reserve the full maximum outcome horizon.
            occupied_until=i+SETUP['horizon']
        if pnl<0:
            consec+=1
            if consec>=LOSS_COOLDOWN_AFTER:
                paused_until=i+LOSS_COOLDOWN_BARS
        else:
            consec=0
    return accepted


def _date_at(x,i):
    if 'ts' not in x.columns or i<0 or i>=len(x): return str(i)
    v=x.ts.iloc[i]
    try: return pd.Timestamp(v).strftime('%Y-%m-%d')
    except Exception: return str(v)


def validate_v491(df:pd.DataFrame,symbol='BTC',cost_bps=8.0)->V491Result:
    symbol=symbol.upper()
    if symbol!='BTC':
        return V491Result(symbol,'NO_SETUP',len(df),0.0,0,0,0,0,0,[],'V4.9.1 diagnoses only the frozen BTC setup')
    x=prepare(df).reset_index(drop=True)
    if len(x)<1650:
        return V491Result(symbol,'INSUFFICIENT_DATA',len(x),0.0,0,0,0,0,0,[],'Need >=1650 bars')
    train_end,folds=_fold_ranges(len(x),SETUP['horizon'])
    if len(folds)!=4:
        return V491Result(symbol,'INSUFFICIENT_DATA',len(x),0.0,0,0,0,0,0,[],'Need 4 complete purged OOS folds')
    atrp=_atr_pct_series(x).iloc[210:train_end].dropna()
    if len(atrp)<350:
        return V491Result(symbol,'INSUFFICIENT_DATA',len(x),0.0,0,0,0,0,0,[],'ATR calibration history too short')
    atr_cutoff=float(atrp.quantile(.80))

    out=[]; total=total_one=pos=pos_one=0
    for fold_id,(start,end) in enumerate(folds,1):
        raw=_raw_fold(x,start,end,atr_cutoff,cost_bps)
        normal=_apply_loss_cooldown_rows(raw,False)
        one=_apply_loss_cooldown_rows(raw,True)
        nv=[p for _,p in normal]; ov=[p for _,p in one]
        n,wr,ev,pf,mdd=_stats(nv)
        on,owr,oev,opf,omdd=_stats(ov)
        positive=n>0 and ev>0; one_positive=on>0 and oev>0
        total+=n; total_one+=on; pos+=int(positive); pos_one+=int(one_positive)
        out.append(FoldDiagnostic(
            fold_id,_date_at(x,start),_date_at(x,end-1),len(raw),n,round(wr,2),round(ev,4),round(pf,3),round(mdd,3),
            on,round(owr,2),round(oev,4),round(opf,3),round(omdd,3),positive,one_positive
        ))

    removed=max(0,total-total_one)
    if pos<3:
        diagnosis=f'Original frozen test remains {pos}/4 positive folds; inspect the negative folds below.'
    else:
        diagnosis=f'Original frozen test has {pos}/4 positive folds.'
    if removed:
        diagnosis+=f' One-position-at-a-time removes {removed} overlapping executed trades and leaves {pos_one}/4 positive folds.'
    else:
        diagnosis+=f' No executed trades overlap under the conservative {SETUP["horizon"]}-bar occupancy audit.'
    return V491Result(symbol,'DIAGNOSTIC_ONLY',len(x),round(atr_cutoff,3),total,pos,total_one,pos_one,removed,[asdict(v) for v in out],diagnosis)
