from telegram.ext import ApplicationBuilder, CommandHandler
from . import bot as old
from . import bot_v56 as v56
from .paper_v57 import leverage_snapshots


async def _leverage_text():
    snaps=await leverage_snapshots()
    if not snaps:
        return '📭 لا توجد صفقات Paper مفتوحة الآن للمقارنة.'
    out=['⚙️ V5.7 LEVERAGE SIMULATOR — مقارنة تعليمية 1x / 3x / 5x / 10x']
    for s in snaps:
        out.append(
            f"\nBTC {s['timeframe']} {s['regime']} {s['side']}\n"
            f"وحدة المخاطرة الافتراضية: ${s['risk_usd']:.2f}\n"
            f"التكلفة التقديرية: {s['cost_pct_of_risk']:.1f}% من المخاطرة"
        )
        for r in s['rows']:
            out.append(
                f"{r['leverage']}x | الهامش ${r['margin_usd']:.2f} | الحجم الاسمي ${r['notional_usd']:.2f} | "
                f"TP بعد التكلفة≈${r['net_tp_usd']:+.2f} | SL بعد التكلفة≈${r['net_sl_usd']:+.2f}"
            )
    out.append('\nالمغزى: مع تثبيت حجم المخاطرة، الرافعة تقلل الهامش المطلوب، لكنها لا تحسن جودة الإشارة ولا تمحو تكلفة التداول.')
    out.append('PAPER ONLY — لا يوجد تنفيذ حقيقي.')
    return '\n'.join(out)


async def start(update,context):
    await update.message.reply_text(
        '🤖 Crypto Multi-Agent Analyst V5.7 جاهز.\n'
        '/paper50 leverage — مقارنة تعليمية للرافعة 1x/3x/5x/10x\n'
        '/paper50 stats — إحصائيات التكلفة\n'
        '/paper50 status | open | trades | why | on | off\n'
        '/analyze BTC\n/scan\n/live\n/help')


async def help_cmd(update,context):
    await update.message.reply_text(
        'V5.7 يضيف Leverage Simulator تعليمي للصفقات الورقية المفتوحة.\n'
        'يعرض كيف تتغير متطلبات الهامش عند 1x/3x/5x/10x مع بقاء وحدة المخاطرة نفسها.\n'
        'لا يقترح رافعة ولا ينفذ أي صفقة حقيقية.')


async def paper50_cmd(update,context):
    action=(context.args[0].lower() if context.args else 'status')
    if action=='leverage':
        msg=await update.message.reply_text('⚙️ أحسب مقارنة الرافعة للصفقات الورقية المفتوحة...')
        try: await msg.edit_text((await _leverage_text())[:4000])
        except Exception as e: await msg.edit_text(f'❌ خطأ leverage simulator: {e}')
        return
    await v56.paper50_cmd(update,context)


def main():
    if not old.TOKEN: raise SystemExit('Set TELEGRAM_BOT_TOKEN in .env')
    app=ApplicationBuilder().token(old.TOKEN).post_init(old.post_init).build()
    handlers=[('start',start),('help',help_cmd),('analyze',old.analyze_cmd),('scan',old.scan_cmd),('live',old.live_cmd),('backtest',old.backtest_cmd),('validate',old.validate_cmd),('validate43',old.validate43_cmd),('validate44',old.validate44_cmd),('validate45',old.validate45_cmd),('paper50',paper50_cmd)]
    for name,fn in handlers: app.add_handler(CommandHandler(name,fn))
    app.job_queue.run_repeating(old.alert_job,interval=300,first=20)
    app.job_queue.run_repeating(v56.v55.paper_job,interval=900,first=45)
    app.run_polling(drop_pending_updates=True)

if __name__=='__main__': main()
