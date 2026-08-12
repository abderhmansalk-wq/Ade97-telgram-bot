from dataclasses import dataclass
from typing import Iterable
import numpy as np
import pandas as pd


@dataclass
class AgentVote:
    name: str
    score: float
    confidence: float
    reasons: list[str]


def _clip(v, lo=-1.0, hi=1.0):
    return float(max(lo, min(hi, v)))


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0)
    dn = -d.clip(upper=0)
    rs = up.ewm(alpha=1 / n, adjust=False).mean() / dn.ewm(alpha=1 / n, adjust=False).mean().replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df.close.shift(1)
    tr = pd.concat([(df.high-df.low).abs(), (df.high-pc).abs(), (df.low-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    x['ema20'] = ema(x.close, 20)
    x['ema50'] = ema(x.close, 50)
    x['ema200'] = ema(x.close, 200)
    x['rsi'] = rsi(x.close, 14)
    x['macd'] = ema(x.close, 12) - ema(x.close, 26)
    x['macds'] = ema(x.macd, 9)
    x['atr'] = atr(x, 14)
    x['vma'] = x.vol.rolling(20).mean()
    return x


def trend_agent(x: pd.DataFrame) -> AgentVote:
    last = x.iloc[-1]
    score = 0.0; reasons=[]
    if last.close > last.ema20 > last.ema50:
        score += .55; reasons.append('EMA20/50 مرتبة صعودياً')
    elif last.close < last.ema20 < last.ema50:
        score -= .55; reasons.append('EMA20/50 مرتبة هبوطياً')
    if pd.notna(last.ema200):
        score += .2 if last.close > last.ema200 else -.2
    fast_hi=x.high.iloc[-10:].max(); slow_hi=x.high.iloc[-20:-10].max()
    fast_lo=x.low.iloc[-10:].min(); slow_lo=x.low.iloc[-20:-10].min()
    if fast_hi > slow_hi and fast_lo > slow_lo:
        score += .25; reasons.append('Dow: قمم وقيعان أعلى')
    elif fast_hi < slow_hi and fast_lo < slow_lo:
        score -= .25; reasons.append('Dow: قمم وقيعان أدنى')
    return AgentVote('Trend/Dow', _clip(score), 55 + abs(score)*40, reasons)


def momentum_agent(x: pd.DataFrame) -> AgentVote:
    last=x.iloc[-1]; prev=x.iloc[-2]
    rv=float(last.rsi) if pd.notna(last.rsi) else 50
    score=0.0; reasons=[]
    if 52 <= rv <= 70:
        score += .4; reasons.append(f'RSI إيجابي {rv:.1f}')
    elif 30 <= rv <= 48:
        score -= .4; reasons.append(f'RSI سلبي {rv:.1f}')
    elif rv > 78:
        score -= .15; reasons.append(f'RSI تشبع شراء {rv:.1f}')
    elif rv < 22:
        score += .15; reasons.append(f'RSI تشبع بيع {rv:.1f}')
    if last.macd > last.macds:
        score += .35
        if prev.macd <= prev.macds: reasons.append('MACD تقاطع صاعد حديث')
    else:
        score -= .35
        if prev.macd >= prev.macds: reasons.append('MACD تقاطع هابط حديث')
    roc=(last.close/x.close.iloc[-6]-1) if len(x)>=6 else 0
    score += _clip(roc*12, -.25, .25)
    return AgentVote('Momentum', _clip(score), 50 + abs(score)*45, reasons)


def wyckoff_agent(x: pd.DataFrame) -> AgentVote:
    last=x.iloc[-1]; reasons=[]; score=0.0
    hi20=x.high.iloc[-21:-1].max(); lo20=x.low.iloc[-21:-1].min()
    vratio=float(last.vol/(last.vma if pd.notna(last.vma) and last.vma else 1))
    spread=max(float(last.high-last.low), 1e-12)
    close_pos=float((last.close-last.low)/spread)
    if last.close > hi20 and vratio > 1.15:
        score += .75; reasons.append('SOS/Markup proxy: اختراق بحجم مرتفع')
    elif last.close < lo20 and vratio > 1.15:
        score -= .75; reasons.append('SOW/Markdown proxy: كسر بحجم مرتفع')
    elif vratio > 1.5 and close_pos > .7:
        score += .3; reasons.append('Effort/Result إيجابي')
    elif vratio > 1.5 and close_pos < .3:
        score -= .3; reasons.append('Effort/Result سلبي')
    else:
        if last.low < lo20 and last.close > lo20: score += .35; reasons.append('Spring محتمل')
        if last.high > hi20 and last.close < hi20: score -= .35; reasons.append('Upthrust محتمل')
    return AgentVote('Wyckoff', _clip(score), 45 + abs(score)*55, reasons)


def smc_agent(x: pd.DataFrame) -> AgentVote:
    last=x.iloc[-1]; reasons=[]; score=0.0
    hh=x.high.iloc[-21:-1].max(); ll=x.low.iloc[-21:-1].min()
    atrv=float(last.atr or 0)
    if last.close > hh:
        score += .55; reasons.append('SMC: Break of Structure صاعد')
    elif last.close < ll:
        score -= .55; reasons.append('SMC: Break of Structure هابط')
    if last.low < ll and last.close > ll:
        score += .3; reasons.append('SMC: سحب سيولة أسفل القاع ثم استرداد')
    if last.high > hh and last.close < hh:
        score -= .3; reasons.append('SMC: سحب سيولة أعلى القمة ثم رفض')
    body=float(abs(last.close-last.open))
    if atrv and body/atrv > 1.1:
        score += .15 if last.close > last.open else -.15
    return AgentVote('SMC', _clip(score), 45 + abs(score)*50, reasons)


def volatility_agent(x: pd.DataFrame) -> AgentVote:
    last=x.iloc[-1]; reasons=[]
    atr_pct=float(last.atr/last.close*100) if last.close else 0
    ret=x.close.pct_change().iloc[-12:]
    drift=float(ret.mean()) if len(ret) else 0
    score=_clip(drift*80, -.25, .25)
    if atr_pct > 6: reasons.append(f'تقلب مرتفع جداً ATR {atr_pct:.2f}%')
    elif atr_pct < .25: reasons.append(f'تقلب ضعيف ATR {atr_pct:.2f}%')
    else: reasons.append(f'تقلب قابل للتداول ATR {atr_pct:.2f}%')
    confidence=70 if .25 <= atr_pct <= 6 else 40
    return AgentVote('Volatility', score, confidence, reasons)


def derivatives_agent(metrics: dict | None) -> AgentVote:
    if not metrics:
        return AgentVote('Derivatives', 0, 0, ['بيانات المشتقات غير متاحة'])
    fr=float(metrics.get('funding_rate') or 0)
    oi_delta=float(metrics.get('oi_change_pct') or 0)
    price_delta=float(metrics.get('price_change_pct') or 0)
    score=0.0; reasons=[]
    if fr > .0008: score -= .20; reasons.append(f'Funding مرتفع {fr*100:.3f}%')
    elif fr < -.0008: score += .20; reasons.append(f'Funding سلبي {fr*100:.3f}%')
    if oi_delta > 1 and price_delta > 0: score += .35; reasons.append('OI يرتفع مع السعر')
    elif oi_delta > 1 and price_delta < 0: score -= .35; reasons.append('OI يرتفع مع هبوط السعر')
    elif oi_delta < -1: reasons.append('OI ينخفض: فك مراكز/تأكيد أقل')
    return AgentVote('Derivatives', _clip(score), 40 + min(abs(oi_delta)*5,35), reasons)


def run_price_agents(df: pd.DataFrame) -> tuple[pd.DataFrame, list[AgentVote]]:
    x=prepare(df)
    votes=[trend_agent(x), momentum_agent(x), wyckoff_agent(x), smc_agent(x), volatility_agent(x)]
    return x, votes


def orderflow_agent(metrics: dict | None) -> AgentVote:
    if not metrics:
        return AgentVote('OrderFlow', 0, 0, ['بيانات Order Flow غير متاحة'])
    imb=float(metrics.get('imbalance') or 0)
    delta=float(metrics.get('trade_delta') or 0)
    spread=float(metrics.get('spread_bps') or 0)
    score=_clip(imb*.55 + delta*.65)
    reasons=[]
    if imb > .18: reasons.append(f'Order Book يميل للمشترين {imb:+.2f}')
    elif imb < -.18: reasons.append(f'Order Book يميل للبائعين {imb:+.2f}')
    if delta > .18: reasons.append(f'Trade Delta شرائي {delta:+.2f}')
    elif delta < -.18: reasons.append(f'Trade Delta بيعي {delta:+.2f}')
    if spread > 8:
        reasons.append(f'Spread واسع {spread:.1f} bps')
        score *= .7
    conf=35 + min(55,(abs(imb)+abs(delta))*35)
    return AgentVote('OrderFlow', _clip(score), min(95,conf), reasons or ['Order Flow متوازن'])


def liquidation_pressure_agent(metrics: dict | None) -> AgentVote:
    if not metrics or not metrics.get('live_available'):
        return AgentVote('LiquidationProxy',0,0,['بيانات الضغط اللحظي غير متاحة'])
    delta=float(metrics.get('trade_delta') or 0)
    cvd=float(metrics.get('cvd_proxy') or 0)
    impulse=float(metrics.get('flow_impulse') or 0)
    oi=float(metrics.get('oi_change_pct') or 0)
    pchg=float(metrics.get('price_change_flow_pct') or 0)
    score=0.0; reasons=[]
    if oi < -0.6 and pchg > 0 and (delta > .22 or cvd > .22):
        score += .55; reasons.append('ضغط إغلاق Short محتمل: OI↓ مع تدفق شراء قوي')
    elif oi < -0.6 and pchg < 0 and (delta < -.22 or cvd < -.22):
        score -= .55; reasons.append('ضغط إغلاق Long محتمل: OI↓ مع تدفق بيع قوي')
    if impulse > .28: score += .20; reasons.append('تسارع مفاجئ في التدفق الشرائي')
    elif impulse < -.28: score -= .20; reasons.append('تسارع مفاجئ في التدفق البيعي')
    conf=35 + min(55,(abs(delta)+abs(cvd)+abs(impulse))*22 + max(0,-oi)*5)
    return AgentVote('LiquidationProxy',_clip(score),min(92,conf),reasons or ['لا توجد علامة Forced-flow قوية'])
