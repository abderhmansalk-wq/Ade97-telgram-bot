from .paper_v53 import *
from .paper_v53 import _conn
from .market import fetch_backtest_candles


def open_positions():
    with _conn() as c:
        rows=c.execute("SELECT * FROM paper_trades_v53 WHERE status='OPEN' ORDER BY id").fetchall()
    return [dict(r) for r in rows]


async def open_positions_snapshot():
    """Return all V5.3/V5.4 open paper positions with latest market-distance metrics."""
    rows=open_positions()
    if not rows:
        return []

    prices={}
    for tf in sorted({r['timeframe'] for r in rows}):
        try:
            df=await fetch_backtest_candles('BTC',tf,260)
            if len(df):
                prices[tf]=float(df.iloc[-1].close)
        except Exception:
            prices[tf]=None

    out=[]
    for r in rows:
        entry=float(r['entry']); tp=float(r['tp']); sl=float(r['sl']); side=r['side']
        price=prices.get(r['timeframe'])
        item=dict(r)
        item['market_price']=price
        if price is None or entry<=0:
            item.update({'tp_distance':None,'sl_distance':None,'tp_distance_pct':None,'sl_distance_pct':None,'progress_pct':None})
            out.append(item); continue

        if side=='LONG':
            tp_dist=tp-price
            sl_dist=price-sl
            denom=tp-entry
            progress=(price-entry)/denom*100 if denom else 0.0
        else:
            tp_dist=price-tp
            sl_dist=sl-price
            denom=entry-tp
            progress=(entry-price)/denom*100 if denom else 0.0

        item.update({
            'tp_distance':tp_dist,
            'sl_distance':sl_dist,
            'tp_distance_pct':abs(tp_dist)/price*100 if price else 0.0,
            'sl_distance_pct':abs(sl_dist)/price*100 if price else 0.0,
            'progress_pct':progress,
        })
        out.append(item)
    return out
