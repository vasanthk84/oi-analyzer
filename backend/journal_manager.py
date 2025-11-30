# backend/journal_manager.py
"""
Trading Journal Manager
Handles trade persistence, performance analytics, and behavioral pattern tracking
"""

import sqlite3
import uuid
from datetime import datetime
import pytz
import pandas as pd
import re
from typing import Optional, Dict, List, Tuple

class TradingJournal:
    def __init__(self, db_path="backend/nifty_history.db"):
        """
        Initialize Trading Journal Manager
        
        Args:
            db_path: Path to SQLite database (uses same DB as historical data)
        """
        self.db_path = db_path
        self.ist_tz = pytz.timezone('Asia/Kolkata')
    
    # ============================================
    # TRADE ENTRY/EXIT RECORDING
    # ============================================
    
    def record_trade_entry(
        self, 
        position_data: Dict, 
        market_context: Dict, 
        source: str = "app_auto",
        session_id: Optional[str] = None
    ) -> str:
        """
        Record a new trade entry with full market context
        
        Args:
            position_data: Dict with keys:
                - tradingsymbol: str
                - quantity: int
                - average_price: float
                - order_id: str (optional)
            market_context: Dict with keys:
                - spot: float
                - vix: float
                - iv_rank: float
                - dte: float
                - delta: float
                - gamma: float
                - theta: float
            source: 'app_auto', 'app_manual', 'zerodha_app', 'unknown'
            session_id: Optional UUID to link multiple legs together
        
        Returns:
            trade_id: Unique identifier for this trade
        """
        trade_id = str(uuid.uuid4())
        now = datetime.now(self.ist_tz)
        
        # Parse symbol for details
        symbol = position_data['tradingsymbol']
        instrument_type = self._extract_instrument_type(symbol)
        strike = self._extract_strike(symbol)
        expiry_date = self._extract_expiry(symbol)
        
        # Time analysis
        day_of_week = now.strftime('%A')
        dte = market_context.get('dte', 0)
        is_expiry_day = dte < 1
        is_zero_dte = dte == 0
        hour_of_entry = now.hour
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO trades (
                    trade_id, session_id, source, symbol, instrument_type, strike, expiry_date,
                    quantity, entry_time, entry_price, entry_order_id,
                    spot_at_entry, vix_at_entry, iv_rank_at_entry, dte_at_entry,
                    delta_at_entry, gamma_at_entry, theta_at_entry,
                    day_of_week, is_expiry_day, is_zero_dte, hour_of_entry,
                    was_planned
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                trade_id,
                session_id or str(uuid.uuid4()),  # Generate session_id if not provided
                source,
                symbol,
                instrument_type,
                strike,
                expiry_date,
                position_data['quantity'],
                now,
                position_data['average_price'],
                position_data.get('order_id'),
                market_context.get('spot'),
                market_context.get('vix'),
                market_context.get('iv_rank'),
                dte,
                market_context.get('delta'),
                market_context.get('gamma'),
                market_context.get('theta'),
                day_of_week,
                is_expiry_day,
                is_zero_dte,
                hour_of_entry,
                source.startswith('app')  # App trades are planned
            ))
            
            conn.commit()
            print(f"✅ Recorded trade entry: {symbol} @ {position_data['average_price']} (ID: {trade_id[:8]}...)")
            
        except Exception as e:
            print(f"❌ Failed to record trade entry: {e}")
            conn.rollback()
        finally:
            conn.close()
        
        return trade_id
    
    def record_trade_exit(
        self, 
        trade_id: str, 
        exit_data: Dict, 
        market_context: Dict, 
        exit_reason: str = "manual", 
        emotional_state: Optional[str] = None,
        notes: Optional[str] = None
    ) -> bool:
        """
        Record trade exit and calculate final metrics
        
        Args:
            trade_id: UUID of the trade
            exit_data: Dict with exit_price and order_id
            market_context: Current market state (spot, vix, delta)
            exit_reason: 'manual', 'stop_loss', 'target', 'roll', 'eod', 'gamma_panic'
            emotional_state: 'calm', 'fearful', 'greedy', 'impatient', etc.
            notes: Post-trade notes/reflections
        
        Returns:
            success: True if exit recorded successfully
        """
        now = datetime.now(self.ist_tz)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Get entry data
            cursor.execute('''
                SELECT entry_time, entry_price, quantity, symbol 
                FROM trades 
                WHERE trade_id = ?
            ''', (trade_id,))
            
            entry = cursor.fetchone()
            if not entry:
                print(f"❌ Trade {trade_id[:8]}... not found")
                conn.close()
                return False
            
            entry_time_str, entry_price, quantity, symbol = entry
            entry_time = datetime.fromisoformat(entry_time_str)
            exit_price = exit_data['exit_price']
            
            # Calculate P&L (for short strangle: profit when price drops)
            realized_pnl = (entry_price - exit_price) * quantity
            realized_pnl_pct = ((entry_price - exit_price) / entry_price) * 100 if entry_price > 0 else 0
            
            # Calculate hold duration
            hold_minutes = int((now - entry_time).total_seconds() / 60)
            
            # Update trade
            cursor.execute('''
                UPDATE trades SET
                    exit_time = ?,
                    exit_price = ?,
                    exit_order_id = ?,
                    exit_reason = ?,
                    realized_pnl = ?,
                    realized_pnl_pct = ?,
                    spot_at_exit = ?,
                    vix_at_exit = ?,
                    delta_at_exit = ?,
                    hold_duration_minutes = ?,
                    emotional_state = ?,
                    notes = ?,
                    updated_at = ?
                WHERE trade_id = ?
            ''', (
                now,
                exit_price,
                exit_data.get('order_id'),
                exit_reason,
                realized_pnl,
                realized_pnl_pct,
                market_context.get('spot'),
                market_context.get('vix'),
                market_context.get('delta'),
                hold_minutes,
                emotional_state,
                notes,
                now,
                trade_id
            ))
            
            conn.commit()
            
            print(f"✅ Recorded trade exit: {symbol} @ {exit_price:.2f} | P&L: {realized_pnl:+.0f} ({realized_pnl_pct:+.1f}%)")
            
            # Update daily summary
            self._update_daily_summary(now.date())
            
            return True
            
        except Exception as e:
            print(f"❌ Failed to record trade exit: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()
    
    def find_trade_by_symbol(self, symbol: str, entry_price: float) -> Optional[str]:
        """
        Find an open trade by symbol and entry price
        Useful for matching Zerodha positions to journal entries
        
        Returns:
            trade_id if found, None otherwise
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT trade_id FROM trades 
            WHERE symbol = ? 
            AND entry_price = ? 
            AND exit_time IS NULL
            ORDER BY entry_time DESC
            LIMIT 1
        ''', (symbol, entry_price))
        
        result = cursor.fetchone()
        conn.close()
        
        return result[0] if result else None
    
    # ============================================
    # POSITION MONITORING
    # ============================================
    
    def track_position_update(self, trade_id: str, ltp: float, unrealized_pnl: float, delta: float):
        """
        Record position snapshot for monitoring max profit/loss
        Call this every 2-5 seconds for open positions
        """
        now = datetime.now(self.ist_tz)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Insert snapshot
            cursor.execute('''
                INSERT INTO position_tracking (trade_id, timestamp, ltp, unrealized_pnl, delta)
                VALUES (?, ?, ?, ?, ?)
            ''', (trade_id, now, ltp, unrealized_pnl, delta))
            
            # Update max profit/loss
            cursor.execute('''
                UPDATE trades SET
                    max_profit = MAX(max_profit, ?),
                    max_loss = MIN(max_loss, ?)
                WHERE trade_id = ?
            ''', (
                unrealized_pnl if unrealized_pnl > 0 else 0, 
                unrealized_pnl if unrealized_pnl < 0 else 0,
                trade_id
            ))
            
            conn.commit()
            
        except Exception as e:
            print(f"Warning: Position tracking failed for {trade_id[:8]}: {e}")
            conn.rollback()
        finally:
            conn.close()
    
    def save_market_snapshot(self, data: Dict):
        """
        Save periodic market snapshots (every 5 minutes recommended)
        
        Args:
            data: Dict with spot, vix, iv_rank, dte, pcr, max_pain
        """
        now = datetime.now(self.ist_tz)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO market_snapshots (timestamp, spot, vix, iv_rank, dte, pcr, max_pain)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                now,
                data.get('spot'),
                data.get('vix'),
                data.get('iv_rank'),
                data.get('dte'),
                data.get('pcr'),
                data.get('max_pain')
            ))
            
            conn.commit()
            
        except Exception as e:
            print(f"Warning: Market snapshot failed: {e}")
            conn.rollback()
        finally:
            conn.close()
    
    # ============================================
    # LESSONS & NOTES
    # ============================================
    
    def add_lesson(
        self, 
        lesson_text: str, 
        category: str, 
        severity: str = "minor", 
        trade_id: Optional[str] = None, 
        action_plan: Optional[str] = None
    ):
        """
        Add a trading lesson
        
        Args:
            lesson_text: What happened?
            category: 'entry', 'exit', 'risk_mgmt', 'emotional', 'strategy'
            severity: 'minor', 'major', 'critical'
            trade_id: Optional link to specific trade
            action_plan: What will you do differently?
        """
        now = datetime.now(self.ist_tz)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO lessons_learned (date, trade_id, category, lesson, severity, action_plan)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (now.date(), trade_id, category, lesson_text, severity, action_plan))
            
            conn.commit()
            print(f"✅ Lesson recorded: [{severity.upper()}] {category}")
            
        except Exception as e:
            print(f"❌ Failed to record lesson: {e}")
            conn.rollback()
        finally:
            conn.close()
    
    def update_trade_notes(self, trade_id: str, emotional_state: str, notes: str):
        """Update emotional state and notes for a trade"""
        now = datetime.now(self.ist_tz)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                UPDATE trades SET
                    emotional_state = ?,
                    notes = ?,
                    updated_at = ?
                WHERE trade_id = ?
            ''', (emotional_state, notes, now, trade_id))
            
            conn.commit()
            return True
            
        except Exception as e:
            print(f"❌ Failed to update notes: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()
    
    # ============================================
    # PERFORMANCE ANALYTICS
    # ============================================
    
    def get_performance_summary(self, days: int = 30) -> Dict:
        """
        Get comprehensive performance analytics
        
        Returns:
            Dict with overall stats, day-of-week analysis, expiry analysis, etc.
        """
        conn = sqlite3.connect(self.db_path)
        
        # Overall Stats
        query_overall = f'''
            SELECT 
                COUNT(*) as total_trades,
                SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
                SUM(CASE WHEN realized_pnl < 0 THEN 1 ELSE 0 END) as losing_trades,
                SUM(realized_pnl) as total_pnl,
                AVG(realized_pnl) as avg_pnl,
                MAX(realized_pnl) as largest_win,
                MIN(realized_pnl) as largest_loss,
                AVG(hold_duration_minutes) as avg_hold_minutes,
                AVG(realized_pnl_pct) as avg_pnl_pct
            FROM trades
            WHERE exit_time >= datetime('now', '-{days} days')
        '''
        
        df_overall = pd.read_sql_query(query_overall, conn)
        overall = df_overall.to_dict('records')[0]
        
        # Calculate win rate
        total = overall.get('total_trades', 0)
        wins = overall.get('winning_trades', 0)
        win_rate = round((wins / total * 100), 2) if total > 0 else 0
        
        # Day of Week Analysis
        query_dow = f'''
            SELECT 
                day_of_week,
                COUNT(*) as trades,
                AVG(realized_pnl) as avg_pnl,
                SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as win_rate
            FROM trades
            WHERE exit_time >= datetime('now', '-{days} days')
            GROUP BY day_of_week
        '''
        
        df_dow = pd.read_sql_query(query_dow, conn)
        
        # Expiry Day Performance
        query_expiry = f'''
            SELECT 
                is_expiry_day,
                COUNT(*) as trades,
                AVG(realized_pnl) as avg_pnl,
                SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as win_rate
            FROM trades
            WHERE exit_time >= datetime('now', '-{days} days')
            GROUP BY is_expiry_day
        '''
        
        df_expiry = pd.read_sql_query(query_expiry, conn)
        
        # Emotional State Analysis
        query_emotional = f'''
            SELECT 
                emotional_state,
                COUNT(*) as trades,
                AVG(realized_pnl) as avg_pnl,
                SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as win_rate
            FROM trades
            WHERE exit_time >= datetime('now', '-{days} days') 
            AND emotional_state IS NOT NULL
            GROUP BY emotional_state
        '''
        
        df_emotional = pd.read_sql_query(query_emotional, conn)
        
        # VIX Correlation
        query_vix = f'''
            SELECT 
                CASE 
                    WHEN vix_at_entry < 12 THEN 'Low (<12)'
                    WHEN vix_at_entry < 15 THEN 'Normal (12-15)'
                    WHEN vix_at_entry < 18 THEN 'Elevated (15-18)'
                    ELSE 'High (>18)'
                END as vix_range,
                COUNT(*) as trades,
                AVG(realized_pnl) as avg_pnl,
                SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as win_rate
            FROM trades
            WHERE exit_time >= datetime('now', '-{days} days')
            GROUP BY vix_range
        '''
        
        df_vix = pd.read_sql_query(query_vix, conn)
        
        conn.close()
        
        return {
            "overall": overall,
            "win_rate": win_rate,
            "by_day_of_week": df_dow.to_dict('records'),
            "expiry_day_analysis": df_expiry.to_dict('records'),
            "emotional_analysis": df_emotional.to_dict('records'),
            "vix_correlation": df_vix.to_dict('records')
        }
    
    def get_recent_lessons(self, limit: int = 10) -> List[Dict]:
        """Get recent trading lessons"""
        conn = sqlite3.connect(self.db_path)
        
        query = '''
            SELECT date, category, lesson, severity, action_plan, trade_id
            FROM lessons_learned
            ORDER BY created_at DESC
            LIMIT ?
        '''
        
        df = pd.read_sql_query(query, conn, params=(limit,))
        conn.close()
        
        return df.to_dict('records')
    
    def get_open_positions(self) -> List[Dict]:
        """Get all currently open positions from journal"""
        conn = sqlite3.connect(self.db_path)
        
        query = '''
            SELECT 
                trade_id, symbol, instrument_type, strike, 
                entry_price, quantity, entry_time,
                spot_at_entry, vix_at_entry, dte_at_entry,
                source, emotional_state
            FROM trades
            WHERE exit_time IS NULL
            ORDER BY entry_time DESC
        '''
        
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        return df.to_dict('records')
    
    # ============================================
    # DAILY SUMMARY MANAGEMENT
    # ============================================
    
    def _update_daily_summary(self, date):
        """Update daily summary statistics"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            # Calculate daily stats
            query = '''
                SELECT 
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) as winning_trades,
                    SUM(CASE WHEN realized_pnl < 0 THEN 1 ELSE 0 END) as losing_trades,
                    SUM(realized_pnl) as total_pnl,
                    MAX(realized_pnl) as largest_win,
                    MIN(realized_pnl) as largest_loss,
                    AVG(vix_at_entry) as avg_vix,
                    AVG(iv_rank_at_entry) as avg_iv_rank,
                    SUM(CASE WHEN emotional_state = 'fearful' THEN 1 ELSE 0 END) as trades_in_fear,
                    SUM(CASE WHEN emotional_state = 'greedy' THEN 1 ELSE 0 END) as trades_in_greed,
                    SUM(CASE WHEN exit_reason = 'gamma_panic' THEN 1 ELSE 0 END) as panic_exits
                FROM trades
                WHERE DATE(entry_time) = ?
            '''
            
            cursor.execute(query, (date,))
            stats = cursor.fetchone()
            
            if stats and stats[0] > 0:  # Only update if there are trades
                cursor.execute('''
                    INSERT OR REPLACE INTO daily_summary (
                        date, total_trades, winning_trades, losing_trades, total_pnl,
                        largest_win, largest_loss, avg_vix, avg_iv_rank,
                        trades_in_fear, trades_in_greed, panic_exits
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (date,) + stats)
                
                conn.commit()
            
        except Exception as e:
            print(f"Warning: Daily summary update failed: {e}")
            conn.rollback()
        finally:
            conn.close()
    
    # ============================================
    # HELPER FUNCTIONS
    # ============================================
    
    def _extract_instrument_type(self, symbol: str) -> Optional[str]:
        """Extract CE or PE from symbol"""
        if symbol.endswith('CE'):
            return 'CE'
        elif symbol.endswith('PE'):
            return 'PE'
        return None
    
    def _extract_strike(self, symbol: str) -> float:
        """Extract strike price from symbol (e.g., NIFTY25NOV26500CE -> 26500)"""
        match = re.search(r'(\d{5})(CE|PE)$', symbol)
        return float(match.group(1)) if match else 0.0
    
    def _extract_expiry(self, symbol: str) -> Optional[str]:
        """Extract expiry date from symbol (e.g., NIFTY25NOV -> 25NOV)"""
        match = re.search(r'(\d{2}[A-Z]{3})', symbol)
        return match.group(1) if match else None


# ============================================
# CONVENIENCE FUNCTIONS FOR API INTEGRATION
# ============================================

def get_journal_instance(db_path="backend/nifty_history.db") -> TradingJournal:
    """Get singleton journal instance"""
    return TradingJournal(db_path)
