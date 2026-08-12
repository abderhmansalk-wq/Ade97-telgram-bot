import numpy as np
import pandas as pd
from src.signal_v43 import validate_v43


def make_df(n=900, seed=43):
    rng=np.random.default_rng(seed)
    trend=np.where(np.arange(n)<n//2,0.0012,-0.0008)
    rets=rng.normal(trend,0.006,n)
    close=100*np.cumprod(1+rets)
    open_=np.r_[close[0],close[:-1]]
    high=np.maximum(open_,close)*(1+rng.uniform(0.001,0.005,n))
    low=np.minimum(open_,close)*(1-rng.uniform(0.001,0.005,n))
    vol=rng.lognormal(8,0.35,n)
    ts=pd.date_range('2026-01-01',periods=n,freq='h',tz='UTC')
    return pd.DataFrame({'ts':ts,'open':open_,'high':high,'low':low,'close':close,'vol':vol})

if __name__=='__main__':
    r=validate_v43(make_df(),'BTC','1h')
    assert r.status in {'PASS','NO_TRADE','INSUFFICIENT_DATA'}
    assert 0 <= r.test_win_rate <= 100
    assert r.tp_atr > 0 and r.sl_atr > 0
    print('V4.3 smoke OK',r)
