import asyncio
import json
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field

import websockets

from .storage import init_db, save_snapshot

WS_PUBLIC = os.getenv('OKX_WS_PUBLIC', 'wss://ws.okx.com:8443/ws/v5/public')
SNAPSHOT_SECONDS = int(os.getenv('SNAPSHOT_SECONDS', '30'))


@dataclass
class LiveState:
    symbol: str
    last: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    bid_depth: float = 0.0
    ask_depth: float = 0.0
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    open_interest: float = 0.0
    funding_rate: float = 0.0
    ts: int = 0
    trades: deque = field(default_factory=lambda: deque(maxlen=5000))

    def as_dict(self):
        depth_total = self.bid_depth + self.ask_depth
        imbalance = (self.bid_depth - self.ask_depth) / depth_total if depth_total else 0.0
        total_trade = self.buy_volume + self.sell_volume
        trade_delta = (self.buy_volume - self.sell_volume) / total_trade if total_trade else 0.0
        spread_bps = ((self.ask-self.bid)/self.last*10000) if self.last and self.ask and self.bid else 0.0
        return {
            'ts': self.ts or int(time.time()*1000), 'last': self.last, 'bid': self.bid, 'ask': self.ask,
            'bid_depth': self.bid_depth, 'ask_depth': self.ask_depth, 'imbalance': imbalance,
            'buy_volume': self.buy_volume, 'sell_volume': self.sell_volume, 'trade_delta': trade_delta,
            'spread_bps': spread_bps, 'open_interest': self.open_interest, 'funding_rate': self.funding_rate,
        }


class RealtimeHub:
    def __init__(self, symbols):
        self.symbols = [s.upper() for s in symbols]
        self.states = {s: LiveState(s) for s in self.symbols}
        self.connected = False
        self.last_error = ''
        self._stop = asyncio.Event()
        self._last_saved = defaultdict(int)

    def snapshot(self, symbol):
        state = self.states.get(symbol.upper())
        return state.as_dict() if state else None

    def _args(self):
        args=[]
        for symbol in self.symbols:
            inst=f'{symbol}-USDT-SWAP'
            args += [
                {'channel':'books5','instId':inst},
                {'channel':'trades','instId':inst},
                {'channel':'open-interest','instId':inst},
                {'channel':'funding-rate','instId':inst},
            ]
        return args

    async def run(self):
        init_db()
        backoff=2
        while not self._stop.is_set():
            try:
                async with websockets.connect(WS_PUBLIC, ping_interval=20, ping_timeout=10, close_timeout=5, max_queue=2048) as ws:
                    await ws.send(json.dumps({'op':'subscribe','args':self._args()}))
                    self.connected=True; self.last_error=''; backoff=2
                    async for raw in ws:
                        if self._stop.is_set(): break
                        if raw == 'pong': continue
                        msg=json.loads(raw)
                        if 'event' in msg: continue
                        await self._handle(msg)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.connected=False; self.last_error=str(e)[:180]
                await asyncio.sleep(backoff)
                backoff=min(30,backoff*2)
        self.connected=False

    async def _handle(self, msg):
        arg=msg.get('arg') or {}; channel=arg.get('channel',''); inst=arg.get('instId','')
        symbol=inst.split('-')[0].upper() if inst else ''
        state=self.states.get(symbol)
        if not state: return
        data=msg.get('data') or []
        if channel.startswith('books') and data:
            d=data[0]; bids=d.get('bids') or []; asks=d.get('asks') or []
            if bids: state.bid=float(bids[0][0]); state.bid_depth=sum(float(x[1]) for x in bids[:5])
            if asks: state.ask=float(asks[0][0]); state.ask_depth=sum(float(x[1]) for x in asks[:5])
            if state.bid and state.ask: state.last=(state.bid+state.ask)/2
            state.ts=int(d.get('ts') or time.time()*1000)
        elif channel == 'trades':
            now=int(time.time()*1000)
            for d in data:
                px=float(d.get('px') or 0); sz=float(d.get('sz') or 0); side=d.get('side')
                if px: state.last=px
                state.trades.append((now,side,sz))
            cutoff=now-60_000
            while state.trades and state.trades[0][0] < cutoff: state.trades.popleft()
            state.buy_volume=sum(t[2] for t in state.trades if t[1]=='buy')
            state.sell_volume=sum(t[2] for t in state.trades if t[1]=='sell')
            state.ts=now
        elif channel == 'open-interest' and data:
            state.open_interest=float(data[0].get('oi') or 0); state.ts=int(data[0].get('ts') or time.time()*1000)
        elif channel == 'funding-rate' and data:
            state.funding_rate=float(data[0].get('fundingRate') or 0); state.ts=int(data[0].get('ts') or time.time()*1000)
        now=int(time.time()*1000)
        if now-self._last_saved[symbol] >= SNAPSHOT_SECONDS*1000:
            save_snapshot(symbol,state.as_dict()); self._last_saved[symbol]=now

    def stop(self):
        self._stop.set()


_HUB = None

def configure_hub(symbols):
    global _HUB
    _HUB=RealtimeHub(symbols)
    return _HUB

def get_hub(): return _HUB
