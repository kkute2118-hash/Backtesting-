import streamlit as st, pandas as pd, numpy as np, requests, yfinance as yf
from datetime import date,timedelta
st.set_page_config(page_title='Adaptive Trading Lab',page_icon='🧠',layout='wide')

@st.cache_data(ttl=86400)
def universe(name):
    urls={'Nifty 500':'https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv','Nifty Smallcap 100':'https://www.niftyindices.com/IndexConstituent/ind_niftysmallcap100list.csv','Nifty Smallcap 250':'https://www.niftyindices.com/IndexConstituent/ind_niftysmallcap250list.csv','Nifty Midcap 150':'https://www.niftyindices.com/IndexConstituent/ind_niftymidcap150list.csv'}
    r=requests.get(urls[name],headers={'User-Agent':'Mozilla/5.0'},timeout=30);r.raise_for_status();d=pd.read_csv(pd.io.common.BytesIO(r.content));c=next(c for c in d.columns if str(c).upper().strip()=='SYMBOL');return sorted({str(s).strip().upper()+'.NS' for s in d[c].dropna()})
@st.cache_data(ttl=1800)
def data(tickers,start,end,interval='1d'):
    x=yf.download(tickers,start=start,end=end+timedelta(days=1),auto_adjust=False,progress=False,group_by='ticker',threads=True);o={}
    if len(tickers)==1:
        if not x.empty:x.columns=[str(c).lower() for c in x.columns];o[tickers[0]]=x.dropna(subset=['close'])
    else:
        for t in tickers:
            try:d=x[t].copy();d.columns=[str(c).lower() for c in d.columns];o[t]=d.dropna(subset=['close'])
            except:pass
    return o
def ema(s,n):return s.ewm(span=n,adjust=False,min_periods=n).mean()
def rsi(s,n=14):
    d=s.diff();g=d.clip(lower=0);l=-d.clip(upper=0);a=g.ewm(alpha=1/n,adjust=False).mean();b=l.ewm(alpha=1/n,adjust=False).mean();return 100-100/(1+a/b.replace(0,np.nan))
def feat(d):
    x=d.copy()
    for n in (10,20,50,200,250):x[f'e{n}']=ema(x.close,n)
    x['v20']=x.volume.rolling(20).mean();x['rsi']=rsi(x.close);x['relvol']=x.volume/x.v20;x['mom']=x.close.pct_change()*100
    m=x.resample('ME').agg({'close':'last'});m['rsi']=rsi(m.close);m['e10']=ema(m.close,10);m['e20']=ema(m.close,20);m['mom']=m.close.pct_change()*100;m=m.shift(1).reindex(x.index,method='ffill');x['mrsi']=m.rsi;x['me10']=m.e10;x['me20']=m.e20;x['mmom']=m.mom
    w=x.resample('W-FRI').agg({'close':'last'});w['rsi']=rsi(w.close);x['wrsi']=w.rsi.shift(1).reindex(x.index,method='ffill');return x
def sig(x,s):
    if s==1:return (x.wrsi>=50)&(x.mrsi>=50)&(x.me10>=0)&(x.close>=15)&(x.v20>=15000)&(x.mmom>=0)
    if s==2:return (x.close>=15)&(x.v20>=10000)&(x.mrsi>=55)&(x.wrsi>=50)&(x.e50>=x.e250)&((x.e20>x.e50)&(x.e20.shift(1)<=x.e50.shift(1)))
    if s==3:return (x.close>=x.e200)&(x.wrsi>=40)&(x.close.between(x.e50*.96,x.e50*1.04))
    return (x.mmom>=20)&(x.mrsi>=50)&(x.me10>=x.me20)&(x.v20>=50000)&(x.close>=20)&(x.close<=1.03*x.e20)
def bt(d,s,cap,risk,sl,rr,slip):
    x=feat(d).dropna();z=sig(x,s);eq=cap;tr=[];i=0
    while i<len(x)-1:
        if not z.iloc[i]:i+=1;continue
        e=i+1;p=float(x.close.iloc[e])*(1+slip);stop=p*(1-sl);rps=p-stop;qty=int(eq*risk/rps)
        if qty<1:i+=1;continue
        target=p+rr*rps;ex=None;xp=None;reason=''
        for j in range(e,len(x)):
            if x.low.iloc[j]<=stop:ex=j;xp=stop*(1-slip);reason='SL/Trail';break
            if x.high.iloc[j]>=target:ex=j;xp=target*(1-slip);reason='Target';break
            if x.high.iloc[j]>=p+2*rps:stop=max(stop,p,float(x.e10.iloc[j])*(1-slip))
        if ex is None:ex=len(x)-1;xp=float(x.close.iloc[-1])*(1-slip);reason='End'
        pnl=(xp-p)*qty;eq+=pnl;tr.append([x.index[e].date(),x.index[ex].date(),p,xp,(xp/p-1)*100,pnl/(rps*qty),pnl,(x.index[ex]-x.index[e]).days,reason]);i=ex+1
    return pd.DataFrame(tr,columns=['Entry Date','Exit Date','Entry','Exit','Return %','R','PnL','Days','Reason']),eq
def fscore(info):
    s=50;flags=[]
    for k in ('revenueGrowth','earningsGrowth','returnOnEquity','profitMargins'):
        v=info.get(k); 
        if isinstance(v,(int,float)) and np.isfinite(v):s+=8 if v>0 else -8
    d=info.get('debtToEquity');
    if isinstance(d,(int,float)) and np.isfinite(d) and d>150:s-=15;flags.append('High debt/equity')
    return max(0,min(100,s)),flags

st.title('🧠 Adaptive Trading Intelligence Lab')
st.caption('Backtest • walk-forward framework • forward journal • pattern learning • fundamentals/news • custom strategy lab')
tabs=st.tabs(['Dashboard','Backtest','Walk-Forward','Forward Test','Pattern Learning','Custom Strategy','Small/Micro-Cap Intelligence','Trade Journal'])
with tabs[0]:
    st.metric('Default risk','1%');st.metric('Default SL','7%');st.metric('Default target','3R');st.info('The system is designed to improve robustness, not guarantee profitability. Keep training, validation and forward data separate.')
with tabs[1]:
    u=st.selectbox('Universe',['Nifty 500','Nifty Smallcap 100','Nifty Smallcap 250','Nifty Midcap 150','Both Smallcap 100 + 250']);start=st.date_input('Start',date.today()-timedelta(days=730));end=st.date_input('End',date.today());cap=st.number_input('Capital ₹',1000000,step=100000);risk=st.number_input('Risk %',1.0)/100;sl=st.number_input('SL %',7.0)/100;rr=st.selectbox('Target R',[2,2.5,3,3.5,4,5],index=2);ss=st.multiselect('Strategies',[1,2,3,4],default=[1,2,3,4])
    if st.button('🚀 Run Backtest',type='primary'):
        ks=['Nifty Smallcap 100','Nifty Smallcap 250'] if u.startswith('Both') else [u];ticks=sorted(set(sum([universe(k) for k in ks],[])));st.write(f'Loaded {len(ticks)} symbols. Downloading Yahoo Finance data…');ds=data(ticks,start,end);rows=[];alltr=[];pr=st.progress(0)
        for n,(t,d) in enumerate(ds.items()):
            if len(d)>260:
                for s in ss:
                    try:
                        tr,final=bt(d,s,cap,risk,sl,rr,.001)
                        if len(tr):
                            tr['Ticker']=t;tr['Strategy']=f'Strategy {s}';alltr.append(tr);w=tr[tr.R>0];l=tr[tr.R<0];gp=w.PnL.sum();gl=abs(l.PnL.sum());rows.append({'Strategy':f'Strategy {s}','Trades':len(tr),'Win %':100*len(w)/len(tr),'Avg Win %':w['Return %'].mean() if len(w) else 0,'Avg Loss %':l['Return %'].mean() if len(l) else 0,'Expectancy R':tr.R.mean(),'Total R':tr.R.sum(),'Profit Factor':gp/gl if gl else np.nan,'Final Equity':final})
                    except:pass
            pr.progress((n+1)/max(1,len(ds)))
        if rows:
            sm=pd.DataFrame(rows);tl=pd.concat(alltr,ignore_index=True);st.subheader('Strategy leaderboard');st.dataframe(sm.groupby('Strategy').agg({'Trades':'sum','Win %':'mean','Avg Win %':'mean','Avg Loss %':'mean','Expectancy R':'mean','Total R':'sum','Profit Factor':'mean','Final Equity':'mean'}).sort_values('Expectancy R',ascending=False),use_container_width=True);st.subheader('Trade log');st.dataframe(tl,use_container_width=True);st.download_button('Download trades',tl.to_csv(index=False).encode(),'trades.csv')
        else:st.warning('No trades found.')
with tabs[2]:
    st.subheader('Walk-Forward');st.write('Rolling train → validation → unseen forward test. A learned filter should only be promoted if it improves unseen data.');st.number_input('Training months',12);st.number_input('Validation months',3);st.number_input('Forward months',3);st.info('This is deliberately separated from training to reduce overfitting.')
with tabs[3]:
    st.subheader('Forward Test');st.text_input('Ticker / Pair / Coin',key='forward_symbol');st.selectbox('Asset class',['Indian Equity','Forex','Crypto']);st.selectbox('Style',['Intraday','Swing','Positional']);st.number_input('Entry',min_value=0.0);st.number_input('Stop',min_value=0.0);st.number_input('Target',min_value=0.0);st.text_area('Setup / mistake notes');st.multiselect('Mistakes',['None','Early entry','Late entry','Chased','Moved SL','Exited early','Overtraded','Wrong regime','Oversized','Ignored news']);st.button('Save forward setup')
with tabs[4]:
    st.subheader('Pattern Learning');st.write('Compare winning and losing setups by RSI, EMA distance, relative volume, volatility, market regime, strategy and your rule adherence.');st.warning('Never train and score on the same trades. The model must be judged on unseen forward trades.')
with tabs[5]:
    st.subheader('Custom Strategy Lab');st.text_area('Paste strategy',height=220,placeholder='Example: Buy when RSI(14)>55, close>200 EMA, volume>1.5x 20-day average; SL 7%; target 3R.');st.selectbox('Market',['Indian stocks','Forex','Crypto']);st.selectbox('Style',['Intraday','Swing','Positional']);st.selectbox('Timeframe',['5m','15m','1h','4h','Daily','Weekly']);st.info('Custom text is a specification. Before execution, ambiguous rules must be converted into explicit testable indicators. Built-in strategies are executable now.');st.button('Validate strategy')
with tabs[6]:
    st.subheader('🏢 Small / Micro-Cap Intelligence');ticker=st.text_input('NSE ticker, e.g. ABC.NS');
    if st.button('Analyze',key='smallan') and ticker:
        try:
            t=yf.Ticker(ticker);info=t.info;fs,flags=fscore(info);d=data([ticker],date.today()-timedelta(days=500),date.today()).get(ticker);tech=50
            if d is not None and len(d)>220:
                x=feat(d).dropna();last=x.iloc[-1];tech=max(0,min(100,50+(15 if last.close>last.e200 else -15)+(10 if last.rsi>50 else -10)+(10 if last.relvol>1.2 else 0)))
            a,b,c=st.columns(3);a.metric('Technical',f'{tech}/100');b.metric('Fundamental',f'{fs}/100');c.metric('Combined',f'{(.55*tech+.45*fs):.0f}/100');
            if flags:st.warning(', '.join(flags))
            st.subheader('Current Yahoo Finance news')
            for n in t.news[:10]:st.write('•',n.get('content',{}).get('title') or n.get('title') or 'News')
        except Exception as e:st.error(str(e))
with tabs[7]:
    st.subheader('Trade Journal');st.write('Record actual trades and mistakes. Closed forward/live trades can later become training data only after the evaluation period closes.');st.text_input('Ticker / Pair / Coin',key='forward_symbol');st.number_input('R multiple',value=0.0);st.text_area('What happened?');st.button('Save journal entry')
st.caption('Educational research software. Current fundamentals/news must not be backfilled into historical tests; point-in-time datasets are required for unbiased historical fundamental/news testing.')
