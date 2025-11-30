# backend/journal_endpoints.py
"""
NEW FILE: Journal API Endpoints for Go Integration
Add these endpoints to nifty_kite_backend.py
"""

from fastapi import FastAPI, Body
from journal_manager_complete import TradingJournal
import logging

journal = TradingJournal("backend/nifty_history.db")
logger = logging.getLogger("JournalAPI")

# ============================================
# TRADE ENTRY RECORDING (Called by Go API)
# ============================================

@app.post("/journal/record_entry")
async def record_trade_entry(payload: dict = Body(...)):
    """
    Called by Go API immediately after order execution
    
    Payload structure:
    {
        "position_data": {
            "tradingsymbol": "NIFTY24DEC24500CE",
            "quantity": 75,
            "average_price": 125.50,
            "order_id": "240001234567"
        },
        "market_context": {
            "spot": 24500.25,
            "vix": 13.45,
            "iv_rank": 45.2,
            "dte": 2.5,
            "delta": 0.18,
            "gamma": 0.0023,
            "theta": -15.5
        },
        "source": "app_auto",  # or "app_manual", "zerodha_app"
        "session_id": "uuid-here"  # Links CE and PE legs
    }
    """
    try:
        trade_id = journal.record_trade_entry(
            position_data=payload["position_data"],
            market_context=payload["market_context"],
            source=payload.get("source", "app_auto"),
            session_id=payload.get("session_id")
        )
        
        logger.info(f"✅ Journal Entry: {payload['position_data']['tradingsymbol']} (ID: {trade_id[:8]})")
        
        return {
            "success": True,
            "trade_id": trade_id,
            "message": "Trade recorded in journal"
        }
        
    except Exception as e:
        logger.error(f"❌ Journal entry failed: {e}")
        return {"success": False, "error": str(e)}


# ============================================
# TRADE EXIT RECORDING (Called by Go API)
# ============================================

@app.post("/journal/record_exit")
async def record_trade_exit(payload: dict = Body(...)):
    """
    Called by Go API when position closes
    
    Payload:
    {
        "trade_id": "uuid-from-entry",
        "exit_data": {
            "exit_price": 45.25,
            "order_id": "240001234568"
        },
        "market_context": {
            "spot": 24650.00,
            "vix": 15.20,
            "delta": 0.32
        },
        "exit_reason": "manual" | "stop_loss" | "target" | "gamma_panic" | "eod",
        "emotional_state": "calm" | "fearful" | "greedy" | "impatient" | null,
        "notes": "Optional trader notes"
    }
    """
    try:
        success = journal.record_trade_exit(
            trade_id=payload["trade_id"],
            exit_data=payload["exit_data"],
            market_context=payload["market_context"],
            exit_reason=payload.get("exit_reason", "manual"),
            emotional_state=payload.get("emotional_state"),
            notes=payload.get("notes")
        )
        
        if success:
            return {
                "success": True,
                "message": "Trade exit recorded"
            }
        else:
            return {
                "success": False,
                "error": "Trade not found or already closed"
            }
            
    except Exception as e:
        logger.error(f"❌ Journal exit failed: {e}")
        return {"success": False, "error": str(e)}


# ============================================
# IDENTIFY ZERODHA APP TRADES (Polling-based)
# ============================================

@app.post("/journal/sync_positions")
async def sync_zerodha_positions():
    """
    Scans current Zerodha positions and identifies trades NOT in journal
    These are assumed to be Zerodha app trades (emotional/manual)
    
    Call this endpoint every 5 minutes as a background task
    """
    try:
        # Get all open positions from Zerodha
        positions_data = kite.positions()
        net = positions_data['net']
        
        # Get open positions from journal
        journal_positions = journal.get_open_positions()
        journal_symbols = {p['symbol'] for p in journal_positions}
        
        new_trades_found = 0
        
        for pos in net:
            if 'NIFTY' not in pos['tradingsymbol']:
                continue
            
            symbol = pos['tradingsymbol']
            
            # If position exists in Zerodha but NOT in journal → Zerodha app trade
            if symbol not in journal_symbols and pos['quantity'] != 0:
                
                # Try to match by symbol + entry price (in case of duplicate entries)
                existing = journal.find_trade_by_symbol(symbol, pos['average_price'])
                
                if not existing:
                    # Record as Zerodha app trade
                    spot = kite.quote(["NSE:NIFTY 50"])["NSE:NIFTY 50"]["last_price"]
                    vix = kite.quote(["NSE:INDIA VIX"])["NSE:INDIA VIX"]["last_price"]
                    
                    # Minimal context (we don't have full greeks)
                    market_context = {
                        "spot": spot,
                        "vix": vix,
                        "iv_rank": 50.0,  # Placeholder
                        "dte": 1.0,  # Estimate
                        "delta": None,
                        "gamma": None,
                        "theta": None
                    }
                    
                    position_data = {
                        "tradingsymbol": symbol,
                        "quantity": abs(pos['quantity']),
                        "average_price": pos['average_price'],
                        "order_id": None
                    }
                    
                    journal.record_trade_entry(
                        position_data=position_data,
                        market_context=market_context,
                        source="zerodha_app"  # 🔑 Key differentiation
                    )
                    
                    new_trades_found += 1
                    logger.info(f"🆕 Detected Zerodha app trade: {symbol}")
        
        return {
            "success": True,
            "new_trades_synced": new_trades_found,
            "message": f"Synced {new_trades_found} Zerodha app trades"
        }
        
    except Exception as e:
        logger.error(f"❌ Position sync failed: {e}")
        return {"success": False, "error": str(e)}


# ============================================
# BEHAVIORAL ANALYTICS & INSIGHTS
# ============================================

@app.get("/journal/performance")
async def get_performance_summary(days: int = 30):
    """
    Returns comprehensive performance analytics
    """
    try:
        summary = journal.get_performance_summary(days=days)
        
        # Add behavioral insights
        insights = generate_behavioral_insights(summary)
        
        return {
            "success": True,
            "period_days": days,
            "overall_stats": summary["overall"],
            "win_rate": summary["win_rate"],
            "by_day_of_week": summary["by_day_of_week"],
            "expiry_performance": summary["expiry_day_analysis"],
            "emotional_analysis": summary["emotional_analysis"],
            "vix_correlation": summary["vix_correlation"],
            "behavioral_insights": insights
        }
        
    except Exception as e:
        logger.error(f"❌ Performance summary failed: {e}")
        return {"success": False, "error": str(e)}


@app.get("/journal/lessons")
async def get_trading_lessons(limit: int = 10):
    """
    Returns recent trading lessons
    """
    try:
        lessons = journal.get_recent_lessons(limit=limit)
        return {
            "success": True,
            "lessons": lessons
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/journal/add_lesson")
async def add_lesson(payload: dict = Body(...)):
    """
    Add a trading lesson
    
    Payload:
    {
        "lesson_text": "Exited too early due to gamma fear",
        "category": "emotional" | "entry" | "exit" | "risk_mgmt" | "strategy",
        "severity": "minor" | "major" | "critical",
        "trade_id": "optional-uuid",
        "action_plan": "Wait 15min during gamma spikes before reacting"
    }
    """
    try:
        journal.add_lesson(
            lesson_text=payload["lesson_text"],
            category=payload["category"],
            severity=payload.get("severity", "minor"),
            trade_id=payload.get("trade_id"),
            action_plan=payload.get("action_plan")
        )
        return {"success": True, "message": "Lesson recorded"}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============================================
# HELPER FUNCTIONS
# ============================================

def generate_behavioral_insights(summary: dict) -> dict:
    """
    Analyzes trading data and generates actionable insights
    """
    insights = {
        "warnings": [],
        "strengths": [],
        "recommendations": []
    }
    
    # Emotional trading analysis
    emotional_data = summary.get("emotional_analysis", [])
    for emotion in emotional_data:
        if emotion["emotional_state"] == "fearful" and emotion["win_rate"] < 40:
            insights["warnings"].append(
                f"Fear-based exits have only {emotion['win_rate']:.1f}% success rate. "
                "Consider waiting 15 minutes before panic exits."
            )
        
        if emotion["emotional_state"] == "calm" and emotion["win_rate"] > 60:
            insights["strengths"].append(
                f"Calm trading shows {emotion['win_rate']:.1f}% win rate. "
                "Maintain this discipline."
            )
    
    # Day of week patterns
    dow_data = summary.get("by_day_of_week", [])
    if dow_data:
        worst_day = min(dow_data, key=lambda x: x.get("win_rate", 0))
        best_day = max(dow_data, key=lambda x: x.get("win_rate", 0))
        
        insights["warnings"].append(
            f"Weakest performance on {worst_day['day_of_week']} "
            f"({worst_day['win_rate']:.1f}% win rate)"
        )
        insights["strengths"].append(
            f"Best performance on {best_day['day_of_week']} "
            f"({best_day['win_rate']:.1f}% win rate)"
        )
    
    # VIX correlation
    vix_data = summary.get("vix_correlation", [])
    for vix_range in vix_data:
        if vix_range["vix_range"] == "High (>18)" and vix_range["win_rate"] < 45:
            insights["recommendations"].append(
                "High VIX environment shows lower win rate. "
                "Consider wider strikes or reducing position size."
            )
    
    return insights
