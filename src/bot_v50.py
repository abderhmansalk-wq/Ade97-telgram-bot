from telegram.ext import ApplicationBuilder, CommandHandler
from . import bot as old
from .paper_v50 import paper_tick, summary, recent_trades, set_enabled, subscribed_chat_id, DB_PATH


def _fmt_summary(s):
    progress=f"{s['closed']}/{s['target_trades']}" if s['target_trades'] else str(s['closed'])
    return (
        f"📒 V5.0 Forward Paper Status\n"
        f"Engine: {'🟢 ON' if s['enabled'] else '⚪ OFF'}\n"
        f"Setup: BTC 4h RANGE LONG | RR 2.0 | loss_cooldown frozen\n"
        f"Closed: {s['closed']} | Open: {s['open']} | Progress: {progress}\n"
        f"WR: {s['win_rate']:.1f}% | EV {s['expectancy_r']:+.3f}R | PF {s['profit_factor']:.2f}\n"
        f"Equity: {s['equity_r']:+.2f}R | MDD {s['max_drawdown_r']:.2f}R | LLS {s['longest_losing_streak']}\n"
        f"Mode: PAPER ONLY — لا توجد أوامر حقيقية إلى OKX."
    )


async def start(update, context):
    await update.message.reply_text(
        '🤖 Crypto Multi-Agent Analyst V5.0 جاهز.\n'
        '/analyze BTC\n/scan\n/live\n'
        '/paper50 on — تشغيل Forward Paper\n'
        '/paper50 status — النتائج الحية\n'
        '/paper50 trades — آخر الصفقات\n/help'
    )


async def help_cmd(update, context):
    await update.message.reply_text(
        '/paper50 on — يبدأ Forward Paper Trading للـBTC 4h RANGE LONG بدون أموال حقيقية.\n'
        '/paper50 off — يوقف فتح إشارات جديدة.\n'
        '/paper50 status — WR/EV/PF/MDD/Equity وعدد الصفقات.\n'
        '/paper50 trades — آخر الصفقات المسجلة.\n'
        'V5.0 لا يرسل أي أمر شراء/بيع إلى OKX.'
    )


async def paper50_cmd(update, context):
    action=(context.args[0].lower() if context.args else 'status')
    chat_id=update.effective_chat.id
    if action=='on':
        set_enabled(True,chat_id)
        await update.message.reply_text('🟢 V5.0 Forward Paper مفعّل. سأراقب BTC 4h وأرسل إشعارًا عند فتح/إغلاق صفقة ورقية فقط.')
        try:
            events=await paper_tick()
            if events:
                await _send_events(context,chat_id,events)
        except Exception as e:
            await update.message.reply_text(f'⚠️ تم التفعيل لكن أول فحص أعطى خطأ: {e}')
        return
    if action=='off':
        set_enabled(False,chat_id)
        await update.message.reply_text('⚪ تم إيقاف Forward Paper. الصفقات التاريخية المسجلة محفوظة.')
        return
    if action=='trades':
        rows=recent_trades(8)
        if not rows:
            await update.message.reply_text('📭 لا توجد صفقات Paper مسجلة بعد.')
            return
        out=['📜 آخر صفقات V5.0:']
        for r in rows:
            state='🟡 OPEN' if r['status']=='OPEN' else ('✅ TP' if (r.get('pnl_r') or 0)>0 else '❌ SL')
            pnl='' if r.get('pnl_r') is None else f" | {float(r['pnl_r']):+.3f}R"
            out.append(f"{state} | {r['signal_ts']} | entry {r['entry']:.2f} | TP {r['tp']:.2f} | SL {r['sl']:.2f}{pnl}")
        await update.message.reply_text('\n'.join(out)[:4000])
        return
    await update.message.reply_text(_fmt_summary(summary()))


async def _send_events(context,chat_id,events):
    for e in events:
        if e['type']=='OPENED':
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    '📝 PAPER OPEN — BTC 4h RANGE LONG\n'
                    f"Signal: {e['signal_ts']}\nEntry: {e['entry']:.2f}\nTP: {e['tp']:.2f}\nSL: {e['sl']:.2f}\n"
                    f"ATR: {e['atr']:.2f} ({e['atr_pct']:.2f}%) | HVcut {e['hv_cut']:.2f}% | score {e['score']}\n"
                    '⚠️ صفقة افتراضية فقط؛ لا يوجد تنفيذ حقيقي.'
                )
            )
        elif e['type']=='CLOSED':
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"🏁 PAPER CLOSE — {e['outcome']}\n"
                    f"Result: {e['pnl_r']:+.3f}R\nClosed: {e['ts']}\n\n"+_fmt_summary(summary())
                )
            )
        elif e['type']=='SUPPRESSED':
            await context.bot.send_message(chat_id=chat_id,text=f"⏸ PAPER signal suppressed: {e['reason']}\nSignal: {e['signal_ts']}")


async def paper_job(context):
    try:
        events=await paper_tick()
        if not events: return
        chat_id=subscribed_chat_id()
        if chat_id:
            await _send_events(context,int(chat_id),events)
    except Exception as e:
        chat_id=subscribed_chat_id()
        if chat_id:
            # Do not spam repeated errors: telegram job queue logs most failures; send only compact notice.
            await context.bot.send_message(chat_id=int(chat_id),text=f'⚠️ V5.0 Paper tick error: {e}')


def main():
    if not old.TOKEN: raise SystemExit('Set TELEGRAM_BOT_TOKEN in .env')
    app=ApplicationBuilder().token(old.TOKEN).post_init(old.post_init).build()
    handlers=[
        ('start',start),('help',help_cmd),('analyze',old.analyze_cmd),('scan',old.scan_cmd),('live',old.live_cmd),
        ('backtest',old.backtest_cmd),('validate',old.validate_cmd),('validate43',old.validate43_cmd),
        ('validate44',old.validate44_cmd),('validate45',old.validate45_cmd),('paper50',paper50_cmd),
    ]
    for name,fn in handlers: app.add_handler(CommandHandler(name,fn))
    app.job_queue.run_repeating(old.alert_job,interval=300,first=20)
    # 4h setup, but poll every 15m; duplicate closed candles are automatically ignored.
    app.job_queue.run_repeating(paper_job,interval=900,first=45)
    app.run_polling(drop_pending_updates=True)

if __name__=='__main__': main()
