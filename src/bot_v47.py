import asyncio
from telegram.ext import ApplicationBuilder, CommandHandler
from . import bot_v46 as old
from .market import fetch_backtest_candles
from .signal_v47 import validate_v47

async def start(update, context):
    await update.message.reply_text('🤖 Crypto Multi-Agent Analyst V4.7 جاهز.\n/analyze BTC\n/scan\n/live\n/validate46 BTC\n/validate47 BTC\n/help')

async def help_cmd(update, context):
    await update.message.reply_text('/validate47 BTC — Final Robustness Gate للـSetups المجمدة من V4.6: Purged/Embargo OOS + Bootstrap EV + Profit Factor + Max Drawdown + stress costs 8/12/16 bps. لا ينقل إلى Paper Trading إلا عند PAPER_READY.')

async def validate47_cmd(update, context):
    symbol=(context.args[0] if context.args else 'BTC').upper().replace('USDT','').replace('-','')
    msg=await update.message.reply_text(f'🧪 V4.7 Final Robustness {symbol}: frozen setups + purged OOS + bootstrap + cost stress...')
    try:
        if symbol!='BTC':
            await msg.edit_text('ℹ️ V4.7 حالياً يختبر فقط الـBTC setups التي نجحت في V4.6. شغّل /validate46 ETH أولاً لاكتشاف مرشحين مستقلين لـETH.')
            return
        # Only 4h is needed because V4.7 freezes the two V4.6 BTC 4h candidates.
        df=await fetch_backtest_candles(symbol,'4h',1500)
        vr=validate_v47(symbol,{'4h':df})
        status={'PAPER_READY':'✅ PAPER READY','HOLD':'⏸ HOLD','NO_FROZEN_SETUP':'⛔ NO SETUP'}.get(vr.status,vr.status)
        rows=[]
        for s in vr.setups:
            flag='✅' if s['status']=='PAPER_READY' else '⏸'
            rows.append(f"{flag} {s['timeframe']} | {s['regime']} | {s['side']} | RR {s['rr']:.2f} | HVcut {s['atr_cutoff_pct']:.2f}%")
            for c in s['costs']:
                rows.append(f"  cost {c['cost_bps']:.0f}bps: n={c['trades']} | WR {c['win_rate']:.1f}% | EV {c['expectancy_r']:+.3f}R | PF {c['profit_factor']:.2f} | MDD {c['max_drawdown_r']:.2f}R | folds+ {c['positive_folds']}/{c['folds']} | boot90 [{c['bootstrap_low_r']:+.3f},{c['bootstrap_high_r']:+.3f}]")
            rows.append('  '+s['reason'])
        text=(f'🧪 V4.7 Final Robustness Gate {symbol}\nStatus: {status}\nPaper-ready setups: {vr.paper_ready_count}\n\n'+'\n'.join(rows)+"\n\nPAPER_READY يتطلب: ≥35 صفقة OOS، ≥2/3 folds موجبة، EV8≥+0.10R، PF8≥1.20، MDD≤10R، bootstrap 5% > 0، وEV16≥+0.05R مع PF16≥1.10. لا يوجد أي إعادة Optimization داخل V4.7.")
        await msg.edit_text(text[:4000])
    except Exception as e:
        await msg.edit_text(f'❌ خطأ V4.7: {e}')


def main():
    if not old.old.TOKEN:
        raise SystemExit('Set TELEGRAM_BOT_TOKEN in .env')
    app=ApplicationBuilder().token(old.old.TOKEN).post_init(old.old.post_init).build()
    handlers=[
        ('start',start),('help',help_cmd),('analyze',old.old.analyze_cmd),('scan',old.old.scan_cmd),('live',old.old.live_cmd),
        ('backtest',old.old.backtest_cmd),('validate',old.old.validate_cmd),('validate43',old.old.validate43_cmd),
        ('validate44',old.old.validate44_cmd),('validate45',old.old.validate45_cmd),('validate46',old.validate46_cmd),
        ('validate47',validate47_cmd),
    ]
    for name,fn in handlers:
        app.add_handler(CommandHandler(name,fn))
    app.job_queue.run_repeating(old.old.alert_job, interval=300, first=20)
    app.run_polling(drop_pending_updates=True)

if __name__=='__main__':
    main()
