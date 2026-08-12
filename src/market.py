import os
import asyncio
import httpx
import pandas as pd

BASE=os.getenv('OKX_BASE_URL','https://www.okx.com').rstrip('/')
TF_TO_OKX={'5m':'5m','15m':'15m','1h':'1H','4h':'4H','1d':'1Dutc','1w':'1Wutc'}

async def _get(client, path, params):
    r=await client.get(f'{BASE}{path}',params=params)
    r.raise_for_status(); j=r.json()
    if j.get('code')!='0': raise RuntimeError(j.get('msg') or f'OKX error {path}')
    return j.get('data') or []


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
    async with httpx.AsyncClient(timeout=15.0) as client:
        rows=await _get(client,'/api/v5/market/candles',{'instId':inst,'bar':bar,'limit':str(min(limit,300))})
    if not rows: raise RuntimeError(f'No candles for {inst} {timeframe}')
    return _rows_to_df(rows)


async def fetch_history_candles(symbol: str,timeframe: str,target_bars: int=2160)->pd.DataFrame:
    """Fetch paginated historical candles from OKX public market history."""
    inst=f'{symbol.upper()}-USDT-SWAP'; bar=TF_TO_OKX[timeframe]
    target=max(300,min(int(target_bars),9000))
    all_rows=[]; after=None; seen=set()
    async with httpx.AsyncClient(timeout=20.0) as client:
        while len(all_rows) < target:
            params={'instId':inst,'bar':bar,'limit':'100'}
            if after is not None:
                params['after']=str(after)
            rows=await _get(client,'/api/v5/market/history-candles',params)
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
            if added == 0 or len(rows) < 2:
                break
            await asyncio.sleep(0.12)
    if not all_rows:
        raise RuntimeError(f'No historical candles for {inst} {timeframe}')
    return _rows_to_df(all_rows).tail(target).reset_index(drop=True)


async def fetch_backtest_candles(symbol: str,timeframe: str,target_bars: int=2160)->pd.DataFrame:
    """Combine up to 300 recent candles with paginated historical candles."""
    recent_task=asyncio.create_task(fetch_candles(symbol,timeframe,300))
    history_task=asyncio.create_task(fetch_history_candles(symbol,timeframe,target_bars))
    recent,history=await asyncio.gather(recent_task,history_task)
    df=pd.concat([history,recent],ignore_index=True)
    df=df.drop_duplicates('ts').sort_values('ts').reset_index(drop=True)
    return df.tail(target_bars).reset_index(drop=True)


async def fetch_public_metrics(symbol: str):
    inst=f'{symbol.upper()}-USDT-SWAP'
    async with httpx.AsyncClient(timeout=15.0) as client:
        ticker,oi,funding=await asyncio.gather(
            _get(client,'/api/v5/market/ticker',{'instId':inst}),
            _get(client,'/api/v5/public/open-interest',{'instId':inst}),
            _get(client,'/api/v5/public/funding-rate',{'instId':inst}),
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
