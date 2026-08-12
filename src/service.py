import asyncio
from .market import fetch_candles, fetch_public_metrics
from .analysis_engine import analyze, pick_best, cross_timeframe_context
from .realtime import get_hub
from .storage import oi_change_pct, flow_features

TIMEFRAMES=['5m','15m','1h','4h','1d','1w']

async def analyze_symbol(symbol: str):
    metrics_task=asyncio.create_task(fetch_public_metrics(symbol))
    frames=await asyncio.gather(*[fetch_candles(symbol,t) for t in TIMEFRAMES])
    metrics=await metrics_task
    hub=get_hub()
    live=hub.snapshot(symbol) if hub else None
    if live and live.get('ts'):
        metrics.update(live)
        metrics['live_available']=True
        metrics['oi_change_pct']=oi_change_pct(symbol)
        metrics.update(flow_features(symbol))
    else:
        metrics['live_available']=False
    results=[analyze(df,t,metrics) for df,t in zip(frames,TIMEFRAMES)]
    best=pick_best(results)
    regime,_=cross_timeframe_context(results)
    metrics['regime']=regime
    return results,best,metrics

def format_report(symbol,results,best,m):
    regime_ar={'BULL':'صاعد','BEAR':'هابط','RANGE':'عرضي/متضارب'}.get(m.get('regime'),'غير محدد')
    live='🟢 لحظي' if m.get('live_available') else '🟡 REST'
    lines=[f'📊 تحليل {symbol.upper()} — OKX',f'السعر: {m["last"]:,.4f} | البيانات: {live}',f'السياق العام 4H/1D/1W: {regime_ar}',f'Funding: {m["funding_rate"]*100:.4f}% | OI: {m["open_interest"]:,.0f} | ΔOI: {m.get("oi_change_pct",0):+.2f}%']
    if m.get('live_available'):
        lines += [f'Order Book imbalance: {m.get("imbalance",0):+.2f} | Trade delta 60s: {m.get("trade_delta",0):+.2f} | Spread: {m.get("spread_bps",0):.2f} bps', f'CVD proxy 15m: {m.get("cvd_proxy",0):+.2f} | Flow impulse: {m.get("flow_impulse",0):+.2f} | Flow ΔPrice: {m.get("price_change_flow_pct",0):+.2f}%']
    lines += ['']
    for r in results:
        arrow='🟢' if r.direction=='صاعد' else ('🔴' if r.direction=='هابط' else '⚪️')
        lines.append(f'{arrow} {r.timeframe}: {r.direction} | ↑ {r.bullish_pct:.0f}% ↓ {r.bearish_pct:.0f}% | توافق {r.agreement:.0f}% | دخول {r.entry_quality:.0f}%')
    side='LONG' if best.direction=='صاعد' else ('SHORT' if best.direction=='هابط' else 'WAIT')
    if best.entry_quality < 70 or best.agreement < 67:
        side='WAIT'
    if m.get('regime')=='BULL' and best.direction=='هابط':
        side='WAIT'
    if m.get('regime')=='BEAR' and best.direction=='صاعد':
        side='WAIT'
    lines += ['',f'🎯 أفضل فريم للتنفيذ: {best.timeframe}',f'الاتجاه المرشح: {side}',f'جودة الإعداد: {best.entry_quality:.0f}%',f'Signal Score: {best.confidence:.0f}%',f'توافق الـAgents: {best.agreement:.0f}%',f'دعم تقريبي: {best.support:,.4f}',f'مقاومة تقريبية: {best.resistance:,.4f}','','أقوى أسباب القرار:']
    lines += [f'• {x}' for x in best.reasons]
    lines += ['', '⚠️ Signal Score ليس احتمالاً إحصائياً. استخدم /validate للعملة والفريم قبل اعتبار أي إعداد قابلاً للتداول.']
    return '\n'.join(lines)
