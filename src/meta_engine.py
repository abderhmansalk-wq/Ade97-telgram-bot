from dataclasses import dataclass, asdict
from .agents import AgentVote

WEIGHTS={
    'Trend/Dow': 1.35,
    'Momentum': 1.0,
    'Wyckoff': 1.05,
    'SMC': 1.05,
    'Volatility': .45,
    'Derivatives': .85,
    'OrderFlow': 1.10,
    'LiquidationProxy': .80,
}

@dataclass
class MetaDecision:
    score: float
    direction: str
    bullish_pct: float
    bearish_pct: float
    neutral_pct: float
    confidence: float
    agreement: float
    reasons: list[str]
    agent_votes: list[dict]


def combine(votes: list[AgentVote]) -> MetaDecision:
    valid=[v for v in votes if v.confidence > 0]
    if not valid:
        return MetaDecision(0,'محايد',36,36,28,0,0,[],[])
    total_w=sum(WEIGHTS.get(v.name,1)*max(v.confidence,25)/100 for v in valid)
    raw=sum(v.score*WEIGHTS.get(v.name,1)*max(v.confidence,25)/100 for v in valid)/(total_w or 1)
    raw=max(-1,min(1,raw))
    pos=sum(1 for v in valid if v.score>.15); neg=sum(1 for v in valid if v.score<-.15)
    directional=max(pos,neg); agreement=100*directional/max(1,pos+neg) if (pos+neg) else 0
    neutral=max(8, 32-abs(raw)*22)
    directional_mass=100-neutral
    bull=directional_mass*(raw+1)/2
    bear=directional_mass-bull
    if bull>=57: direction='صاعد'
    elif bear>=57: direction='هابط'
    else: direction='محايد'
    confidence=min(96,max(25, 42+abs(raw)*38 + max(0,agreement-50)*.22))
    reasons=[]
    for v in sorted(valid,key=lambda z: abs(z.score)*z.confidence,reverse=True):
        if v.reasons:
            reasons.append(f'{v.name}: {v.reasons[0]}')
    return MetaDecision(round(raw,3),direction,round(bull,1),round(bear,1),round(neutral,1),round(confidence,1),round(agreement,1),reasons[:6],[asdict(v) for v in valid])
