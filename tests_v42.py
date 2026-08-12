import numpy as np
import pandas as pd
from src.optimizer import optimize_oos


def make_df(n=900):
    rng=np.random.default_rng(42)
    close=[100.0]
    for i in range(1,n):
        regime=.0012 if (i//120)%2==0 else -.0010
        close.append(close[-1]*(1+rng.normal(regime,.007)))
    close=np.array(close)
    open_=np.r_[close[0],close[:-1]]
    high=np.maximum(open_,close)*(1+rng.uniform(0,.004,n))
    low=np.minimum(open_,close)*(1-rng.uniform(0,.004,n))
    vol=rng.lognormal(8,.25,n)
    ts=pd.date_range('2026-01-01', periods=n, freq='h', tz='UTC')
    return pd.DataFrame({'ts':ts,'open':open_,'high':high,'low':low,'close':close,'vol':vol})


def main():
    r=optimize_oos(make_df(),'BTC','1h',horizon=3,min_history=210,step=6)
    assert r.train_rows > 0 and r.test_rows > 0
    assert r.status in {'PASS','NO_TRADE','INSUFFICIENT_DATA'}
    assert 0 <= r.test_accuracy <= 100
    assert r.threshold in {.16,.20,.24,.28,.32}
    print('V4.2 optimizer smoke OK',r.status,r.test_accuracy,r.test_signals)

if __name__=='__main__': main()
