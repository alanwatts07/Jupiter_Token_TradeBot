# Hyperliquid Candlestick Dashboard (app_anon.py)
# MODIFIED: Now uses SQLite for persistent data storage instead of a JSON file.

import time
import dash
from dash import dcc, html
from dash.dependencies import Input, Output, State
import plotly.graph_objects as go
import pandas as pd
import json
import os
from datetime import datetime
import numpy as np
import sqlite3

# --- Configuration ---
DATA_FILE = "token_price_data_v3.json"
PRICE_SAVANT_DB = "price_savant.db"  # CHANGED: Using SQLite database now
COIN_TO_TRACK = "ANON"
APP_REFRESH_SECONDS = 5
ATR_PERIOD = 14
ATR_MULTIPLIER = 2

# Global variable to track last processed record
last_processed_count = 0

# --- Database Initialization ---
def init_database():
    """Creates the SQLite database and the price_data table if they don't exist."""
    print(f"Initializing database at {PRICE_SAVANT_DB}...")
    conn = sqlite3.connect(PRICE_SAVANT_DB)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS price_data (
            timestamp TEXT PRIMARY KEY,
            price REAL,
            ohlc_open REAL, ohlc_high REAL, ohlc_low REAL, ohlc_close REAL,
            wma_fib_0 REAL, wma_fib_50 REAL, fib_entry REAL, atr REAL,
            atr_multiplier REAL, highest_high_42 REAL, lowest_low_42 REAL,
            trigger_armed BOOLEAN, buy_signal BOOLEAN, reset_threshold REAL,
            price_above_reset BOOLEAN, price_below_entry BOOLEAN,
            price_above_fib_0 BOOLEAN, in_buy_zone BOOLEAN
        )
    ''')
    conn.commit()
    conn.close()
    print("Database initialized successfully.")

def get_last_processed_count_from_db():
    """Gets the number of records already processed from the database."""
    try:
        conn = sqlite3.connect(PRICE_SAVANT_DB)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM price_data")
        count = cursor.fetchone()[0]
        conn.close()
        return count
    except Exception as e:
        print(f"Could not get record count from DB, starting from 0. Error: {e}")
        return 0

# --- Helper Functions ---
def format_small_price(price):
    if price == 0: return "$0.00"
    elif price < 0.000001: return f"${price:.8f}"
    elif price < 0.001: return f"${price:.6f}"
    elif price < 1: return f"${price:.4f}"
    else: return f"${price:,.2f}"

def calculate_drop_needed_percentage(current_price, target_price):
    if target_price == 0 or pd.isna(target_price) or current_price <= target_price:
        return "In Zone"
    drop_needed = ((current_price - target_price) / current_price) * 100
    return f"{drop_needed:.1f}%"

# --- Fibonacci Calculator Class ---
class FibonacciCalculator:
    def __init__(self, config=None):
        self.config = config or {
            'trading': {
                'atr_multiplier': ATR_MULTIPLIER,
                'fib_entry_floor_pct': 0.85,
                'reset_pct_above_fib_0': 0.05
            }
        }
    def calculate_fib_levels(self, df):
        if len(df) < 66:
            df['wma_fib_0'], df['wma_fib_50'] = np.nan, np.nan
            return df
        df_copy = df.copy()
        df_copy['highest_high'] = df_copy['high'].rolling(window=42).max()
        df_copy['lowest_low'] = df_copy['low'].rolling(window=42).min()
        df_copy['wma_fib_0'] = df_copy['lowest_low'].rolling(window=24).mean()
        df_copy['wma_fib_50'] = (df_copy['highest_high'] - ((df_copy['highest_high'] - df_copy['lowest_low']) * 0.5)).rolling(window=24).mean()
        return df_copy

def create_enhanced_record(price_record, fib_data_map, trade_state, previous_trigger_state=None):
    enhanced_record = {key: None for key in [ # Initialize with None
        'timestamp', 'price', 'ohlc_open', 'ohlc_high', 'ohlc_low', 'ohlc_close',
        'wma_fib_0', 'wma_fib_50', 'fib_entry', 'atr', 'atr_multiplier',
        'highest_high_42', 'lowest_low_42', 'trigger_armed', 'buy_signal',
        'reset_threshold', 'price_above_reset', 'price_below_entry',
        'price_above_fib_0', 'in_buy_zone'
    ]}
    enhanced_record.update(price_record)
    
    try:
        record_time = pd.to_datetime(price_record['timestamp'])
        window_time = record_time.floor('5min')
        window_key = window_time.strftime('%Y-%m-%d %H:%M:%S')
        
        if window_key in fib_data_map:
            fib_data = fib_data_map[window_key]
            enhanced_record.update(fib_data)
            
            current_price = price_record['price']
            wma_fib_0 = fib_data['wma_fib_0']
            fib_entry = fib_data['fib_entry']
            
            if wma_fib_0 is not None and fib_entry is not None:
                reset_threshold = wma_fib_0 * 1.05
                trigger_armed = previous_trigger_state if previous_trigger_state is not None else False
                buy_signal = False
                
                if current_price > reset_threshold: trigger_armed = False
                elif current_price < fib_entry: trigger_armed = True
                if trigger_armed and current_price > wma_fib_0: buy_signal = True
                
                enhanced_record.update({
                    'trigger_armed': trigger_armed, 'buy_signal': buy_signal,
                    'reset_threshold': reset_threshold,
                    'price_above_reset': current_price > reset_threshold,
                    'price_below_entry': current_price < fib_entry,
                    'price_above_fib_0': current_price > wma_fib_0,
                    'in_buy_zone': (fib_entry <= current_price <= wma_fib_0)
                })
                return enhanced_record, trigger_armed
    except Exception as e:
        print(f"❌ Error processing record: {e}")
    
    return enhanced_record, previous_trigger_state

def update_price_savant_db(new_records):
    """MODIFIED: Inserts new records into the SQLite database."""
    if not new_records:
        return
    
    conn = sqlite3.connect(PRICE_SAVANT_DB)
    cursor = conn.cursor()
    
    # Prepare data for insertion
    columns = [
        'timestamp', 'price', 'ohlc_open', 'ohlc_high', 'ohlc_low', 'ohlc_close',
        'wma_fib_0', 'wma_fib_50', 'fib_entry', 'atr', 'atr_multiplier',
        'highest_high_42', 'lowest_low_42', 'trigger_armed', 'buy_signal',
        'reset_threshold', 'price_above_reset', 'price_below_entry',
        'price_above_fib_0', 'in_buy_zone'
    ]
    
    data_to_insert = []
    for record in new_records:
        # Ensure all columns are present, defaulting to None if missing
        data_to_insert.append(tuple(record.get(col) for col in columns))

    try:
        # Use INSERT OR IGNORE to prevent errors on duplicate timestamps
        cursor.executemany(f'''
            INSERT OR IGNORE INTO price_data ({', '.join(columns)})
            VALUES ({', '.join(['?'] * len(columns))})
        ''', data_to_insert)
        
        conn.commit()
        print(f"✅ Successfully inserted {cursor.rowcount} new records into {PRICE_SAVANT_DB}.")
    except Exception as e:
        print(f"❌ Database insert error: {e}")
    finally:
        conn.close()


# --- Dash App Initialization ---
app = dash.Dash(__name__)
app.title = f"{COIN_TO_TRACK} Price Dashboard"

# Initialize database and last processed count
init_database()
last_processed_count = get_last_processed_count_from_db()
print(f"🚀 Starting with {last_processed_count} already processed records in the database.")
print(f"🎛️ ATR Multiplier: {ATR_MULTIPLIER}")

# --- App Layout ---
app.layout = html.Div(style={'backgroundColor': '#111111', 'color': '#FFFFFF', 'fontFamily': 'sans-serif', 'height': '100vh', 'display': 'flex', 'flexDirection': 'column'}, children=[
    dcc.Store(id='trade-state-storage', data={'trigger_on': False, 'in_position': False, 'entry_price': None, 'position_size': 0.0}),
    html.H1(f"{COIN_TO_TRACK} - Jupiter Signal Generator", style={'textAlign': 'center', 'padding': '20px'}),
    dcc.Graph(id='live-candlestick-chart', style={'flex-grow': '1'}),
    html.Div(id='indicator-display', style={'textAlign': 'center', 'padding': '20px', 'fontSize': '18px'}),
    dcc.Interval(id='interval-component', interval=APP_REFRESH_SECONDS * 1000, n_intervals=0)
])

# --- Main Callback ---
@app.callback(
    [Output('live-candlestick-chart', 'figure'), Output('indicator-display', 'children'), Output('trade-state-storage', 'data')],
    Input('interval-component', 'n_intervals'),
    [State('trade-state-storage', 'data'), State('live-candlestick-chart', 'relayoutData')]
)
def update_chart_and_indicators(n, trade_state, relayout_data):
    global last_processed_count
    try:
        with open(DATA_FILE, 'r') as f: data = json.load(f)
        if not data: raise ValueError("No data in file")

        df = pd.DataFrame(data)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)
        ohlc_df = df['price'].resample('5min').ohlc()
        ohlc_df.dropna(inplace=True)

        fib_calculator = FibonacciCalculator()
        df_with_fibs = fib_calculator.calculate_fib_levels(ohlc_df)

        high_low = df_with_fibs['high'] - df_with_fibs['low']
        high_prev_close = np.abs(df_with_fibs['high'] - df_with_fibs['close'].shift())
        low_prev_close = np.abs(df_with_fibs['low'] - df_with_fibs['close'].shift())
        tr = pd.concat([high_low, high_prev_close, low_prev_close], axis=1).max(axis=1)
        df_with_fibs['atr'] = tr.rolling(window=ATR_PERIOD).mean()

        atr_multiplier = fib_calculator.config['trading']['atr_multiplier']
        df_with_fibs['fib_entry'] = df_with_fibs['wma_fib_0'] - (df_with_fibs['atr'] * atr_multiplier)
        floor_multiplier = fib_calculator.config['trading']['fib_entry_floor_pct']
        df_with_fibs['fib_entry'] = np.maximum(df_with_fibs['fib_entry'], df_with_fibs['wma_fib_0'] * floor_multiplier)
        
        # --- Incremental update to database ---
        current_count = len(data)
        if current_count > last_processed_count:
            fib_data_map = {ts.strftime('%Y-%m-%d %H:%M:%S'): row.to_dict() for ts, row in df_with_fibs.iterrows()}
            new_records_to_process = data[last_processed_count:]
            
            # Get the last trigger state from the DB for continuity
            conn = sqlite3.connect(PRICE_SAVANT_DB)
            cursor = conn.cursor()
            cursor.execute("SELECT trigger_armed FROM price_data ORDER BY timestamp DESC LIMIT 1")
            last_db_record = cursor.fetchone()
            conn.close()
            last_trigger_state = last_db_record[0] if last_db_record else False

            new_enhanced_records = []
            current_trigger_state = last_trigger_state
            for record in new_records_to_process:
                enhanced_record, current_trigger_state = create_enhanced_record(record, fib_data_map, trade_state, current_trigger_state)
                new_enhanced_records.append(enhanced_record)
            
            update_price_savant_db(new_enhanced_records)
            last_processed_count = current_count

        # (The rest of the Dash UI update logic remains the same)
        # ... [omitted for brevity, no changes needed here] ...
        latest_close = df_with_fibs['close'].iloc[-1]
        fig = go.Figure(data=[go.Candlestick(x=df_with_fibs.index, open=df_with_fibs['open'], high=df_with_fibs['high'], low=df_with_fibs['low'], close=df_with_fibs['close'], name='Candles')])
        fig.add_trace(go.Scatter(x=df_with_fibs.index, y=df_with_fibs['wma_fib_0'], mode='lines', name='WMA Fib 0', line=dict(color='lime', width=2)))
        fig.add_trace(go.Scatter(x=df_with_fibs.index, y=df_with_fibs['fib_entry'], mode='lines', name=f'Fib Entry (ATR×{atr_multiplier})', line=dict(color='cyan', width=2, dash='dash')))
        fig.update_layout(title_text=f'Last Updated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}', yaxis_title='Price (SOL)', xaxis_rangeslider_visible=False, template='plotly_dark')
        indicator_text = f"Latest Price: {format_small_price(latest_close)}"
        
        return fig, indicator_text, trade_state

    except (FileNotFoundError, json.JSONDecodeError, ValueError, IndexError) as e:
        fig = go.Figure().update_layout(title_text=f"Waiting for data... ({e})", template='plotly_dark')
        return fig, f"Error: {e}", trade_state

if __name__ == '__main__':
    app.run(debug=True, port=8051)

