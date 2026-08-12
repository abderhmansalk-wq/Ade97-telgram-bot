from dataclasses import dataclass, asdict, field
import pandas as pd
from .agents import prepare
from .signal_v43 import _layer_signal

@dataclass
class FoldResult:
    fold: int
    side: str
    rr: float
    trades: int
    win_rate: float
    expectancy_r: float
    positive: bool

@dataclass
class V44Result:
    symbol: str
    timeframe: str
    status: str
    folds: int
    total_trades: int
    long_trades: int
    short_trades: int
    win_rate: float
    long_win_rate: float
    short_win_rate: float
    expectancy_r: float
    long_expectancy_r: float
    short_expectancy_r: float
    positive_folds: int
    long_positive_folds: int
    short_positive_folds: int
    selected_long_rr: float
    selected_short_rr: float
    fee_slippage_bps: float
    fold_details: list[dict] = field(default_factory=list)


def _trade_pnl_r(x, i, side, tp_atr, sl_atr, horizon, cost_bps):
    entry=float(x.close.iloc[i]); a=float(x.atr.iloc[i] or 0)
    if not entry or not a: return None
    stop_dist=sl_atr*a
    cost_r=(cost_bps/10000.0*entry)/(stop_dist or 1e-12)
    reward=tp_atr/sl_atr
    if side=='LONG': tp=entry+tp_atr*a; sl=entry-sl_atr*a
    else: tp=entry-tp_atr*a; sl=entry+sl_atr*a
    end=min(len(x),i+1+horizon)
    for j in range(i+1,end):
        hi=float(x.high.iloc[j]); lo=float(x.low.iloc[j])
        if side=='LONG': hit_tp=hi>=tp; hit_sl=lo<=sl
        else: hit_tp=lo<=tp; hit_sl=hi>=sl
        if hit_tp and hit_sl: return -1.0-cost_r
        if hit_tp: return reward-cost_r
        if hit_sl: return -1.0-cost_r
    return None


def _eval_range(x,start,end,side_filter,min_score,tp_atr,sl_atr,horizon,cost_bps):
    pnls=[]
    for i in range(max(210,start),min(end,len(x)-horizon)):
        side,score,_=_layer_signal(x,i)
        if side=='WAIT' or score<min_score: continue
        if side_filter!='BOTH' and side!=side_filter: continue
        pnl=_trade_pnl_r(x,i,side,tp_atr,sl_atr,horizon,cost_bps)
        if pnl is not None: pnls.append((side,pnl))
    if not pnls:
        return {'n':0,'wr':0.0,'exp':0.0,'long_n':0,'short_n':0,'long_wr':0.0,'short_wr':0.0,'long_exp':0.0,'short_exp':0.0}
    longs=[p for s,p in pnls if s=='LONG']; shorts=[p for s,p in pnls if s=='SHORT']
    vals=[p for _,p in pnls]
    def wr(v): return 100*sum(1 for p in v if p>0)/len(v) if v else 0.0
    def ex(v): return sum(v)/len(v) if v else 0.0
    return {'n':len(vals),'wr':wr(vals),'exp':ex(vals),'long_n':len(longs),'short_n':len(shorts),'long_wr':wr(longs),'short_wr':wr(shorts),'long_exp':ex(longs),'short_exp':ex(shorts)}


def _choose_rr(x,start,end,side,horizon,cost_bps):
    best=None
    for min_score in (4,5):
        for tp_atr,sl_atr in ((1.0,1.0),(1.25,1.0),(1.5,1.0),(2.0,1.0)):
            st=_eval_range(x,start,end,side,min_score,tp_atr,sl_atr,horizon,cost_bps)
            if st['n']<15: continue
            obj=st['exp'] + min(.12,st['n']/500)
            if best is None or obj>best[0]: best=(obj,min_score,tp_atr,sl_atr,st)
    return best


def validate_v44(df: pd.DataFrame,symbol: str,timeframe: str,fee_slippage_bps: float=8.0) -> V44Result:
    x=prepare(df).reset_index(drop=True)
    n=len(x)
    if n<900:
        return V44Result(symbol.upper(),timeframe,'INSUFFICIENT_DATA',0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,fee_slippage_bps,[])
    horizon={'5m':24,'15m':16,'1h':16,'4h':12,'1d':8,'1w':6}.get(timeframe,16)
    # Expanding train + sequential test windows. No test window is used to choose its own parameters.
    test_size=max(180,n//6)
    train_end=max(540,n-3*test_size)
    folds=[]; agg=[]
    selected_long_rr=1.0; selected_short_rr=1.0
    for fold in range(3):
        test_start=train_end+fold*test_size
        test_end=min(n,test_start+test_size)
        if test_end-test_start<80: break
        long_cfg=_choose_rr(x,210,test_start,'LONG',horizon,fee_slippage_bps)
        short_cfg=_choose_rr(x,210,test_start,'SHORT',horizon,fee_slippage_bps)
        for side,cfg in [('LONG',long_cfg),('SHORT',short_cfg)]:
            if not cfg: continue
            _,min_score,tp,sl,_=cfg
            st=_eval_range(x,test_start,test_end,side,min_score,tp,sl,horizon,fee_slippage_bps)
            rr=tp/sl
            if side=='LONG': selected_long_rr=rr
            else: selected_short_rr=rr
            fr=FoldResult(fold+1,side,rr,st['n'],round(st['wr'],2),round(st['exp'],4),st['exp']>0)
            folds.append(fr); agg.append((side,st))
    total=sum(st['n'] for _,st in agg)
    long_n=sum(st['n'] for s,st in agg if s=='LONG'); short_n=sum(st['n'] for s,st in agg if s=='SHORT')
    def wavg(field,side=None):
        items=[st for s,st in agg if side is None or s==side]
        den=sum(st['n'] for st in items)
        return sum(st[field]*st['n'] for st in items)/den if den else 0.0
    overall_exp=wavg('exp'); long_exp=wavg('exp','LONG'); short_exp=wavg('exp','SHORT')
    overall_wr=wavg('wr'); long_wr=wavg('wr','LONG'); short_wr=wavg('wr','SHORT')
    pos=sum(1 for f in folds if f.positive)
    long_pos=sum(1 for f in folds if f.side=='LONG' and f.positive)
    short_pos=sum(1 for f in folds if f.side=='SHORT' and f.positive)
    long_pass=long_n>=25 and long_exp>=0.05 and long_pos>=2
    short_pass=short_n>=25 and short_exp>=0.05 and short_pos>=2
    if long_pass and short_pass: status='PASS_BOTH'
    elif long_pass: status='PASS_LONG'
    elif short_pass: status='PASS_SHORT'
    else: status='NO_TRADE'
    return V44Result(symbol.upper(),timeframe,status,len({f.fold for f in folds}),total,long_n,short_n,
        round(overall_wr,2),round(long_wr,2),round(short_wr,2),round(overall_exp,4),round(long_exp,4),round(short_exp,4),
        pos,long_pos,short_pos,selected_long_rr,selected_short_rr,fee_slippage_bps,[asdict(f) for f in folds])

def to_dict(x): return asdict(x)
