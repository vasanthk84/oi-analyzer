# backend/trade_autopsy.py
"""
POST-TRADE AUTOPSY SYSTEM
Analyzes what went right/wrong in each trade from an option seller's perspective
Provides actionable insights to improve future decisions
"""

import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz
from typing import Dict, List, Tuple

class TradeAutopsy:
    def __init__(self, db_path="backend/nifty_history.db"):
        self.db_path = db_path
        self.ist_tz = pytz.timezone('Asia/Kolkata')
    
    def analyze_trade(self, trade_id: str) -> Dict:
        """
        Complete autopsy of a single trade
        Returns detailed analysis with what went right/wrong
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get complete trade data
        cursor.execute('''
            SELECT 
                symbol, instrument_type, strike, entry_time, exit_time,
                entry_price, exit_price, quantity, realized_pnl, realized_pnl_pct,
                spot_at_entry, spot_at_exit, vix_at_entry, vix_at_exit,
                iv_rank_at_entry, dte_at_entry, 
                delta_at_entry, delta_at_exit,
                gamma_at_entry, theta_at_entry,
                hold_duration_minutes, exit_reason, emotional_state,
                day_of_week, is_expiry_day, is_zero_dte, hour_of_entry,
                max_profit, max_loss, was_planned, source, notes
            FROM trades
            WHERE trade_id = ?
        ''', (trade_id,))
        
        row = cursor.fetchone()
        if not row:
            conn.close()
            return {"error": "Trade not found"}
        
        # Parse data
        (symbol, opt_type, strike, entry_time_str, exit_time_str,
         entry_price, exit_price, quantity, pnl, pnl_pct,
         spot_entry, spot_exit, vix_entry, vix_exit,
         iv_rank, dte, delta_entry, delta_exit,
         gamma, theta, hold_mins, exit_reason, emotion,
         dow, is_expiry, is_0dte, entry_hour,
         max_profit, max_loss, was_planned, source, notes) = row
        
        entry_time = datetime.fromisoformat(entry_time_str)
        exit_time = datetime.fromisoformat(exit_time_str) if exit_time_str else None
        
        # Calculate metrics
        spot_move = spot_exit - spot_entry if spot_exit else 0
        spot_move_pct = (spot_move / spot_entry * 100) if spot_entry else 0
        vix_change = vix_exit - vix_entry if vix_exit and vix_entry else 0
        
        # Get position tracking data
        cursor.execute('''
            SELECT timestamp, ltp, unrealized_pnl, delta
            FROM position_tracking
            WHERE trade_id = ?
            ORDER BY timestamp
        ''', (trade_id,))
        
        tracking_data = cursor.fetchall()
        conn.close()
        
        # Build autopsy report
        autopsy = {
            "trade_summary": {
                "symbol": symbol,
                "type": opt_type,
                "strike": strike,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "was_winner": pnl > 0,
                "hold_duration_mins": hold_mins,
                "entry_time": entry_time.strftime("%Y-%m-%d %H:%M"),
                "exit_time": exit_time.strftime("%Y-%m-%d %H:%M") if exit_time else None,
            },
            "market_conditions": self._analyze_market_conditions(
                spot_entry, spot_exit, vix_entry, vix_exit, iv_rank, dte,
                is_expiry, is_0dte, dow, entry_hour
            ),
            "timing_analysis": self._analyze_timing(
                entry_time, entry_hour, dow, is_expiry, is_0dte, dte,
                vix_entry, iv_rank, gamma
            ),
            "position_quality": self._analyze_position_quality(
                delta_entry, gamma, theta, strike, spot_entry, opt_type, dte
            ),
            "exit_analysis": self._analyze_exit_decision(
                pnl, pnl_pct, exit_reason, emotion, hold_mins,
                max_profit, max_loss, entry_price, exit_price,
                spot_move_pct, vix_change
            ),
            "greek_behavior": self._analyze_greeks(
                delta_entry, delta_exit, gamma, spot_move, opt_type
            ),
            "emotional_factors": self._analyze_emotional_state(
                emotion, exit_reason, was_planned, source, hold_mins, pnl
            ),
            "what_went_right": [],
            "what_went_wrong": [],
            "lessons": [],
            "next_time": []
        }
        
        # Compile insights
        autopsy = self._compile_insights(autopsy)
        
        return autopsy
    
    def _analyze_market_conditions(self, spot_entry, spot_exit, vix_entry, vix_exit,
                                   iv_rank, dte, is_expiry, is_0dte, dow, entry_hour):
        """Analyze if market conditions were favorable for option selling"""
        
        analysis = {
            "vix_environment": "Unknown",
            "iv_rank_assessment": "Unknown",
            "spot_movement": 0,
            "was_favorable": True,
            "warnings": []
        }
        
        # VIX Analysis
        if vix_entry:
            if vix_entry < 12:
                analysis["vix_environment"] = "Low (Dangerous for sellers)"
                analysis["was_favorable"] = False
                analysis["warnings"].append("VIX was too low - premiums compressed, limited profit potential")
            elif vix_entry < 15:
                analysis["vix_environment"] = "Normal"
            elif vix_entry < 18:
                analysis["vix_environment"] = "Elevated (Good for sellers)"
            else:
                analysis["vix_environment"] = "High (Excellent for sellers)"
        
        # VIX Spike Check
        if vix_entry and vix_exit:
            vix_change_pct = ((vix_exit - vix_entry) / vix_entry) * 100
            if vix_change_pct > 10:
                analysis["warnings"].append(f"VIX spiked {vix_change_pct:.1f}% during trade - unexpected volatility expansion")
        
        # IV Rank
        if iv_rank:
            if iv_rank < 30:
                analysis["iv_rank_assessment"] = "Low (<30) - Premium risk"
                analysis["warnings"].append("IV Rank was low - minimal edge, premiums could collapse further")
            elif iv_rank < 50:
                analysis["iv_rank_assessment"] = "Medium (30-50)"
            else:
                analysis["iv_rank_assessment"] = "High (>50) - Good selling opportunity"
        
        # Spot Movement
        if spot_entry and spot_exit:
            spot_move_pct = ((spot_exit - spot_entry) / spot_entry) * 100
            analysis["spot_movement"] = spot_move_pct
            
            if abs(spot_move_pct) > 2:
                analysis["warnings"].append(f"Large spot movement: {spot_move_pct:+.2f}%")
        
        # DTE Risk
        if is_0dte:
            analysis["warnings"].append("⚠️ 0 DTE trade - Extreme gamma risk, theta not enough to offset")
        elif dte and dte < 2:
            analysis["warnings"].append(f"Very close to expiry ({dte:.1f} days) - High gamma risk")
        
        # Time of Entry
        if entry_hour:
            if entry_hour < 10:
                analysis["warnings"].append("Entered in first hour - High volatility window")
            elif entry_hour >= 15:
                analysis["warnings"].append("Entered late in day - Limited time to profit from theta")
        
        # Day of Week
        if dow in ['Monday', 'Friday']:
            analysis["warnings"].append(f"Traded on {dow} - Statistically higher volatility day")
        
        return analysis
    
    def _analyze_timing(self, entry_time, entry_hour, dow, is_expiry, is_0dte,
                       dte, vix, iv_rank, gamma):
        """Was the entry timing optimal?"""
        
        timing = {
            "entry_timing_grade": "B",
            "should_have_waited": False,
            "reasons": []
        }
        
        # Morning Rush (9:15 - 10:00)
        if entry_hour and entry_hour < 10:
            timing["should_have_waited"] = True
            timing["reasons"].append("❌ Entered during morning volatility spike (9:15-10:00)")
            timing["reasons"].append("→ Better: Wait till 10:30 AM for volatility to settle")
            timing["entry_timing_grade"] = "D"
        
        # High Gamma + Early Entry
        if gamma and gamma > 0.002 and entry_hour and entry_hour < 11:
            timing["should_have_waited"] = True
            timing["reasons"].append("❌ High gamma (>0.002) + early entry = Recipe for disaster")
            timing["reasons"].append("→ Better: Wait for gamma to cool or spot to stabilize")
        
        # VIX Spike Timing
        if vix and vix > 18 and entry_hour and entry_hour < 12:
            timing["reasons"].append("⚠️ VIX was elevated early in day - Could have gotten better entry later")
            timing["should_have_waited"] = True
        
        # Expiry Day Entry
        if is_expiry or is_0dte:
            if entry_hour and entry_hour < 14:
                timing["reasons"].append("❌ Expiry day trade before 2 PM - Maximum gamma risk window")
                timing["reasons"].append("→ Better: On expiry, trade only after 2 PM or avoid entirely")
                timing["entry_timing_grade"] = "F"
            else:
                timing["reasons"].append("✅ Expiry day entry after 2 PM - Acceptable risk window")
                timing["entry_timing_grade"] = "B"
        
        # Low IV Rank
        if iv_rank and iv_rank < 30:
            timing["should_have_waited"] = True
            timing["reasons"].append("❌ IV Rank <30 - Premium too low, should wait for IV expansion")
            timing["reasons"].append("→ Better: Wait for IV Rank >40 for meaningful premium")
        
        # Good Timing Scenarios
        if not timing["should_have_waited"]:
            if dte and dte >= 3 and vix and vix > 15:
                timing["reasons"].append("✅ Good entry: Sufficient DTE + Decent VIX")
                timing["entry_timing_grade"] = "A"
            
            if entry_hour and 11 <= entry_hour <= 14:
                timing["reasons"].append("✅ Entered in stable trading hours (11 AM - 2 PM)")
        
        return timing
    
    def _analyze_position_quality(self, delta, gamma, theta, strike, spot, opt_type, dte):
        """Analyze if the position selection was optimal"""
        
        quality = {
            "position_grade": "B",
            "strike_selection": "Unknown",
            "risk_assessment": [],
            "improvements": []
        }
        
        # Delta Analysis
        if delta:
            abs_delta = abs(delta)
            
            if abs_delta < 0.15:
                quality["strike_selection"] = "Far OTM (Delta <0.15) - Very safe but low premium"
                quality["risk_assessment"].append("✅ Conservative strike - Low probability of being tested")
            elif abs_delta < 0.25:
                quality["strike_selection"] = "Safe OTM (Delta 0.15-0.25) - Good balance"
                quality["risk_assessment"].append("✅ Optimal strike selection for income generation")
                quality["position_grade"] = "A"
            elif abs_delta < 0.35:
                quality["strike_selection"] = "Moderate OTM (Delta 0.25-0.35) - Higher risk"
                quality["risk_assessment"].append("⚠️ Decent premium but higher probability of loss")
            else:
                quality["strike_selection"] = "Close to ATM (Delta >0.35) - High risk"
                quality["risk_assessment"].append("❌ Too close to money - High risk of assignment")
                quality["improvements"].append("→ Use wider strikes (target delta <0.25)")
                quality["position_grade"] = "D"
        
        # Gamma Risk
        if gamma:
            if gamma > 0.003:
                quality["risk_assessment"].append("❌ Extremely high gamma - Position could explode against you")
                quality["improvements"].append("→ Avoid positions with gamma >0.003")
                quality["position_grade"] = "F"
            elif gamma > 0.002:
                quality["risk_assessment"].append("⚠️ High gamma - Requires close monitoring")
                quality["improvements"].append("→ Consider rolling to wider strikes")
        
        # Theta Analysis
        if theta and dte:
            daily_theta = abs(theta)
            
            if dte < 2 and daily_theta < 10:
                quality["risk_assessment"].append("❌ Low theta near expiry - Not worth the gamma risk")
                quality["improvements"].append("→ Near expiry, theta must be substantial to justify risk")
        
        # Distance from Spot
        if strike and spot:
            distance = abs(strike - spot)
            distance_pct = (distance / spot) * 100
            
            if distance_pct < 1:
                quality["risk_assessment"].append(f"❌ Strike too close ({distance_pct:.1f}% from spot)")
                quality["improvements"].append("→ Maintain at least 2% buffer from spot")
            elif distance_pct < 2:
                quality["risk_assessment"].append(f"⚠️ Moderate distance ({distance_pct:.1f}% from spot)")
            else:
                quality["risk_assessment"].append(f"✅ Safe distance ({distance_pct:.1f}% from spot)")
        
        return quality
    
    def _analyze_exit_decision(self, pnl, pnl_pct, exit_reason, emotion,
                               hold_mins, max_profit, max_loss,
                               entry_price, exit_price, spot_move_pct, vix_change):
        """Analyze if the exit was optimal"""
        
        exit_analysis = {
            "exit_grade": "B",
            "was_optimal": True,
            "missed_opportunity": False,
            "insights": []
        }
        
        # Quick Exit Analysis
        if hold_mins and hold_mins < 30:
            exit_analysis["was_optimal"] = False
            exit_analysis["insights"].append("❌ Extremely quick exit (<30 mins) - Likely panic")
            exit_analysis["insights"].append("→ Lesson: Wait at least 30-60 mins for noise to settle")
            exit_analysis["exit_grade"] = "F"
        
        # Emotional Exit
        if emotion and emotion in ['fearful', 'panic', 'impatient']:
            exit_analysis["was_optimal"] = False
            exit_analysis["insights"].append(f"❌ Exit driven by {emotion} emotion - Not systematic")
            exit_analysis["insights"].append("→ Lesson: Follow predefined exit rules, not emotions")
            exit_analysis["exit_grade"] = "D"
        
        # Loss Analysis
        if pnl and pnl < 0:
            loss_pct = abs(pnl_pct) if pnl_pct else 0
            
            if loss_pct < 20:
                exit_analysis["insights"].append(f"⚠️ Small loss ({loss_pct:.1f}%) - Could have been avoided")
                
                if exit_reason == "manual" and hold_mins and hold_mins < 60:
                    exit_analysis["insights"].append("→ Likely exited during temporary volatility spike")
                    exit_analysis["insights"].append("→ Better: Set stop at 50% loss, give position breathing room")
            
            elif loss_pct < 50:
                exit_analysis["insights"].append(f"Moderate loss ({loss_pct:.1f}%) - Within acceptable range")
                
                if exit_reason == "stop_loss":
                    exit_analysis["insights"].append("✅ Systematic exit at stop loss - Good discipline")
                    exit_analysis["exit_grade"] = "B"
            
            else:
                exit_analysis["insights"].append(f"❌ Large loss ({loss_pct:.1f}%) - Stop was too late")
                exit_analysis["insights"].append("→ Lesson: Exit at 50% loss maximum for short options")
                exit_analysis["exit_grade"] = "F"
        
        # Profit Analysis
        elif pnl and pnl > 0:
            profit_pct = pnl_pct if pnl_pct else 0
            
            # Check if left money on table
            if max_profit and pnl < max_profit * 0.7:
                exit_analysis["missed_opportunity"] = True
                exit_analysis["insights"].append(f"⚠️ Exited too early - Could have made {(max_profit/pnl):.1f}x more")
                exit_analysis["insights"].append("→ Better: Use trailing stops or target 50-70% max profit")
            
            if profit_pct >= 50:
                exit_analysis["insights"].append(f"✅ Excellent exit at {profit_pct:.1f}% profit")
                exit_analysis["exit_grade"] = "A"
            elif profit_pct >= 30:
                exit_analysis["insights"].append(f"✅ Good exit at {profit_pct:.1f}% profit")
            else:
                exit_analysis["insights"].append(f"⚠️ Small profit ({profit_pct:.1f}%) - Could have waited")
        
        # Gamma Panic Exit
        if exit_reason == "gamma_panic":
            exit_analysis["insights"].append("❌ Exited due to gamma panic - Position never properly sized")
            exit_analysis["insights"].append("→ Lesson: If gamma scares you, position is too big or too close")
            exit_analysis["exit_grade"] = "D"
        
        # VIX Spike Exit
        if vix_change and vix_change > 1.5:
            if pnl and pnl < 0:
                exit_analysis["insights"].append("✅ Right to exit during VIX spike - Avoided bigger loss")
                exit_analysis["exit_grade"] = "A"
        
        return exit_analysis
    
    def _analyze_greeks(self, delta_entry, delta_exit, gamma, spot_move, opt_type):
        """Analyze how Greeks impacted the trade"""
        
        greek_analysis = {
            "delta_impact": "Unknown",
            "gamma_impact": "Unknown",
            "insights": []
        }
        
        # Delta Movement
        if delta_entry and delta_exit:
            delta_change = abs(delta_exit) - abs(delta_entry)
            
            if delta_change > 0.10:
                greek_analysis["delta_impact"] = "Position moved significantly closer to ATM"
                greek_analysis["insights"].append("❌ Delta increased by >0.10 - Position was tested")
                greek_analysis["insights"].append("→ Next time: Wider strikes or exit when delta increases >0.05")
            elif delta_change > 0.05:
                greek_analysis["delta_impact"] = "Moderate delta increase"
                greek_analysis["insights"].append("⚠️ Position approached ATM - Was heading toward danger zone")
            else:
                greek_analysis["delta_impact"] = "Delta remained stable"
                greek_analysis["insights"].append("✅ Strike selection was safe - Never seriously threatened")
        
        # Gamma Impact
        if gamma:
            if gamma > 0.003:
                greek_analysis["gamma_impact"] = "Extremely high gamma - Position was radioactive"
                greek_analysis["insights"].append("❌ Gamma >0.003 means position can explode in minutes")
                greek_analysis["insights"].append("→ Lesson: Never sell options with gamma >0.0025")
            elif gamma > 0.002:
                greek_analysis["gamma_impact"] = "High gamma - Required constant monitoring"
                greek_analysis["insights"].append("⚠️ High gamma requires active management")
            else:
                greek_analysis["gamma_impact"] = "Manageable gamma"
        
        # Spot Move Impact
        if spot_move and gamma:
            estimated_delta_change = gamma * abs(spot_move)
            
            if estimated_delta_change > 0.08:
                greek_analysis["insights"].append(f"❌ Spot moved {spot_move:+.0f} points causing major delta shift")
                greek_analysis["insights"].append("→ This is why you need wide strikes with low gamma")
        
        return greek_analysis
    
    def _analyze_emotional_state(self, emotion, exit_reason, was_planned, source, hold_mins, pnl):
        """Analyze emotional and behavioral factors"""
        
        emotional = {
            "discipline_grade": "B",
            "was_systematic": was_planned,
            "insights": []
        }
        
        # Planned vs Reactive
        if not was_planned or source == "zerodha_app":
            emotional["discipline_grade"] = "D"
            emotional["insights"].append("❌ Unplanned trade (Zerodha app) - Likely emotional")
            emotional["insights"].append("→ Lesson: All trades should be pre-analyzed and planned")
        
        # Emotional State
        if emotion:
            if emotion in ['fearful', 'panic']:
                emotional["insights"].append("❌ Fear-driven decision making - This is your enemy")
                emotional["insights"].append("→ Lesson: Set rules BEFORE trade, follow them mechanically")
                emotional["discipline_grade"] = "F"
            
            elif emotion in ['greedy', 'overconfident']:
                emotional["insights"].append("❌ Greed-driven trade - Likely oversized or too aggressive")
                emotional["insights"].append("→ Lesson: Stick to position sizing rules, no exceptions")
                emotional["discipline_grade"] = "D"
            
            elif emotion == 'calm':
                emotional["insights"].append("✅ Calm, systematic execution - This is the way")
                emotional["discipline_grade"] = "A"
        
        # Quick Exit Pattern
        if hold_mins and hold_mins < 15:
            emotional["insights"].append("❌ Exit within 15 minutes = Pure panic, no analysis")
            emotional["insights"].append("→ Rule: Never close before 30 mins unless stop loss hit")
        
        # Manual Override
        if exit_reason == "manual" and pnl and pnl < 0:
            emotional["insights"].append("⚠️ Manual exit on loss - Were you following a plan?")
        
        return emotional
    
    def _compile_insights(self, autopsy):
        """Compile what went right/wrong and actionable lessons"""
        
        trade = autopsy["trade_summary"]
        market = autopsy["market_conditions"]
        timing = autopsy["timing_analysis"]
        position = autopsy["position_quality"]
        exit_info = autopsy["exit_analysis"]
        greeks = autopsy["greek_behavior"]
        emotional = autopsy["emotional_factors"]
        
        # WHAT WENT RIGHT
        if trade["was_winner"]:
            autopsy["what_went_right"].append("✅ Trade was profitable")
        
        if not timing["should_have_waited"]:
            autopsy["what_went_right"].append("✅ Entry timing was good")
        
        if position["position_grade"] in ['A', 'B']:
            autopsy["what_went_right"].append("✅ Strike selection was appropriate")
        
        if emotional["discipline_grade"] in ['A', 'B']:
            autopsy["what_went_right"].append("✅ Trade was systematic and planned")
        
        if market["was_favorable"] and market["vix_environment"] in ["Elevated (Good for sellers)", "High (Excellent for sellers)"]:
            autopsy["what_went_right"].append("✅ Sold premium in favorable VIX environment")
        
        # WHAT WENT WRONG
        if not trade["was_winner"]:
            autopsy["what_went_wrong"].append("❌ Trade resulted in loss")
        
        if timing["should_have_waited"]:
            autopsy["what_went_wrong"].append("❌ Poor entry timing - should have waited")
        
        if position["position_grade"] in ['D', 'F']:
            autopsy["what_went_wrong"].append("❌ Strike selection was too aggressive")
        
        if emotional["discipline_grade"] in ['D', 'F']:
            autopsy["what_went_wrong"].append("❌ Trade lacked discipline/planning")
        
        if not market["was_favorable"]:
            autopsy["what_went_wrong"].append("❌ Market conditions were unfavorable for selling")
        
        for warning in market["warnings"]:
            if "0 DTE" in warning or "High gamma" in warning:
                autopsy["what_went_wrong"].append(f"❌ {warning}")
        
        # LESSONS LEARNED
        autopsy["lessons"] = self._extract_lessons(autopsy)
        
        # NEXT TIME (Actionable Items)
        autopsy["next_time"] = self._generate_action_items(autopsy)
        
        return autopsy
    
    def _extract_lessons(self, autopsy):
        """Extract key lessons from the trade"""
        lessons = []
        
        timing = autopsy["timing_analysis"]
        position = autopsy["position_quality"]
        exit_info = autopsy["exit_analysis"]
        market = autopsy["market_conditions"]
        
        # Add all reason-based lessons
        for reason in timing.get("reasons", []):
            if "→" in reason:
                lessons.append(reason.split("→")[1].strip())
        
        for improvement in position.get("improvements", []):
            if "→" in improvement:
                lessons.append(improvement.split("→")[1].strip())
        
        for insight in exit_info.get("insights", []):
            if "→ Lesson:" in insight:
                lessons.append(insight.split("→ Lesson:")[1].strip())
        
        return list(set(lessons))  # Remove duplicates
    
    def _generate_action_items(self, autopsy):
        """Generate specific action items for next trade"""
        actions = []
        
        timing = autopsy["timing_analysis"]
        position = autopsy["position_quality"]
        market = autopsy["market_conditions"]
        emotional = autopsy["emotional_factors"]
        
        # Timing Actions
        if timing["should_have_waited"]:
            actions.append("⏰ TIMING: Wait for 10:30 AM entry, avoid morning volatility")
        
        # VIX Actions
        if market.get("iv_rank_assessment") == "Low (<30) - Premium risk":
            actions.append("📊 VIX: Don't sell when IV Rank <30, wait for expansion >40")
        
        # Position Sizing
        if position["position_grade"] in ['D', 'F']:
            actions.append("🎯 STRIKES: Use wider strikes, target delta <0.25")
        
        # Gamma Management
        if "High gamma" in str(position.get("risk_assessment", [])):
            actions.append("⚡ GAMMA: Never sell options with gamma >0.0025")
        
        # DTE Management
        if market.get("warnings") and any("DTE" in w for w in market["warnings"]):
            actions.append("📅 DTE: Avoid trading with <3 DTE, gamma risk too high")
        
        # Emotional Discipline
        if emotional["discipline_grade"] in ['D', 'F']:
            actions.append("🧘 DISCIPLINE: Plan trade in advance, set stops BEFORE entering")
        
        # Exit Management
        if "stop_loss" not in str(autopsy.get("exit_analysis", {})):
            actions.append("🛑 EXITS: Always use 50% loss stop, 70% profit target")
        
        return actions


# ============================================
# API ENDPOINT INTEGRATION
# ============================================

def get_trade_autopsy(trade_id: str) -> Dict:
    """
    API endpoint function to get complete trade autopsy
    Call this after trade is closed to get detailed analysis
    """
    autopsy_engine = TradeAutopsy()
    return autopsy_engine.analyze_trade(trade_id)


# Example Usage in FastAPI endpoint
"""
@app.get("/api/journal/trade_autopsy/{trade_id}")
async def get_trade_analysis(trade_id: str):
    try:
        autopsy = get_trade_autopsy(trade_id)
        return {"success": True, "autopsy": autopsy}
    except Exception as e:
        return {"success": False, "error": str(e)}
"""