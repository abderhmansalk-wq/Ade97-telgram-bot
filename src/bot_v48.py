import asyncio
from telegram.ext import ApplicationBuilder, CommandHandler
from . import bot as old
from .market import fetch_backtest_candles
from .signal_v48 import validate_v48

async def start(update, context):
    await update.message.reply_text('🤖 Crypto Multi-Agent Analyst V4.8.1 جاهز.\n/analyze BTC\n/scan\n/live\n/validate48 BTC\n/help')

async def help_cmd(update, context):
    await update.message.reply_text('/analyze BTC — تحليل 6 فريمات + Agents + Order Flow\n/scan — فحص القائمة\n/live — حالة WebSocket\n/validate47 BTC — Final robustness gate\n/validate48 BTC — V4.8.1 Risk Overlay على نفس عينة V4.7 (1500 شمعة 4h)')

async def validate48_cmd(update, context):
    symbol=(context.args[0] if context.args else 'BTC').upper().replace('USDT','').replace('-','')
    msg=await update.message.reply_text(f'🛡️ V4.8.1 Risk Overlay {symbol} 4h على نفس عينة V4.7... قد يستغرق 1–3 دقائق')
    try:
        # Must match V4.7 exactly so baseline is directly comparable.
        df=await fetch_backtest_candles(symbol,'4h',1500)
        vr=validate_v48(df,symbol)
        status='✅ PAPER_READY' if vr.status=='PAPER_READY' else ('⏸ HOLD' if vr.status=='HOLD' else vr.status)
        ranked=sorted(vr.overlays,key=lambda o:(o['status']=='PAPER_READY',-o['max_drawdown_r'],o['expectancy_r']),reverse=True)
        rows=[]
        for o in ranked:
            flag='✅' if o['status']=='PAPER_READY' else '•'
            rows.append(f"{flag} {o['name']} | n={o['trades']} | WR {o['win_rate']:.1f}% | EV {o['expectancy_r']:+.3f}R | PF {o['profit_factor']:.2f} | MDD {o['max_drawdown_r']:.2f}R | LLS {o['longest_losing_streak']} | MC95 {o['monte_carlo_mdd_p95']:.2f}R\n{o['reason']}")
        text=(f'🛡️ V4.8.1 Risk Overlay {symbol} — 4h RANGE LONG\nStatus: {status}\nأفضل Overlay: {vr.best_overlay}\nSample: 1500 bars (مطابق V4.7)\n\n'+'\n'.join(rows)+"\n\nPAPER_READY يتطلب n≥35، EV≥+0.10R، PF≥1.20، MDD≤10R، وMonte Carlo MDD 95%≤14R. قواعد الدخول ثابتة؛ الاختبار يغير إدارة المخاطر فقط.")
        await msg.edit_text(text[:4000])
    except Exception as e:
        await msg.edit_text(f'❌ خطأ V4.8.1: {e}')


def main():
    if not old.TOKEN: raise SystemExit('Set TELEGRAM_BOT_TOKEN in .env')
    app=ApplicationBuilder().token(old.TOKEN).post_init(old.post_init).build()
    handlers=[('start',start),('help',help_cmd),('analyze',old.analyze_cmd),('scan',old.scan_cmd),('live',old.live_cmd),('backtest',old.backtest_cmd),('validate',old.validate_cmd),('validate43',old.validate43_cmd),('validate44',old.validate44_cmd),('validate45',old.validate45_cmd),('validate48',validate48_cmd)]
    for name,fn in handlers: app.add_handler(CommandHandler(name,fn))
    app.job_queue.run_repeating(old.alert_job, interval=300, first=20)
    app.run_polling(drop_pending_updates=True)

if __name__=='__main__': main()
