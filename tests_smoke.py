import numpy as np, pandas as pd
from src.analysis_engine import analyze, pick_best, cross_timeframe_context
from src.backtest import walk_forward

def make_df(n=420, trend=.001):
    rng=np.random.default_rng(7)
    rets=rng.normal(trend,.01,n)
    close=100*np.cumprod(1+rets)
    open_=np.r_[close[0],close[:-1]]
    high=np.maximum(open_,close)*(1+rng.uniform(0,.006,n))
    low=np.minimum(open_,close)*(1-rng.uniform(0,.006,n))
    vol=rng.lognormal(8,.25,n)
    return pd.DataFrame({'open':open_,'high':high,'low':low,'close':close,'vol':vol})

def main():
    frames=[]
    for tf in ['5m','15m','1h','4h','1d','1w']:
        r=analyze(make_df(),tf,{'funding_rate':0.0001,'oi_change_pct':2,'price_change_pct':1})
        assert 0<=r.bullish_pct<=100 and 0<=r.entry_quality<=100
        frames.append(r)
    best=pick_best(frames); regime,_=cross_timeframe_context(frames)
    bt=walk_forward(make_df(520),'1h',horizon=3,step=12)
    assert bt.samples>0
    print('OK',best.timeframe,regime,bt)
if __name__=='__main__': main()
