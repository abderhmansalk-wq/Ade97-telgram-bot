import os
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from .service import analyze_symbol, format_report
from .market import fetch_candles
from .backtest import walk_forward
from .realtime import configure_hub, get_hub
from .storage import should_send_alert

load_dotenv()
TOKEN=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
WATCHLIST=[x.strip().upper() for x in os.getenv('WATCHLIST','BTC,ETH').split(',') if x.strip()]
THRESH=float(os.getenv('ALERT_THRESHOLD','72'))
ADMIN_CHAT_ID=os.getenv('ADMIN_CHAT_ID','').strip()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('🤖 Crypto Multi-Agent Analyst V4 جاهز.\n/analyze BTC\n/scan\n/live\n/backtest BTC 1h\n/help')

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('/analyze BTC — تحليل 6 فريمات + Agents + Order Flow\n/scan — فحص قائمة العملات\n/live — حالة WebSocket والبيانات اللحظية\n/backtest BTC 1h — اختبار تاريخي أولي\nالإنذارات الدورية تعمل عند ضبط ADMIN_CHAT_ID.')

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

async def backtest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbol=(context.args[0] if context.args else 'BTC').upper().replace('USDT','').replace('-','')
    timeframe=(context.args[1] if len(context.args)>1 else '1h').lower()
    if timeframe not in ['5m','15m','1h','4h','1d','1w']:
        await update.message.reply_text('الفريمات: 5m / 15m / 1h / 4h / 1d / 1w')
        return
    msg=await update.message.reply_text(f'🧪 Backtest أولي {symbol} {timeframe}...')
    try:
        df=await fetch_candles(symbol,timeframe,300)
        horizon={'5m':6,'15m':4,'1h':3,'4h':2,'1d':2,'1w':1}[timeframe]
        bt=walk_forward(df,timeframe,horizon=horizon,min_history=210,step=3)
        await msg.edit_text(
            f'🧪 Backtest {symbol} — {timeframe}\n'
            f'Samples: {bt.samples}\n'
            f'Accuracy: {bt.accuracy:.1f}%\n'
            f'Long accuracy: {bt.bullish_accuracy:.1f}%\n'
            f'Short accuracy: {bt.bearish_accuracy:.1f}%\n'
            f'Brier-like: {bt.brier_like:.4f}\n'
            f'ECE calibration error: {bt.ece:.4f}\n'
            + ('Calibration:\n' + '\n'.join(f"• {b['low']}-{b['high']}%: predicted {b['predicted_pct']:.1f}% / realized {b['realized_pct']:.1f}% (n={b['samples']})" for b in bt.calibration) + '\n\n' if bt.calibration else '\n') +
            '⚠️ هذا اختبار قصير على آخر شموع OKX، وليس اعتماداً نهائياً للنموذج.'
        )
    except Exception as e:
        await msg.edit_text(f'❌ خطأ Backtest: {e}')

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
