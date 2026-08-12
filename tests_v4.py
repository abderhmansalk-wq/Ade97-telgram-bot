import os, tempfile, time
os.environ['MARKET_DB_PATH']=tempfile.mktemp(suffix='.db')
from src.storage import init_db, save_snapshot, flow_features, should_send_alert
from src.agents import liquidation_pressure_agent

init_db(); now=int(time.time()*1000)
for i in range(12):
    save_snapshot('BTC', {'ts':now-(11-i)*30000,'last':100+i*.15,'buy_volume':120+i*8,'sell_volume':80-i*2,
                          'trade_delta':.2+i*.025,'imbalance':.1,'open_interest':1000-i*8})
f=flow_features('BTC')
assert f['samples'] == 12 and f['cvd_proxy'] > 0
vote=liquidation_pressure_agent(dict(f, live_available=True, trade_delta=.48, oi_change_pct=-1.2))
assert vote.score > 0
assert should_send_alert('BTC','LONG','15m',80)
assert not should_send_alert('BTC','LONG','15m',80)
assert should_send_alert('BTC','SHORT','15m',80)
print('V4 smoke OK', f, vote.score)
