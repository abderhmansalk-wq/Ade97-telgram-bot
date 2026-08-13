from dataclasses import dataclass, asdict, field
import pandas as pd
from .agents import prepare
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
    e20=float(r.ema20); e50=float(r.ema50); e200=float(r.ema200)
    slope50=(e50-float(x.ema50.iloc[max(0,i-8)]))/(close or 1)
    spread=abs(e20-e50)/(close or 1)
    if atr_pct >= 1.8:
        return 'HIGH_VOL'
    trend=(close>e200 and e20>e50 and slope50>.0010) or (close<e200 and e20<e50 and slope50<-.0010)
    if trend and spread>.0010:
        return 'TREND'
    return 'RANGE'


def _trend_signal(x,i):
    r=x.iloc[i]; prev=x.iloc[i-1]
    close=float(r.close); e20=float(r.ema20); e50=float(r.ema50); e200=float(r.ema200)
    rv=float(r.rsi) if pd.notna(r.rsi) else 50
    macd=float(r.macd); sig=float(r.macds)
    body=abs(float(r.close-r.open)); spread=max(float(r.high-r.low),1e-12)
    score=0
    if close>e200 and e20>e50:
        side='LONG'
        if rv>=50: score+=1
        if macd>sig: score+=1
        if close>float(x.high.iloc[i-6:i].max()): score+=1
        if float(r.close)>float(r.open) and body/spread>=.30: score+=1
        return side,score
    if close<e200 and e20<e50:
        side='SHORT'
        if rv<=50: score+=1
        if macd<sig: score+=1
        if close<float(x.low.iloc[i-6:i].min()): score+=1
        if float(r.close)<float(r.open) and body/spread>=.30: score+=1
        return side,score
    return 'WAIT',0


def _range_signal(x,i):
    r=x.iloc[i]
    rv=float(r.rsi) if pd.notna(r.rsi) else 50
    hi=float(x.high.iloc[i-24:i].max()); lo=float(x.low.iloc[i-24:i].min())
    width=max(hi-lo,1e-12); pos=(float(r.close)-lo)/width
    body=abs(float(r.close-r.open)); spread=max(float(r.high-r.low),1e-12)
    score=0
    if pos<=.30 and rv<=45:
        side='LONG'
        if float(r.close)>float(r.open): score+=1
        if body/spread>=.25: score+=1
        if float(r.low)<=float(x.low.iloc[i-6:i].min()): score+=1
        if float(r.close)>lo: score+=1
        return side,score
    if pos>=.70 and rv>=55:
        side='SHORT'
        if float(r.close)<float(r.open): score+=1
        if body/spread>=.25: score+=1
        if float(r.high)>=float(x.high.iloc[i-6:i].max()): score+=1
        if float(r.close)<hi: score+=1
        return side,score
    return 'WAIT',0


def _highvol_signal(x,i):
    r=x.iloc[i]
    close=float(r.close); body=abs(float(r.close-r.open)); spread=max(float(r.high-r.low),1e-12)
    if body/spread<.45: return 'WAIT',0
    rv=float(r.rsi) if pd.notna(r.rsi) else 50
    hi=float(x.high.iloc[i-10:i].max()); lo=float(x.low.iloc[i-10:i].min())
    score=0
    if close>hi and float(r.close)>float(r.open):
        if rv>=55: score+=1
        if float(r.macd)>float(r.macds): score+=1
        if body/spread>=.60: score+=1
        if pd.notna(r.vma) and r.vma and float(r.vol)>=float(r.vma): score+=1
        return 'LONG',score
    if close<lo and float(r.close)<float(r.open):
        if rv<=45: score+=1
        if float(r.macd)<float(r.macds): score+=1
        if body/spread>=.60: score+=1
        if pd.notna(r.vma) and r.vma and float(r.vol)>=float(r.vma): score+=1
        return 'SHORT',score
    return 'WAIT',0


def _signal_for_regime(x,i,regime):
    if i<210 or classify_regime(x,i)!=regime:
        return 'WAIT',0,[]
    if regime=='TREND': side,score=_trend_signal(x,i)
    elif regime=='RANGE': side,score=_range_signal(x,i)
    else: side,score=_highvol_signal(x,i)
    return side,score,[regime] if side!='WAIT' else []


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
    score_grid=(2,3,4)
    for min_score in score_grid:
        for tp,sl in ((1,1),(1.25,1),(1.5,1),(2,1)):
            st=_eval(x,start,end,regime,side,min_score,tp,sl,horizon,cost_bps)
            if st['n']<8: continue
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
            min_trades=12 if timeframe=='4h' else 16
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
