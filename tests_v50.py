import os
import tempfile
import importlib
import numpy as np
import pandas as pd


def make_df(n=1800, drift=.0003, vol=.012):
    rng=np.random.default_rng(50)
    ret=rng.normal(drift,vol,n)
    close=100*np.cumprod(1+ret)
    open_=np.r_[close[0],close[:-1]]
    high=np.maximum(open_,close)*(1+rng.uniform(0,.006,n))
    low=np.minimum(open_,close)*(1-rng.uniform(0,.006,n))
    volume=rng.lognormal(8,.3,n)
    ts=pd.date_range('2025-08-01',periods=n,freq='4h',tz='UTC')
    return pd.DataFrame({'ts':ts,'open':open_,'high':high,'low':low,'close':close,'vol':volume})


def main():
    with tempfile.TemporaryDirectory() as d:
        os.environ['PAPER_DB_PATH']=os.path.join(d,'paper.db')
        import src.paper_v50 as p
        importlib.reload(p)
        p.set_enabled(True,123)
        assert p.is_enabled() is True
        assert p.subscribed_chat_id()==123
        s=p.summary()
        assert s['closed']==0 and s['open']==0
        # Core persistence tables exist and can round-trip state.
        p.set_state('x',{'a':1})
        assert p.get_state('x')['a']==1
        # Metrics should remain sane on empty/new database.
        assert s['profit_factor']>=0 and s['max_drawdown_r']>=0
        assert p.SETUP['symbol']=='BTC' and p.SETUP['timeframe']=='4h'
        print('V5.0 paper smoke OK',p.DB_PATH)

if __name__=='__main__': main()
