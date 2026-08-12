import os
import asyncio
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from .service import analyze_symbol, format_report
from .market import fetch_backtest_candles
from .backtest import walk_forward
from .optimizer import optimize_oos
from .signal_v43 import validate_v43
from .signal_v44 import validate_v44
from .signal_v45 import validate_v45
from .realtime import configure_hub, get_hub
from .storage import should_send_alert

load_dotenv()
TOKEN=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
WATCHLIST=[x.strip().upper() for x in os.getenv('WATCHLIST','BTC,ETH').split(',') if x.strip()]
THRESH=float(os.getenv('ALERT_THRESHOLD','72'))
ADMIN_CHAT_ID=os.getenv('ADMIN_CHAT_ID','').strip()

BACKTEST_CFG={
    '5m': {'bars':3000,'horizon':6,'step':6},
    '15m':{'bars':3000,'horizon':4,'step':5},
    '1h': {'bars':2160,'horizon':3,'step':3},
    '4h': {'bars':720,'horizon':2,'step':2},
    '1d': {'bars':300,'horizon':2,'step':1},
    '1w': {'bars':300,'horizon':1,'step':1},
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('🤖 Crypto Multi-Agent Analyst V4.5.1 جاهز.\n/analyze BTC\n/scan\n/live\n/validate45 BTC\n/help')

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('/analyze BTC — تحليل 6 فريمات + Agents + Order Flow\n/scan — فحص قائمة العملات\n/live — حالة WebSocket\n/backtest BTC 1h — Backtest تقليدي\n/validate44 BTC 1h — Rolling OOS + Fees/Slippage\n/validate45 BTC — V4.5.1 يفحص 15m/1h/4h بشكل متسلسل لتجنب Rate Limit')

async def analyze_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol=(context.args[0] if context.args else 'BTC').upper().replace('USDT','').replace('-','')
    msg=await update.message.reply_text(f'⏳ أجمع وأحلل {symbol}...')
    try:
        results,best,metrics=await analyze_symbol(symbol)
        await msg.edit_text(format_report(symbol,results,best,metrics))
    except Exception as e:
        await msg.edit_text(f'❌ خطأ أثناء التحليل: {e}')

async def scan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    out=['🔎 أفضل الإشارات:']
    for s in WATCHLIST:
        try:
            _,b,_=await analyze_symbol(s)
            side='LONG' if b.direction=='صاعد' else ('SHORT' if b.direction=='هابط' else 'WAIT')
            out.append(f'{s}: {side} | {b.timeframe} | جودة {b.entry_quality:.0f}%')
        except Exception:
            out.append(f'{s}: error')
    await update.message.reply_text('\n'.join(out))

async def backtest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol=(context.args[0] if context.args else 'BTC').upper().replace('USDT','').replace('-','')
    timeframe=(context.args[1] if len(context.args)>1 else '1h').lower()
    if timeframe not in BACKTEST_CFG:
        await update.message.reply_text('الفريمات: 5m / 15m / 1h / 4h / 1d / 1w'); return
    cfg=BACKTEST_CFG[timeframe]
    msg=await update.message.reply_text(f'🧪 Backtest {symbol} {timeframe}...')
    try:
        df=await fetch_backtest_candles(symbol,timeframe,cfg['bars'])
        min_history=min(210,max(80,len(df)//3))
        bt=walk_forward(df,timeframe,horizon=cfg['horizon'],min_history=min_history,step=cfg['step'])
        await msg.edit_text(f'🧪 Backtest {symbol} — {timeframe}\nCandles: {bt.bars} | Signals: {bt.samples}\nAccuracy: {bt.accuracy:.1f}%\nLONG: {bt.bullish_accuracy:.1f}%\nSHORT: {bt.bearish_accuracy:.1f}%\n⚠️ Signal Scores فقط.')
    except Exception as e: await msg.edit_text(f'❌ خطأ Backtest: {e}')

async def validate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol=(context.args[0] if context.args else 'BTC').upper().replace('USDT','').replace('-','')
    timeframe=(context.args[1] if len(context.args)>1 else '1h').lower()
    if timeframe not in BACKTEST_CFG: await update.message.reply_text('الفريمات غير صحيحة'); return
    cfg=BACKTEST_CFG[timeframe]
    msg=await update.message.reply_text(f'🧠 V4.2 {symbol} {timeframe}...')
    try:
        df=await fetch_backtest_candles(symbol,timeframe,cfg['bars'])
        vr=optimize_oos(df,symbol,timeframe,horizon=cfg['horizon'],min_history=min(210,max(80,len(df)//3)),step=cfg['step'])
        await msg.edit_text(f'V4.2 {symbol} {timeframe}\nStatus: {vr.status}\nTrain: {vr.train_accuracy:.1f}%\nOOS: {vr.test_accuracy:.1f}%')
    except Exception as e: await msg.edit_text(f'❌ {e}')

async def validate43_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol=(context.args[0] if context.args else 'BTC').upper().replace('USDT','').replace('-','')
    timeframe=(context.args[1] if len(context.args)>1 else '1h').lower()
    if timeframe not in BACKTEST_CFG: await update.message.reply_text('الفريمات غير صحيحة'); return
    cfg=BACKTEST_CFG[timeframe]
    msg=await update.message.reply_text(f'🧪 V4.3 {symbol} {timeframe}...')
    try:
        df=await fetch_backtest_candles(symbol,timeframe,max(cfg['bars'],2160 if timeframe=='1h' else cfg['bars']))
        vr=validate_v43(df,symbol,timeframe)
        await msg.edit_text(f'V4.3 {symbol} {timeframe}\nStatus: {vr.status}\nOOS trades: {vr.test_trades}\nWR: {vr.test_win_rate:.1f}%')
    except Exception as e: await msg.edit_text(f'❌ {e}')

async def validate44_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol=(context.args[0] if context.args else 'BTC').upper().replace('USDT','').replace('-','')
    timeframe=(context.args[1] if len(context.args)>1 else '1h').lower()
    if timeframe not in BACKTEST_CFG: await update.message.reply_text('الفريمات غير صحيحة'); return
    cfg=BACKTEST_CFG[timeframe]
    msg=await update.message.reply_text(f'🧪 V4.4 {symbol} {timeframe}...')
    try:
        df=await fetch_backtest_candles(symbol,timeframe,max(cfg['bars'],2160 if timeframe=='1h' else cfg['bars']))
        vr=validate_v44(df,symbol,timeframe,fee_slippage_bps=8.0)
        await msg.edit_text(f'V4.4 {symbol} {timeframe}\nStatus: {vr.status}\nTrades: {vr.total_trades}\nWR: {vr.win_rate:.1f}%\nEV: {vr.expectancy_r:+.3f}R/trade\nLONG EV: {vr.long_expectancy_r:+.3f}R\nSHORT EV: {vr.short_expectancy_r:+.3f}R')
    except Exception as e: await msg.edit_text(f'❌ {e}')

async def validate45_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol=(context.args[0] if context.args else 'BTC').upper().replace('USDT','').replace('-','')
    msg=await update.message.reply_text(f'🧪 V4.5.1 Regime scan {symbol}: 15m → 1h → 4h... قد يستغرق 1–2 دقيقة')
    try:
        # Smaller but still useful samples; fetched strictly sequentially to protect OKX IP rate limits.
        tfs={'15m':1600,'1h':1200,'4h':720}
        frames={}
        for tf,bars in tfs.items():
            frames[tf]=await fetch_backtest_candles(symbol,tf,bars)
            await asyncio.sleep(1.5)
        vr=validate_v45(symbol,frames,fee_slippage_bps=8.0)
        status='✅ PASS' if vr.status=='PASS' else '⛔ NO TRADE'
        rows=[]
        ranked=sorted(vr.buckets,key=lambda b:(b['status']=='PASS',b['expectancy_r'],b['trades']),reverse=True)
        for b in ranked[:10]:
            flag='✅' if b['status']=='PASS' else '•'
            rows.append(f"{flag} {b['timeframe']} | {b['regime']} | {b['side']} | n={b['trades']} | WR {b['win_rate']:.1f}% | EV {b['expectancy_r']:+.3f}R | folds+ {b['positive_folds']}/{b['folds']} | RR {b['rr']:.2f}")
        best=(f"أفضل Bucket مثبت: {vr.best_timeframe} / {vr.best_regime} / {vr.best_side} | EV {vr.best_expectancy_r:+.3f}R" if vr.status=='PASS' else 'لا يوجد Bucket يحقق شروط PASS حالياً.')
        text=(f'🧪 V4.5.1 Regime-Specialized OOS {symbol}\nStatus: {status}\nCosts: {vr.fee_slippage_bps:.1f} bps round-trip\n{best}\n\nTop buckets:\n'+'\n'.join(rows)+"\n\nPASS يحتاج Edge صافي ≥ +0.05R، عدد صفقات كافٍ، ونتيجة موجبة في ≥2 نوافذ OOS مستقلة.")
        await msg.edit_text(text[:4000])
    except Exception as e:
        await msg.edit_text(f'❌ خطأ V4.5.1: {e}')

async def live_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    hub=get_hub()
    if not hub: await update.message.reply_text('🔴 محرك WebSocket غير مهيأ.'); return
    lines=[f'📡 WebSocket: {"🟢 متصل" if hub.connected else "🔴 غير متصل"}']
    if hub.last_error: lines.append(f'آخر خطأ: {hub.last_error}')
    for s in WATCHLIST:
        x=hub.snapshot(s) or {}
        if not x.get('ts'): lines.append(f'{s}: في انتظار أول Snapshot...'); continue
        lines.append(f'{s}: {x.get("last",0):,.4f} | Book {x.get("imbalance",0):+.2f} | Delta {x.get("trade_delta",0):+.2f} | Spread {x.get("spread_bps",0):.2f}bps')
    await update.message.reply_text('\n'.join(lines))

async def post_init(app):
    hub=configure_hub(WATCHLIST); app.create_task(hub.run(), name='okx-realtime-hub')

async def alert_job(context: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_CHAT_ID: return
    for s in WATCHLIST:
        try:
            rs,b,m=await analyze_symbol(s)
            if b.entry_quality >= THRESH and b.direction!='محايد':
                side='LONG' if b.direction=='صاعد' else 'SHORT'
                if should_send_alert(s,side,b.timeframe,b.entry_quality):
                    await context.bot.send_message(chat_id=ADMIN_CHAT_ID,text='🚨 إشارة جديدة/متغيرة\n'+format_report(s,rs,b,m))
        except Exception: pass

def main():
    if not TOKEN: raise SystemExit('Set TELEGRAM_BOT_TOKEN in .env')
    app=ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    for name,fn in [('start',start),('help',help_cmd),('analyze',analyze_cmd),('scan',scan_cmd),('live',live_cmd),('backtest',backtest_cmd),('validate',validate_cmd),('validate43',validate43_cmd),('validate44',validate44_cmd),('validate45',validate45_cmd)]:
        app.add_handler(CommandHandler(name,fn))
    app.job_queue.run_repeating(alert_job, interval=300, first=20); app.run_polling(drop_pending_updates=True)

if __name__=='__main__': main()
