import sqlite3
import pandas as pd
import os
from datetime import datetime

# Ensure we write to the same folder as this script (backend/)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "nifty_history.db")

# CSV Files (Update filenames if they change)
NIFTY_CSV = "NIFTY 50-01-01-2025-to-23-11-2025.csv" # Or whatever your main NIFTY file is named
VIX_CSV = "hist_india_vix_-01-01-2025-to-25-11-2025.csv"

def init_db():
    print(f"Initializing DB at: {DB_FILE}")
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Create table with VIX column
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
            
    conn.commit()
    conn.close()

def parse_date(date_str):
    """
    Tries to parse date from common formats found in NSE CSVs.
    Returns datetime.date object or None.
    """
    formats = [
        "%d-%b-%Y", # 01-JAN-2025
        "%d-%m-%Y", # 01-01-2025
        "%Y-%m-%d"  # 2025-01-01
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue
    return None

def import_csv():
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

    print("Reading CSV files...")
    try:
        # 1. Load NIFTY Data
        df_nifty = pd.read_csv(nifty_path)
        df_nifty.columns = df_nifty.columns.str.strip() # Clean headers
        
        # 2. Load VIX Data (Optional - proceed even if missing, but warn)
        df_vix = pd.DataFrame()
        if os.path.exists(vix_path):
            df_vix = pd.read_csv(vix_path)
            df_vix.columns = df_vix.columns.str.strip()
        else:
            print("Warning: VIX CSV not found. Importing only Nifty OHLC.")

        # 3. Standardize Dates for Merging
        df_nifty['date_obj'] = df_nifty['Date'].apply(lambda x: parse_date(str(x)))
        df_nifty = df_nifty.dropna(subset=['date_obj']) # Drop invalid dates
        
        if not df_vix.empty:
            # VIX CSV often has 'Date ' with space
            vix_date_col = 'Date' if 'Date' in df_vix.columns else df_vix.columns[0] 
            df_vix['date_obj'] = df_vix[vix_date_col].apply(lambda x: parse_date(str(x)))
            df_vix = df_vix.dropna(subset=['date_obj'])
            
            # Keep only relevant VIX columns (Date + Close)
            # Usually 'Close' is the value we want. Rename to 'vix_close'
            vix_val_col = 'Close' if 'Close' in df_vix.columns else df_vix.columns[4] # Fallback index
            df_vix = df_vix[['date_obj', vix_val_col]].rename(columns={vix_val_col: 'vix'})
            
            # 4. Merge Dataframes
            print("Merging Nifty and VIX data...")
            final_df = pd.merge(df_nifty, df_vix, on='date_obj', how='left')
        else:
            final_df = df_nifty
            final_df['vix'] = 0 # Default if no VIX file

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
                if pd.isna(_vix): _vix = 0
                
                cursor.execute('''
                    INSERT OR REPLACE INTO nifty_ohlc (date, open, high, low, close, vix)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (date_str, _open, _high, _low, _close, _vix))
                records += 1
            except Exception as e:
                print(f"Skipping row {row['Date']}: {e}")
                
        conn.commit()
        conn.close()
        print(f"Success! Imported {records} records with VIX data.")
        
    except Exception as e:
        print(f"Import failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    init_db()
    import_csv()