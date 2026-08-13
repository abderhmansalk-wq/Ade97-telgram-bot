import numpy as np, pandas as pd
from src.signal_v49 import validate_v49

def make_df(n=1800, drift=.0004, vol=.012):
    rng=np.random.default_rng(49)
    ret=rng.normal(drift,vol,n)
    close=100*np.cumprod(1+ret)
    open_=np.r_[close[0],close[:-1]]
    high=np.maximum(open_,close)*(1+rng.uniform(0,.006,n))
    low=np.minimum(open_,close)*(1-rng.uniform(0,.006,n))
    volume=rng.lognormal(8,.3,n)
    ts=pd.date_range('2025-01-01',periods=n,freq='4h',tz='UTC')
    return pd.DataFrame({'ts':ts,'open':open_,'high':high,'low':low,'close':close,'vol':volume})

def main():
    r=validate_v49(make_df(),'BTC')
    assert r.status in ('FORWARD_TEST_READY','HOLD')
    assert r.sample_bars==1800
    assert len(r.costs)==3
    for c in r.costs:
        assert c['folds']==4
        assert c['trades']>=0
        assert c['max_drawdown_r']>=0
        assert c['monte_carlo_mdd_p95']>=0
        assert c['bootstrap_low_r']<=c['bootstrap_high_r']
    print('V4.9 smoke OK',r.status)

if __name__=='__main__': main()
