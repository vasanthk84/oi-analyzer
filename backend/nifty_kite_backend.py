import uvicorn
from fastapi import FastAPI, HTTPException, Body
from kiteconnect import KiteConnect
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
import logging
import os
import pytz 
import sqlite3
import math
from dotenv import load_dotenv

# --- CONFIGURATION ---
load_dotenv()

API_KEY = os.getenv("KITE_API_KEY")
ACCESS_TOKEN = os.getenv("KITE_ACCESS_TOKEN")
DB_FILE = "backend/nifty_history.db" 

app = FastAPI()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NiftyEngine")

instrument_cache = { "nifty_tokens": [], "expiry": None, "strike_map": {} }

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
            token_map[row['instrument_token']] = { "strike": row['strike'], "type": row['instrument_type'], "symbol": row['tradingsymbol'] }
        instrument_cache["nifty_tokens"] = tokens
        instrument_cache["expiry"] = str(nearest_expiry)
        instrument_cache["strike_map"] = token_map
        logger.info(f"Cached {len(tokens)} contracts")
    except Exception as e:
        logger.error(f"Error fetching instruments: {e}")

try:
    if API_KEY and ACCESS_TOKEN:
        refresh_instruments()
except Exception as e:
    logger.warning(f"Initial refresh skipped: {e}")

# ... (Keep Max Pain, Greeks, Historical, RSI Logic same as previous file - omitted to save space, assume they exist) ...
# RE-INSERTING HELPER FUNCTIONS FOR COMPLETENESS TO AVOID ERRORS
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

def norm_cdf(x): return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0
def norm_pdf(x): return math.exp(-0.5 * x ** 2) / math.sqrt(2 * math.pi)
def calculate_greeks(S, K, T, r, sigma, option_type):
    if T <= 0: return {"delta": 0, "gamma": 0, "theta": 0, "vega": 0}
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    gamma = norm_pdf(d1) / (S * sigma * math.sqrt(T))
    vega = S * norm_pdf(d1) * math.sqrt(T) / 100
    if option_type == 'CE':
        delta = norm_cdf(d1)
        theta = (- (S * norm_pdf(d1) * sigma) / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * norm_cdf(d2)) / 365
    else:
        delta = norm_cdf(d1) - 1
        theta = (- (S * norm_pdf(d1) * sigma) / (2 * math.sqrt(T)) + r * K * math.exp(-r * T) * norm_cdf(-d2)) / 365
    return {"delta": round(delta, 3), "gamma": round(gamma, 5), "theta": round(theta, 2), "vega": round(vega, 2)}

def get_next_expiry_date(current_date):
    switchover_date = date(2025, 9, 1)
    target_weekday = 3 if current_date < switchover_date else 1
    days_ahead = target_weekday - current_date.weekday()
    if days_ahead < 0: days_ahead += 7
    return current_date + timedelta(days=days_ahead)

def fetch_nifty_history_db():
    try:
        conn = sqlite3.connect(DB_FILE)
        df = pd.read_sql_query("SELECT * FROM nifty_ohlc ORDER BY date DESC LIMIT 365", conn)
        conn.close()
        return df
    except: return pd.DataFrame()

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1: return 50
    deltas = np.diff(prices)
    seed = deltas[:period+1]
    up = seed[seed >= 0].sum()/period
    down = -seed[seed < 0].sum()/period
    rs = up/down
    rsi = np.zeros_like(prices)
    rsi[:period] = 100. - 100./(1. + rs)
    for i in range(period, len(prices)):
        delta = deltas[i-1]
        if delta > 0: upval = delta; downval = 0.
        else: upval = 0.; downval = -delta
        up = (up*(period-1) + upval)/period
        down = (down*(period-1) + downval)/period
        rs = up/down
        rsi[i] = 100. - 100./(1. + rs)
    return rsi[-1]

def round50(n): return round(n / 50) * 50

def get_historical_buffers(spot, days_to_expiry):
    df = fetch_nifty_history_db()
    avg_range, max_range, std_dev, sample_size = 0, 0, 0, 0
    if not df.empty:
        df['date'] = pd.to_datetime(df['date']).dt.date
        relevant_moves = []
        for index, row in df.iterrows():
            row_date = row['date']
            hist_expiry = get_next_expiry_date(row_date)
            hist_dte = (hist_expiry - row_date).days
            if hist_dte == days_to_expiry:
                relevant_moves.append({"range": row['high'] - row['low']})
        if relevant_moves:
            stats_df = pd.DataFrame(relevant_moves)
            avg_range = stats_df['range'].mean()
            std_dev = stats_df['range'].std()
            max_range = stats_df['range'].max()
            sample_size = len(stats_df)
    if sample_size == 0:
        straddle_proxy = spot * 0.01 
        avg_range = straddle_proxy * 0.8 
        max_range = straddle_proxy * 1.5
        std_dev = straddle_proxy * 0.2
    cons_buffer = avg_range + (2 * std_dev)
    mod_buffer = avg_range + (1 * std_dev)
    agg_buffer = avg_range                  
    if days_to_expiry == 0: agg_buffer = max_range 
    return { "conservative": cons_buffer, "moderate": mod_buffer, "aggressive": agg_buffer, "sample_size": sample_size, "avg_range": avg_range, "std_dev": std_dev }

@app.post("/update_daily_ohlc")
def update_daily_ohlc():
    try:
        quote = kite.quote(["NSE:NIFTY 50"])
        ohlc = quote["NSE:NIFTY 50"]["ohlc"]
        current_price = quote["NSE:NIFTY 50"]["last_price"]
        today_str = str(datetime.now().date())
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''INSERT OR REPLACE INTO nifty_ohlc (date, open, high, low, close) VALUES (?, ?, ?, ?, ?)''', (today_str, ohlc['open'], ohlc['high'], ohlc['low'], current_price))
        conn.commit()
        conn.close()
        return {"status": "success", "message": f"Saved Data for {today_str}: Close {current_price}"}
    except Exception as e:
        logger.error(f"Daily Update Failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/historical_analysis")
def get_historical_analysis():
    # ... (Same as previous implementation, simplified here) ...
    try:
        today = datetime.now().date()
        expiry_today = get_next_expiry_date(today)
        days_to_expiry = (expiry_today - today).days
        quote_nifty = kite.quote(["NSE:NIFTY 50"])
        spot = quote_nifty["NSE:NIFTY 50"]["last_price"]
        df = fetch_nifty_history_db()
        rsi_val = 50
        if not df.empty:
            df_sorted = df.sort_values(by='date')
            closes = df_sorted['close'].tolist()
            closes.append(spot)
            rsi_val = calculate_rsi(closes)
        hist_data = get_historical_buffers(spot, days_to_expiry)
        suggestions = {
            "conservative": { "call": round50(spot + hist_data["conservative"]), "put": round50(spot - hist_data["conservative"]), "prob_worthless": "High (Safe)" },
            "moderate": { "call": round50(spot + hist_data["moderate"]), "put": round50(spot - hist_data["moderate"]), "prob_worthless": "Medium" },
            "aggressive": { "call": round50(spot + hist_data["aggressive"]), "put": round50(spot - hist_data["aggressive"]), "prob_worthless": "Low (Risky)" }
        }
        return { "dte": days_to_expiry, "source": f"Local DB ({hist_data['sample_size']})", "expiry_date": str(expiry_today), "rsi": round(rsi_val, 2), "sample_size": hist_data['sample_size'], "stats": { "avg_range": round(hist_data['avg_range'], 2), "std_dev": round(hist_data['std_dev'], 2) }, "suggestions": suggestions, "gamma_blast_risk": (days_to_expiry == 0) }
    except Exception as e:
        logger.error(f"History Analysis failed: {e}")
        return {"stats": {}, "suggestions": {"conservative":{}, "moderate":{}, "aggressive":{}}}

# --- NEW: EXECUTION & POSITIONS ---

def get_symbol_for_strike(strike, type_):
    # Lookup symbol from cache
    for t, det in instrument_cache['strike_map'].items():
        if det['strike'] == strike and det['type'] == type_:
            return det['symbol']
    return None

@app.post("/execute_strangle")
def execute_strangle(payload: dict = Body(...)):
    """
    Places 2 SELL orders (CE + PE) for the given strikes.
    Payload: { "call_strike": 26200, "put_strike": 25800, "qty": 25 }
    """
    try:
        call_strike = payload.get("call_strike")
        put_strike = payload.get("put_strike")
        qty = payload.get("qty", 25) # Default 1 Lot

        call_symbol = get_symbol_for_strike(call_strike, 'CE')
        put_symbol = get_symbol_for_strike(put_strike, 'PE')

        if not call_symbol or not put_symbol:
            raise HTTPException(status_code=400, detail="Invalid Strikes. Refresh Instruments.")

        # Place Orders
        # Note: Using VARIETY_REGULAR & MARKET for simplicity.
        # In real prod, add margin checks and error handling per order.
        
        # 1. Sell Call
        order_id_ce = kite.place_order(
            tradingsymbol=call_symbol,
            exchange=kite.EXCHANGE_NFO,
            transaction_type=kite.TRANSACTION_TYPE_SELL,
            quantity=qty,
            order_type=kite.ORDER_TYPE_MARKET,
            product=kite.PRODUCT_MIS,
            variety=kite.VARIETY_REGULAR
        )
        
        # 2. Sell Put
        order_id_pe = kite.place_order(
            tradingsymbol=put_symbol,
            exchange=kite.EXCHANGE_NFO,
            transaction_type=kite.TRANSACTION_TYPE_SELL,
            quantity=qty,
            order_type=kite.ORDER_TYPE_MARKET,
            product=kite.PRODUCT_MIS,
            variety=kite.VARIETY_REGULAR
        )

        return {
            "status": "success", 
            "message": f"Orders Placed. IDs: {order_id_ce}, {order_id_pe}",
            "executed_strikes": {"call": call_strike, "put": put_strike}
        }

    except Exception as e:
        logger.error(f"Execution Failed: {e}")
        # Return 200 with error status to handle gracefully in UI
        return {"status": "error", "message": str(e)} 

@app.get("/positions")
def get_positions():
    """Fetches Net Positions from Kite"""
    try:
        positions = kite.positions()
        net = positions['net']
        
        # Filter for NIFTY only to keep dashboard clean
        nifty_positions = [p for p in net if 'NIFTY' in p['tradingsymbol']]
        
        return {"data": nifty_positions}
    except Exception as e:
        logger.error(f"Positions fetch failed: {e}")
        return {"data": []}

@app.get("/analyze")
def get_analysis():
    # ... (Keep existing analyze logic exactly as is) ...
    if not instrument_cache["nifty_tokens"]:
        refresh_instruments()
        if not instrument_cache["nifty_tokens"]: raise HTTPException(status_code=500, detail="Instruments not loaded.")
    try:
        quotes_idx = kite.quote(["NSE:NIFTY 50", "NSE:INDIA VIX"])
        quote_nifty = quotes_idx["NSE:NIFTY 50"]
        quote_vix = quotes_idx.get("NSE:INDIA VIX", {})
        nifty_spot = quote_nifty["last_price"]
        vix_val = quote_vix.get("last_price", 13.0)
        
        expiry_date_str = instrument_cache["expiry"]
        expiry_date = datetime.strptime(expiry_date_str, "%Y-%m-%d").date()
        today = datetime.now().date()
        days_to_expiry = (expiry_date - today).days
        time_to_expiry_years = max(0.5, days_to_expiry) / 365.0 
        risk_free_rate = 0.07
        sigma = vix_val / 100.0
        
        atm_strike = round(nifty_spot / 50) * 50
        atm_greeks = calculate_greeks(nifty_spot, atm_strike, time_to_expiry_years, risk_free_rate, sigma, 'CE')
        
        relevant_tokens = []
        token_details = []
        hist_data = get_historical_buffers(nifty_spot, days_to_expiry)
        max_buffer = hist_data["conservative"] + 200 
        skew_up_strike = atm_strike + 500
        skew_down_strike = atm_strike - 500
        
        for token, details in instrument_cache["strike_map"].items():
            if abs(details['strike'] - nifty_spot) <= max_buffer:
                relevant_tokens.append(token)
                token_details.append({**details, "token": token})
        
        quotes = kite.quote(relevant_tokens)
        data = []
        skew_call_price, skew_put_price = 0, 0
        
        for det in token_details:
            q = quotes.get(str(det['token'])) or quotes.get(det['token'])
            if q:
                if det['strike'] == skew_up_strike and det['type'] == 'CE': skew_call_price = q['last_price']
                if det['strike'] == skew_down_strike and det['type'] == 'PE': skew_put_price = q['last_price']
                spread = 0
                if q['depth']['buy'] and q['depth']['sell']:
                    bid = q['depth']['buy'][0]['price']
                    ask = q['depth']['sell'][0]['price']
                    if ask > 0: spread = ((ask - bid) / ask) * 100
                data.append({ "strike": det['strike'], "type": det['type'], "oi": q['oi'], "ltp": q['last_price'], "volume": q['volume'], "spread": spread, "liquidity_ok": q['volume'] > 1000 and q['oi'] > 50000 and spread < 5, "buy_qty": q['buy_quantity'], "sell_qty": q['sell_quantity'] })
        
        df = pd.DataFrame(data)
        ce_df = df[df['type'] == 'CE'].set_index('strike')
        pe_df = df[df['type'] == 'PE'].set_index('strike')
        
        def get_profile_data(call_k, put_k):
            c_ltp = ce_df.loc[call_k]['ltp'] if call_k in ce_df.index else 0
            p_ltp = pe_df.loc[put_k]['ltp'] if put_k in pe_df.index else 0
            c_greeks = calculate_greeks(nifty_spot, call_k, time_to_expiry_years, risk_free_rate, sigma, 'CE')
            p_greeks = calculate_greeks(nifty_spot, put_k, time_to_expiry_years, risk_free_rate, sigma, 'PE')
            def get_stats(df, k):
                if k in df.index:
                    r = df.loc[k]
                    return { "ok": bool(r['liquidity_ok']), "buy_qty": int(r['buy_qty']), "sell_qty": int(r['sell_qty']) }
                return { "ok": False, "buy_qty": 0, "sell_qty": 0 }
            return { "rec_call": float(call_k), "rec_put": float(put_k), "est_credit": float(c_ltp + p_ltp), "call_stats": get_stats(ce_df, call_k), "put_stats": get_stats(pe_df, put_k), "call_greeks": c_greeks, "put_greeks": p_greeks }

        profiles = {
            "conservative": get_profile_data(round50(nifty_spot + hist_data["conservative"]), round50(nifty_spot - hist_data["conservative"])),
            "moderate": get_profile_data(round50(nifty_spot + hist_data["moderate"]), round50(nifty_spot - hist_data["moderate"])),
            "aggressive": get_profile_data(round50(nifty_spot + hist_data["aggressive"]), round50(nifty_spot - hist_data["aggressive"]))
        }
        
        atm_ce_ltp = ce_df.loc[atm_strike]['ltp'] if atm_strike in ce_df.index else 0
        atm_pe_ltp = pe_df.loc[atm_strike]['ltp'] if atm_strike in pe_df.index else 0
        straddle_cost = atm_ce_ltp + atm_pe_ltp
        volatility_skew = skew_put_price / skew_call_price if skew_call_price > 0 else 0
        max_pain = calculate_max_pain(df)
        res_strike = ce_df['oi'].idxmax()
        sup_strike = pe_df['oi'].idxmax()
        pcr = round(pe_df['oi'].sum() / ce_df['oi'].sum(), 2) if ce_df['oi'].sum() > 0 else 0
        
        combined_idx = sorted(list(set(ce_df.index) | set(pe_df.index)))
        chart_data = {
            "strikes": combined_idx,
            "ce_oi": [int(ce_df.loc[s]['oi']) if s in ce_df.index else 0 for s in combined_idx],
            "pe_oi": [int(pe_df.loc[s]['oi']) if s in pe_df.index else 0 for s in combined_idx],
            "ce_vol": [int(ce_df.loc[s]['volume']) if s in ce_df.index else 0 for s in combined_idx], 
            "pe_vol": [int(pe_df.loc[s]['volume']) if s in pe_df.index else 0 for s in combined_idx], 
        }
        
        return {
            "timestamp": get_ist_time().strftime("%H:%M:%S"), "nifty_spot": nifty_spot, "vix": {"value": float(vix_val), "change": float(quote_vix.get("net_change", 0))}, "greeks": atm_greeks, "skew": { "value": round(volatility_skew, 2), "put_price": skew_put_price, "call_price": skew_call_price }, "metrics": { "max_pain": float(max_pain), "pcr": pcr, "support": float(sup_strike), "resistance": float(res_strike) }, "strangle_intel": profiles, "straddle_intel": { "atm_strike": float(atm_strike), "cost": float(straddle_cost), "upper_be": float(atm_strike+straddle_cost), "lower_be": float(atm_strike-straddle_cost) }, "chart_data": chart_data
        }
        
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)