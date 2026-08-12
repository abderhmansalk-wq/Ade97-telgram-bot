from dataclasses import dataclass, asdict
from itertools import product
import pandas as pd
from .agents import run_price_agents

AGENTS=['Trend/Dow','Momentum','Wyckoff','SMC','Volatility']
BASE={'Trend/Dow':1.35,'Momentum':1.0,'Wyckoff':1.05,'SMC':1.05,'Volatility':0.45}

@dataclass
class ValidationResult:
    symbol: str
    timeframe: str
    train_rows: int
    test_rows: int
    train_signals: int
    test_signals: int
    train_accuracy: float
    test_accuracy: float
    test_long_accuracy: float
    test_short_accuracy: float
    test_long_samples: int
    test_short_samples: int
    threshold: float
    weights: dict
    coverage_pct: float
    status: str


def _features(df: pd.DataFrame, horizon: int, min_history: int, step: int):
    rows=[]
    end=len(df)-horizon
    for i in range(min_history,end,step):
        hist=df.iloc[:i+1]
        _,votes=run_price_agents(hist)
        feat={v.name:(float(v.score),float(v.confidence)) for v in votes}
        future=float(df.close.iloc[i+horizon]/df.close.iloc[i]-1)
        rows.append((feat,future))
    return rows


def _decision(feat, weights, threshold):
    num=0.0; den=0.0
    for name,(score,conf) in feat.items():
        w=float(weights.get(name,1.0))*max(conf,25)/100
        num += score*w; den += w
    raw=num/(den or 1.0)
    if raw >= threshold: return 'LONG',raw
    if raw <= -threshold: return 'SHORT',raw
    return 'WAIT',raw


def _score(rows, weights, threshold):
    sig=[]
    for feat,future in rows:
        side,raw=_decision(feat,weights,threshold)
        if side=='WAIT': continue
        correct=(future>0 and side=='LONG') or (future<0 and side=='SHORT')
        sig.append((side,correct,raw))
    if not sig:
        return {'n':0,'acc':0.0,'long_n':0,'short_n':0,'long_acc':0.0,'short_acc':0.0}
    longs=[x for x in sig if x[0]=='LONG']; shorts=[x for x in sig if x[0]=='SHORT']
    return {
        'n':len(sig),
        'acc':100*sum(x[1] for x in sig)/len(sig),
        'long_n':len(longs),'short_n':len(shorts),
        'long_acc':100*sum(x[1] for x in longs)/len(longs) if longs else 0.0,
        'short_acc':100*sum(x[1] for x in shorts)/len(shorts) if shorts else 0.0,
    }


def _objective(stat, total_rows):
    if stat['n'] < max(25,int(total_rows*.08)):
        return -999
    coverage=stat['n']/max(1,total_rows)
    side_penalty=0
    if stat['long_n'] and stat['long_acc'] < 48: side_penalty += 2
    if stat['short_n'] and stat['short_acc'] < 48: side_penalty += 2
    return stat['acc'] + min(4,coverage*8) - side_penalty


def optimize_oos(df: pd.DataFrame, symbol: str, timeframe: str, horizon: int=3,
                 min_history: int=210, step: int=3, train_ratio: float=.70) -> ValidationResult:
    rows=_features(df,horizon,min_history,step)
    split=max(1,min(len(rows)-1,int(len(rows)*train_ratio)))
    train=rows[:split]; test=rows[split:]
    if len(test)<10:
        return ValidationResult(symbol,timeframe,len(train),len(test),0,0,0,0,0,0,0,0,.20,BASE,0,'INSUFFICIENT_DATA')

    multipliers=[0.6,1.0,1.4]
    thresholds=[.16,.20,.24,.28,.32]
    best=None
    for vals in product(multipliers, repeat=4):
        weights=dict(BASE)
        for name,m in zip(['Trend/Dow','Momentum','Wyckoff','SMC'],vals):
            weights[name]=BASE[name]*m
        for th in thresholds:
            st=_score(train,weights,th)
            obj=_objective(st,len(train))
            if best is None or obj>best[0]:
                best=(obj,weights,th,st)

    _,weights,threshold,train_stat=best
    test_stat=_score(test,weights,threshold)
    coverage=100*test_stat['n']/max(1,len(test))
    status='PASS'
    if test_stat['n'] < 25 or test_stat['acc'] < 52.5:
        status='NO_TRADE'
    if test_stat['long_n']>=10 and test_stat['long_acc']<48:
        status='NO_TRADE'
    if test_stat['short_n']>=10 and test_stat['short_acc']<48:
        status='NO_TRADE'

    return ValidationResult(
        symbol.upper(),timeframe,len(train),len(test),train_stat['n'],test_stat['n'],
        round(train_stat['acc'],2),round(test_stat['acc'],2),
        round(test_stat['long_acc'],2),round(test_stat['short_acc'],2),
        test_stat['long_n'],test_stat['short_n'],round(threshold,3),
        {k:round(v,3) for k,v in weights.items()},round(coverage,2),status
    )

def to_dict(x): return asdict(x)
