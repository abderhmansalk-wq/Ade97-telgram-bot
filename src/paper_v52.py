import sqlite3
import numpy as np
import pandas as pd

from .agents import prepare
from .market import fetch_backtest_candles
from .signal_v45 import _range_signal
from .signal_v46 import classify_regime, _atr_pct_series
from .paper_v50 import DB_PATH, get_state, set_state

TIMEFRAMES={
    '15m': {'bars':800,'hours':0.25},
    '1h': {'bars':1000,'hours':1.0},
    '4h': {'bars':1800,'hours':4.0},
}
RR=2.0
MIN_SCORE=2
COST_BPS=8.0
TARGET_PER_TF=40
LOSS_COOLDOWN_AFTER=2
LOSS_COOLDOWN_BARS=12


def _conn():
    c=sqlite3.connect(DB_PATH,timeout=20)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('''CREATE TABLE IF NOT EXISTS paper_trades_v52 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timeframe TEXT NOT NULL,
        signal_ts TEXT NOT NULL,
        opened_ts TEXT NOT NULL,
        closed_ts TEXT,
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
        note TEXT,
        UNIQUE(timeframe,signal_ts)
    )''')
    c.commit()
    return c


def set_enabled(enabled,chat_id=None):
    set_state('v52_enabled',bool(enabled))
    if chat_id is not None: set_state('v52_chat_id',int(chat_id))


def is_enabled():
    v=get_state('v52_enabled',None)
    if v is None:
        return bool(get_state('enabled',False))
    return bool(v)


def subscribed_chat_id():
    return get_state('v52_chat_id',get_state('chat_id',None))


def _pf(vals):
    if not vals: return 0.0
    a=np.asarray(vals,float); gp=float(a[a>0].sum()); gl=float(-a[a<0].sum())
    return gp/gl if gl>0 else (99.0 if gp>0 else 0.0)


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


def summary(timeframe=None):
    where=' WHERE timeframe=?' if timeframe else ''
    params=(timeframe,) if timeframe else ()
    with _conn() as c:
        rows=c.execute(f'SELECT * FROM paper_trades_v52{where} ORDER BY id',params).fetchall()
    closed=[r for r in rows if r['status']=='CLOSED' and r['pnl_r'] is not None]
    vals=[float(r['pnl_r']) for r in closed]
    return {
        'timeframe':timeframe or 'ALL','enabled':is_enabled(),'closed':len(closed),
        'open':sum(r['status']=='OPEN' for r in rows),'win_rate':100*sum(v>0 for v in vals)/len(vals) if vals else 0.0,
        'expectancy_r':float(np.mean(vals)) if vals else 0.0,'profit_factor':_pf(vals),
        'max_drawdown_r':_mdd(vals),'longest_losing_streak':_lls(vals),'equity_r':float(sum(vals)),
        'target_trades':TARGET_PER_TF,
    }


def summaries(): return {tf:summary(tf) for tf in TIMEFRAMES}


def recent_trades(limit=12):
    with _conn() as c:
        rows=c.execute('SELECT * FROM paper_trades_v52 ORDER BY id DESC LIMIT ?',(int(limit),)).fetchall()
    return [dict(r) for r in rows]


def _open_trade(tf):
    with _conn() as c:
        r=c.execute("SELECT * FROM paper_trades_v52 WHERE timeframe=? AND status='OPEN' ORDER BY id DESC LIMIT 1",(tf,)).fetchone()
    return dict(r) if r else None


def _recent_closed(tf,limit=20):
    with _conn() as c:
        rows=c.execute("SELECT * FROM paper_trades_v52 WHERE timeframe=? AND status='CLOSED' ORDER BY id DESC LIMIT ?",(tf,int(limit))).fetchall()
    return [dict(r) for r in rows]


def _can_open(tf,signal_ts):
    if _open_trade(tf): return False,'position already open on this timeframe'
    closed=_recent_closed(tf)
    if len(closed)>=2 and all(float(x.get('pnl_r') or 0)<0 for x in closed[:2]):
        last=get_state(f'v52_last_loss_{tf}',None)
        if last:
            elapsed=pd.Timestamp(signal_ts)-pd.Timestamp(last)
            cooldown=pd.Timedelta(hours=TIMEFRAMES[tf]['hours']*LOSS_COOLDOWN_BARS)
            if elapsed<cooldown: return False,f'loss_cooldown active ({LOSS_COOLDOWN_BARS} bars)'
    return True,''


def _cost_r(entry,atr):
    return (COST_BPS/10000.0)*float(entry)/float(atr) if entry and atr else 0.0


def _close_trade(trade,ts,price,gross_r,outcome):
    net=float(gross_r)-_cost_r(trade['entry'],trade['atr'])
    with _conn() as c:
        c.execute("UPDATE paper_trades_v52 SET closed_ts=?,status='CLOSED',pnl_r=?,exit_price=?,outcome=? WHERE id=?",
                  (str(ts),net,float(price),outcome,int(trade['id'])))
        c.commit()
    if net<0: set_state(f"v52_last_loss_{trade['timeframe']}",str(ts))
    return net


def _manage_open(tf,x):
    trade=_open_trade(tf)
    if not trade: return None
    newer=x[x.ts>pd.Timestamp(trade['opened_ts'])]
    for _,row in newer.iterrows():
        lo=float(row.low); hi=float(row.high)
        if lo<=trade['sl'] and hi>=trade['tp']:
            r=_close_trade(trade,row.ts,trade['sl'],-1.0,'SL_same_bar_conservative')
            return {'type':'CLOSED','timeframe':tf,'pnl_r':r,'outcome':'SL same candle','ts':str(row.ts)}
        if lo<=trade['sl']:
            r=_close_trade(trade,row.ts,trade['sl'],-1.0,'SL')
            return {'type':'CLOSED','timeframe':tf,'pnl_r':r,'outcome':'SL','ts':str(row.ts)}
        if hi>=trade['tp']:
            r=_close_trade(trade,row.ts,trade['tp'],RR,'TP')
            return {'type':'CLOSED','timeframe':tf,'pnl_r':r,'outcome':'TP','ts':str(row.ts)}
    return None


def _latest_closed_index(x): return len(x)-2


async def explain_timeframe(tf):
    cfg=TIMEFRAMES[tf]
    df=await fetch_backtest_candles('BTC',tf,cfg['bars'])
    x=prepare(df).reset_index(drop=True); i=_latest_closed_index(x)
    if i<210: return {'timeframe':tf,'ready':False,'reason':'insufficient history'}
    atrp=_atr_pct_series(x).iloc[210:i].dropna()
    if len(atrp)<250: return {'timeframe':tf,'ready':False,'reason':'ATR calibration history too short'}
    cut=float(atrp.quantile(.80)); row=x.iloc[i]; regime=classify_regime(x,i,cut); side,score=_range_signal(x,i)
    allowed,block=_can_open(tf,str(row.ts))
    checks={'engine_on':is_enabled(),'regime_ok':regime=='RANGE','side_ok':side=='LONG','score_ok':int(score)>=MIN_SCORE,'risk_ok':allowed}
    if not checks['engine_on']: reason='Engine OFF'
    elif not checks['regime_ok']: reason=f'Regime={regime}; need RANGE'
    elif not checks['side_ok']: reason=f'Trigger={side or "NONE"}; need LONG'
    elif not checks['score_ok']: reason=f'Score={int(score)}; need >= {MIN_SCORE}'
    elif not checks['risk_ok']: reason=block
    else: reason='ELIGIBLE'
    return {'timeframe':tf,'ready':all(checks.values()),'reason':reason,'signal_ts':str(row.ts),'close':float(row.close),
            'regime':regime,'side':side or 'NONE','score':int(score),'min_score':MIN_SCORE,'atr':float(row.atr),
            'atr_pct':float(row.atr)/float(row.close)*100,'hv_cut':cut,'checks':checks}


async def _tick_tf(tf):
    cfg=TIMEFRAMES[tf]
    df=await fetch_backtest_candles('BTC',tf,cfg['bars'])
    x=prepare(df).reset_index(drop=True); i=_latest_closed_index(x)
    if i<210: return []
    atrp=_atr_pct_series(x).iloc[210:i].dropna()
    if len(atrp)<250: return []
    cut=float(atrp.quantile(.80)); events=[]
    closed=_manage_open(tf,x)
    if closed: events.append(closed)
    row=x.iloc[i]; signal_ts=str(row.ts)
    with _conn() as c:
        exists=c.execute('SELECT id FROM paper_trades_v52 WHERE timeframe=? AND signal_ts=?',(tf,signal_ts)).fetchone()
    if exists: return events
    if classify_regime(x,i,cut)!='RANGE': return events
    side,score=_range_signal(x,i)
    if side!='LONG' or int(score)<MIN_SCORE: return events
    allowed,reason=_can_open(tf,signal_ts)
    if not allowed:
        key=f'v52_suppressed_{tf}'; last=get_state(key,{}) or {}
        if last.get('signal_ts')!=signal_ts or last.get('reason')!=reason:
            set_state(key,{'signal_ts':signal_ts,'reason':reason})
            events.append({'type':'SUPPRESSED','timeframe':tf,'signal_ts':signal_ts,'reason':reason})
        return events
    entry=float(row.close); atr=float(row.atr); tp=entry+RR*atr; sl=entry-atr
    with _conn() as c:
        c.execute('''INSERT INTO paper_trades_v52(timeframe,signal_ts,opened_ts,entry,tp,sl,atr,atr_pct,hv_cut,score,cost_bps,status,note)
                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                  (tf,signal_ts,signal_ts,entry,tp,sl,atr,atr/entry*100,cut,int(score),COST_BPS,'OPEN','V5.2 MTF forward paper'))
        c.commit()
    events.append({'type':'OPENED','timeframe':tf,'signal_ts':signal_ts,'entry':entry,'tp':tp,'sl':sl,'atr':atr,'atr_pct':atr/entry*100,'hv_cut':cut,'score':int(score)})
    return events


async def paper_tick_all():
    if not is_enabled(): return []
    events=[]
    for tf in TIMEFRAMES:
        try:
            events.extend(await _tick_tf(tf))
        except Exception as e:
            events.append({'type':'ERROR','timeframe':tf,'reason':str(e)})
    set_state('v52_last_tick_ts',str(pd.Timestamp.utcnow()))
    return events
