import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from .service import analyze_symbol, format_report
from .market import fetch_backtest_candles
from .backtest import walk_forward
from .optimizer import optimize_oos
from .signal_v43 import validate_v43
from .signal_v44 import validate_v44
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
    await update.message.reply_text('🤖 Crypto Multi-Agent Analyst V4.4 جاهز.\n/analyze BTC\n/scan\n/live\n/backtest BTC 1h\n/validate44 BTC 1h\n/help')

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('/analyze BTC — تحليل 6 فريمات + Agents + Order Flow\n/scan — فحص قائمة العملات\n/live — حالة WebSocket والبيانات اللحظية\n/backtest BTC 1h — Walk-forward تاريخي موسع + Calibration\n/validate BTC 1h — V4.2 أوزان + Out-of-Sample\n/validate43 BTC 1h — V4.3 Layered + ATR barriers\n/validate44 BTC 1h — V4.4 Rolling OOS + LONG/SHORT منفصل + Fees/Slippage\nالإنذارات الدورية تعمل عند ضبط ADMIN_CHAT_ID.')

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
            rs,b,m=await analyze_symbol(s)
            side='LONG' if b.direction=='صاعد' else ('SHORT' if b.direction=='هابط' else 'WAIT')
            out.append(f'{s}: {side} | {b.timeframe} | جودة {b.entry_quality:.0f}%')
        except Exception:
            out.append(f'{s}: error')
    await update.message.reply_text('\n'.join(out))


def _bins_text(title,bins):
    if not bins:
        return f'{title}: لا توجد عينات كافية'
    lines=[f'{title}:']
    for b in bins:
        lines.append(f"• {b['low']}-{b['high']}%: توقع {b['predicted_pct']:.1f}% / تحقق {b['realized_pct']:.1f}% (n={b['samples']})")
    return '\n'.join(lines)

async def backtest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol=(context.args[0] if context.args else 'BTC').upper().replace('USDT','').replace('-','')
    timeframe=(context.args[1] if len(context.args)>1 else '1h').lower()
    if timeframe not in BACKTEST_CFG:
        await update.message.reply_text('الفريمات: 5m / 15m / 1h / 4h / 1d / 1w'); return
    cfg=BACKTEST_CFG[timeframe]
    msg=await update.message.reply_text(f'🧪 V4.4 Backtest موسع {symbol} {timeframe}...')
    try:
        df=await fetch_backtest_candles(symbol,timeframe,cfg['bars'])
        min_history=min(210,max(80,len(df)//3))
        bt=walk_forward(df,timeframe,horizon=cfg['horizon'],min_history=min_history,step=cfg['step'])
        start=bt.start[:10] if bt.start else '?'; end=bt.end[:10] if bt.end else '?'
        text=(f'🧪 Backtest {symbol} — {timeframe}\nالفترة: {start} → {end}\nCandles: {bt.bars} | Signals: {bt.samples}\n\nAccuracy: {bt.accuracy:.1f}%\nLONG: {bt.bullish_accuracy:.1f}% (n={bt.long_samples})\nSHORT: {bt.bearish_accuracy:.1f}% (n={bt.short_samples})\nECE: {bt.ece:.4f}\n\n⚠️ Signal Scores وليست احتمالات مضمونة.')
        await msg.edit_text(text[:4000])
    except Exception as e: await msg.edit_text(f'❌ خطأ Backtest: {e}')

async def validate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol=(context.args[0] if context.args else 'BTC').upper().replace('USDT','').replace('-','')
    timeframe=(context.args[1] if len(context.args)>1 else '1h').lower()
    if timeframe not in BACKTEST_CFG: await update.message.reply_text('الفريمات: 5m / 15m / 1h / 4h / 1d / 1w'); return
    cfg=BACKTEST_CFG[timeframe]
    msg=await update.message.reply_text(f'🧠 V4.2 Optimization + OOS {symbol} {timeframe}...')
    try:
        df=await fetch_backtest_candles(symbol,timeframe,cfg['bars'])
        min_history=min(210,max(80,len(df)//3))
        vr=optimize_oos(df,symbol,timeframe,horizon=cfg['horizon'],min_history=min_history,step=cfg['step'])
        status='✅ PASS' if vr.status=='PASS' else '⛔ NO TRADE'
        await msg.edit_text(f'🧠 V4.2 {symbol} {timeframe}\nStatus: {status}\nTrain: {vr.train_accuracy:.1f}%\nOOS: {vr.test_accuracy:.1f}%\nLONG: {vr.test_long_accuracy:.1f}%\nSHORT: {vr.test_short_accuracy:.1f}%')
    except Exception as e: await msg.edit_text(f'❌ خطأ V4.2: {e}')

async def validate43_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol=(context.args[0] if context.args else 'BTC').upper().replace('USDT','').replace('-','')
    timeframe=(context.args[1] if len(context.args)>1 else '1h').lower()
    if timeframe not in BACKTEST_CFG: await update.message.reply_text('الفريمات: 5m / 15m / 1h / 4h / 1d / 1w'); return
    cfg=BACKTEST_CFG[timeframe]; bars=max(cfg['bars'],2160 if timeframe=='1h' else cfg['bars'])
    msg=await update.message.reply_text(f'🧪 V4.3 Layered + ATR OOS {symbol} {timeframe}...')
    try:
        df=await fetch_backtest_candles(symbol,timeframe,bars); vr=validate_v43(df,symbol,timeframe)
        status='✅ PASS' if vr.status=='PASS' else '⛔ NO TRADE'
        rr=vr.tp_atr/vr.sl_atr if vr.sl_atr else 0
        await msg.edit_text(f'🧪 V4.3 {symbol} — {timeframe}\nStatus: {status}\nOOS trades: {vr.test_trades}\nWin rate: {vr.test_win_rate:.1f}%\nLONG: {vr.test_long_win_rate:.1f}% (n={vr.test_long_trades})\nSHORT: {vr.test_short_win_rate:.1f}% (n={vr.test_short_trades})\nR:R≈{rr:.2f}\nCoverage: {vr.coverage_pct:.1f}%')
    except Exception as e: await msg.edit_text(f'❌ خطأ V4.3: {e}')

async def validate44_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol=(context.args[0] if context.args else 'BTC').upper().replace('USDT','').replace('-','')
    timeframe=(context.args[1] if len(context.args)>1 else '1h').lower()
    if timeframe not in BACKTEST_CFG: await update.message.reply_text('الفريمات: 5m / 15m / 1h / 4h / 1d / 1w'); return
    cfg=BACKTEST_CFG[timeframe]; bars=max(cfg['bars'],2160 if timeframe=='1h' else cfg['bars'])
    msg=await update.message.reply_text(f'🧪 V4.4 Robust Rolling OOS {symbol} {timeframe}...')
    try:
        df=await fetch_backtest_candles(symbol,timeframe,bars)
        vr=validate_v44(df,symbol,timeframe,fee_slippage_bps=8.0)
        status={'PASS_BOTH':'✅ PASS BOTH','PASS_LONG':'✅ PASS LONG','PASS_SHORT':'✅ PASS SHORT','NO_TRADE':'⛔ NO TRADE','INSUFFICIENT_DATA':'⚠️ DATA غير كافية'}.get(vr.status,vr.status)
        folds='\n'.join(f"• Fold {f['fold']} {f['side']}: RR {f['rr']:.2f} | n={f['trades']} | WR {f['win_rate']:.1f}% | EV {f['expectancy_r']:+.3f}R" for f in vr.fold_details)
        text=(f'🧪 V4.4 Robust OOS {symbol} — {timeframe}\nStatus: {status}\n\nRolling folds: {vr.folds}\nCosts: {vr.fee_slippage_bps:.1f} bps round-trip\nTotal OOS trades: {vr.total_trades}\nWin rate: {vr.win_rate:.1f}%\nNet expectancy: {vr.expectancy_r:+.3f}R/trade\n\nLONG: n={vr.long_trades} | WR {vr.long_win_rate:.1f}% | EV {vr.long_expectancy_r:+.3f}R | positive folds {vr.long_positive_folds}/{vr.folds} | selected RR≈{vr.selected_long_rr:.2f}\nSHORT: n={vr.short_trades} | WR {vr.short_win_rate:.1f}% | EV {vr.short_expectancy_r:+.3f}R | positive folds {vr.short_positive_folds}/{vr.folds} | selected RR≈{vr.selected_short_rr:.2f}\n\nPer-fold:\n{folds}\n\nPASS يحتاج ≥25 صفقة للاتجاه، EV صافي ≥ +0.05R، ونتيجة موجبة في ≥2 نوافذ مستقلة.')
        await msg.edit_text(text[:4000])
    except Exception as e: await msg.edit_text(f'❌ خطأ V4.4 Robust OOS: {e}')

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
    app.add_handler(CommandHandler('start',start)); app.add_handler(CommandHandler('help',help_cmd))
    app.add_handler(CommandHandler('analyze',analyze_cmd)); app.add_handler(CommandHandler('scan',scan_cmd)); app.add_handler(CommandHandler('live',live_cmd))
    app.add_handler(CommandHandler('backtest',backtest_cmd)); app.add_handler(CommandHandler('validate',validate_cmd)); app.add_handler(CommandHandler('validate43',validate43_cmd)); app.add_handler(CommandHandler('validate44',validate44_cmd))
    app.job_queue.run_repeating(alert_job, interval=300, first=20); app.run_polling(drop_pending_updates=True)

if __name__=='__main__': main()
