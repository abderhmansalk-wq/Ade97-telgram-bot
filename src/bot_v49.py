from telegram.ext import ApplicationBuilder, CommandHandler
from . import bot as old
from .market import fetch_backtest_candles
from .signal_v49 import validate_v49

async def start(update, context):
    await update.message.reply_text('🤖 Crypto Multi-Agent Analyst V4.9 جاهز.\n/analyze BTC\n/scan\n/live\n/validate49 BTC\n/help')

async def help_cmd(update, context):
    await update.message.reply_text('/validate49 BTC — Extended confirmation للـBTC 4h RANGE LONG + loss_cooldown المجمد. 4 Purged OOS folds + stress costs + bootstrap + Monte Carlo. النجاح يعني FORWARD_TEST_READY فقط، وليس تداول حقيقي.')

async def validate49_cmd(update, context):
    symbol=(context.args[0] if context.args else 'BTC').upper().replace('USDT','').replace('-','')
    msg=await update.message.reply_text(f'🧪 V4.9 Extended Confirmation {symbol} 4h... قد يستغرق 2–4 دقائق')
    try:
        if symbol!='BTC':
            await msg.edit_text('ℹ️ V4.9 يختبر فقط Setup BTC المجمد حالياً.')
            return
        df=await fetch_backtest_candles(symbol,'4h',1800)
        vr=validate_v49(df,symbol)
        status={'FORWARD_TEST_READY':'✅ FORWARD TEST READY','HOLD':'⏸ HOLD','INSUFFICIENT_DATA':'⚠️ INSUFFICIENT DATA','NO_SETUP':'⛔ NO SETUP'}.get(vr.status,vr.status)
        rows=[]
        for c in vr.costs:
            rows.append(f"cost {c['cost_bps']:.0f}bps: n={c['trades']} | WR {c['win_rate']:.1f}% | EV {c['expectancy_r']:+.3f}R | PF {c['profit_factor']:.2f} | MDD {c['max_drawdown_r']:.2f}R | LLS {c['longest_losing_streak']} | MC95 {c['monte_carlo_mdd_p95']:.2f}R | folds+ {c['positive_folds']}/{c['folds']} | boot90 [{c['bootstrap_low_r']:+.3f},{c['bootstrap_high_r']:+.3f}]")
        text=(f'🧪 V4.9 Extended Confirmation {symbol}\nStatus: {status}\nSetup: 4h RANGE LONG | RR 2.0 | Overlay: loss_cooldown ثابت\nSample: {vr.sample_bars} bars | HVcut {vr.atr_cutoff_pct:.2f}%\n\n'+'\n'.join(rows)+f"\n\n{vr.reason}\n\nFORWARD_TEST_READY يعني ننتقل فقط إلى Paper/Forward Trading حي. لا يوجد تعديل للـSetup أو Overlay داخل V4.9.")
        await msg.edit_text(text[:4000])
    except Exception as e:
        await msg.edit_text(f'❌ خطأ V4.9: {e}')


def main():
    if not old.TOKEN: raise SystemExit('Set TELEGRAM_BOT_TOKEN in .env')
    app=ApplicationBuilder().token(old.TOKEN).post_init(old.post_init).build()
    handlers=[
        ('start',start),('help',help_cmd),('analyze',old.analyze_cmd),('scan',old.scan_cmd),('live',old.live_cmd),
        ('backtest',old.backtest_cmd),('validate',old.validate_cmd),('validate43',old.validate43_cmd),
        ('validate44',old.validate44_cmd),('validate45',old.validate45_cmd),('validate49',validate49_cmd),
    ]
    for name,fn in handlers: app.add_handler(CommandHandler(name,fn))
    app.job_queue.run_repeating(old.alert_job, interval=300, first=20)
    app.run_polling(drop_pending_updates=True)

if __name__=='__main__': main()
