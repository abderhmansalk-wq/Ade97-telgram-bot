import sqlite3
import numpy as np

from .paper_v50 import DB_PATH
from .paper_v53 import COST_BPS, TIMEFRAMES


def _conn():
    c=sqlite3.connect(DB_PATH,timeout=20)
    c.row_factory=sqlite3.Row
    return c


def _cost_r(entry,atr,cost_bps=COST_BPS):
    return (float(cost_bps)/10000.0)*float(entry)/float(atr) if entry and atr else 0.0


def timeframe_cost_stats():
    out={}
    with _conn() as c:
        for tf in TIMEFRAMES:
            rows=c.execute("SELECT entry,atr,pnl_r FROM paper_trades_v53 WHERE timeframe=? AND status='CLOSED' AND pnl_r IS NOT NULL ORDER BY id",(tf,)).fetchall()
            costs=[_cost_r(r['entry'],r['atr']) for r in rows]
            net=[float(r['pnl_r']) for r in rows]
            gross=[n+c for n,c in zip(net,costs)]
            out[tf]={
                'trades':len(rows),
                'avg_cost_r':float(np.mean(costs)) if costs else 0.0,
                'gross_ev_r':float(np.mean(gross)) if gross else 0.0,
                'net_ev_r':float(np.mean(net)) if net else 0.0,
                'total_cost_r':float(sum(costs)),
                'cost_drag_r':(float(np.mean(gross))-float(np.mean(net))) if net else 0.0,
            }
    return out
