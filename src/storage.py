import json
import os
import sqlite3
import threading
import time
from pathlib import Path

DB_PATH = Path(os.getenv('MARKET_DB_PATH', 'data/market.db'))
_LOCK = threading.Lock()


def _connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('PRAGMA synchronous=NORMAL')
    return con


def init_db():
    with _LOCK, _connect() as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS market_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            last REAL,
            bid REAL,
            ask REAL,
            bid_depth REAL,
            ask_depth REAL,
            imbalance REAL,
            buy_volume REAL,
            sell_volume REAL,
            trade_delta REAL,
            open_interest REAL,
            funding_rate REAL,
            raw_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_snapshots_symbol_ts
        ON market_snapshots(symbol, ts DESC);
        ''')


def save_snapshot(symbol: str, snapshot: dict):
    row = dict(snapshot)
    ts = int(row.get('ts') or time.time() * 1000)
    fields = (
        ts, symbol.upper(), row.get('last'), row.get('bid'), row.get('ask'),
        row.get('bid_depth'), row.get('ask_depth'), row.get('imbalance'),
        row.get('buy_volume'), row.get('sell_volume'), row.get('trade_delta'),
        row.get('open_interest'), row.get('funding_rate'),
        json.dumps(row, ensure_ascii=False, separators=(',', ':')),
    )
    with _LOCK, _connect() as con:
        con.execute('''
        INSERT INTO market_snapshots (
          ts,symbol,last,bid,ask,bid_depth,ask_depth,imbalance,buy_volume,sell_volume,
          trade_delta,open_interest,funding_rate,raw_json
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ''', fields)


def latest_snapshot(symbol: str):
    with _connect() as con:
        cur = con.execute('''SELECT raw_json FROM market_snapshots
                             WHERE symbol=? ORDER BY ts DESC LIMIT 1''', (symbol.upper(),))
        row = cur.fetchone()
    return json.loads(row[0]) if row else None


def oi_change_pct(symbol: str, lookback_ms: int = 15 * 60 * 1000):
    now = int(time.time() * 1000)
    with _connect() as con:
        latest = con.execute('''SELECT open_interest FROM market_snapshots
                                WHERE symbol=? AND open_interest IS NOT NULL
                                ORDER BY ts DESC LIMIT 1''', (symbol.upper(),)).fetchone()
        older = con.execute('''SELECT open_interest FROM market_snapshots
                               WHERE symbol=? AND ts<=? AND open_interest IS NOT NULL
                               ORDER BY ts DESC LIMIT 1''', (symbol.upper(), now-lookback_ms)).fetchone()
    if not latest or not older or not older[0]: return 0.0
    return (float(latest[0]) / float(older[0]) - 1.0) * 100.0


def flow_features(symbol: str, lookback_ms: int = 15 * 60 * 1000):
    now = int(time.time() * 1000)
    with _connect() as con:
        rows = con.execute('''SELECT ts,last,buy_volume,sell_volume,trade_delta,imbalance,open_interest
                              FROM market_snapshots
                              WHERE symbol=? AND ts>=?
                              ORDER BY ts ASC''', (symbol.upper(), now-lookback_ms)).fetchall()
    if not rows:
        return {'cvd_proxy':0.0,'flow_impulse':0.0,'trade_delta_avg':0.0,'book_imbalance_avg':0.0,'price_change_flow_pct':0.0,'samples':0}
    deltas=[]; imbs=[]; signed=[]
    first_price=float(rows[0][1] or 0); last_price=float(rows[-1][1] or 0)
    for _,_,buy,sell,td,imb,_ in rows:
        b=float(buy or 0); s=float(sell or 0)
        deltas.append(float(td or 0)); imbs.append(float(imb or 0)); signed.append(b-s)
    gross=sum(abs(x) for x in signed) or 1.0
    cvd=max(-1.0,min(1.0,sum(signed)/gross))
    tail=deltas[-min(4,len(deltas)):]
    head=deltas[:-len(tail)] or [0.0]
    impulse=(sum(tail)/len(tail))-(sum(head)/len(head))
    price_chg=((last_price/first_price)-1)*100 if first_price and last_price else 0.0
    return {
        'cvd_proxy':round(cvd,4), 'flow_impulse':round(max(-1,min(1,impulse)),4),
        'trade_delta_avg':round(sum(deltas)/len(deltas),4),
        'book_imbalance_avg':round(sum(imbs)/len(imbs),4),
        'price_change_flow_pct':round(price_chg,4), 'samples':len(rows),
    }


def init_alert_state():
    with _LOCK, _connect() as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS alert_state (
            symbol TEXT PRIMARY KEY,
            side TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            quality REAL NOT NULL,
            sent_ts INTEGER NOT NULL
        );
        ''')


def should_send_alert(symbol: str, side: str, timeframe: str, quality: float,
                      cooldown_ms: int = 60 * 60 * 1000, quality_step: float = 7.0) -> bool:
    init_alert_state()
    now=int(time.time()*1000); symbol=symbol.upper()
    with _LOCK, _connect() as con:
        row=con.execute('SELECT side,timeframe,quality,sent_ts FROM alert_state WHERE symbol=?',(symbol,)).fetchone()
        send=False
        if not row:
            send=True
        else:
            old_side,old_tf,old_q,old_ts=row
            send = (side != old_side) or (timeframe != old_tf) or (quality >= float(old_q)+quality_step) or (now-int(old_ts) >= cooldown_ms)
        if send:
            con.execute('''INSERT INTO alert_state(symbol,side,timeframe,quality,sent_ts) VALUES(?,?,?,?,?)
                           ON CONFLICT(symbol) DO UPDATE SET side=excluded.side,timeframe=excluded.timeframe,
                           quality=excluded.quality,sent_ts=excluded.sent_ts''',(symbol,side,timeframe,float(quality),now))
        return send
