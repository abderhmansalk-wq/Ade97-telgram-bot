from dataclasses import dataclass, asdict, field
import pandas as pd
from .analysis_engine import analyze

@dataclass
class CalibrationBin:
    low: int
    high: int
    samples: int
    predicted_pct: float
    realized_pct: float

@dataclass
class BacktestResult:
    timeframe: str
    bars: int
    samples: int
    long_samples: int
    short_samples: int
    accuracy: float
    bullish_accuracy: float
    bearish_accuracy: float
    avg_forward_return_pct: float
    brier_like: float
    ece: float = 0.0
    start: str = ''
    end: str = ''
    horizon_bars: int = 0
    calibration: list[dict] = field(default_factory=list)
    long_calibration: list[dict] = field(default_factory=list)
    short_calibration: list[dict] = field(default_factory=list)


def _calibration(rows):
    bins=[]; total=max(1,len(rows)); ece=0.0
    for lo,hi in [(50,60),(60,70),(70,80),(80,90),(90,101)]:
        bucket=[]
        for direction,correct,fret,pred,actual,declared in rows:
            if lo <= declared < hi:
                bucket.append((pred,actual))
        if not bucket: continue
        pp=sum(x[0] for x in bucket)/len(bucket)*100
        rr=sum(x[1] for x in bucket)/len(bucket)*100
        ece += len(bucket)/total * abs(pp-rr)/100
        bins.append(asdict(CalibrationBin(lo,hi,len(bucket),round(pp,1),round(rr,1))))
    return round(ece,4),bins


def walk_forward(df: pd.DataFrame,timeframe: str,horizon: int=3,min_history: int=210,step: int=3)->BacktestResult:
    rows=[]
    end_i=len(df)-horizon
    for i in range(min_history,end_i,step):
        hist=df.iloc[:i+1]
        r=analyze(hist,timeframe,None)
        future=float(df.close.iloc[i+horizon]/df.close.iloc[i]-1)
        if r.direction=='محايد': continue
        correct=(future>0 and r.direction=='صاعد') or (future<0 and r.direction=='هابط')
        side_prob=(r.bullish_pct if r.direction=='صاعد' else r.bearish_pct)/100
        side_actual=1 if correct else 0
        declared=max(r.bullish_pct,r.bearish_pct)
        rows.append((r.direction,correct,future*100,side_prob,side_actual,declared))
    start=str(df.ts.iloc[0]) if 'ts' in df and len(df) else ''
    end=str(df.ts.iloc[-1]) if 'ts' in df and len(df) else ''
    if not rows:
        return BacktestResult(timeframe,len(df),0,0,0,0,0,0,0,0,0,start=start,end=end,horizon_bars=horizon)
    n=len(rows); bull=[x for x in rows if x[0]=='صاعد']; bear=[x for x in rows if x[0]=='هابط']
    acc=sum(x[1] for x in rows)/n*100
    ba=sum(x[1] for x in bull)/len(bull)*100 if bull else 0
    be=sum(x[1] for x in bear)/len(bear)*100 if bear else 0
    avg=sum(x[2] for x in rows)/n
    brier=sum((x[3]-x[4])**2 for x in rows)/n
    ece,bins=_calibration(rows)
    _,long_bins=_calibration(bull)
    _,short_bins=_calibration(bear)
    return BacktestResult(
        timeframe,len(df),n,len(bull),len(bear),round(acc,2),round(ba,2),round(be,2),
        round(avg,3),round(brier,4),ece,start,end,horizon,bins,long_bins,short_bins
    )

def to_dict(x): return asdict(x)
