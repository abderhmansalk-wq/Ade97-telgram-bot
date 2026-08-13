import numpy as np, pandas as pd
from src.signal_v46 import validate_v46

def make_df(n=1500, drift=.0004, vol=.01):
    rng=np.random.default_rng(46)
    ret=rng.normal(drift,vol,n)
    close=100*np.cumprod(1+ret)
    open_=np.r_[close[0],close[:-1]]
    high=np.maximum(open_,close)*(1+rng.uniform(0,.005,n))
    low=np.minimum(open_,close)*(1-rng.uniform(0,.005,n))
    volume=rng.lognormal(8,.3,n)
    ts=pd.date_range('2026-01-01',periods=n,freq='h',tz='UTC')
    return pd.DataFrame({'ts':ts,'open':open_,'high':high,'low':low,'close':close,'vol':volume})

def main():
    frames={'15m':make_df(1800,.0002,.008),'1h':make_df(1500,.0004,.010),'4h':make_df(1200,.0006,.013)}
    r=validate_v46('BTC',frames,8.0)
    assert r.status in ('PASS','NO_TRADE')
    assert len(r.buckets)==18
    assert any(b['folds']==3 for b in r.buckets)
    assert any(b['atr_percentile']>0 for b in r.buckets)
    assert any(b['regime']=='HIGH_VOL' for b in r.buckets)
    print('V4.6 smoke OK',r.status,len(r.buckets))

if __name__=='__main__': main()
