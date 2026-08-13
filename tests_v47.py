import numpy as np, pandas as pd
from src.signal_v47 import validate_v47

def make_df(n=1500):
    rng=np.random.default_rng(47)
    ret=rng.normal(.00025,.012,n)
    # alternating drift blocks create both trend/range-like conditions
    for k in range(100,n,250):
        ret[k:k+80]+=0.0010 if (k//250)%2==0 else -0.0010
    close=100*np.cumprod(1+ret)
    open_=np.r_[close[0],close[:-1]]
    high=np.maximum(open_,close)*(1+rng.uniform(0,.006,n))
    low=np.minimum(open_,close)*(1-rng.uniform(0,.006,n))
    vol=rng.lognormal(8,.35,n)
    ts=pd.date_range('2025-01-01',periods=n,freq='4h',tz='UTC')
    return pd.DataFrame({'ts':ts,'open':open_,'high':high,'low':low,'close':close,'vol':vol})

def main():
    r=validate_v47('BTC',{'4h':make_df()})
    assert r.status in ('PAPER_READY','HOLD')
    assert len(r.setups)==2
    for s in r.setups:
        assert s['status'] in ('PAPER_READY','HOLD','INSUFFICIENT_DATA')
        assert len(s['costs']) in (0,3)
        if s['costs']:
            assert [c['cost_bps'] for c in s['costs']]==[8.0,12.0,16.0]
            assert all(c['folds']==3 for c in s['costs'])
    print('V4.7 smoke OK',r.status,r.paper_ready_count)

if __name__=='__main__': main()
