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

from fastapi.responses import StreamingResponse
import asyncio
from fastapi.middleware.cors import CORSMiddleware

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

# --- DATABASE INIT ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS nifty_ohlc (
            date TEXT PRIMARY KEY,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            vix REAL
        )
    ''')
    cursor.execute("PRAGMA table_info(nifty_ohlc)")
    columns = [info[1] for info in cursor.fetchall()]
    if 'vix' not in columns:
        try:
            cursor.execute("ALTER TABLE nifty_ohlc ADD COLUMN vix REAL")
            logger.info("Migrated DB: Added 'vix' column")
        except Exception as e:
            logger.error(f"DB Migration failed: {e}")
    conn.commit()
    conn.close()

init_db()

# ============================================
# REAL-TIME POSITION STREAMING (SSE)
# ============================================

@app.get("/positions/stream")
async def stream_positions():
    """
    Server-Sent Events endpoint for real-time position updates.
    Updates every 1 second. No more polling needed!
    """
    async def event_generator():
        try:
            while True:
                # Fetch positions from Kite
                positions_data = kite.positions()
                net = positions_data['net']
                nifty_positions = [p for p in net if 'NIFTY' in p['tradingsymbol']]
                
                # Calculate real-time MTM
                total_mtm = 0
                for pos in nifty_positions:
                    # CRITICAL: Correct MTM formula
                    # For SELL positions (qty < 0): MTM = (AvgPrice - LTP) * |Qty|
                    # For BUY positions (qty > 0): MTM = (LTP - AvgPrice) * Qty
                    mtm = (pos['last_price'] - pos['average_price']) * pos['quantity']
                    pos['mtm'] = round(mtm, 2)
                    total_mtm += mtm
                
                # Stream as Server-Sent Event
                data = {
                    "positions": nifty_positions,
                    "total_mtm": round(total_mtm, 2),
                    "timestamp": get_ist_time().strftime("%H:%M:%S")
                }
                
                yield f"data: {json.dumps(data)}\n\n"
                
                # Update every 1 second
                await asyncio.sleep(1)
                
        except asyncio.CancelledError:
            logger.info("Position stream closed by client")
        except Exception as e:
            logger.error(f"Position stream error: {e}")
            
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*"  # CORS for React
        }
    )


# ============================================
# ENHANCED POSITIONS ENDPOINT
# ============================================

@app.get("/positions")
def get_positions_enhanced():
    """
    Enhanced positions endpoint with real-time MTM calculation.
    Keeps backward compatibility with existing code.
    """
    try:
        positions_data = kite.positions()
        net = positions_data['net']
        nifty_positions = [p for p in net if 'NIFTY' in p['tradingsymbol']]
        
        # Add real-time MTM calculation
        total_mtm = 0
        for pos in nifty_positions:
            mtm = (pos['last_price'] - pos['average_price']) * pos['quantity']
            pos['mtm'] = round(mtm, 2)
            total_mtm += mtm
        
        return {
            "success": True,
            "data": nifty_positions,
            "total_mtm": round(total_mtm, 2),
            "timestamp": get_ist_time().strftime("%H:%M:%S")
        }
    except Exception as e:
        logger.error(f"Positions fetch failed: {e}")
        return {
            "success": False,
            "data": [],
            "total_mtm": 0,
            "error": str(e)
        }

# Add this BEFORE any route definitions (after app = FastAPI())
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],  # React dev servers
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================
# HEALTH CHECK ENDPOINT
# ============================================

@app.get("/health")
def health_check():
    """
    Simple health check for the React app to verify backend is alive.
    """
    try:
        # Test Kite connection
        quote = kite.quote(["NSE:NIFTY 50"])
        spot = quote["NSE:NIFTY 50"]["last_price"]
        
        return {
            "status": "ok",
            "backend": "python",
            "spot": spot,
            "timestamp": get_ist_time().strftime("%H:%M:%S")
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }


# ============================================
# SYSTEM CAPABILITIES ENDPOINT
# ============================================

@app.get("/capabilities")
def get_capabilities():
    """
    Tells React app what features are available.
    """
    return {
        "backend": "python",
        "version": "1.0",
        "features": {
            "analytics": True,
            "greeks_calculation": True,
            "regime_detection": True,
            "historical_analysis": True,
            "execution": True,
            "position_tracking": True,
            "position_management": False,  # Python doesn't have this
            "risk_management": False,      # Python doesn't have this
            "auto_trading": False          # Python doesn't have this
        },
        "endpoints": {
            "analyze": "/analyze",
            "execute": "/execute_strangle",
            "positions": "/positions",
            "positions_stream": "/positions/stream",
            "historical": "/historical_analysis"
        }
    }

# ============================================
# USAGE INSTRUCTIONS
# ============================================

"""
DEPLOYMENT STEPS:

1. Add CORS middleware at the top (after app = FastAPI()):
   
   from fastapi.middleware.cors import CORSMiddleware
   app.add_middleware(CORSMiddleware, ...)

2. Add all the new endpoints above to your file

3. Restart your Python backend:
   
   python backend/nifty_kite_backend.py

4. Test the new SSE endpoint:
   
   curl http://localhost:8000/positions/stream
   
   You should see real-time position updates streaming!

5. Test health check:
   
   curl http://localhost:8000/health

6. Deploy React components and start using!

NOTES:
- SSE will automatically reconnect if connection drops
- MTM calculation is now accurate for both buy/sell positions
- All endpoints are CORS-enabled for React
- No breaking changes to existing code
"""

# --- INSTRUMENT FETCHING AND CACHING ---
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

# --- CALCULATION HELPERS ---
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
    if down == 0: return 100
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

def round50(n): 
    try:
        if math.isnan(n): return 0
        return round(n / 50) * 50
    except:
        return 0

# --- INTELLIGENT SYSTEM LOGIC (NEW) ---

def calculate_iv_rank(current_vix, df):
    if df.empty or 'vix' not in df.columns or df['vix'].isnull().all():
        return {"rank": 50, "status": "Neutral (No Data)"}
    
    vix_series = df['vix'].dropna()
    if len(vix_series) < 10:
        return {"rank": 50, "status": "Neutral (Low Data)"}

    min_vix = vix_series.min()
    max_vix = vix_series.max()
    
    if max_vix == min_vix: return {"rank": 50, "status": "Stable"}

    rank = ((current_vix - min_vix) / (max_vix - min_vix)) * 100
    
    status = "Neutral"
    if rank > 70: status = "High (Sell Opportunity)"
    elif rank > 50: status = "Moderately High"
    elif rank < 30: status = "Low (Premium Risk)"
    
    return {"rank": round(rank, 1), "status": status}

def detect_market_regime(spot, df, vix_val, rsi_val):
    if df.empty: return "Neutral", {"bias": "Neutral", "adjust_call": 1.0, "adjust_put": 1.0}

    closes = pd.to_numeric(df['close'])
    sma_20 = closes.head(20).mean()
    trend_strength = ((spot - sma_20) / sma_20) * 100
    high_vol =VX = vix_val > 18
    
    regime = "Neutral"
    details = {"bias": "Neutral", "adjust_call": 1.0, "adjust_put": 1.0}

    if high_vol:
        regime = "High Volatility"
        details = {"bias": "Volatile", "adjust_call": 1.15, "adjust_put": 1.15} 
    elif trend_strength > 2 and rsi_val > 55:
        regime = "Bullish Trend"
        details = {"bias": "Bullish", "adjust_call": 1.25, "adjust_put": 0.9} 
    elif trend_strength < -2 and rsi_val < 45:
        regime = "Bearish Trend"
        details = {"bias": "Bearish", "adjust_call": 0.9, "adjust_put": 1.25}
    elif abs(trend_strength) < 1.5:
        regime = "Range Bound"
        details = {"bias": "Range", "adjust_call": 0.95, "adjust_put": 0.95}

    return regime, details

def get_dte_adjustment(days_to_expiry, vix_val):
    if days_to_expiry == 0:
        return 2.0, "⚠️ 0 DTE: Gamma Risk High"
    elif days_to_expiry == 1:
        return 1.3, "⚠️ 1 DTE: Caution"
    elif vix_val < 11 and days_to_expiry > 4:
         return 1.4, "Low VIX + Long Time"
    return 1.0, "Standard Decay"

def get_skew_adjustment(skew_val, pcr):
    adj_call = 1.0
    adj_put = 1.0
    if skew_val > 1.2 and pcr > 1.2:
        adj_call = 0.9
        adj_put = 1.15
    elif skew_val < 0.8 and pcr < 0.7:
        adj_call = 1.15
        adj_put = 0.9
    return adj_call, adj_put

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
            # Fix: Handle case with single data point (std returns NaN)
            if len(stats_df) > 1:
                std_dev = stats_df['range'].std()
            else:
                std_dev = avg_range * 0.2 # Fallback
            max_range = stats_df['range'].max()
            sample_size = len(stats_df)
    
    if sample_size == 0:
        straddle_proxy = spot * 0.01 
        avg_range = straddle_proxy * 0.8 
        max_range = straddle_proxy * 1.5
        std_dev = straddle_proxy * 0.2

    # --- UPDATED LOGIC ---
    # Ensure no NaN values propagate
    if math.isnan(avg_range): avg_range = spot * 0.01
    if math.isnan(std_dev): std_dev = avg_range * 0.2

    # Conservative = 2 SD (95% Safety)
    cons_buffer = avg_range + (2 * std_dev)
    
    # Moderate = 1 SD (68% Safety)
    mod_buffer = avg_range + (1 * std_dev)
    
    # Aggressive = Tighter than avg range to ensure premium
    agg_buffer = avg_range * 0.8 
    
    return { 
        "conservative": cons_buffer, "moderate": mod_buffer, "aggressive": agg_buffer, 
        "sample_size": sample_size, "avg_range": avg_range, "std_dev": std_dev 
    }

# --- ENDPOINTS ---

@app.post("/update_daily_ohlc")
def update_daily_ohlc():
    try:
        quote = kite.quote(["NSE:NIFTY 50", "NSE:INDIA VIX"])
        nifty_ohlc = quote["NSE:NIFTY 50"]["ohlc"]
        current_price = quote["NSE:NIFTY 50"]["last_price"]
        vix_price = quote.get("NSE:INDIA VIX", {}).get("last_price", 0)

        today_str = str(datetime.now().date())
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO nifty_ohlc (date, open, high, low, close, vix) 
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (today_str, nifty_ohlc['open'], nifty_ohlc['high'], nifty_ohlc['low'], current_price, vix_price))
        conn.commit()
        conn.close()
        return {"status": "success", "message": f"Saved {today_str}: Spot {current_price}"}
    except Exception as e:
        logger.error(f"Daily Update Failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/historical_analysis")
def get_historical_analysis():
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
        return { 
            "dte": days_to_expiry, "source": f"Local DB ({hist_data['sample_size']})", "expiry_date": str(expiry_today), 
            "rsi": round(rsi_val, 2), "sample_size": hist_data['sample_size'], 
            "stats": { "avg_range": round(hist_data['avg_range'], 2), "std_dev": round(hist_data['std_dev'], 2) }, 
            "suggestions": suggestions, "gamma_blast_risk": (days_to_expiry == 0) 
        }
    except Exception as e:
        logger.error(f"History Analysis failed: {e}")
        # Fix: Return placeholders instead of empty dict to prevent 'undefined' in UI
        err_struct = {"call": "--", "put": "--", "prob_worthless": "Error"}
        return {
            "stats": {}, 
            "suggestions": {"conservative": err_struct, "moderate": err_struct, "aggressive": err_struct}
        }

def get_symbol_for_strike(strike, type_):
    for t, det in instrument_cache['strike_map'].items():
        if det['strike'] == strike and det['type'] == type_:
            return det['symbol']
    return None

@app.post("/execute_strangle")
def execute_strangle(payload: dict = Body(...)):
    try:
        call_strike = payload.get("call_strike")
        put_strike = payload.get("put_strike")
        # CHANGED: Default quantity set to 75 as requested (Safer side)
        qty = payload.get("qty", 75) 
        call_symbol = get_symbol_for_strike(call_strike, 'CE')
        put_symbol = get_symbol_for_strike(put_strike, 'PE')
        if not call_symbol or not put_symbol: raise HTTPException(status_code=400, detail="Invalid Strikes. Refresh Instruments.")
        order_id_ce = kite.place_order(tradingsymbol=call_symbol, exchange=kite.EXCHANGE_NFO, transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=qty, order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS, variety=kite.VARIETY_REGULAR)
        order_id_pe = kite.place_order(tradingsymbol=put_symbol, exchange=kite.EXCHANGE_NFO, transaction_type=kite.TRANSACTION_TYPE_SELL, quantity=qty, order_type=kite.ORDER_TYPE_MARKET, product=kite.PRODUCT_MIS, variety=kite.VARIETY_REGULAR)
        return {"status": "success", "message": f"Orders Placed. IDs: {order_id_ce}, {order_id_pe}", "executed_strikes": {"call": call_strike, "put": put_strike}}
    except Exception as e:
        logger.error(f"Execution Failed: {e}")
        return {"status": "error", "message": str(e)} 

@app.get("/positions")
def get_positions():
    try:
        positions = kite.positions()
        net = positions['net']
        nifty_positions = [p for p in net if 'NIFTY' in p['tradingsymbol']]
        return {"data": nifty_positions}
    except Exception as e:
        logger.error(f"Positions fetch failed: {e}")
        return {"data": []}

@app.get("/analyze")
def get_analysis():
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
        
        hist_df = fetch_nifty_history_db()
        hist_data = get_historical_buffers(nifty_spot, days_to_expiry)
        
        iv_rank_data = calculate_iv_rank(vix_val, hist_df)
        
        rsi_val = 50
        if not hist_df.empty:
            closes = hist_df.sort_values(by='date')['close'].tolist()
            closes.append(nifty_spot)
            rsi_val = calculate_rsi(closes)
            
        regime_name, regime_details = detect_market_regime(nifty_spot, hist_df, vix_val, rsi_val)
        dte_mult, dte_msg = get_dte_adjustment(days_to_expiry, vix_val)
        
        max_buffer = (hist_data["conservative"] * 1.5) + 300 
        relevant_tokens = []
        token_details = []
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

        volatility_skew = skew_put_price / skew_call_price if skew_call_price > 0 else 0
        pcr = round(pe_df['oi'].sum() / ce_df['oi'].sum(), 2) if ce_df['oi'].sum() > 0 else 0
        skew_adj_call, skew_adj_put = get_skew_adjustment(volatility_skew, pcr)

        # --- UPDATED IV RANK MULTIPLIER ---
        iv_rank_mult = 1.0
        # High IV: Can go wider (Safe) and still get premium
        if iv_rank_data["rank"] > 50: iv_rank_mult = 1.1 
        # Low IV: Premiums are low. Conservative wants safety (Wider), Aggressive wants premium (Tighter).
        elif iv_rank_data["rank"] < 30: iv_rank_mult = 1.2 # Base safety widening
        
        def get_profile_data(base_buffer, profile_name):
            call_dist = base_buffer
            put_dist = base_buffer
            
            call_dist *= regime_details["adjust_call"]
            put_dist *= regime_details["adjust_put"]
            
            call_dist *= skew_adj_call
            put_dist *= skew_adj_put
            
            # --- UPDATED SAFETY APPLICATION ---
            safety_factor = iv_rank_mult * dte_mult
            
            if profile_name == "aggressive":
                # Aggressive Logic:
                # 1. Ignore excessive safety padding (reduce impact by 80%)
                if safety_factor > 1.0:
                    safety_factor = 1.0 + (safety_factor - 1.0) * 0.2
                
                # 2. If Low IV (<30), TIGHTEN further to find premium
                # (Overriding the base safety widening)
                if iv_rank_data["rank"] < 30:
                    safety_factor *= 0.85 

            elif profile_name == "moderate":
                # Moderate Logic: Partial safety (reduce impact by 40%)
                if safety_factor > 1.0:
                    safety_factor = 1.0 + (safety_factor - 1.0) * 0.6
            
            # Conservative Logic: Accepts full safety factor (Safest, Lowest Premium)

            call_dist *= safety_factor
            put_dist *= safety_factor
            
            call_k = round50(nifty_spot + call_dist)
            put_k = round50(nifty_spot - put_dist)

            c_ltp = ce_df.loc[call_k]['ltp'] if call_k in ce_df.index else 0
            p_ltp = pe_df.loc[put_k]['ltp'] if put_k in pe_df.index else 0
            c_greeks = calculate_greeks(nifty_spot, call_k, time_to_expiry_years, risk_free_rate, sigma, 'CE')
            p_greeks = calculate_greeks(nifty_spot, put_k, time_to_expiry_years, risk_free_rate, sigma, 'PE')
            
            def get_stats(df, k):
                if k in df.index:
                    r = df.loc[k]
                    return { "ok": bool(r['liquidity_ok']), "buy_qty": int(r['buy_qty']), "sell_qty": int(r['sell_qty']) }
                return { "ok": False, "buy_qty": 0, "sell_qty": 0 }
                
            return { 
                "rec_call": float(call_k), "rec_put": float(put_k), 
                "est_credit": float(c_ltp + p_ltp), 
                "call_stats": get_stats(ce_df, call_k), "put_stats": get_stats(pe_df, put_k), 
                "call_greeks": c_greeks, "put_greeks": p_greeks 
            }

        profiles = {
            "conservative": get_profile_data(hist_data["conservative"], "conservative"),
            "moderate": get_profile_data(hist_data["moderate"], "moderate"),
            "aggressive": get_profile_data(hist_data["aggressive"], "aggressive")
        }
        
        atm_ce_ltp = ce_df.loc[atm_strike]['ltp'] if atm_strike in ce_df.index else 0
        atm_pe_ltp = pe_df.loc[atm_strike]['ltp'] if atm_strike in pe_df.index else 0
        straddle_cost = atm_ce_ltp + atm_pe_ltp
        max_pain = calculate_max_pain(df)
        res_strike = ce_df['oi'].idxmax()
        sup_strike = pe_df['oi'].idxmax()
        
        combined_idx = sorted(list(set(ce_df.index) | set(pe_df.index)))
        chart_data = {
            "strikes": combined_idx,
            "ce_oi": [int(ce_df.loc[s]['oi']) if s in ce_df.index else 0 for s in combined_idx],
            "pe_oi": [int(pe_df.loc[s]['oi']) if s in pe_df.index else 0 for s in combined_idx],
            "ce_vol": [int(ce_df.loc[s]['volume']) if s in ce_df.index else 0 for s in combined_idx], 
            "pe_vol": [int(pe_df.loc[s]['volume']) if s in pe_df.index else 0 for s in combined_idx], 
        }
        
        return {
            "timestamp": get_ist_time().strftime("%H:%M:%S"), 
            "nifty_spot": nifty_spot, 
            "vix": {"value": float(vix_val), "change": float(quote_vix.get("net_change", 0))}, 
            "greeks": atm_greeks, 
            "skew": { "value": round(volatility_skew, 2), "put_price": skew_put_price, "call_price": skew_call_price }, 
            "metrics": { "max_pain": float(max_pain), "pcr": pcr, "support": float(sup_strike), "resistance": float(res_strike) }, 
            "strangle_intel": profiles, 
            "straddle_intel": { "atm_strike": float(atm_strike), "cost": float(straddle_cost), "upper_be": float(atm_strike+straddle_cost), "lower_be": float(atm_strike-straddle_cost) }, 
            "chart_data": chart_data,
            "market_intel": {
                "regime": regime_name,
                "regime_bias": regime_details["bias"],
                "iv_rank": iv_rank_data["rank"],
                "iv_status": iv_rank_data["status"],
                "dte_msg": dte_msg,
                "rsi": round(rsi_val, 1)
            }
        }
        
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)