from .paper_v54 import open_positions_snapshot
from .paper_v53 import COST_BPS

DEFAULT_CAPITAL_USD=1000.0
DEFAULT_RISK_PCT=1.0
LEVERAGES=(1,3,5,10)


def _cost_fraction_of_risk(entry, atr, cost_bps=COST_BPS):
    if not entry or not atr:
        return 0.0
    return (float(cost_bps)/10000.0)*float(entry)/float(atr)


def simulate_trade(trade, capital_usd=DEFAULT_CAPITAL_USD, risk_pct=DEFAULT_RISK_PCT):
    entry=float(trade['entry']); tp=float(trade['tp']); sl=float(trade['sl'])
    side=str(trade['side']); rr=float(trade['rr']); atr=float(trade['atr'])
    risk_usd=float(capital_usd)*float(risk_pct)/100.0
    stop_pct=abs(entry-sl)/entry if entry else 0.0
    notional=(risk_usd/stop_pct) if stop_pct>0 else 0.0
    cost_units=_cost_fraction_of_risk(entry,atr)
    cost_usd=cost_units*risk_usd
    gross_tp_usd=rr*risk_usd
    net_tp_usd=gross_tp_usd-cost_usd
    net_sl_usd=-risk_usd-cost_usd
    rows=[]
    for lev in LEVERAGES:
        margin=notional/lev if lev else notional
        # Simplified educational buffer only. Exact liquidation depends on exchange maintenance margin and fees.
        approx_liq_move_pct=100.0/lev if lev else 100.0
        stop_move_pct=stop_pct*100.0
        buffer_ratio=(approx_liq_move_pct/stop_move_pct) if stop_move_pct else 0.0
        rows.append({
            'leverage':lev,
            'margin_usd':margin,
            'notional_usd':notional,
            'risk_usd':risk_usd,
            'cost_usd':cost_usd,
            'cost_pct_of_risk':cost_units*100.0,
            'gross_tp_usd':gross_tp_usd,
            'net_tp_usd':net_tp_usd,
            'net_sl_usd':net_sl_usd,
            'stop_move_pct':stop_move_pct,
            'approx_liq_move_pct':approx_liq_move_pct,
            'liq_buffer_vs_stop':buffer_ratio,
        })
    return {
        'timeframe':trade['timeframe'],'regime':trade['regime'],'side':side,
        'entry':entry,'tp':tp,'sl':sl,'rr':rr,'score':trade['score'],
        'capital_usd':float(capital_usd),'risk_pct':float(risk_pct),
        'risk_usd':risk_usd,'stop_move_pct':stop_pct*100.0,
        'cost_pct_of_risk':cost_units*100.0,'cost_usd':cost_usd,'rows':rows,
    }


async def leverage_snapshots(capital_usd=DEFAULT_CAPITAL_USD, risk_pct=DEFAULT_RISK_PCT):
    trades=await open_positions_snapshot()
    return [simulate_trade(t,capital_usd,risk_pct) for t in trades]
