from dataclasses import dataclass, asdict
import pandas as pd
from .agents import run_price_agents, derivatives_agent, orderflow_agent, liquidation_pressure_agent
from .meta_engine import combine

@dataclass
class TFResult:
    timeframe: str
    direction: str
    bullish_pct: float
    bearish_pct: float
    neutral_pct: float
    score: float
    confidence: float
    entry_quality: float
    agreement: float
    reasons: list[str]
    price: float
    atr_pct: float
    support: float
    resistance: float
    agents: list[dict]


def analyze(df: pd.DataFrame, timeframe: str, metrics: dict | None=None) -> TFResult:
    if len(df)<80: raise ValueError('Need at least 80 candles')
    x,votes=run_price_agents(df)
    if metrics is not None:
        votes.append(derivatives_agent(metrics))
        if metrics.get('live_available'):
            votes.append(orderflow_agent(metrics))
            votes.append(liquidation_pressure_agent(metrics))
    meta=combine(votes)
    last=x.iloc[-1]
    support=float(x.low.iloc[-50:].quantile(.12)); resistance=float(x.high.iloc[-50:].quantile(.88))
    atrpct=float(last.atr/last.close*100) if last.close else 0
    if meta.direction=='صاعد': room=max(0,(resistance-last.close)/last.close*100)
    elif meta.direction=='هابط': room=max(0,(last.close-support)/last.close*100)
    else: room=0
    volatility_penalty=max(0,atrpct-6)*3 + (8 if atrpct<.18 else 0)
    quality=max(10,min(96, meta.confidence*.65 + meta.agreement*.22 + min(room,4)*3 - volatility_penalty))
    return TFResult(timeframe,meta.direction,meta.bullish_pct,meta.bearish_pct,meta.neutral_pct,meta.score,meta.confidence,round(quality,1),meta.agreement,meta.reasons,float(last.close),round(atrpct,2),support,resistance,meta.agent_votes)


def cross_timeframe_context(results: list[TFResult]):
    m={r.timeframe:r for r in results}
    hscore=sum(m[t].score*w for t,w in [('1w',.8),('1d',1.25),('4h',1.4)] if t in m)
    if hscore>.35: regime='BULL'
    elif hscore<-.35: regime='BEAR'
    else: regime='RANGE'
    return regime,hscore


def pick_best(results: list[TFResult]):
    regime,_=cross_timeframe_context(results)
    weights={'5m':.80,'15m':1.15,'1h':1.25,'4h':.95,'1d':.60,'1w':.35}
    candidates=[]
    for r in results:
        if r.direction=='محايد': continue
        side='BULL' if r.direction=='صاعد' else 'BEAR'
        regime_bonus=1.10 if regime==side else (.72 if regime!='RANGE' else 1.0)
        candidates.append((r.entry_quality*weights.get(r.timeframe,1)*regime_bonus,r))
    return max(candidates,key=lambda z:z[0])[1] if candidates else max(results,key=lambda r:r.entry_quality)


def to_dict(r): return asdict(r)
