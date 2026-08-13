import numpy as np, pandas as pd
from src.signal_v491 import validate_v491

def make_df(n=1800, drift=.0004, vol=.012):
    rng=np.random.default_rng(491)
    ret=rng.normal(drift,vol,n)
    close=100*np.cumprod(1+ret)
    open_=np.r_[close[0],close[:-1]]
    high=np.maximum(open_,close)*(1+rng.uniform(0,.006,n))
    low=np.minimum(open_,close)*(1-rng.uniform(0,.006,n))
    volume=rng.lognormal(8,.3,n)
    ts=pd.date_range('2025-01-01',periods=n,freq='4h',tz='UTC')
    return pd.DataFrame({'ts':ts,'open':open_,'high':high,'low':low,'close':close,'vol':volume})

def main():
    r=validate_v491(make_df(),'BTC',8.0)
    assert r.status=='DIAGNOSTIC_ONLY'
    assert len(r.folds)==4
    assert r.total_trades>=r.one_position_total_trades
    assert r.overlap_removed==r.total_trades-r.one_position_total_trades
    for f in r.folds:
        assert f['start'] and f['end']
        assert f['executed_trades']>=f['one_position_trades']
        assert f['max_drawdown_r']>=0
        assert f['one_position_max_drawdown_r']>=0
    print('V4.9.1 diagnostic OK',r.total_trades,r.one_position_total_trades,r.positive_folds,r.one_position_positive_folds)

if __name__=='__main__': main()
