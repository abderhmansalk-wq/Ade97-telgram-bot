import asyncio
from telegram.ext import ApplicationBuilder, CommandHandler
from . import bot as old
from .market import fetch_backtest_candles
from .signal_v46 import validate_v46

async def start(update, context):
    await update.message.reply_text('🤖 Crypto Multi-Agent Analyst V4.6 جاهز.\n/analyze BTC\n/scan\n/live\n/validate46 BTC\n/help')

async def help_cmd(update, context):
    await update.message.reply_text('/analyze BTC — تحليل 6 فريمات + Agents + Order Flow\n/scan — فحص القائمة\n/live — حالة WebSocket\n/validate44 BTC 1h — Rolling OOS\n/validate45 BTC — V4.5.1\n/validate46 BTC — ATR percentile regimes + 3 OOS folds صارمة')

async def validate46_cmd(update, context):
    symbol=(context.args[0] if context.args else 'BTC').upper().replace('USDT','').replace('-','')
    msg=await update.message.reply_text(f'🧪 V4.6 {symbol}: 15m → 1h → 4h مع 3 نوافذ OOS... قد يستغرق 2–4 دقائق')
    try:
        # More history for 4h so every bucket can form three independent OOS folds.
        tfs={'15m':1800,'1h':1500,'4h':1200}
        frames={}
        for tf,bars in tfs.items():
            frames[tf]=await fetch_backtest_candles(symbol,tf,bars)
            await asyncio.sleep(1.5)
        vr=validate_v46(symbol,frames,fee_slippage_bps=8.0)
        status='✅ PASS' if vr.status=='PASS' else '⛔ NO TRADE'
        ranked=sorted(vr.buckets,key=lambda b:(b['status']=='PASS',b['expectancy_r'],b['trades']),reverse=True)
        rows=[]
        for b in ranked[:12]:
            flag='✅' if b['status']=='PASS' else '•'
            rows.append(f"{flag} {b['timeframe']} | {b['regime']} | {b['side']} | n={b['trades']} | WR {b['win_rate']:.1f}% | EV {b['expectancy_r']:+.3f}R | folds+ {b['positive_folds']}/{b['folds']} | RR {b['rr']:.2f} | HVcut {b['atr_percentile']:.2f}%")
        best=(f"أفضل Bucket مثبت: {vr.best_timeframe} / {vr.best_regime} / {vr.best_side} | EV {vr.best_expectancy_r:+.3f}R" if vr.status=='PASS' else 'لا يوجد Bucket يحقق شروط PASS حالياً.')
        text=(f'🧪 V4.6 Robust Regime OOS {symbol}\nStatus: {status}\nCosts: {vr.fee_slippage_bps:.1f} bps round-trip\n{best}\n\nTop buckets:\n'+'\n'.join(rows)+"\n\nV4.6: HIGH_VOL = أعلى 20% من ATR في Train فقط. PASS يتطلب 3 folds كاملة، Edge صافي ≥ +0.05R، وعدد صفقات كافٍ، و≥2 folds موجبة.")
        await msg.edit_text(text[:4000])
    except Exception as e:
        await msg.edit_text(f'❌ خطأ V4.6: {e}')


def main():
    if not old.TOKEN:
        raise SystemExit('Set TELEGRAM_BOT_TOKEN in .env')
    app=ApplicationBuilder().token(old.TOKEN).post_init(old.post_init).build()
    handlers=[
        ('start',start),('help',help_cmd),('analyze',old.analyze_cmd),('scan',old.scan_cmd),('live',old.live_cmd),
        ('backtest',old.backtest_cmd),('validate',old.validate_cmd),('validate43',old.validate43_cmd),
        ('validate44',old.validate44_cmd),('validate45',old.validate45_cmd),('validate46',validate46_cmd),
    ]
    for name,fn in handlers:
        app.add_handler(CommandHandler(name,fn))
    app.job_queue.run_repeating(old.alert_job, interval=300, first=20)
    app.run_polling(drop_pending_updates=True)

if __name__=='__main__':
    main()
