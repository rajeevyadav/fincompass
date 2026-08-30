from __future__ import annotations
import numpy as np, pandas as pd

def sma(s,n): return pd.to_numeric(s,errors='coerce').rolling(n,min_periods=n).mean()
def ema(s,n): return pd.to_numeric(s,errors='coerce').ewm(span=n,adjust=False,min_periods=n).mean()
def rsi(close,n=14):
    c=pd.to_numeric(close,errors='coerce'); d=c.diff(); up=d.clip(lower=0).ewm(alpha=1/n,adjust=False,min_periods=n).mean(); dn=(-d.clip(upper=0)).ewm(alpha=1/n,adjust=False,min_periods=n).mean(); rs=up/dn.replace(0,np.nan); return 100-100/(1+rs)
def macd(close,fast=12,slow=26,signal=9):
    line=ema(close,fast)-ema(close,slow); sig=line.ewm(span=signal,adjust=False,min_periods=signal).mean(); return line,sig,line-sig
def bollinger(close,n=20,k=2):
    c=pd.to_numeric(close,errors='coerce'); m=c.rolling(n,min_periods=n).mean(); sd=c.rolling(n,min_periods=n).std(); return m,m+k*sd,m-k*sd
def atr(frame,n=14):
    h=pd.to_numeric(frame['High'],errors='coerce'); l=pd.to_numeric(frame['Low'],errors='coerce'); c=pd.to_numeric(frame['Close'],errors='coerce'); pc=c.shift(1); tr=pd.concat([(h-l).abs(),(h-pc).abs(),(l-pc).abs()],axis=1).max(axis=1); return tr.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
def technical_summary(frame):
    c=frame['Close']; rs=rsi(c); m,s,h=macd(c); mid,up,lo=bollinger(c); last=float(c.dropna().iloc[-1])
    out={'close':last,'sma_50':float(sma(c,50).iloc[-1]) if len(c)>=50 else None,'sma_200':float(sma(c,200).iloc[-1]) if len(c)>=200 else None,'rsi_14':float(rs.iloc[-1]) if pd.notna(rs.iloc[-1]) else None,'macd':float(m.iloc[-1]) if pd.notna(m.iloc[-1]) else None,'macd_signal':float(s.iloc[-1]) if pd.notna(s.iloc[-1]) else None,'bollinger_mid':float(mid.iloc[-1]) if pd.notna(mid.iloc[-1]) else None,'bollinger_upper':float(up.iloc[-1]) if pd.notna(up.iloc[-1]) else None,'bollinger_lower':float(lo.iloc[-1]) if pd.notna(lo.iloc[-1]) else None}
    if {'High','Low','Close'}.issubset(frame.columns):
        a=atr(frame); out['atr_14']=float(a.iloc[-1]) if pd.notna(a.iloc[-1]) else None
    return out
