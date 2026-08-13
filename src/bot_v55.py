from telegram.ext import ApplicationBuilder, CommandHandler
from . import bot as old
from .paper_v53 import paper_tick_all, summaries, recent_trades, set_enabled, subscribed_chat_id, explain_timeframe, TIMEFRAMES, REGIMES, COST_BPS
from .paper_v54 import open_positions_snapshot

MAX_COST_WARN_R=0.30


def _cost_r(entry, atr):
    return (float(COST_BPS)/10000.0)*float(entry)/float(atr) if entry and atr else 0.0


def _fmt_status():
    ss=summaries(); on=next(iter(ss.values()))['enabled'] if ss else False
    out=["📒 V5.5 Cost Monitor Forward Paper",f"Engine: {'🟢 ON' if on else '⚪ OFF'}","BTC | 15m / 1h / 4h","RANGE: LONG RR2.0 | TREND: LONG/SHORT RR1.5 | score>=2"]
    for tf in TIMEFRAMES:
        for r in REGIMES:
            s=ss[(tf,r)]
            out.append(f"{tf} {r}: {s['closed']}/{s['target_trades']} closed | Open {s['open']} | WR {s['win_rate']:.1f}% | EV {s['expectancy_r']:+.3f}R | PF {s['profit_factor']:.2f}")
    out.append('Cost monitor: ⚠️ warning when expected cost > 0.30R')
    out.append('Mode: PAPER ONLY — لا توجد أوامر حقيقية إلى OKX.')
    return '\n'.join(out)


async def start(update,context):
    await update.message.reply_text(
        '🤖 Crypto Multi-Agent Analyst V5.5 جاهز.\n'
        '/paper50 status — النتائج + Cost Monitor\n'
        '/paper50 open — الصفقات المفتوحة والتكلفة بالـR\n'
        '/paper50 trades — آخر الصفقات\n'
        '/paper50 why — تشخيص + Expected cost R\n'
        '/paper50 on | off\n'
        '/analyze BTC\n/scan\n/live\n/help')


async def help_cmd(update,context):
    await update.message.reply_text(
        'V5.5 يضيف مراقبة تكلفة على Forward Paper.\n'
        'يعرض Expected cost in R ويضع ⚠️ إذا تجاوزت 0.30R.\n'
        'تم إيقاف رسائل suppressed المتكررة من Telegram؛ تبقى الإدارة الداخلية كما هي.\n'
        'Paper Only — لا يوجد تنفيذ حقيقي.')


async def _why_text(tf):
    e=await explain_timeframe(tf)
    if 'actual_regime' not in e: return f"{tf}: ⚠️ {e.get('reason','unknown')}"
    cost=_cost_r(e['close'],e['atr'])
    flag='⚠️ HIGH' if cost>MAX_COST_WARN_R else '✅ OK'
    out=[f"🔎 {tf} | Close {e['close']:.2f} | Current {e['actual_regime']}",
         f"ATR {e['atr']:.2f} ({e['atr_pct']:.2f}%) | Expected cost {cost:.3f}R {flag}"]
    for b in e['buckets']:
        mark='🟢' if b['ready'] else '⏸'
        net_tp=float(b['rr'])-cost
        net_sl=-1.0-cost
        out.append(f"{b['regime']}: {mark} {b['side']} | Score {b['score']}/2 | RR {b['rr']:.1f} | net TP≈{net_tp:+.3f}R | net SL≈{net_sl:+.3f}R | {b['reason']}")
    return '\n'.join(out)


async def _open_text():
    rows=await open_positions_snapshot()
    if not rows: return '📭 لا توجد صفقات Paper مفتوحة الآن.'
    out=[f'📂 V5.5 OPEN POSITIONS — {len(rows)}']
    for r in rows:
        p=r.get('market_price'); cost=_cost_r(r['entry'],r['atr']); flag='⚠️ HIGH COST' if cost>MAX_COST_WARN_R else '✅ COST OK'
        if p is None:
            out.append(f"\n🟡 BTC {r['timeframe']} {r['regime']} {r['side']}\nEntry {r['entry']:.2f} | TP {r['tp']:.2f} | SL {r['sl']:.2f}\nExpected cost {cost:.3f}R {flag}")
            continue
        progress=float(r.get('progress_pct') or 0.0); tp_pct=float(r.get('tp_distance_pct') or 0.0); sl_pct=float(r.get('sl_distance_pct') or 0.0)
        state='🟢 باتجاه TP' if progress>0 else ('🔴 باتجاه SL' if progress<0 else '⚪ عند الدخول')
        out.append(f"\n{state} — BTC {r['timeframe']} {r['regime']} {r['side']}\nEntry: {r['entry']:.2f} | Now: {p:.2f}\nTP: {r['tp']:.2f} | distance {tp_pct:.2f}%\nSL: {r['sl']:.2f} | distance {sl_pct:.2f}%\nProgress: {progress:+.1f}% | RR {float(r['rr']):.1f} | Score {r['score']}\nExpected cost: {cost:.3f}R {flag}")
    out.append('\n⚠️ Cost Monitor فقط — لا يغيّر قرار الدخول. Paper فقط.')
    return '\n'.join(out)


async def paper50_cmd(update,context):
    action=(context.args[0].lower() if context.args else 'status'); chat_id=update.effective_chat.id
    if action=='on':
        set_enabled(True,chat_id); await update.message.reply_text('🟢 V5.5 مفعّل — Paper فقط.'); return
    if action=='off':
        set_enabled(False,chat_id); await update.message.reply_text('⚪ تم إيقاف فتح إشارات Paper. السجل محفوظ.'); return
    if action=='open':
        msg=await update.message.reply_text('📡 أفحص الصفقات والتكلفة...')
        try: await msg.edit_text((await _open_text())[:4000])
        except Exception as e: await msg.edit_text(f'❌ خطأ open: {e}')
        return
    if action=='trades':
        rows=recent_trades(16)
        if not rows: await update.message.reply_text('📭 لا توجد صفقات مسجلة بعد.'); return
        out=['📜 آخر صفقات V5.5:']
        for r in rows:
            state='🟡 OPEN' if r['status']=='OPEN' else ('✅ TP' if (r.get('pnl_r') or 0)>0 else '❌ SL')
            pnl='' if r.get('pnl_r') is None else f" | {float(r['pnl_r']):+.3f}R"
            cost=_cost_r(r['entry'],r['atr'])
            out.append(f"{state} {r['timeframe']} {r['regime']} {r['side']} | cost {cost:.3f}R{pnl}")
        await update.message.reply_text('\n'.join(out)[:4000]); return
    if action=='why':
        requested=(context.args[1].lower() if len(context.args)>1 else None)
        tfs=[requested] if requested in TIMEFRAMES else list(TIMEFRAMES)
        msg=await update.message.reply_text('🔎 أفحص V5.5 Cost Monitor...')
        parts=[]
        for tf in tfs:
            try: parts.append(await _why_text(tf))
            except Exception as e: parts.append(f'{tf}: ❌ {e}')
        await msg.edit_text(('🔎 V5.5 WHY — BTC\n\n'+'\n\n'.join(parts))[:4000]); return
    await update.message.reply_text(_fmt_status()[:4000])


async def _send_events(context,chat_id,events):
    for e in events:
        tf=e.get('timeframe','?'); regime=e.get('regime','?')
        if e['type']=='OPENED':
            cost=_cost_r(e['entry'], e['entry']*e['atr_pct']/100.0)
            flag=' ⚠️ HIGH COST' if cost>MAX_COST_WARN_R else ''
            text=(f"📝 PAPER OPEN — BTC {tf} {regime} {e['side']}\nEntry: {e['entry']:.2f} | TP: {e['tp']:.2f} | SL: {e['sl']:.2f}\nRR {e['rr']:.1f} | Score {e['score']} | Expected cost {cost:.3f}R{flag}\n⚠️ افتراضية فقط.")
        elif e['type']=='CLOSED': text=f"🏁 PAPER CLOSE — BTC {tf} {regime} {e.get('side','')} | {e['outcome']} | {e['pnl_r']:+.3f}R\nClosed: {e['ts']}"
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
