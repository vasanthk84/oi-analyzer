import uvicorn
from fastapi import FastAPI, HTTPException
from kiteconnect import KiteConnect
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
import os
import pytz  # NEW: For Timezone handling
from dotenv import load_dotenv

# --- CONFIGURATION ---
load_dotenv()

API_KEY = os.getenv("KITE_API_KEY")
ACCESS_TOKEN = os.getenv("KITE_ACCESS_TOKEN")

# Initialize App & Logger
app = FastAPI()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NiftyEngine")

# Validation
if not API_KEY or not ACCESS_TOKEN:
    logger.error("CRITICAL: API Credentials not found in .env file")

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
    """Returns current time in Indian Standard Time"""
    utc_now = datetime.now(pytz.utc)
    ist_tz = pytz.timezone('Asia/Kolkata')
    return utc_now.astimezone(ist_tz)

def refresh_instruments():
    try:
        logger.info("Fetching Master Instrument Dump...")
        instruments = kite.instruments("NFO")
        df = pd.DataFrame(instruments)
        df = df[df['name'] == 'NIFTY']
        
        df['expiry'] = pd.to_datetime(df['expiry']).dt.date
        today = datetime.now().date()
        future_expiries = df[df['expiry'] >= today]['expiry'].unique()
        
        if len(future_expiries) == 0:
            raise Exception("No future expiries found")
            
        nearest_expiry = sorted(future_expiries)[0]
        logger.info(f"Selected Expiry: {nearest_expiry}")
        
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

# Run once on startup
try:
    if API_KEY and ACCESS_TOKEN:
        refresh_instruments()
except:
    logger.warning("Could not initialize instruments.")

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

@app.get("/analyze")
def get_analysis():
    if not instrument_cache["nifty_tokens"]:
        refresh_instruments()
        if not instrument_cache["nifty_tokens"]:
             raise HTTPException(status_code=500, detail="Instruments not loaded.")

    try:
        # 1. Fetch Spot
        quote_nifty = kite.quote(["NSE:NIFTY 50"])
        nifty_spot = quote_nifty["NSE:NIFTY 50"]["last_price"]
        
        # 2. Filter Strikes (Spot +/- 600)
        relevant_tokens = []
        token_details = []
        
        for token, details in instrument_cache["strike_map"].items():
            if abs(details['strike'] - nifty_spot) <= 600:
                relevant_tokens.append(token)
                token_details.append({**details, "token": token})
        
        # 3. Fetch Quotes
        quotes = kite.quote(relevant_tokens)
        
        # 4. Build DataFrame
        data = []
        for det in token_details:
            q = quotes.get(str(det['token'])) or quotes.get(det['token'])
            if q:
                price_change = q['last_price'] - q['ohlc']['close']
                data.append({
                    "strike": det['strike'],
                    "type": det['type'],
                    "oi": q['oi'],
                    "ltp": q['last_price'],
                    "price_change": price_change,
                    "volume": q['volume']
                })
        
        df = pd.DataFrame(data)
        ce_df = df[df['type'] == 'CE'].set_index('strike')
        pe_df = df[df['type'] == 'PE'].set_index('strike')
        
        # --- STRANGLE LOGIC ---
        res_strike = ce_df['oi'].idxmax()
        sup_strike = pe_df['oi'].idxmax()
        rec_call_strike = res_strike + 50
        rec_put_strike = sup_strike - 50
        
        rec_call_ltp = ce_df.loc[rec_call_strike]['ltp'] if rec_call_strike in ce_df.index else 0
        rec_put_ltp = pe_df.loc[rec_put_strike]['ltp'] if rec_put_strike in pe_df.index else 0
        est_strangle_credit = rec_call_ltp + rec_put_ltp

        # --- STRADDLE LOGIC ---
        # Find ATM Strike (nearest 50)
        atm_strike = round(nifty_spot / 50) * 50
        
        atm_ce_ltp = ce_df.loc[atm_strike]['ltp'] if atm_strike in ce_df.index else 0
        atm_pe_ltp = pe_df.loc[atm_strike]['ltp'] if atm_strike in pe_df.index else 0
        
        straddle_cost = atm_ce_ltp + atm_pe_ltp
        upper_be = atm_strike + straddle_cost
        lower_be = atm_strike - straddle_cost
        safety_margin = round((straddle_cost / nifty_spot) * 100, 2)

        # Range PCR
        total_ce_oi = ce_df['oi'].sum()
        total_pe_oi = pe_df['oi'].sum()
        pcr = round(total_pe_oi / total_ce_oi, 2) if total_ce_oi > 0 else 0
        
        # Max Pain
        max_pain = calculate_max_pain(df)
        
        # Chart Data
        combined_idx = sorted(list(set(ce_df.index) | set(pe_df.index)))
        
        chart_data = {
            "strikes": combined_idx,
            "ce_oi": [int(ce_df.loc[s]['oi']) if s in ce_df.index else 0 for s in combined_idx],
            "pe_oi": [int(pe_df.loc[s]['oi']) if s in pe_df.index else 0 for s in combined_idx],
            "ce_vol": [int(ce_df.loc[s]['volume']) if s in ce_df.index else 0 for s in combined_idx], 
            "pe_vol": [int(pe_df.loc[s]['volume']) if s in pe_df.index else 0 for s in combined_idx], 
        }

        # Current IST Time
        ist_now = get_ist_time()

        return {
            "timestamp": ist_now.strftime("%H:%M:%S"),
            "is_market_open": 9 <= ist_now.hour < 16, # Simple check
            "nifty_spot": nifty_spot,
            "expiry": instrument_cache["expiry"],
            "metrics": {
                "max_pain": float(max_pain),
                "pcr": pcr,
                "support": float(sup_strike),
                "resistance": float(res_strike)
            },
            "strangle_intel": {
                "rec_call": float(rec_call_strike),
                "rec_put": float(rec_put_strike),
                "est_credit": float(est_strangle_credit),
                "range_width": float(rec_call_strike - rec_put_strike)
            },
            "straddle_intel": {
                "atm_strike": float(atm_strike),
                "cost": float(straddle_cost),
                "upper_be": float(upper_be),
                "lower_be": float(lower_be),
                "safety_pct": float(safety_margin)
            },
            "chart_data": chart_data
        }

    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)