from src.agents import orderflow_agent
from src.meta_engine import combine
from src.realtime import LiveState
from src.storage import init_db


def main():
    s=LiveState('BTC', last=100, bid=99.9, ask=100.1, bid_depth=75, ask_depth=25,
                buy_volume=60, sell_volume=20, open_interest=1234, funding_rate=.0001, ts=1)
    x=s.as_dict()
    assert x['imbalance'] > .4
    assert x['trade_delta'] > .4
    vote=orderflow_agent({**x, 'live_available': True})
    assert vote.score > 0
    meta=combine([vote])
    assert meta.score > 0
    init_db()
    print('V3 smoke OK', x['imbalance'], x['trade_delta'], vote.score)

if __name__=='__main__': main()
