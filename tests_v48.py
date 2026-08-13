import numpy as np, pandas as pd
from src.signal_v48 import validate_v48
from src.signal_v47 import validate_v47

def make_df(n=1500, drift=.0004, vol=.012):
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
    df=make_df()
    r=validate_v48(df,'BTC')
    assert r.status in ('PAPER_READY','HOLD')
    assert len(r.overlays)==6
    names={o['name'] for o in r.overlays}
    assert {'baseline','cooldown','loss_cooldown','dd_brake','vol_extreme','combo'} <= names
    for o in r.overlays:
        assert o['max_drawdown_r']>=0
        assert o['monte_carlo_mdd_p95']>=0
        assert o['longest_losing_streak']>=0

    # Regression: V4.8 baseline must be the same frozen RANGE/LONG setup and OOS sample as V4.7 cost=8bps.
    r47=validate_v47('BTC',{'4h':df})
    range_long=next(s for s in r47.setups if s['regime']=='RANGE' and s['side']=='LONG')
    cost8=next(c for c in range_long['costs'] if c['cost_bps']==8.0)
    baseline=next(o for o in r.overlays if o['name']=='baseline')
    assert baseline['trades']==cost8['trades'], (baseline['trades'],cost8['trades'])
    assert abs(baseline['expectancy_r']-cost8['expectancy_r'])<1e-9
    assert abs(baseline['profit_factor']-cost8['profit_factor'])<1e-9
    assert abs(baseline['max_drawdown_r']-cost8['max_drawdown_r'])<1e-9
    print('V4.8.1 smoke OK',r.status,r.best_overlay,'baseline n=',baseline['trades'])

if __name__=='__main__': main()
