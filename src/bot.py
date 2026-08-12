import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from .service import analyze_symbol, format_report
from .market import fetch_backtest_candles
from .backtest import walk_forward
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
    await update.message.reply_text('🤖 Crypto Multi-Agent Analyst V4.1 جاهز.\n/analyze BTC\n/scan\n/live\n/backtest BTC 1h\n/help')

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('/analyze BTC — تحليل 6 فريمات + Agents + Order Flow\n/scan — فحص قائمة العملات\n/live — حالة WebSocket والبيانات اللحظية\n/backtest BTC 1h — Walk-forward تاريخي موسع + Calibration\nالإنذارات الدورية تعمل عند ضبط ADMIN_CHAT_ID.')

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
        await update.message.reply_text('الفريمات: 5m / 15m / 1h / 4h / 1d / 1w')
        return
    cfg=BACKTEST_CFG[timeframe]
    msg=await update.message.reply_text(f'🧪 V4.1 Backtest موسع {symbol} {timeframe}... قد يستغرق قليلاً')
    try:
        df=await fetch_backtest_candles(symbol,timeframe,cfg['bars'])
        min_history=min(210,max(80,len(df)//3))
        bt=walk_forward(df,timeframe,horizon=cfg['horizon'],min_history=min_history,step=cfg['step'])
        start=bt.start[:10] if bt.start else '?'; end=bt.end[:10] if bt.end else '?'
        text=(
            f'🧪 V4.1 Backtest {symbol} — {timeframe}\n'
            f'الفترة: {start} → {end}\n'
            f'Candles: {bt.bars} | Signals: {bt.samples}\n'
            f'Forward horizon: {bt.horizon_bars} bars\n\n'
            f'Accuracy الكلية: {bt.accuracy:.1f}%\n'
            f'LONG: {bt.bullish_accuracy:.1f}% (n={bt.long_samples})\n'
            f'SHORT: {bt.bearish_accuracy:.1f}% (n={bt.short_samples})\n'
            f'Brier-like: {bt.brier_like:.4f}\n'
            f'ECE: {bt.ece:.4f}\n\n'
            + _bins_text('Calibration الكلية',bt.calibration) + '\n\n'
            + _bins_text('LONG calibration',bt.long_calibration) + '\n\n'
            + _bins_text('SHORT calibration',bt.short_calibration) + '\n\n'
            + '⚠️ النتيجة Walk-forward على البيانات المتاحة من OKX وليست ضماناً للأداء المستقبلي. نحتاج Out-of-sample قبل اعتماد أي نسبة كاحتمال حقيقي.'
        )
        await msg.edit_text(text[:4000])
    except Exception as e:
        await msg.edit_text(f'❌ خطأ Backtest V4.1: {e}')

async def live_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    hub=get_hub()
    if not hub:
        await update.message.reply_text('🔴 محرك WebSocket غير مهيأ.')
        return
    lines=[f'📡 WebSocket: {"🟢 متصل" if hub.connected else "🔴 غير متصل"}']
    if hub.last_error: lines.append(f'آخر خطأ: {hub.last_error}')
    for s in WATCHLIST:
        x=hub.snapshot(s) or {}
        if not x.get('ts'):
            lines.append(f'{s}: في انتظار أول Snapshot...')
            continue
        lines.append(f'{s}: {x.get("last",0):,.4f} | Book {x.get("imbalance",0):+.2f} | Delta {x.get("trade_delta",0):+.2f} | Spread {x.get("spread_bps",0):.2f}bps')
    await update.message.reply_text('\n'.join(lines))

async def post_init(app):
    hub=configure_hub(WATCHLIST)
    app.create_task(hub.run(), name='okx-realtime-hub')

async def alert_job(context: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_CHAT_ID: return
    for s in WATCHLIST:
        try:
            rs,b,m=await analyze_symbol(s)
            if b.entry_quality >= THRESH and b.direction!='محايد':
                side='LONG' if b.direction=='صاعد' else 'SHORT'
                if should_send_alert(s,side,b.timeframe,b.entry_quality):
                    await context.bot.send_message(chat_id=ADMIN_CHAT_ID,text='🚨 إشارة جديدة/متغيرة\n'+format_report(s,rs,b,m))
        except Exception:
            pass

def main():
    if not TOKEN: raise SystemExit('Set TELEGRAM_BOT_TOKEN in .env')
    app=ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler('start',start))
    app.add_handler(CommandHandler('help',help_cmd))
    app.add_handler(CommandHandler('analyze',analyze_cmd))
    app.add_handler(CommandHandler('scan',scan_cmd))
    app.add_handler(CommandHandler('live',live_cmd))
    app.add_handler(CommandHandler('backtest',backtest_cmd))
    app.job_queue.run_repeating(alert_job, interval=300, first=20)
    app.run_polling(drop_pending_updates=True)

if __name__=='__main__': main()
