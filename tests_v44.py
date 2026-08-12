import numpy as np, pandas as pd
from src.signal_v44 import validate_v44

def make_df(n=1400):
    rng=np.random.default_rng(44)
    rets=rng.normal(.00025,.009,n)
    close=100*np.cumprod(1+rets)
    open_=np.r_[close[0],close[:-1]]
    high=np.maximum(open_,close)*(1+rng.uniform(0,.005,n))
    low=np.minimum(open_,close)*(1-rng.uniform(0,.005,n))
    vol=rng.lognormal(8,.25,n)
    ts=pd.date_range('2026-01-01',periods=n,freq='h',tz='UTC')
    return pd.DataFrame({'ts':ts,'open':open_,'high':high,'low':low,'close':close,'vol':vol})

r=validate_v44(make_df(),'BTC','1h',8.0)
assert r.status in {'PASS_BOTH','PASS_LONG','PASS_SHORT','NO_TRADE','INSUFFICIENT_DATA'}
assert r.fee_slippage_bps==8.0
assert r.total_trades>=0
print('V4.4 smoke OK',r.status,r.total_trades,r.expectancy_r)
