from telegram.ext import ApplicationBuilder, CommandHandler
from . import bot as old
from .market import fetch_backtest_candles
from .signal_v491 import validate_v491

async def start(update, context):
    await update.message.reply_text('🤖 Crypto Multi-Agent Analyst V4.9.1 جاهز.\n/analyze BTC\n/scan\n/live\n/validate49 BTC\n/diagnose491 BTC\n/help')

async def help_cmd(update, context):
    await update.message.reply_text('/diagnose491 BTC — Diagnostic فقط للـV4.9: يعرض كل OOS fold بالتاريخ وn/WR/EV/PF/MDD ويفحص one-position-at-a-time بدون أي Optimization أو تغيير للـSetup.')

async def diagnose491_cmd(update, context):
    symbol=(context.args[0] if context.args else 'BTC').upper().replace('USDT','').replace('-','')
    msg=await update.message.reply_text(f'🔬 V4.9.1 Diagnostic {symbol} 4h... قد يستغرق 2–4 دقائق')
    try:
        if symbol!='BTC':
            await msg.edit_text('ℹ️ V4.9.1 يشخّص فقط Setup BTC المجمد حالياً.')
            return
        df=await fetch_backtest_candles(symbol,'4h',1800)
        vr=validate_v491(df,symbol,8.0)
        rows=[]
        for f in vr.folds:
            flag='✅' if f['positive'] else '❌'
            oflag='✅' if f['one_position_positive'] else '❌'
            rows.append(
                f"{flag} Fold {f['fold']} | {f['start']} → {f['end']}\n"
                f" raw={f['raw_candidates']} | exec n={f['executed_trades']} | WR {f['win_rate']:.1f}% | EV {f['expectancy_r']:+.3f}R | PF {f['profit_factor']:.2f} | MDD {f['max_drawdown_r']:.2f}R\n"
                f" {oflag} one-position: n={f['one_position_trades']} | WR {f['one_position_win_rate']:.1f}% | EV {f['one_position_expectancy_r']:+.3f}R | PF {f['one_position_profit_factor']:.2f} | MDD {f['one_position_max_drawdown_r']:.2f}R"
            )
        text=(
            f'🔬 V4.9.1 Diagnostic Gate {symbol}\nStatus: {vr.status}\nSample: {vr.sample_bars} bars | HVcut {vr.atr_cutoff_pct:.2f}%\n'
            f'Frozen execution: n={vr.total_trades} | positive folds {vr.positive_folds}/4\n'
            f'One-position: n={vr.one_position_total_trades} | positive folds {vr.one_position_positive_folds}/4 | overlap removed {vr.overlap_removed}\n\n'
            +'\n\n'.join(rows)+f'\n\n{vr.diagnosis}\n\nهذه نتيجة تشخيصية فقط؛ لا تغيّر شروط V4.9 ولا تمنح PAPER_READY.'
        )
        await msg.edit_text(text[:4000])
    except Exception as e:
        await msg.edit_text(f'❌ خطأ V4.9.1: {e}')


def main():
    if not old.TOKEN: raise SystemExit('Set TELEGRAM_BOT_TOKEN in .env')
    app=ApplicationBuilder().token(old.TOKEN).post_init(old.post_init).build()
    handlers=[
        ('start',start),('help',help_cmd),('analyze',old.analyze_cmd),('scan',old.scan_cmd),('live',old.live_cmd),
        ('backtest',old.backtest_cmd),('validate',old.validate_cmd),('validate43',old.validate43_cmd),
        ('validate44',old.validate44_cmd),('validate45',old.validate45_cmd),('diagnose491',diagnose491_cmd),
    ]
    for name,fn in handlers: app.add_handler(CommandHandler(name,fn))
    app.job_queue.run_repeating(old.alert_job, interval=300, first=20)
    app.run_polling(drop_pending_updates=True)

if __name__=='__main__': main()
