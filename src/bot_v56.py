from telegram.ext import ApplicationBuilder, CommandHandler
from . import bot as old
from . import bot_v55 as v55
from .paper_v53 import TIMEFRAMES
from .paper_v56 import timeframe_cost_stats


def _stats_text():
    stats=timeframe_cost_stats()
    out=['📊 V5.6 COST STATISTICS — BTC']
    for tf in TIMEFRAMES:
        s=stats[tf]
        out.append(
            f"{tf}: trades {s['trades']} | avg cost {s['avg_cost_r']:.3f}R | "
            f"gross EV {s['gross_ev_r']:+.3f}R | net EV {s['net_ev_r']:+.3f}R | "
            f"total cost {s['total_cost_r']:.3f}R"
        )
    out.append('Gross EV = النتيجة قبل التكلفة | Net EV = بعد التكلفة.')
    out.append('Paper Only — لا يوجد تنفيذ حقيقي.')
    return '\n'.join(out)


async def start(update,context):
    await update.message.reply_text(
        '🤖 Crypto Multi-Agent Analyst V5.6 جاهز.\n'
        '/paper50 status — النتائج + Cost Monitor\n'
        '/paper50 stats — avg cost / gross EV / net EV / trades\n'
        '/paper50 open — الصفقات المفتوحة والتكلفة بالـR\n'
        '/paper50 trades — آخر الصفقات\n'
        '/paper50 why — التشخيص الحالي\n'
        '/paper50 on | off\n'
        '/analyze BTC\n/scan\n/live\n/help')


async def help_cmd(update,context):
    await update.message.reply_text(
        'V5.6 يضيف Cost Statistics لكل فريم 15m/1h/4h.\n'
        '/paper50 stats — trades + avg cost R + gross EV + net EV + total cost.\n'
        'باقي أوامر V5.5 تعمل كما هي.\n'
        'Paper Only — لا يوجد تنفيذ حقيقي.')


async def paper50_cmd(update,context):
    action=(context.args[0].lower() if context.args else 'status')
    if action=='stats':
        await update.message.reply_text(_stats_text()[:4000]); return
    if action=='status':
        text=v55._fmt_status()+'\n\n'+_stats_text()
        await update.message.reply_text(text[:4000]); return
    await v55.paper50_cmd(update,context)


def main():
    if not old.TOKEN: raise SystemExit('Set TELEGRAM_BOT_TOKEN in .env')
    app=ApplicationBuilder().token(old.TOKEN).post_init(old.post_init).build()
    handlers=[('start',start),('help',help_cmd),('analyze',old.analyze_cmd),('scan',old.scan_cmd),('live',old.live_cmd),('backtest',old.backtest_cmd),('validate',old.validate_cmd),('validate43',old.validate43_cmd),('validate44',old.validate44_cmd),('validate45',old.validate45_cmd),('paper50',paper50_cmd)]
    for name,fn in handlers: app.add_handler(CommandHandler(name,fn))
    app.job_queue.run_repeating(old.alert_job,interval=300,first=20)
    app.job_queue.run_repeating(v55.paper_job,interval=900,first=45)
    app.run_polling(drop_pending_updates=True)

if __name__=='__main__': main()
