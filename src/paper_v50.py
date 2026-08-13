import os
import json
import sqlite3
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from .agents import prepare
from .market import fetch_backtest_candles
from .signal_v45 import _range_signal
from .signal_v46 import classify_regime, _atr_pct_series

# Frozen after V4.9.1. V5.0 is FORWARD PAPER ONLY: no exchange orders, no optimization.
SETUP={
    'symbol':'BTC','timeframe':'4h','regime':'RANGE','side':'LONG',
    'rr':2.0,'min_score':2,'horizon':12,
}
LOSS_COOLDOWN_AFTER=2
LOSS_COOLDOWN_BARS=12
COST_BPS=float(os.getenv('PAPER_COST_BPS','8.0'))
TARGET_FORWARD_TRADES=int(os.getenv('PAPER_TARGET_TRADES','40'))


def _db_path():
    configured=os.getenv('PAPER_DB_PATH','').strip()
    if configured:
        p=Path(configured)
    else:
        data=Path('/data')
        p=(data/'ade_paper_v50.db') if data.exists() and os.access(data,os.W_OK) else Path('/tmp/ade_paper_v50.db')
    p.parent.mkdir(parents=True,exist_ok=True)
    return str(p)

DB_PATH=_db_path()


def _conn():
    c=sqlite3.connect(DB_PATH,timeout=20)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('''CREATE TABLE IF NOT EXISTS paper_state (
        key TEXT PRIMARY KEY, value TEXT NOT NULL
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS paper_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        signal_ts TEXT UNIQUE NOT NULL,
        opened_ts TEXT NOT NULL,
        closed_ts TEXT,
        symbol TEXT NOT NULL,
        timeframe TEXT NOT NULL,
        regime TEXT NOT NULL,
        side TEXT NOT NULL,
        entry REAL NOT NULL,
        tp REAL NOT NULL,
        sl REAL NOT NULL,
        atr REAL NOT NULL,
        atr_pct REAL NOT NULL,
        hv_cut REAL NOT NULL,
        score INTEGER NOT NULL,
        cost_bps REAL NOT NULL,
        status TEXT NOT NULL,
        pnl_r REAL,
        exit_price REAL,
        outcome TEXT,
        note TEXT
    )''')
    c.commit()
    return c


def get_state(key,default=None):
    with _conn() as c:
        r=c.execute('SELECT value FROM paper_state WHERE key=?',(key,)).fetchone()
    if not r: return default
    try: return json.loads(r['value'])
    except Exception: return r['value']


def set_state(key,value):
    with _conn() as c:
        c.execute('INSERT INTO paper_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,json.dumps(value)))
        c.commit()


def set_enabled(enabled:bool,chat_id:Optional[int]=None):
    set_state('enabled',bool(enabled))
    if chat_id is not None: set_state('chat_id',int(chat_id))


def is_enabled(): return bool(get_state('enabled',False))
def subscribed_chat_id(): return get_state('chat_id',None)


def _pf(vals):
    if not vals: return 0.0
    a=np.asarray(vals,float); gains=float(a[a>0].sum()); losses=float(-a[a<0].sum())
    return gains/losses if losses>0 else (99.0 if gains>0 else 0.0)


def _mdd(vals):
    if not vals: return 0.0
    a=np.asarray(vals,float); curve=np.r_[0.0,np.cumsum(a)]; peak=np.maximum.accumulate(curve)
    return float(np.max(peak-curve))


def _lls(vals):
    best=cur=0
    for v in vals:
        if v<0: cur+=1; best=max(best,cur)
        else: cur=0
    return best


def summary():
    with _conn() as c:
        closed=c.execute("SELECT pnl_r FROM paper_trades WHERE status='CLOSED' ORDER BY id").fetchall()
        open_rows=c.execute("SELECT * FROM paper_trades WHERE status='OPEN' ORDER BY id").fetchall()
        total=c.execute('SELECT COUNT(*) n FROM paper_trades').fetchone()['n']
        last=c.execute('SELECT * FROM paper_trades ORDER BY id DESC LIMIT 1').fetchone()
    vals=[float(r['pnl_r']) for r in closed if r['pnl_r'] is not None]
    n=len(vals); wr=100*sum(v>0 for v in vals)/n if n else 0.0
    return {
        'db_path':DB_PATH,'enabled':is_enabled(),'total_records':int(total),'closed':n,'open':len(open_rows),
        'win_rate':wr,'expectancy_r':float(np.mean(vals)) if vals else 0.0,'profit_factor':_pf(vals),
        'max_drawdown_r':_mdd(vals),'longest_losing_streak':_lls(vals),'equity_r':float(sum(vals)),
        'target_trades':TARGET_FORWARD_TRADES,'last':dict(last) if last else None,
    }


def recent_trades(limit=8):
    with _conn() as c:
        rows=c.execute('SELECT * FROM paper_trades ORDER BY id DESC LIMIT ?',(int(limit),)).fetchall()
    return [dict(r) for r in rows]


def _open_trade():
    with _conn() as c:
        r=c.execute("SELECT * FROM paper_trades WHERE status='OPEN' ORDER BY id DESC LIMIT 1").fetchone()
    return dict(r) if r else None


def _recent_closed(limit=20):
    with _conn() as c:
        rows=c.execute("SELECT * FROM paper_trades WHERE status='CLOSED' ORDER BY id DESC LIMIT ?",(int(limit),)).fetchall()
    return [dict(r) for r in rows]


def _can_open(signal_index:int):
    if _open_trade(): return False,'one-position-at-a-time: position already open'
    closed=_recent_closed(20)
    if len(closed)>=2 and all(float(x.get('pnl_r') or 0)<0 for x in closed[:2]):
        last_loss_idx=get_state('last_loss_signal_index',None)
        if last_loss_idx is not None and signal_index-int(last_loss_idx)<LOSS_COOLDOWN_BARS:
            return False,f'loss_cooldown active ({LOSS_COOLDOWN_BARS} bars after 2 losses)'
    return True,''


def _cost_r(entry,atr,cost_bps):
    if not entry or not atr: return 0.0
    return (float(cost_bps)/10000.0)*float(entry)/float(atr)


def _close_trade(trade,ts,exit_price,gross_r,outcome,signal_index):
    net_r=float(gross_r)-_cost_r(trade['entry'],trade['atr'],trade['cost_bps'])
    with _conn() as c:
        c.execute("UPDATE paper_trades SET closed_ts=?,status='CLOSED',pnl_r=?,exit_price=?,outcome=? WHERE id=?",
                  (str(ts),net_r,float(exit_price),str(outcome),int(trade['id'])))
        c.commit()
    if net_r<0:
        set_state('last_loss_signal_index',int(signal_index))
    return net_r


def _manage_open(x):
    trade=_open_trade()
    if not trade: return None
    opened=pd.Timestamp(trade['opened_ts'])
    newer=x[x.ts>opened]
    if newer.empty: return None
    # First-touch, conservative if TP and SL are touched in the same candle: SL wins.
    for idx,row in newer.iterrows():
        lo=float(row.low); hi=float(row.high)
        if lo<=float(trade['sl']) and hi>=float(trade['tp']):
            r=_close_trade(trade,row.ts,trade['sl'],-1.0,'SL_same_bar_conservative',int(idx))
            return {'type':'CLOSED','trade':trade,'pnl_r':r,'outcome':'SL (same candle conservative)','ts':str(row.ts)}
        if lo<=float(trade['sl']):
            r=_close_trade(trade,row.ts,trade['sl'],-1.0,'SL',int(idx))
            return {'type':'CLOSED','trade':trade,'pnl_r':r,'outcome':'SL','ts':str(row.ts)}
        if hi>=float(trade['tp']):
            r=_close_trade(trade,row.ts,trade['tp'],SETUP['rr'],'TP',int(idx))
            return {'type':'CLOSED','trade':trade,'pnl_r':r,'outcome':'TP','ts':str(row.ts)}
    return None


def _latest_closed_index(df):
    # OKX newest candle may still be forming; using the penultimate candle prevents look-ahead/partial-bar entries.
    return len(df)-2


def _try_open(x,atr_cutoff):
    i=_latest_closed_index(x)
    if i<210: return None
    row=x.iloc[i]
    signal_ts=str(row.ts)
    with _conn() as c:
        exists=c.execute('SELECT id FROM paper_trades WHERE signal_ts=?',(signal_ts,)).fetchone()
    if exists: return None
    if classify_regime(x,i,atr_cutoff)!='RANGE': return None
    side,score=_range_signal(x,i)
    if side!='LONG' or int(score)<SETUP['min_score']: return None
    allowed,reason=_can_open(i)
    if not allowed:
        # Record suppressed signal for audit, but it is not a trade.
        set_state('last_suppressed',{'signal_ts':signal_ts,'reason':reason,'score':int(score)})
        return {'type':'SUPPRESSED','reason':reason,'signal_ts':signal_ts}
    entry=float(row.close); atr=float(row.atr); atr_pct=atr/entry*100 if entry else 0.0
    tp=entry+SETUP['rr']*atr; sl=entry-atr
    with _conn() as c:
        c.execute('''INSERT INTO paper_trades(signal_ts,opened_ts,symbol,timeframe,regime,side,entry,tp,sl,atr,atr_pct,hv_cut,score,cost_bps,status,note)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                  (signal_ts,signal_ts,'BTC','4h','RANGE','LONG',entry,tp,sl,atr,atr_pct,float(atr_cutoff),int(score),COST_BPS,'OPEN','V5.0 forward paper; frozen setup'))
        c.commit()
    set_state('last_signal_index',i)
    return {'type':'OPENED','signal_ts':signal_ts,'entry':entry,'tp':tp,'sl':sl,'atr':atr,'atr_pct':atr_pct,'hv_cut':atr_cutoff,'score':int(score)}


async def paper_tick():
    """One forward-only evaluation. Safe to call frequently; acts once per closed 4h candle."""
    if not is_enabled(): return []
    df=await fetch_backtest_candles('BTC','4h',1800)
    x=prepare(df).reset_index(drop=True)
    i=_latest_closed_index(x)
    if i<210: return []
    # Live cutoff uses only information available before the signal candle.
    atrp=_atr_pct_series(x).iloc[210:i].dropna()
    if len(atrp)<300: return []
    atr_cutoff=float(atrp.quantile(.80))
    events=[]
    closed=_manage_open(x)
    if closed: events.append(closed)
    opened=_try_open(x,atr_cutoff)
    if opened: events.append(opened)
    set_state('last_tick_ts',str(pd.Timestamp.utcnow()))
    set_state('last_hv_cut',atr_cutoff)
    return events
