import sqlite3
import pandas as pd
import os
from datetime import datetime

# Ensure we write to the same folder as this script (backend/)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "nifty_history.db")

# CSV Files (Update filenames if they change)
NIFTY_CSV = "NIFTY 50-01-01-2025-to-23-11-2025.csv"
VIX_CSV = "hist_india_vix_-01-01-2025-to-25-11-2025.csv"

def init_db():
    """Initialize database with complete schema including Trading Journal tables"""
    print(f"Initializing DB at: {DB_FILE}")
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # ============================================
    # EXISTING NIFTY OHLC TABLE (Keep unchanged)
    # ============================================
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
    
    # Check if 'vix' column exists (for existing DBs)
    cursor.execute("PRAGMA table_info(nifty_ohlc)")
    columns = [info[1] for info in cursor.fetchall()]
    if 'vix' not in columns:
        print("Adding 'vix' column to existing table...")
        try:
            cursor.execute("ALTER TABLE nifty_ohlc ADD COLUMN vix REAL")
        except Exception as e:
            print(f"Migration error: {e}")
    
    # ============================================
    # TRADING JOURNAL TABLES (NEW)
    # ============================================
    
    print("Creating Trading Journal tables...")
    
    # Main Trades Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            
            -- Trade Identity
            trade_id TEXT UNIQUE NOT NULL,
            session_id TEXT,
            source TEXT NOT NULL,
            
            -- Basic Trade Info
            symbol TEXT NOT NULL,
            instrument_type TEXT,
            strike REAL,
            expiry_date TEXT,
            quantity INTEGER,
            
            -- Entry Details
            entry_time TIMESTAMP NOT NULL,
            entry_price REAL NOT NULL,
            entry_order_id TEXT,
            
            -- Exit Details (NULL if still open)
            exit_time TIMESTAMP,
            exit_price REAL,
            exit_order_id TEXT,
            exit_reason TEXT,
            
            -- P&L
            realized_pnl REAL,
            realized_pnl_pct REAL,
            
            -- Market Context at Entry
            spot_at_entry REAL,
            vix_at_entry REAL,
            iv_rank_at_entry REAL,
            dte_at_entry REAL,
            delta_at_entry REAL,
            gamma_at_entry REAL,
            theta_at_entry REAL,
            
            -- Market Context at Exit
            spot_at_exit REAL,
            vix_at_exit REAL,
            delta_at_exit REAL,
            
            -- Time Analysis
            day_of_week TEXT,
            is_expiry_day BOOLEAN,
            is_zero_dte BOOLEAN,
            hour_of_entry INTEGER,
            
            -- Trade Quality Metrics
            max_profit REAL DEFAULT 0,
            max_loss REAL DEFAULT 0,
            hold_duration_minutes INTEGER,
            
            -- Post-Trade Analysis
            was_planned BOOLEAN DEFAULT 1,
            emotional_state TEXT,
            notes TEXT,
            
            -- Metadata
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Market Snapshots Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS market_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP NOT NULL,
            spot REAL,
            vix REAL,
            iv_rank REAL,
            dte REAL,
            pcr REAL,
            max_pain REAL
        )
    ''')
    
    # Position Tracking Table (for monitoring open trades)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS position_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id TEXT NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            ltp REAL,
            unrealized_pnl REAL,
            delta REAL,
            FOREIGN KEY (trade_id) REFERENCES trades(trade_id)
        )
    ''')
    
    # Daily Summary Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_summary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE NOT NULL,
            
            -- Performance
            total_trades INTEGER,
            winning_trades INTEGER,
            losing_trades INTEGER,
            total_pnl REAL,
            largest_win REAL,
            largest_loss REAL,
            
            -- Market Stats
            avg_vix REAL,
            avg_iv_rank REAL,
            
            -- Behavioral Patterns
            trades_in_fear INTEGER DEFAULT 0,
            trades_in_greed INTEGER DEFAULT 0,
            panic_exits INTEGER DEFAULT 0,
            
            -- Time Analysis
            best_performing_hour INTEGER,
            worst_performing_hour INTEGER,
            
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Trading Lessons Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS lessons_learned (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            trade_id TEXT,
            category TEXT,
            lesson TEXT NOT NULL,
            severity TEXT,
            action_plan TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (trade_id) REFERENCES trades(trade_id)
        )
    ''')
    
    # Trading Patterns Table (ML/AI Training Data)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trading_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            
            -- Pattern Signature
            pattern_type TEXT NOT NULL,
            
            -- Conditions
            vix_range TEXT,
            dte INTEGER,
            day_of_week TEXT,
            time_of_day TEXT,
            
            -- Behavior Observed
            typical_action TEXT,
            success_rate REAL,
            avg_pnl REAL,
            sample_size INTEGER,
            
            -- Recommendations
            suggested_action TEXT,
            
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # ============================================
    # CREATE INDEXES FOR PERFORMANCE
    # ============================================
    
    print("Creating indexes...")
    
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_entry_time ON trades(entry_time)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_exit_time ON trades(exit_time)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_source ON trades(source)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_day_of_week ON trades(day_of_week)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_trades_is_expiry ON trades(is_expiry_day)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_snapshot_time ON market_snapshots(timestamp)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tracking_trade ON position_tracking(trade_id, timestamp)')
    
    # ============================================
    # CREATE USEFUL VIEWS
    # ============================================
    
    print("Creating views...")
    
    # View: Current Open Positions
    cursor.execute('''
        CREATE VIEW IF NOT EXISTS v_open_positions AS
        SELECT 
            t.trade_id,
            t.symbol,
            t.instrument_type,
            t.strike,
            t.entry_price,
            t.entry_time,
            t.spot_at_entry,
            t.vix_at_entry,
            t.dte_at_entry,
            t.delta_at_entry,
            t.source,
            t.emotional_state,
            (julianday('now') - julianday(t.entry_time)) * 24 * 60 AS hold_minutes
        FROM trades t
        WHERE t.exit_time IS NULL
        ORDER BY t.entry_time DESC
    ''')
    
    # View: Weekly Performance
    cursor.execute('''
        CREATE VIEW IF NOT EXISTS v_weekly_performance AS
        SELECT 
            strftime('%Y-%W', date) AS week,
            SUM(total_pnl) AS weekly_pnl,
            AVG(CAST(winning_trades AS REAL) / NULLIF(total_trades, 0) * 100) AS avg_win_rate,
            SUM(total_trades) AS total_trades,
            AVG(avg_vix) AS avg_vix
        FROM daily_summary
        GROUP BY week
        ORDER BY week DESC
    ''')
    
    # View: Emotional Trading Analysis
    cursor.execute('''
        CREATE VIEW IF NOT EXISTS v_emotional_analysis AS
        SELECT 
            emotional_state,
            COUNT(*) AS trade_count,
            AVG(realized_pnl) AS avg_pnl,
            SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) AS win_rate,
            AVG(hold_duration_minutes) AS avg_hold_minutes
        FROM trades
        WHERE exit_time IS NOT NULL AND emotional_state IS NOT NULL
        GROUP BY emotional_state
    ''')
    
    # View: VIX Performance Correlation
    cursor.execute('''
        CREATE VIEW IF NOT EXISTS v_vix_performance AS
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
        WHERE exit_time IS NOT NULL
        GROUP BY vix_range
    ''')
    
    # View: Day of Week Performance
    cursor.execute('''
        CREATE VIEW IF NOT EXISTS v_dow_performance AS
        SELECT 
            day_of_week,
            COUNT(*) as trades,
            AVG(realized_pnl) as avg_pnl,
            SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as win_rate,
            AVG(hold_duration_minutes) as avg_hold_minutes
        FROM trades
        WHERE exit_time IS NOT NULL
        GROUP BY day_of_week
        ORDER BY 
            CASE day_of_week
                WHEN 'Monday' THEN 1
                WHEN 'Tuesday' THEN 2
                WHEN 'Wednesday' THEN 3
                WHEN 'Thursday' THEN 4
                WHEN 'Friday' THEN 5
            END
    ''')
    
    conn.commit()
    conn.close()
    
    print("✅ Database schema created successfully!")
    print("\nCreated tables:")
    print("  1. nifty_ohlc (existing - for historical data)")
    print("  2. trades (NEW - main trading journal)")
    print("  3. market_snapshots (NEW - periodic market data)")
    print("  4. position_tracking (NEW - position monitoring)")
    print("  5. daily_summary (NEW - daily performance)")
    print("  6. lessons_learned (NEW - trading lessons)")
    print("  7. trading_patterns (NEW - ML/AI patterns)")
    print("\nCreated views:")
    print("  - v_open_positions")
    print("  - v_weekly_performance")
    print("  - v_emotional_analysis")
    print("  - v_vix_performance")
    print("  - v_dow_performance")

def parse_date(date_str):
    """
    Tries to parse date from common formats found in NSE CSVs.
    Returns datetime.date object or None.
    """
    formats = [
        "%d-%b-%Y",  # 01-JAN-2025
        "%d-%m-%Y",  # 01-01-2025
        "%Y-%m-%d"   # 2025-01-01
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue
    return None

def import_csv():
    """Import NIFTY and VIX historical data"""
    # Check if files exist
    nifty_path = os.path.join(BASE_DIR, NIFTY_CSV)
    vix_path = os.path.join(BASE_DIR, VIX_CSV)
    
    # Fallback to check current directory if not found in backend/
    if not os.path.exists(nifty_path) and os.path.exists(NIFTY_CSV):
        nifty_path = NIFTY_CSV
    if not os.path.exists(vix_path) and os.path.exists(VIX_CSV):
        vix_path = VIX_CSV

    if not os.path.exists(nifty_path):
        print(f"Error: Nifty CSV not found: {nifty_path}")
        return

    print("\n" + "="*60)
    print("IMPORTING HISTORICAL DATA")
    print("="*60)
    print("Reading CSV files...")
    
    try:
        # 1. Load NIFTY Data
        df_nifty = pd.read_csv(nifty_path)
        df_nifty.columns = df_nifty.columns.str.strip()  # Clean headers
        
        # 2. Load VIX Data (Optional - proceed even if missing, but warn)
        df_vix = pd.DataFrame()
        if os.path.exists(vix_path):
            df_vix = pd.read_csv(vix_path)
            df_vix.columns = df_vix.columns.str.strip()
        else:
            print("Warning: VIX CSV not found. Importing only Nifty OHLC.")

        # 3. Standardize Dates for Merging
        df_nifty['date_obj'] = df_nifty['Date'].apply(lambda x: parse_date(str(x)))
        df_nifty = df_nifty.dropna(subset=['date_obj'])  # Drop invalid dates
        
        if not df_vix.empty:
            # VIX CSV often has 'Date ' with space
            vix_date_col = 'Date' if 'Date' in df_vix.columns else df_vix.columns[0] 
            df_vix['date_obj'] = df_vix[vix_date_col].apply(lambda x: parse_date(str(x)))
            df_vix = df_vix.dropna(subset=['date_obj'])
            
            # Keep only relevant VIX columns (Date + Close)
            vix_val_col = 'Close' if 'Close' in df_vix.columns else df_vix.columns[4]
            df_vix = df_vix[['date_obj', vix_val_col]].rename(columns={vix_val_col: 'vix'})
            
            # 4. Merge Dataframes
            print("Merging Nifty and VIX data...")
            final_df = pd.merge(df_nifty, df_vix, on='date_obj', how='left')
        else:
            final_df = df_nifty
            final_df['vix'] = 0  # Default if no VIX file

        # 5. Insert into DB
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        records = 0
        for _, row in final_df.iterrows():
            try:
                date_str = str(row['date_obj'])
                
                # Extract values safely
                _open = row.get('Open', 0)
                _high = row.get('High', 0)
                _low = row.get('Low', 0)
                _close = row.get('Close', 0)
                _vix = row.get('vix', 0)
                
                # Handle NaN (pandas uses NaN for missing merge values)
                if pd.isna(_vix): 
                    _vix = 0
                
                cursor.execute('''
                    INSERT OR REPLACE INTO nifty_ohlc (date, open, high, low, close, vix)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (date_str, _open, _high, _low, _close, _vix))
                records += 1
            except Exception as e:
                print(f"Skipping row {row['Date']}: {e}")
                
        conn.commit()
        conn.close()
        
        print(f"✅ Success! Imported {records} records with VIX data.")
        print("="*60)
        
    except Exception as e:
        print(f"❌ Import failed: {e}")
        import traceback
        traceback.print_exc()

def verify_schema():
    """Verify database schema is correct"""
    print("\n" + "="*60)
    print("VERIFYING DATABASE SCHEMA")
    print("="*60)
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # List all tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    
    print("\nTables found:")
    for table in tables:
        table_name = table[0]
        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        count = cursor.fetchone()[0]
        print(f"  ✓ {table_name} ({count} records)")
    
    # List all views
    cursor.execute("SELECT name FROM sqlite_master WHERE type='view'")
    views = cursor.fetchall()
    
    print("\nViews found:")
    for view in views:
        print(f"  ✓ {view[0]}")
    
    conn.close()
    print("="*60)

if __name__ == "__main__":
    print("""
╔═══════════════════════════════════════════════════════════╗
║        NIFTY HISTORY & TRADING JOURNAL DATABASE           ║
║              Schema Initialization Tool                   ║
╚═══════════════════════════════════════════════════════════╝
    """)
    
    # Initialize schema
    init_db()
    
    # Import historical data
    import_csv()
    
    # Verify everything worked
    verify_schema()
    
    print("""
╔═══════════════════════════════════════════════════════════╗
║                    SETUP COMPLETE!                        ║
╠═══════════════════════════════════════════════════════════╣
║  Your database is ready for:                              ║
║  ✓ Historical OHLC data                                   ║
║  ✓ Trading journal entries                                ║
║  ✓ Performance analytics                                  ║
║  ✓ Behavioral pattern tracking                            ║
║  ✓ ML/AI training data collection                         ║
╠═══════════════════════════════════════════════════════════╣
║  Next steps:                                              ║
║  1. Copy journal_manager.py to backend/                   ║
║  2. Update nifty_kite_backend.py with journal endpoints   ║
║  3. Add journal page to your dashboard                    ║
║  4. Start trading and watch patterns emerge!              ║
╚═══════════════════════════════════════════════════════════╝
    """)