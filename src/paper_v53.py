import sqlite3
import numpy as np
import pandas as pd

from .agents import prepare
from .market import fetch_backtest_candles
from .signal_v45 import _range_signal, _trend_signal
from .signal_v46 import classify_regime, _atr_pct_series
from .paper_v50 import DB_PATH, get_state, set_state

TIMEFRAMES={
    '15m': {'bars':800,'hours':0.25},
    '1h': {'bars':1000,'hours':1.0},
    '4h': {'bars':1800,'hours':4.0},
}
REGIMES=('RANGE','TREND')
RANGE_RR=2.0
TREND_RR=1.5
MIN_SCORE=2
COST_BPS=8.0
TARGET_PER_BUCKET=40
LOSS_COOLDOWN_BARS=12


def _conn():
    c=sqlite3.connect(DB_PATH,timeout=20)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('''CREATE TABLE IF NOT EXISTS paper_trades_v53 (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timeframe TEXT NOT NULL,
        regime TEXT NOT NULL,
        side TEXT NOT NULL,
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
        rr REAL NOT NULL,
        cost_bps REAL NOT NULL,
        status TEXT NOT NULL,
        pnl_r REAL,
        exit_price REAL,
        outcome TEXT,
        note TEXT,
        UNIQUE(timeframe,regime,signal_ts)
    )''')
    c.commit(); return c


def set_enabled(enabled,chat_id=None):
    set_state('v53_enabled',bool(enabled))
    if chat_id is not None: set_state('v53_chat_id',int(chat_id))


def is_enabled():
    v=get_state('v53_enabled',None)
    if v is None: return bool(get_state('v52_enabled',get_state('enabled',False)))
    return bool(v)


def subscribed_chat_id(): return get_state('v53_chat_id',get_state('v52_chat_id',get_state('chat_id',None)))


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


def summary(tf,regime):
    with _conn() as c:
        rows=c.execute('SELECT * FROM paper_trades_v53 WHERE timeframe=? AND regime=? ORDER BY id',(tf,regime)).fetchall()
    closed=[r for r in rows if r['status']=='CLOSED' and r['pnl_r'] is not None]
    vals=[float(r['pnl_r']) for r in closed]
    return {'timeframe':tf,'regime':regime,'enabled':is_enabled(),'closed':len(closed),'open':sum(r['status']=='OPEN' for r in rows),
            'win_rate':100*sum(v>0 for v in vals)/len(vals) if vals else 0.0,'expectancy_r':float(np.mean(vals)) if vals else 0.0,
            'profit_factor':_pf(vals),'max_drawdown_r':_mdd(vals),'longest_losing_streak':_lls(vals),'equity_r':float(sum(vals)),
            'target_trades':TARGET_PER_BUCKET}


def summaries(): return {(tf,r):summary(tf,r) for tf in TIMEFRAMES for r in REGIMES}


def recent_trades(limit=16):
    with _conn() as c: rows=c.execute('SELECT * FROM paper_trades_v53 ORDER BY id DESC LIMIT ?',(int(limit),)).fetchall()
    return [dict(r) for r in rows]


def _open_trade(tf,regime):
    with _conn() as c:
        r=c.execute("SELECT * FROM paper_trades_v53 WHERE timeframe=? AND regime=? AND status='OPEN' ORDER BY id DESC LIMIT 1",(tf,regime)).fetchone()
    return dict(r) if r else None


def _recent_closed(tf,regime,limit=20):
    with _conn() as c:
        rows=c.execute("SELECT * FROM paper_trades_v53 WHERE timeframe=? AND regime=? AND status='CLOSED' ORDER BY id DESC LIMIT ?",(tf,regime,int(limit))).fetchall()
    return [dict(r) for r in rows]


def _can_open(tf,regime,signal_ts):
    if _open_trade(tf,regime): return False,'position already open in this bucket'
    closed=_recent_closed(tf,regime)
    if len(closed)>=2 and all(float(x.get('pnl_r') or 0)<0 for x in closed[:2]):
        last=get_state(f'v53_last_loss_{tf}_{regime}',None)
        if last:
            elapsed=pd.Timestamp(signal_ts)-pd.Timestamp(last)
            cd=pd.Timedelta(hours=TIMEFRAMES[tf]['hours']*LOSS_COOLDOWN_BARS)
            if elapsed<cd: return False,f'loss_cooldown active ({LOSS_COOLDOWN_BARS} bars)'
    return True,''


def _cost_r(entry,atr): return (COST_BPS/10000.0)*float(entry)/float(atr) if entry and atr else 0.0


def _close_trade(trade,ts,price,gross_r,outcome):
    net=float(gross_r)-_cost_r(trade['entry'],trade['atr'])
    with _conn() as c:
        c.execute("UPDATE paper_trades_v53 SET closed_ts=?,status='CLOSED',pnl_r=?,exit_price=?,outcome=? WHERE id=?",
                  (str(ts),net,float(price),outcome,int(trade['id']))); c.commit()
    if net<0: set_state(f"v53_last_loss_{trade['timeframe']}_{trade['regime']}",str(ts))
    return net


def _manage_open(tf,regime,x):
    trade=_open_trade(tf,regime)
    if not trade: return None
    newer=x[x.ts>pd.Timestamp(trade['opened_ts'])]
    for _,row in newer.iterrows():
        lo=float(row.low); hi=float(row.high); side=trade['side']; sl=float(trade['sl']); tp=float(trade['tp'])
        sl_hit=(lo<=sl) if side=='LONG' else (hi>=sl)
        tp_hit=(hi>=tp) if side=='LONG' else (lo<=tp)
        if sl_hit and tp_hit:
            r=_close_trade(trade,row.ts,sl,-1.0,'SL_same_bar_conservative')
            return {'type':'CLOSED','timeframe':tf,'regime':regime,'side':side,'pnl_r':r,'outcome':'SL same candle','ts':str(row.ts)}
        if sl_hit:
            r=_close_trade(trade,row.ts,sl,-1.0,'SL')
            return {'type':'CLOSED','timeframe':tf,'regime':regime,'side':side,'pnl_r':r,'outcome':'SL','ts':str(row.ts)}
        if tp_hit:
            r=_close_trade(trade,row.ts,tp,float(trade['rr']),'TP')
            return {'type':'CLOSED','timeframe':tf,'regime':regime,'side':side,'pnl_r':r,'outcome':'TP','ts':str(row.ts)}
    return None


def _latest_closed_index(x): return len(x)-2


def _signal(x,i,regime):
    if regime=='RANGE':
        side,score=_range_signal(x,i)
        if side!='LONG': return 'WAIT',int(score)
        return side,int(score)
    side,score=_trend_signal(x,i)
    return side,int(score)


def _rr(regime): return RANGE_RR if regime=='RANGE' else TREND_RR


async def explain_timeframe(tf):
    cfg=TIMEFRAMES[tf]; df=await fetch_backtest_candles('BTC',tf,cfg['bars']); x=prepare(df).reset_index(drop=True); i=_latest_closed_index(x)
    if i<210: return {'timeframe':tf,'reason':'insufficient history'}
    atrp=_atr_pct_series(x).iloc[210:i].dropna()
    if len(atrp)<250: return {'timeframe':tf,'reason':'ATR calibration history too short'}
    cut=float(atrp.quantile(.80)); row=x.iloc[i]; actual=classify_regime(x,i,cut)
    out={'timeframe':tf,'signal_ts':str(row.ts),'close':float(row.close),'actual_regime':actual,'atr':float(row.atr),'atr_pct':float(row.atr)/float(row.close)*100,'hv_cut':cut,'buckets':[]}
    for regime in REGIMES:
        side,score=_signal(x,i,regime); allowed,block=_can_open(tf,regime,str(row.ts))
        regime_ok=actual==regime; side_ok=(side=='LONG') if regime=='RANGE' else side in ('LONG','SHORT')
        score_ok=score>=MIN_SCORE; ready=is_enabled() and regime_ok and side_ok and score_ok and allowed
        if not is_enabled(): reason='Engine OFF'
        elif not regime_ok: reason=f'current={actual}; need {regime}'
        elif not side_ok: reason='no valid trigger'
        elif not score_ok: reason=f'Score={score}; need >= {MIN_SCORE}'
        elif not allowed: reason=block
        else: reason='ELIGIBLE'
        out['buckets'].append({'regime':regime,'side':side,'score':score,'rr':_rr(regime),'ready':ready,'reason':reason,'risk_ok':allowed})
    return out


async def _tick_tf(tf):
    cfg=TIMEFRAMES[tf]; df=await fetch_backtest_candles('BTC',tf,cfg['bars']); x=prepare(df).reset_index(drop=True); i=_latest_closed_index(x)
    if i<210: return []
    atrp=_atr_pct_series(x).iloc[210:i].dropna()
    if len(atrp)<250: return []
    cut=float(atrp.quantile(.80)); actual=classify_regime(x,i,cut); row=x.iloc[i]; signal_ts=str(row.ts); events=[]
    for regime in REGIMES:
        closed=_manage_open(tf,regime,x)
        if closed: events.append(closed)
        with _conn() as c:
            exists=c.execute('SELECT id FROM paper_trades_v53 WHERE timeframe=? AND regime=? AND signal_ts=?',(tf,regime,signal_ts)).fetchone()
        if exists or actual!=regime: continue
        side,score=_signal(x,i,regime)
        valid_side=(side=='LONG') if regime=='RANGE' else side in ('LONG','SHORT')
        if not valid_side or score<MIN_SCORE: continue
        allowed,reason=_can_open(tf,regime,signal_ts)
        if not allowed:
            key=f'v53_suppressed_{tf}_{regime}'; last=get_state(key,{}) or {}
            if last.get('signal_ts')!=signal_ts or last.get('reason')!=reason:
                set_state(key,{'signal_ts':signal_ts,'reason':reason}); events.append({'type':'SUPPRESSED','timeframe':tf,'regime':regime,'signal_ts':signal_ts,'reason':reason})
            continue
        entry=float(row.close); atr=float(row.atr); rr=_rr(regime)
        if side=='LONG': tp=entry+rr*atr; sl=entry-atr
        else: tp=entry-rr*atr; sl=entry+atr
        with _conn() as c:
            c.execute('''INSERT INTO paper_trades_v53(timeframe,regime,side,signal_ts,opened_ts,entry,tp,sl,atr,atr_pct,hv_cut,score,rr,cost_bps,status,note)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                      (tf,regime,side,signal_ts,signal_ts,entry,tp,sl,atr,atr/entry*100,cut,score,rr,COST_BPS,'OPEN','V5.3 dual-regime forward paper')); c.commit()
        events.append({'type':'OPENED','timeframe':tf,'regime':regime,'side':side,'signal_ts':signal_ts,'entry':entry,'tp':tp,'sl':sl,'score':score,'rr':rr,'atr_pct':atr/entry*100})
    return events


async def paper_tick_all():
    if not is_enabled(): return []
    events=[]
    for tf in TIMEFRAMES:
        try: events.extend(await _tick_tf(tf))
        except Exception as e: events.append({'type':'ERROR','timeframe':tf,'reason':str(e)})
    set_state('v53_last_tick_ts',str(pd.Timestamp.utcnow())); return events
