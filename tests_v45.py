import numpy as np, pandas as pd
from src.signal_v45 import validate_v45

def make_df(n=1200, drift=.0004):
    rng=np.random.default_rng(45)
    ret=rng.normal(drift,.009,n)
    close=100*np.cumprod(1+ret)
    open_=np.r_[close[0],close[:-1]]
    high=np.maximum(open_,close)*(1+rng.uniform(0,.004,n))
    low=np.minimum(open_,close)*(1-rng.uniform(0,.004,n))
    vol=rng.lognormal(8,.3,n)
    ts=pd.date_range('2026-01-01',periods=n,freq='h',tz='UTC')
    return pd.DataFrame({'ts':ts,'open':open_,'high':high,'low':low,'close':close,'vol':vol})

def main():
    frames={'15m':make_df(1200,.0002),'1h':make_df(1200,.0004),'4h':make_df(720,.0006)}
    r=validate_v45('BTC',frames,8.0)
    assert r.status in ('PASS','NO_TRADE')
    assert len(r.buckets)>0
    for b in r.buckets:
        assert b['regime'] in ('TREND','RANGE','HIGH_VOL')
        assert b['side'] in ('LONG','SHORT')
    print('V4.5 smoke OK',r.status,len(r.buckets))

if __name__=='__main__': main()
