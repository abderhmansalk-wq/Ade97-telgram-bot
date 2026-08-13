import numpy as np, pandas as pd
from src.signal_v48 import validate_v48

def make_df(n=1200, drift=.0004, vol=.012):
    rng=np.random.default_rng(48)
    ret=rng.normal(drift,vol,n)
    close=100*np.cumprod(1+ret)
    open_=np.r_[close[0],close[:-1]]
    high=np.maximum(open_,close)*(1+rng.uniform(0,.006,n))
    low=np.minimum(open_,close)*(1-rng.uniform(0,.006,n))
    volume=rng.lognormal(8,.3,n)
    ts=pd.date_range('2026-01-01',periods=n,freq='4h',tz='UTC')
    return pd.DataFrame({'ts':ts,'open':open_,'high':high,'low':low,'close':close,'vol':volume})

def main():
    r=validate_v48(make_df(),'BTC')
    assert r.status in ('PAPER_READY','HOLD')
    assert len(r.overlays)==6
    names={o['name'] for o in r.overlays}
    assert {'baseline','cooldown','loss_cooldown','dd_brake','vol_extreme','combo'} <= names
    for o in r.overlays:
        assert o['max_drawdown_r']>=0
        assert o['monte_carlo_mdd_p95']>=0
        assert o['longest_losing_streak']>=0
    print('V4.8 smoke OK',r.status,r.best_overlay)

if __name__=='__main__': main()
