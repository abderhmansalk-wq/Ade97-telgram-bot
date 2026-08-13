from telegram.ext import ApplicationBuilder, CommandHandler
from . import bot as old
from .paper_v53 import paper_tick_all, summaries, recent_trades, set_enabled, subscribed_chat_id, explain_timeframe, TIMEFRAMES, REGIMES


def _fmt_status():
    ss=summaries(); on=next(iter(ss.values()))['enabled'] if ss else False
    out=["📒 V5.3 Dual-Regime Forward Paper",f"Engine: {'🟢 ON' if on else '⚪ OFF'}","BTC | 15m / 1h / 4h","RANGE: LONG RR2.0 | TREND: LONG/SHORT RR1.5 | score>=2"]
    for tf in TIMEFRAMES:
        for r in REGIMES:
            s=ss[(tf,r)]
            out.append(f"{tf} {r}: {s['closed']}/{s['target_trades']} closed | Open {s['open']} | WR {s['win_rate']:.1f}% | EV {s['expectancy_r']:+.3f}R | PF {s['profit_factor']:.2f}")
    out.append('Mode: PAPER ONLY — لا توجد أوامر حقيقية إلى OKX.')
    return '\n'.join(out)


async def start(update,context):
    await update.message.reply_text(
        '🤖 Crypto Multi-Agent Analyst V5.3 جاهز.\n'
        '/paper50 on — تشغيل Dual-Regime Paper\n'
        '/paper50 status — نتائج RANGE/TREND لكل فريم\n'
        '/paper50 trades — آخر الصفقات\n'
        '/paper50 why — تشخيص 15m/1h/4h\n'
        '/paper50 why 1h — تشخيص فريم واحد\n'
        '/analyze BTC\n/scan\n/live\n/help')


async def help_cmd(update,context):
    await update.message.reply_text(
        'V5.3 يراقب BTC على 15m و1h و4h.\n'
        'RANGE وTREND مساران منفصلان بإحصائيات مستقلة.\n'
        'TREND يسمح LONG أو SHORT، وRANGE يحتفظ بـLONG فقط.\n'
        '/paper50 on | off | status | trades | why\n'
        'Paper Only — لا يوجد تنفيذ حقيقي.')


async def _why_text(tf):
    e=await explain_timeframe(tf)
    if 'actual_regime' not in e: return f"{tf}: ⚠️ {e.get('reason','unknown')}"
    out=[f"🔎 {tf} | Close {e['close']:.2f} | Current {e['actual_regime']}",f"ATR {e['atr']:.2f} ({e['atr_pct']:.2f}%) | HVcut {e['hv_cut']:.2f}%"]
    for b in e['buckets']:
        mark='🟢' if b['ready'] else '⏸'
        out.append(f"{b['regime']}: {mark} {b['side']} | Score {b['score']}/2 | RR {b['rr']:.1f} | Risk {'✅' if b['risk_ok'] else '❌'} | {b['reason']}")
    return '\n'.join(out)


async def paper50_cmd(update,context):
    action=(context.args[0].lower() if context.args else 'status'); chat_id=update.effective_chat.id
    if action=='on':
        set_enabled(True,chat_id)
        await update.message.reply_text('🟢 V5.3 مفعّل: RANGE + TREND على 15m/1h/4h، Paper فقط.')
        try:
            events=await paper_tick_all()
            if events: await _send_events(context,chat_id,events)
        except Exception as e: await update.message.reply_text(f'⚠️ أول فحص أعطى خطأ: {e}')
        return
    if action=='off':
        set_enabled(False,chat_id); await update.message.reply_text('⚪ تم إيقاف فتح إشارات V5.3. السجل محفوظ.'); return
    if action=='trades':
        rows=recent_trades(16)
        if not rows: await update.message.reply_text('📭 لا توجد صفقات V5.3 مسجلة بعد.'); return
        out=['📜 آخر صفقات V5.3:']
        for r in rows:
            state='🟡 OPEN' if r['status']=='OPEN' else ('✅ TP' if (r.get('pnl_r') or 0)>0 else '❌ SL')
            pnl='' if r.get('pnl_r') is None else f" | {float(r['pnl_r']):+.3f}R"
            out.append(f"{state} {r['timeframe']} {r['regime']} {r['side']} | E {r['entry']:.2f} TP {r['tp']:.2f} SL {r['sl']:.2f}{pnl}")
        await update.message.reply_text('\n'.join(out)[:4000]); return
    if action=='why':
        requested=(context.args[1].lower() if len(context.args)>1 else None)
        tfs=[requested] if requested in TIMEFRAMES else list(TIMEFRAMES)
        msg=await update.message.reply_text('🔎 أفحص V5.3...')
        parts=[]
        for tf in tfs:
            try: parts.append(await _why_text(tf))
            except Exception as e: parts.append(f'{tf}: ❌ {e}')
        await msg.edit_text(('🔎 V5.3 WHY — BTC\n\n'+'\n\n'.join(parts))[:4000]); return
    await update.message.reply_text(_fmt_status()[:4000])


async def _send_events(context,chat_id,events):
    for e in events:
        tf=e.get('timeframe','?'); regime=e.get('regime','?')
        if e['type']=='OPENED':
            text=(f"📝 PAPER OPEN — BTC {tf} {regime} {e['side']}\nSignal: {e['signal_ts']}\nEntry: {e['entry']:.2f}\nTP: {e['tp']:.2f}\nSL: {e['sl']:.2f}\nRR {e['rr']:.1f} | Score {e['score']} | ATR {e['atr_pct']:.2f}%\n⚠️ افتراضية فقط.")
        elif e['type']=='CLOSED': text=f"🏁 PAPER CLOSE — BTC {tf} {regime} {e.get('side','')} | {e['outcome']} | {e['pnl_r']:+.3f}R\nClosed: {e['ts']}"
        elif e['type']=='SUPPRESSED': text=f"⏸ {tf} {regime} signal suppressed: {e['reason']}"
        elif e['type']=='ERROR': text=f"⚠️ {tf} paper tick error: {e['reason']}"
        else: continue
        await context.bot.send_message(chat_id=chat_id,text=text[:4000])


async def paper_job(context):
    events=await paper_tick_all()
    if not events: return
    chat_id=subscribed_chat_id()
    if chat_id: await _send_events(context,int(chat_id),events)


def main():
    if not old.TOKEN: raise SystemExit('Set TELEGRAM_BOT_TOKEN in .env')
    app=ApplicationBuilder().token(old.TOKEN).post_init(old.post_init).build()
    handlers=[('start',start),('help',help_cmd),('analyze',old.analyze_cmd),('scan',old.scan_cmd),('live',old.live_cmd),('backtest',old.backtest_cmd),('validate',old.validate_cmd),('validate43',old.validate43_cmd),('validate44',old.validate44_cmd),('validate45',old.validate45_cmd),('paper50',paper50_cmd)]
    for name,fn in handlers: app.add_handler(CommandHandler(name,fn))
    app.job_queue.run_repeating(old.alert_job,interval=300,first=20)
    app.job_queue.run_repeating(paper_job,interval=900,first=45)
    app.run_polling(drop_pending_updates=True)

if __name__=='__main__': main()
