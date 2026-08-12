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

async def fetch_candles(symbol: str,timeframe: str,limit: int=240)->pd.DataFrame:
    inst=f'{symbol.upper()}-USDT-SWAP'; bar=TF_TO_OKX[timeframe]
    async with httpx.AsyncClient(timeout=15.0) as client:
        rows=await _get(client,'/api/v5/market/candles',{'instId':inst,'bar':bar,'limit':str(min(limit,300))})
    if not rows: raise RuntimeError(f'No candles for {inst} {timeframe}')
    cols=['ts','open','high','low','close','vol','volCcy','volCcyQuote','confirm']
    df=pd.DataFrame(rows,columns=cols[:len(rows[0])])
    for c in ['open','high','low','close','vol']: df[c]=pd.to_numeric(df[c],errors='coerce')
    df['ts']=pd.to_datetime(pd.to_numeric(df.ts),unit='ms',utc=True)
    return df.sort_values('ts').reset_index(drop=True)

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
