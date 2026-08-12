import os
import asyncio
import time
import httpx
import pandas as pd

BASE=os.getenv('OKX_BASE_URL','https://www.okx.com').rstrip('/')
TF_TO_OKX={'5m':'5m','15m':'15m','1h':'1H','4h':'4H','1d':'1Dutc','1w':'1Wutc'}

# OKX public history is IP-rate-limited. Be deliberately conservative because
# cloud egress IPs may be shared with other workloads.
_HISTORY_LOCK=asyncio.Lock()
_LAST_HISTORY_REQUEST=0.0
_HISTORY_MIN_INTERVAL=float(os.getenv('OKX_HISTORY_MIN_INTERVAL','1.10'))
_HISTORY_CACHE_TTL=int(os.getenv('OKX_HISTORY_CACHE_TTL','1800'))
_HISTORY_CACHE={}

async def _get(client, path, params, retries=6, rate_limited=False):
    global _LAST_HISTORY_REQUEST
    for attempt in range(retries):
        if rate_limited:
            wait=max(0.0,_HISTORY_MIN_INTERVAL-(time.monotonic()-_LAST_HISTORY_REQUEST))
            if wait:
                await asyncio.sleep(wait)
        r=await client.get(f'{BASE}{path}',params=params)
        if rate_limited:
            _LAST_HISTORY_REQUEST=time.monotonic()
        if r.status_code==429:
            retry_after=r.headers.get('Retry-After')
            try:
                delay=float(retry_after) if retry_after else min(30.0,1.5*(2**attempt))
            except Exception:
                delay=min(30.0,1.5*(2**attempt))
            await asyncio.sleep(delay)
            continue
        r.raise_for_status()
        j=r.json()
        if j.get('code')!='0':
            raise RuntimeError(j.get('msg') or f'OKX error {path}')
        return j.get('data') or []
    raise RuntimeError('OKX rate limit persisted after retries. Wait 1–2 minutes and retry.')


def _rows_to_df(rows):
    if not rows:
        return pd.DataFrame(columns=['ts','open','high','low','close','vol'])
    cols=['ts','open','high','low','close','vol','volCcy','volCcyQuote','confirm']
    df=pd.DataFrame(rows,columns=cols[:len(rows[0])])
    for c in ['open','high','low','close','vol']:
        df[c]=pd.to_numeric(df[c],errors='coerce')
    df['ts']=pd.to_datetime(pd.to_numeric(df.ts),unit='ms',utc=True)
    return df.drop_duplicates('ts').sort_values('ts').reset_index(drop=True)


async def fetch_candles(symbol: str,timeframe: str,limit: int=240)->pd.DataFrame:
    inst=f'{symbol.upper()}-USDT-SWAP'; bar=TF_TO_OKX[timeframe]
    async with httpx.AsyncClient(timeout=20.0) as client:
        rows=await _get(client,'/api/v5/market/candles',{'instId':inst,'bar':bar,'limit':str(min(limit,300))},retries=4)
    if not rows: raise RuntimeError(f'No candles for {inst} {timeframe}')
    return _rows_to_df(rows)


async def fetch_history_candles(symbol: str,timeframe: str,target_bars: int=2160)->pd.DataFrame:
    """Fetch historical candles with serialized requests, conservative pacing and cache."""
    inst=f'{symbol.upper()}-USDT-SWAP'; bar=TF_TO_OKX[timeframe]
    target=max(300,min(int(target_bars),9000))
    key=(symbol.upper(),timeframe,target)
    cached=_HISTORY_CACHE.get(key)
    if cached and time.monotonic()-cached[0] < _HISTORY_CACHE_TTL:
        return cached[1].copy()

    async with _HISTORY_LOCK:
        cached=_HISTORY_CACHE.get(key)
        if cached and time.monotonic()-cached[0] < _HISTORY_CACHE_TTL:
            return cached[1].copy()

        all_rows=[]; after=None; seen=set()
        async with httpx.AsyncClient(timeout=35.0) as client:
            while len(all_rows) < target:
                params={'instId':inst,'bar':bar,'limit':'100'}
                if after is not None:
                    params['after']=str(after)
                rows=await _get(client,'/api/v5/market/history-candles',params,retries=7,rate_limited=True)
                if not rows:
                    break
                added=0
                for row in rows:
                    ts=int(row[0])
                    if ts not in seen:
                        seen.add(ts); all_rows.append(row); added+=1
                oldest=min(int(r[0]) for r in rows)
                if after is not None and oldest >= int(after):
                    break
                after=oldest
                if added==0 or len(rows)<2:
                    break
        if not all_rows:
            raise RuntimeError(f'No historical candles for {inst} {timeframe}')
        df=_rows_to_df(all_rows).tail(target).reset_index(drop=True)
        _HISTORY_CACHE[key]=(time.monotonic(),df.copy())
        return df


async def fetch_backtest_candles(symbol: str,timeframe: str,target_bars: int=2160)->pd.DataFrame:
    """Fetch history first, then recent candles; avoids concurrent bursts against OKX."""
    history=await fetch_history_candles(symbol,timeframe,target_bars)
    await asyncio.sleep(0.6)
    recent=await fetch_candles(symbol,timeframe,300)
    df=pd.concat([history,recent],ignore_index=True)
    df=df.drop_duplicates('ts').sort_values('ts').reset_index(drop=True)
    return df.tail(target_bars).reset_index(drop=True)


async def fetch_public_metrics(symbol: str):
    inst=f'{symbol.upper()}-USDT-SWAP'
    async with httpx.AsyncClient(timeout=15.0) as client:
        ticker,oi,funding=await asyncio.gather(
            _get(client,'/api/v5/market/ticker',{'instId':inst},retries=3),
            _get(client,'/api/v5/public/open-interest',{'instId':inst},retries=3),
            _get(client,'/api/v5/public/funding-rate',{'instId':inst},retries=3),
        )
    t=(ticker or [{}])[0]; o=(oi or [{}])[0]; f=(funding or [{}])[0]
    last=float(t.get('last') or 0); open24=float(t.get('open24h') or 0)
    return {
        'last':last,'open24h':open24,
        'high24h':float(t.get('high24h') or 0),'low24h':float(t.get('low24h') or 0),
        'vol24h':float(t.get('vol24h') or 0),'open_interest':float(o.get('oi') or 0),
        'funding_rate':float(f.get('fundingRate') or 0),'next_funding_time':f.get('nextFundingTime') or f.get('fundingTime'),
        'price_change_pct': ((last/open24)-1)*100 if last and open24 else 0,
        'oi_change_pct':0.0,
    }
