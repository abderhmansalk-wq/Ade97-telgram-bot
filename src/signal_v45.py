from dataclasses import dataclass, asdict, field
import pandas as pd
from .agents import prepare
from .signal_v43 import _layer_signal
from .signal_v44 import _trade_pnl_r

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

@dataclass
class V45Result:
    symbol: str
    status: str
    best_timeframe: str
    best_regime: str
    best_side: str
    best_expectancy_r: float
    fee_slippage_bps: float
    buckets: list[dict]=field(default_factory=list)


def classify_regime(x: pd.DataFrame, i: int) -> str:
    r=x.iloc[i]
    close=float(r.close); a=float(r.atr or 0)
    if not close or not a: return 'RANGE'
    atr_pct=a/close*100
    if atr_pct >= 1.8:
        return 'HIGH_VOL'
    e20=float(r.ema20); e50=float(r.ema50); e200=float(r.ema200)
    slope50=(e50-float(x.ema50.iloc[max(0,i-8)]))/(close or 1)
    spread=abs(e20-e50)/(close or 1)
    trend=(close>e200 and e20>e50 and slope50>.0015) or (close<e200 and e20<e50 and slope50<-.0015)
    if trend and spread>.0015:
        return 'TREND'
    return 'RANGE'


def _signal_for_regime(x,i,regime):
    side,score,reasons=_layer_signal(x,i)
    if side=='WAIT': return side,score,reasons
    actual=classify_regime(x,i)
    if actual!=regime: return 'WAIT',0,['Regime mismatch']
    r=x.iloc[i]
    if regime=='RANGE':
        rv=float(r.rsi) if pd.notna(r.rsi) else 50
        hi=float(x.high.iloc[i-20:i].max()); lo=float(x.low.iloc[i-20:i].min())
        pos=(float(r.close)-lo)/(hi-lo or 1e-12)
        if side=='LONG' and not (pos<.35 and rv<48): return 'WAIT',0,['Range filter']
        if side=='SHORT' and not (pos>.65 and rv>52): return 'WAIT',0,['Range filter']
    elif regime=='HIGH_VOL':
        body=abs(float(r.close-r.open)); spread=max(float(r.high-r.low),1e-12)
        if body/spread<.5: return 'WAIT',0,['Weak high-vol candle']
    return side,score,reasons


def _eval(x,start,end,regime,side,min_score,tp,sl,horizon,cost_bps):
    vals=[]
    for i in range(max(210,start),min(end,len(x)-horizon)):
        s,score,_=_signal_for_regime(x,i,regime)
        if s!=side or score<min_score: continue
        pnl=_trade_pnl_r(x,i,s,tp,sl,horizon,cost_bps)
        if pnl is not None: vals.append(pnl)
    if not vals: return {'n':0,'wr':0.0,'exp':0.0}
    return {'n':len(vals),'wr':100*sum(p>0 for p in vals)/len(vals),'exp':sum(vals)/len(vals)}


def _choose(x,start,end,regime,side,horizon,cost_bps):
    best=None
    for min_score in (4,5):
        for tp,sl in ((1,1),(1.25,1),(1.5,1),(2,1)):
            st=_eval(x,start,end,regime,side,min_score,tp,sl,horizon,cost_bps)
            if st['n']<10: continue
            obj=st['exp']+min(.08,st['n']/600)
            if best is None or obj>best[0]: best=(obj,min_score,tp,sl,st)
    return best


def validate_frame(df,symbol,timeframe,cost_bps=8.0):
    x=prepare(df).reset_index(drop=True); n=len(x)
    if n<520: return []
    horizon={'15m':20,'1h':16,'4h':12}.get(timeframe,16)
    test_size=max(90,n//6); train_end=max(300,n-3*test_size)
    out=[]
    for regime in REGIMES:
        for side in SIDES:
            fold_stats=[]; rr_last=1.0
            for fold in range(3):
                ts=train_end+fold*test_size; te=min(n,ts+test_size)
                if te-ts<60: continue
                cfg=_choose(x,210,ts,regime,side,horizon,cost_bps)
                if not cfg: continue
                _,ms,tp,sl,_=cfg; rr_last=tp/sl
                st=_eval(x,ts,te,regime,side,ms,tp,sl,horizon,cost_bps)
                fold_stats.append(st)
            trades=sum(s['n'] for s in fold_stats)
            exp=sum(s['exp']*s['n'] for s in fold_stats)/trades if trades else 0.0
            wr=sum(s['wr']*s['n'] for s in fold_stats)/trades if trades else 0.0
            pos=sum(1 for s in fold_stats if s['n'] and s['exp']>0)
            min_trades=16 if timeframe=='4h' else 20
            status='PASS' if trades>=min_trades and exp>=.05 and pos>=2 else 'NO_TRADE'
            out.append(BucketResult(timeframe,regime,side,trades,round(wr,2),round(exp,4),pos,len(fold_stats),rr_last,status))
    return out


def validate_v45(symbol:str, frames:dict[str,pd.DataFrame], fee_slippage_bps:float=8.0)->V45Result:
    buckets=[]
    for tf,df in frames.items(): buckets.extend(validate_frame(df,symbol,tf,fee_slippage_bps))
    passed=[b for b in buckets if b.status=='PASS']
    best=max(passed,key=lambda b:(b.expectancy_r,b.trades),default=None)
    if best:
        status='PASS'; btf=best.timeframe; br=best.regime; bs=best.side; be=best.expectancy_r
    else:
        status='NO_TRADE'; btf=br=bs='-'; be=0.0
    return V45Result(symbol.upper(),status,btf,br,bs,be,fee_slippage_bps,[asdict(b) for b in buckets])
