from dataclasses import dataclass, asdict
import pandas as pd
from .agents import prepare

@dataclass
class V43Result:
    symbol: str
    timeframe: str
    train_candidates: int
    test_candidates: int
    train_trades: int
    test_trades: int
    train_win_rate: float
    test_win_rate: float
    test_long_win_rate: float
    test_short_win_rate: float
    test_long_trades: int
    test_short_trades: int
    coverage_pct: float
    min_score: int
    tp_atr: float
    sl_atr: float
    horizon_bars: int
    status: str


def _layer_signal(x: pd.DataFrame, i: int):
    if i < 210:
        return 'WAIT',0,[]
    r=x.iloc[i]
    prev=x.iloc[i-1]
    close=float(r.close)
    atrv=float(r.atr or 0)
    if not close or not atrv:
        return 'WAIT',0,[]

    # 1) Regime: slow trend must be clear.
    ema200=float(r.ema200); ema50=float(r.ema50); ema20=float(r.ema20)
    ema50_prev=float(x.ema50.iloc[i-8])
    bull_regime=close>ema200 and ema50>ema50_prev
    bear_regime=close<ema200 and ema50<ema50_prev
    if not bull_regime and not bear_regime:
        return 'WAIT',0,['Regime unclear']
    side='LONG' if bull_regime else 'SHORT'
    score=1; reasons=['Regime']

    # 2) Setup: medium trend + structure alignment.
    hi20=float(x.high.iloc[i-20:i].max()); lo20=float(x.low.iloc[i-20:i].min())
    hi8=float(x.high.iloc[i-8:i].max()); lo8=float(x.low.iloc[i-8:i].min())
    setup_long=ema20>ema50 and (float(r.low)>lo20 or close>hi8)
    setup_short=ema20<ema50 and (float(r.high)<hi20 or close<lo8)
    if (side=='LONG' and setup_long) or (side=='SHORT' and setup_short):
        score+=1; reasons.append('Setup')
    else:
        return 'WAIT',score,reasons

    # 3) Trigger: momentum resumes in regime direction.
    rv=float(r.rsi) if pd.notna(r.rsi) else 50
    macd=float(r.macd); macds=float(r.macds)
    prev_macd=float(prev.macd); prev_sig=float(prev.macds)
    trigger_long=(macd>macds and rv>=50 and (prev_macd<=prev_sig or close>float(x.high.iloc[i-5:i].max())))
    trigger_short=(macd<macds and rv<=50 and (prev_macd>=prev_sig or close<float(x.low.iloc[i-5:i].min())))
    if (side=='LONG' and trigger_long) or (side=='SHORT' and trigger_short):
        score+=1; reasons.append('Trigger')
    else:
        return 'WAIT',score,reasons

    # 4) Confirmation: candle/volume should not fight the signal.
    body=abs(float(r.close-r.open)); spread=max(float(r.high-r.low),1e-12)
    body_frac=body/spread
    vma=float(r.vma) if pd.notna(r.vma) and r.vma else 0
    vol_ok=(float(r.vol)>=vma*.80) if vma else True
    candle_long=float(r.close)>float(r.open) and body_frac>=.35
    candle_short=float(r.close)<float(r.open) and body_frac>=.35
    if vol_ok and ((side=='LONG' and candle_long) or (side=='SHORT' and candle_short)):
        score+=1; reasons.append('Confirmation')

    # 5) Risk/noise filter: reject dead or extreme-volatility conditions.
    atr_pct=atrv/close*100
    risk_ok=.20 <= atr_pct <= 4.5
    if risk_ok:
        score+=1; reasons.append('RiskFilter')
    else:
        return 'WAIT',score,reasons

    return side,score,reasons


def _barrier_outcome(x: pd.DataFrame, i: int, side: str, tp_atr: float, sl_atr: float, horizon: int):
    entry=float(x.close.iloc[i]); a=float(x.atr.iloc[i] or 0)
    if not entry or not a:
        return None
    if side=='LONG':
        tp=entry+tp_atr*a; sl=entry-sl_atr*a
    else:
        tp=entry-tp_atr*a; sl=entry+sl_atr*a
    end=min(len(x),i+1+horizon)
    for j in range(i+1,end):
        hi=float(x.high.iloc[j]); lo=float(x.low.iloc[j])
        if side=='LONG':
            hit_tp=hi>=tp; hit_sl=lo<=sl
        else:
            hit_tp=lo<=tp; hit_sl=hi>=sl
        if hit_tp and hit_sl:
            return False  # conservative: ambiguous intrabar path counts as loss
        if hit_tp: return True
        if hit_sl: return False
    return None


def _evaluate(x, start, end, min_score, tp_atr, sl_atr, horizon):
    trades=[]; candidates=0
    for i in range(max(210,start),min(end,len(x)-horizon)):
        side,score,_=_layer_signal(x,i)
        if side=='WAIT':
            continue
        candidates+=1
        if score<min_score:
            continue
        outcome=_barrier_outcome(x,i,side,tp_atr,sl_atr,horizon)
        if outcome is None:
            continue
        trades.append((side,outcome))
    longs=[t for t in trades if t[0]=='LONG']; shorts=[t for t in trades if t[0]=='SHORT']
    def wr(items): return 100*sum(1 for _,w in items if w)/len(items) if items else 0.0
    return {'candidates':candidates,'n':len(trades),'wr':wr(trades),'long_n':len(longs),'short_n':len(shorts),'long_wr':wr(longs),'short_wr':wr(shorts)}


def validate_v43(df: pd.DataFrame, symbol: str, timeframe: str, train_ratio: float=.70) -> V43Result:
    x=prepare(df).reset_index(drop=True)
    split=max(260,min(len(x)-80,int(len(x)*train_ratio)))
    train_start=210; train_end=split; test_start=split; test_end=len(x)
    # Small, pre-declared grid to reduce overfitting.
    configs=[]
    for min_score in (4,5):
        for tp_atr,sl_atr in ((1.0,1.0),(1.25,1.0),(1.5,1.0)):
            for horizon in (8,12,16):
                st=_evaluate(x,train_start,train_end,min_score,tp_atr,sl_atr,horizon)
                if st['n']<20: continue
                expectancy=st['wr']*(tp_atr/sl_atr) - (100-st['wr'])
                # Prefer edge with enough trades, not raw win rate alone.
                objective=expectancy + min(8,st['n']/15)
                configs.append((objective,min_score,tp_atr,sl_atr,horizon,st))
    if not configs:
        return V43Result(symbol.upper(),timeframe,0,0,0,0,0,0,0,0,0,0,0,5,1,1,12,'INSUFFICIENT_DATA')
    configs.sort(key=lambda z:z[0],reverse=True)
    _,min_score,tp_atr,sl_atr,horizon,train=configs[0]
    test=_evaluate(x,test_start,test_end,min_score,tp_atr,sl_atr,horizon)
    test_rows=max(1,test_end-test_start)
    coverage=100*test['n']/test_rows
    status='PASS'
    # Require enough truly resolved OOS trades and positive risk-adjusted edge.
    breakeven=100/(1+tp_atr/sl_atr)
    if test['n']<20 or test['wr'] < breakeven+3:
        status='NO_TRADE'
    if test['long_n']>=8 and test['long_wr'] < breakeven:
        status='NO_TRADE'
    if test['short_n']>=8 and test['short_wr'] < breakeven:
        status='NO_TRADE'
    return V43Result(
        symbol.upper(),timeframe,train['candidates'],test['candidates'],train['n'],test['n'],
        round(train['wr'],2),round(test['wr'],2),round(test['long_wr'],2),round(test['short_wr'],2),
        test['long_n'],test['short_n'],round(coverage,2),min_score,tp_atr,sl_atr,horizon,status
    )

def to_dict(x): return asdict(x)
