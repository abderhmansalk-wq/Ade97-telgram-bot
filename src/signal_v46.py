from dataclasses import dataclass, asdict, field
import pandas as pd
from .agents import prepare
from .signal_v44 import _trade_pnl_r
from .signal_v45 import _trend_signal, _range_signal, _highvol_signal

REGIMES=('TREND','RANGE','HIGH_VOL')
SIDES=('LONG','SHORT')

@dataclass
class BucketResult:
    timeframe: str
    regime: str
    side: str
    trades: int
    win_rate: float
    expectancy_r: float
    positive_folds: int
    folds: int
    rr: float
    status: str
    atr_percentile: float

@dataclass
class V46Result:
    symbol: str
    status: str
    best_timeframe: str
    best_regime: str
    best_side: str
    best_expectancy_r: float
    fee_slippage_bps: float
    buckets: list[dict]=field(default_factory=list)


def _atr_pct_series(x: pd.DataFrame):
    return (x.atr / x.close.replace(0, pd.NA) * 100).astype(float)


def classify_regime(x: pd.DataFrame, i: int, atr_cutoff: float) -> str:
    r=x.iloc[i]
    close=float(r.close); a=float(r.atr or 0)
    if not close or not a: return 'RANGE'
    atr_pct=a/close*100
    if atr_pct >= atr_cutoff:
        return 'HIGH_VOL'
    e20=float(r.ema20); e50=float(r.ema50); e200=float(r.ema200)
    slope50=(e50-float(x.ema50.iloc[max(0,i-8)]))/(close or 1)
    spread=abs(e20-e50)/(close or 1)
    trend=(close>e200 and e20>e50 and slope50>.0010) or (close<e200 and e20<e50 and slope50<-.0010)
    if trend and spread>.0010:
        return 'TREND'
    return 'RANGE'


def _signal_for_regime(x,i,regime,atr_cutoff):
    if i<210 or classify_regime(x,i,atr_cutoff)!=regime:
        return 'WAIT',0
    if regime=='TREND': return _trend_signal(x,i)
    if regime=='RANGE': return _range_signal(x,i)
    return _highvol_signal(x,i)


def _eval(x,start,end,regime,side,min_score,tp,sl,horizon,cost_bps,atr_cutoff):
    vals=[]
    for i in range(max(210,start),min(end,len(x)-horizon)):
        s,score=_signal_for_regime(x,i,regime,atr_cutoff)
        if s!=side or score<min_score: continue
        pnl=_trade_pnl_r(x,i,s,tp,sl,horizon,cost_bps)
        if pnl is not None: vals.append(pnl)
    if not vals: return {'n':0,'wr':0.0,'exp':0.0}
    return {'n':len(vals),'wr':100*sum(p>0 for p in vals)/len(vals),'exp':sum(vals)/len(vals)}


def _choose(x,start,end,regime,side,horizon,cost_bps,atr_cutoff):
    best=None
    for min_score in (2,3,4):
        for tp,sl in ((1,1),(1.25,1),(1.5,1),(2,1)):
            st=_eval(x,start,end,regime,side,min_score,tp,sl,horizon,cost_bps,atr_cutoff)
            if st['n']<8: continue
            obj=st['exp']+min(.08,st['n']/600)
            if best is None or obj>best[0]: best=(obj,min_score,tp,sl,st)
    return best


def validate_frame(df,symbol,timeframe,cost_bps=8.0):
    x=prepare(df).reset_index(drop=True); n=len(x)
    min_required={'15m':900,'1h':900,'4h':900}.get(timeframe,900)
    if n<min_required: return []
    horizon={'15m':20,'1h':16,'4h':12}.get(timeframe,16)
    # Force exactly three OOS folds of equal size, preserving a meaningful expanding train.
    test_size=max(120,min(220,(n-420)//3))
    train_end=n-3*test_size
    if train_end<420: return []
    atrp=_atr_pct_series(x)
    out=[]
    for regime in REGIMES:
        for side in SIDES:
            fold_stats=[]; rr_last=1.0; atr_cutoffs=[]
            for fold in range(3):
                ts=train_end+fold*test_size; te=ts+test_size
                if te>n: continue
                # Derive high-vol threshold from train data only, avoiding leakage.
                train_atr=atrp.iloc[210:ts].dropna()
                if len(train_atr)<200: continue
                atr_cutoff=float(train_atr.quantile(.80))
                atr_cutoffs.append(atr_cutoff)
                cfg=_choose(x,210,ts,regime,side,horizon,cost_bps,atr_cutoff)
                if not cfg:
                    fold_stats.append({'n':0,'wr':0.0,'exp':0.0})
                    continue
                _,ms,tp,sl,_=cfg; rr_last=tp/sl
                st=_eval(x,ts,te,regime,side,ms,tp,sl,horizon,cost_bps,atr_cutoff)
                fold_stats.append(st)
            trades=sum(s['n'] for s in fold_stats)
            exp=sum(s['exp']*s['n'] for s in fold_stats)/trades if trades else 0.0
            wr=sum(s['wr']*s['n'] for s in fold_stats)/trades if trades else 0.0
            pos=sum(1 for s in fold_stats if s['n'] and s['exp']>0)
            folds=len(fold_stats)
            min_trades=18 if timeframe=='4h' else 24
            status='PASS' if folds==3 and trades>=min_trades and exp>=.05 and pos>=2 else 'NO_TRADE'
            avg_cutoff=sum(atr_cutoffs)/len(atr_cutoffs) if atr_cutoffs else 0.0
            out.append(BucketResult(timeframe,regime,side,trades,round(wr,2),round(exp,4),pos,folds,rr_last,status,round(avg_cutoff,3)))
    return out


def validate_v46(symbol:str, frames:dict[str,pd.DataFrame], fee_slippage_bps:float=8.0)->V46Result:
    buckets=[]
    for tf,df in frames.items(): buckets.extend(validate_frame(df,symbol,tf,fee_slippage_bps))
    passed=[b for b in buckets if b.status=='PASS']
    best=max(passed,key=lambda b:(b.expectancy_r,b.trades),default=None)
    if best:
        status='PASS'; btf=best.timeframe; br=best.regime; bs=best.side; be=best.expectancy_r
    else:
        status='NO_TRADE'; btf=br=bs='-'; be=0.0
    return V46Result(symbol.upper(),status,btf,br,bs,be,fee_slippage_bps,[asdict(b) for b in buckets])
