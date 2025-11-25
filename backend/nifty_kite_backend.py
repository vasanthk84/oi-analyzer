import uvicorn
from fastapi import FastAPI, HTTPException
from kiteconnect import KiteConnect
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
import logging
import os
import pytz 
import sqlite3
from dotenv import load_dotenv

# --- CONFIGURATION ---
load_dotenv()

API_KEY = os.getenv("KITE_API_KEY")
ACCESS_TOKEN = os.getenv("KITE_ACCESS_TOKEN")
DB_FILE = "backend/nifty_history.db" # Path relative to root run

# Initialize App & Logger
app = FastAPI()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NiftyEngine")

# Global Cache
instrument_cache = {
    "nifty_tokens": [],
    "expiry": None,
    "strike_map": {} 
}

# Initialize Kite
try:
    kite = KiteConnect(api_key=API_KEY)
    kite.set_access_token(ACCESS_TOKEN)
except Exception as e:
    logger.error(f"Failed to initialize KiteConnect: {e}")

def get_ist_time():
    utc_now = datetime.now(pytz.utc)
    ist_tz = pytz.timezone('Asia/Kolkata')
    return utc_now.astimezone(ist_tz)

def refresh_instruments():
    try:
        instruments = kite.instruments("NFO")
        df = pd.DataFrame(instruments)
        df = df[df['name'] == 'NIFTY']
        df['expiry'] = pd.to_datetime(df['expiry']).dt.date
        today = datetime.now().date()
        future_expiries = df[df['expiry'] >= today]['expiry'].unique()
        if len(future_expiries) == 0: raise Exception("No future expiries")
        nearest_expiry = sorted(future_expiries)[0]
        
        expiry_df = df[df['expiry'] == nearest_expiry]
        token_map = {}
        tokens = []
        for _, row in expiry_df.iterrows():
            tokens.append(row['instrument_token'])
            token_map[row['instrument_token']] = {
                "strike": row['strike'],
                "type": row['instrument_type'],
                "symbol": row['tradingsymbol']
            }
        instrument_cache["nifty_tokens"] = tokens
        instrument_cache["expiry"] = str(nearest_expiry)
        instrument_cache["strike_map"] = token_map
        logger.info(f"Cached {len(tokens)} contracts")
    except Exception as e:
        logger.error(f"Error fetching instruments: {e}")

# Initial Fetch
try:
    if API_KEY and ACCESS_TOKEN: refresh_instruments()
except: pass

def calculate_max_pain(chain_df):
    strikes = chain_df['strike'].unique()
    strikes.sort()
    losses = []
    for expiry_price in strikes:
        ce_loss = np.maximum(0, expiry_price - chain_df[chain_df['type'] == 'CE']['strike']) * chain_df[chain_df['type'] == 'CE']['oi']
        pe_loss = np.maximum(0, chain_df[chain_df['type'] == 'PE']['strike'] - expiry_price) * chain_df[chain_df['type'] == 'PE']['oi']
        losses.append(ce_loss.sum() + pe_loss.sum())
    min_loss_idx = np.argmin(losses)
    return strikes[min_loss_idx]

# --- HISTORICAL LOGIC (PURE DB - NO KITE HISTORICAL API) ---

def get_next_expiry_date(current_date):
    switchover_date = date(2025, 9, 1)
    if current_date < switchover_date:
        target_weekday = 3 # Thursday
    else:
        target_weekday = 1 # Tuesday
    days_ahead = target_weekday - current_date.weekday()
    if days_ahead < 0: days_ahead += 7
    return current_date + timedelta(days=days_ahead)

def fetch_nifty_history_db():
    """
    Fetches history ONLY from local SQLite DB.
    Does NOT attempt to call Kite Historical API.
    """
    try:
        conn = sqlite3.connect(DB_FILE)
        query = "SELECT * FROM nifty_ohlc ORDER BY date DESC LIMIT 365"
        df = pd.read_sql_query(query, conn)
        conn.close()
        return df
    except Exception as e:
        logger.error(f"DB Fetch Error: {e}")
        return pd.DataFrame()

@app.post("/update_daily_ohlc")
def update_daily_ohlc():
    """
    Fetches TODAY's snapshot from Kite Quote (Allowed on Base Plan)
    and saves it to the local DB to fill daily gaps.
    """
    try:
        # Fetch Nifty 50 Quote (Base API)
        quote = kite.quote(["NSE:NIFTY 50"])
        ohlc = quote["NSE:NIFTY 50"]["ohlc"]
        current_price = quote["NSE:NIFTY 50"]["last_price"]
        
        today_str = str(datetime.now().date())
        
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO nifty_ohlc (date, open, high, low, close)
            VALUES (?, ?, ?, ?, ?)
        ''', (today_str, ohlc['open'], ohlc['high'], ohlc['low'], current_price))
        
        conn.commit()
        conn.close()
        
        return {"status": "success", "message": f"Saved Data for {today_str}: Close {current_price}"}
        
    except Exception as e:
        logger.error(f"Daily Update Failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/historical_analysis")
def get_historical_analysis():
    try:
        # 1. Setup Context
        today = datetime.now().date()
        expiry_today = get_next_expiry_date(today)
        days_to_expiry = (expiry_today - today).days
        
        # 2. Get Live Spot (For Trade Suggestions)
        quote_nifty = kite.quote(["NSE:NIFTY 50"])
        spot = quote_nifty["NSE:NIFTY 50"]["last_price"]
        
        # 3. Fetch from Local DB
        df = fetch_nifty_history_db()
        
        avg_range = 0
        max_range = 0
        std_dev = 0
        sample_size = 0
        
        if not df.empty:
            df['date'] = pd.to_datetime(df['date']).dt.date
            relevant_moves = []
            
            for index, row in df.iterrows():
                row_date = row['date']
                hist_expiry = get_next_expiry_date(row_date)
                hist_dte = (hist_expiry - row_date).days
                
                if hist_dte == days_to_expiry:
                    high_low_range = row['high'] - row['low']
                    relevant_moves.append({"range": high_low_range})
            
            if relevant_moves:
                stats_df = pd.DataFrame(relevant_moves)
                avg_range = stats_df['range'].mean()
                std_dev = stats_df['range'].std()
                max_range = stats_df['range'].max()
                sample_size = len(stats_df)
        
        # 4. Fallback (If DB is empty or no matches found)
        # Use Straddle Price proxy if historical data is missing
        if sample_size == 0:
            # Calculate Live ATM Straddle Cost as a volatility proxy
            atm_strike = round(spot / 50) * 50
            straddle_cost = 0
            
            # Quick Straddle fetch
            for t, details in instrument_cache["strike_map"].items():
                if details['strike'] == atm_strike:
                    try:
                        q = kite.quote(str(t))
                        straddle_cost += q[str(t)]['last_price']
                    except: pass
            
            # Safety default if fetch fails
            if straddle_cost == 0: straddle_cost = spot * 0.01 

            avg_range = straddle_cost * 0.8 
            max_range = straddle_cost * 1.5
            std_dev = straddle_cost * 0.2

        # 5. Calculate Buffers
        cons_buffer = avg_range + (2 * std_dev)
        mod_buffer = avg_range + (1 * std_dev)
        agg_buffer = avg_range
        
        # 6. Generate Trade Levels
        def round50(n): return round(n / 50) * 50

        suggestions = {
            "conservative": {
                "call": round50(spot + cons_buffer),
                "put": round50(spot - cons_buffer),
                "prob_worthless": "High (Safe)"
            },
            "moderate": {
                "call": round50(spot + mod_buffer),
                "put": round50(spot - mod_buffer),
                "prob_worthless": "Medium"
            },
            "aggressive": {
                "call": round50(spot + agg_buffer),
                "put": round50(spot - agg_buffer),
                "prob_worthless": "Low (Risky)"
            }
        }
        
        # 0 DTE Gamma Blast Adjustment (Use Max Range instead of Avg)
        if days_to_expiry == 0:
             suggestions["aggressive"]["call"] = round50(spot + max_range)
             suggestions["aggressive"]["put"] = round50(spot - max_range)

        return {
            "dte": days_to_expiry,
            "source": f"Local DB ({sample_size} matches)" if sample_size > 0 else "Live Volatility Proxy",
            "expiry_date": str(expiry_today),
            "sample_size": sample_size,
            "stats": {
                "avg_range": round(avg_range, 2),
                "max_range": round(max_range, 2),
                "std_dev": round(std_dev, 2)
            },
            "suggestions": suggestions,
            "gamma_blast_risk": (days_to_expiry == 0)
        }

    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        return {"stats": {}, "suggestions": {"conservative":{}, "moderate":{}, "aggressive":{}}}

@app.get("/analyze")
def get_analysis():
    if not instrument_cache["nifty_tokens"]:
        refresh_instruments()
        if not instrument_cache["nifty_tokens"]: raise HTTPException(status_code=500, detail="Instruments not loaded.")
    try:
        quote_nifty = kite.quote(["NSE:NIFTY 50"])
        nifty_spot = quote_nifty["NSE:NIFTY 50"]["last_price"]
        
        relevant_tokens = []
        token_details = []
        for token, details in instrument_cache["strike_map"].items():
            if abs(details['strike'] - nifty_spot) <= 600:
                relevant_tokens.append(token)
                token_details.append({**details, "token": token})
        
        quotes = kite.quote(relevant_tokens)
        data = []
        for det in token_details:
            q = quotes.get(str(det['token'])) or quotes.get(det['token'])
            if q:
                price_change = q['last_price'] - q['ohlc']['close']
                data.append({ "strike": det['strike'], "type": det['type'], "oi": q['oi'], "ltp": q['last_price'], "price_change": price_change, "volume": q['volume'] })
        
        df = pd.DataFrame(data)
        ce_df = df[df['type'] == 'CE'].set_index('strike')
        pe_df = df[df['type'] == 'PE'].set_index('strike')
        
        res_strike = ce_df['oi'].idxmax()
        sup_strike = pe_df['oi'].idxmax()
        rec_call_strike = res_strike + 50
        rec_put_strike = sup_strike - 50
        rec_call_ltp = ce_df.loc[rec_call_strike]['ltp'] if rec_call_strike in ce_df.index else 0
        rec_put_ltp = pe_df.loc[rec_put_strike]['ltp'] if rec_put_strike in pe_df.index else 0
        est_strangle_credit = rec_call_ltp + rec_put_ltp
        
        atm_strike = round(nifty_spot / 50) * 50
        atm_ce_ltp = ce_df.loc[atm_strike]['ltp'] if atm_strike in ce_df.index else 0
        atm_pe_ltp = pe_df.loc[atm_strike]['ltp'] if atm_strike in pe_df.index else 0
        straddle_cost = atm_ce_ltp + atm_pe_ltp
        upper_be = atm_strike + straddle_cost
        lower_be = atm_strike - straddle_cost
        safety_margin = round((straddle_cost / nifty_spot) * 100, 2)
        
        total_ce_oi = ce_df['oi'].sum()
        total_pe_oi = pe_df['oi'].sum()
        pcr = round(total_pe_oi / total_ce_oi, 2) if total_ce_oi > 0 else 0
        max_pain = calculate_max_pain(df)
        
        combined_idx = sorted(list(set(ce_df.index) | set(pe_df.index)))
        chart_data = {
            "strikes": combined_idx,
            "ce_oi": [int(ce_df.loc[s]['oi']) if s in ce_df.index else 0 for s in combined_idx],
            "pe_oi": [int(pe_df.loc[s]['oi']) if s in pe_df.index else 0 for s in combined_idx],
            "ce_vol": [int(ce_df.loc[s]['volume']) if s in ce_df.index else 0 for s in combined_idx], 
            "pe_vol": [int(pe_df.loc[s]['volume']) if s in pe_df.index else 0 for s in combined_idx], 
        }
        ist_now = get_ist_time()
        return {
            "timestamp": ist_now.strftime("%H:%M:%S"),
            "is_market_open": 9 <= ist_now.hour < 16,
            "nifty_spot": nifty_spot,
            "expiry": instrument_cache["expiry"],
            "metrics": { "max_pain": float(max_pain), "pcr": pcr, "support": float(sup_strike), "resistance": float(res_strike) },
            "strangle_intel": { "rec_call": float(rec_call_strike), "rec_put": float(rec_put_strike), "est_credit": float(est_strangle_credit), "range_width": float(rec_call_strike - rec_put_strike) },
            "straddle_intel": { "atm_strike": float(atm_strike), "cost": float(straddle_cost), "upper_be": float(upper_be), "lower_be": float(lower_be), "safety_pct": float(safety_margin) },
            "chart_data": chart_data
        }
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)