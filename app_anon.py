# Hyperliquid Candlestick Dashboard (app.py)
#
# This Dash application reads price data, calculates signals, and determines
# its initial position state by reading a trade log file on startup.
# It now displays the PnL %, plots individual trades, shows the average entry price,
# and passes the ATR value to the signal file.
# Additionally creates price_savant.json with incremental updates to avoid
# reprocessing enormous datasets.
# Now also saves the most recent savant data to trigger.json
# NOTE: This version has had the ATR-based stop-loss functionality removed.
#
# Prerequisites:
# pip install dash pandas plotly numpy
#
# To Run:
# 1. Ensure your trade logs are up-to-date.
# 2. Make sure 'collector.py' is running in a separate terminal.
# 3. Save this file as 'app.py'.
# 4. Run from your terminal: python app.py

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
import requests

# Wallet and token configuration
TRACKED_WALLET = "Gtt5hRMyN8EKPY45Un7k7jbL4nzsokJSbhxU9TwoBfiB"
TRACKED_TOKEN = "FhvBDEr46meW6NHWHNeShDzvbXWabNzyT6uGinEgBAGS"
SOL_ADDRESS = "So11111111111111111111111111111111111111112"

# --- Configuration ---
DATA_FILE = "token_price_data_v3.json"
SIGNAL_FILE = "trade_signals.json"
PRICE_SAVANT_FILE = "price_savant_anon.json"  # Enhanced price data file
TRIGGER_FILE = "trigger2.json"  # Most recent savant data
LOG_FILE = "trade_log.json"
COIN_TO_TRACK ="ANON"
APP_REFRESH_SECONDS = 5
ATR_PERIOD = 14

# Wallet cache globals
wallet_cache = {}
last_wallet_fetch = 0
WALLET_CACHE_DURATION = 300  # Cache for 5 minutes (300 seconds)

def get_wallet_analysis(current_token_price_sol):
    """
    Analyzes trades to calculate P&L for both open and closed positions in SOL.
    """
    try:
        print("🔍 Calculating position in SOL...")

        # Your actual trades in SOL
        hardcoded_trades = [
            {
                'trade_type': 'SELL',
                'token_amount': 482784.0,
                'sol_spent': 1.62, # For a sell, this is SOL received
                'timestamp': '2025-08-16T20:39:13'
            },
            {
                'trade_type': 'BUY',
                'token_amount': 91660.0,
                'sol_spent': 0.1992,
                'timestamp': '2025-08-16T10:38:08'
            },
            {
                'trade_type': 'BUY',
                'token_amount': 80468.0,
                'sol_spent': 0.1992,
                'timestamp': '2025-08-16T07:37:08'
            },
            {
                'trade_type': 'BUY',
                'token_amount': 101483.0,
                'sol_spent': 0.1992,
                'timestamp': '2025-08-15T22:32:08'
            },
            {
                'trade_type': 'BUY',
                'token_amount': 81290.0,
                'sol_spent': 0.1992,
                'timestamp': '2025-08-15T22:08:08'
            },
            {
                'trade_type': 'BUY',
                'token_amount': 127831.0,
                'sol_spent': 0.2988,
                'timestamp': '2025-08-15T20:51:08'
            }
        ]
        
        # --- CORRECTED LOGIC ---
        # Separate totals for buys and sells
        total_tokens_bought = 0.0
        total_sol_spent_on_buys = 0.0
        total_tokens_sold = 0.0
        total_sol_received_from_sells = 0.0

        for trade in hardcoded_trades:
            if trade['trade_type'] == 'BUY':
                total_tokens_bought += trade['token_amount']
                total_sol_spent_on_buys += trade['sol_spent']
            elif trade['trade_type'] == 'SELL':
                total_tokens_sold += trade['token_amount']
                total_sol_received_from_sells += trade['sol_spent']

        # Check if the position is fully closed
        # Allow for a small tolerance due to floating point inaccuracies
        if abs(total_tokens_bought - total_tokens_sold) < 1.0: 
            print("✅ Position is fully closed.")
            
            # Realized P&L
            pnl_sol = total_sol_received_from_sells - total_sol_spent_on_buys
            pnl_percentage = (pnl_sol / total_sol_spent_on_buys) * 100 if total_sol_spent_on_buys > 0 else 0
            
            avg_entry_price_sol = total_sol_spent_on_buys / total_tokens_bought if total_tokens_bought > 0 else 0
            avg_sell_price_sol = total_sol_received_from_sells / total_tokens_sold if total_tokens_sold > 0 else 0

            result = {
                'has_position': False, # Position is closed
                'message': f'Position closed for a realized gain of {pnl_sol:+.4f} SOL.',
                'current_tokens': 0,
                'avg_entry_price_sol': avg_entry_price_sol,
                'avg_sell_price_sol': avg_sell_price_sol,
                'initial_investment_sol': total_sol_spent_on_buys,
                'total_sol_received': total_sol_received_from_sells,
                'pnl_sol': pnl_sol,
                'pnl_percentage': pnl_percentage,
                'total_trades': len(hardcoded_trades)
            }
            
            print(f"💰 Realized P&L: {pnl_percentage:+.2f}% ({pnl_sol:+.4f} SOL)")
            print(f"   Total Invested: {total_sol_spent_on_buys:.4f} SOL for {total_tokens_bought:,.0f} tokens")
            print(f"   Total Received: {total_sol_received_from_sells:.4f} SOL for {total_tokens_sold:,.0f} tokens")
            return result

        else: # Position is still open
            print("⏳ Position is still open.")
            current_tokens = total_tokens_bought - total_tokens_sold
            avg_entry_price_sol = total_sol_spent_on_buys / total_tokens_bought if total_tokens_bought > 0 else 0
            
            # Current value of held tokens
            current_value_sol = current_tokens * current_token_price_sol
            
            # Unrealized P&L = (Value of what you have + Value of what you sold) - What you spent
            pnl_sol = (current_value_sol + total_sol_received_from_sells) - total_sol_spent_on_buys
            pnl_percentage = (pnl_sol / total_sol_spent_on_buys) * 100 if total_sol_spent_on_buys > 0 else 0

            result = {
                'has_position': True,
                'current_tokens': current_tokens,
                'avg_entry_price_sol': avg_entry_price_sol,
                'current_token_price_sol': current_token_price_sol,
                'initial_investment_sol': total_sol_spent_on_buys,
                'current_value_sol': current_value_sol,
                'pnl_sol': pnl_sol,
                'pnl_percentage': pnl_percentage,
                'total_trades': len(hardcoded_trades),
                'message': 'Open position calculation'
            }
            
            print(f"   Current tokens: {current_tokens:,.0f} ANON")
            print(f"   Total invested: {total_sol_spent_on_buys:.4f} SOL")
            print(f"   Avg entry: {avg_entry_price_sol:.10f} SOL per ANON")
            print(f"   Current price: {current_token_price_sol:.10f} SOL per ANON")
            print(f"   Current value: {current_value_sol:.4f} SOL")
            print(f"   Unrealized P&L: {pnl_percentage:+.2f}% ({pnl_sol:+.4f} SOL)")
            return result

    except Exception as e:
        print(f"❌ Error in wallet analysis: {e}")
        return { 'has_position': False, 'message': f'Error: {str(e)}' }

# Global variable to track last processed record
last_processed_count = 0

# --- Helper function to read trade logs ---
def read_trade_logs(log_file_path):
    """Safely reads and returns the contents of the trade log file."""
    try:
        if not os.path.exists(log_file_path):
            return []
        with open(log_file_path, 'r') as f:
            logs = json.load(f)
        return logs if isinstance(logs, list) else []
    except (json.JSONDecodeError, Exception):
        return []

# --- Function to Read Logs and Determine Initial State ---
def get_initial_trade_state(log_file_path):
    """Reads the trade log to determine the current position state on startup."""
    default_state = {'in_position': False, 'entry_price': None, 'position_size': 0.0}
    logs = read_trade_logs(log_file_path)
    if not logs:
        print(f"[*] Log file '{log_file_path}' not found or empty. Starting with no position.")
        return default_state

    try:
        last_sell_index = -1
        for i in range(len(logs) - 1, -1, -1):
            if logs[i].get('trade_type') == 'sell':
                last_sell_index = i
                break
        
        trades_since_last_sell = logs[last_sell_index + 1:]
        buys_in_cycle = [t for t in trades_since_last_sell if t.get('trade_type') == 'buy' or 'trade_type' not in t]

        if not buys_in_cycle:
            return default_state
        else:
            total_size = sum(float(b.get('calculated_asset_size', 0)) for b in buys_in_cycle)
            first_buy_price = float(buys_in_cycle[0]['exchange_response']['response']['data']['statuses'][0]['filled']['avgPx'])
            print(f"✅ STATE RECOVERY: Found active position. Size: {total_size}, Entry: {first_buy_price}")
            return {'in_position': True, 'entry_price': first_buy_price, 'position_size': total_size}
    except Exception as e:
        print(f"❌ Error processing log file for initial state: {e}")
        return default_state

def format_small_price(price):
    """Format very small prices with appropriate precision"""
    if price == 0:
        return "$0.00"
    elif price < 0.000001:
        return f"${price:.8f}"
    elif price < 0.001:
        return f"${price:.6f}"
    elif price < 1:
        return f"${price:.4f}"
    else:
        return f"${price:,.2f}"

def calculate_drop_needed_percentage(current_price, target_price):
    """Calculate how much price needs to drop to reach target"""
    if target_price == 0 or pd.isna(target_price) or current_price <= target_price:
        return "In Zone"
    drop_needed = ((current_price - target_price) / current_price) * 100
    return f"{drop_needed:.1f}%"

def calculate_percentage_diff(current_price, target_price):
    """Calculate percentage difference between current price and target"""
    if target_price == 0 or pd.isna(target_price):
        return "N/A"
    diff_pct = ((current_price - target_price) / target_price) * 100
    return f"{diff_pct:+.2f}%"

# --- Fibonacci Calculator Class ---
class FibonacciCalculator:
    def __init__(self, config=None):
        self.config = config or {'trading': {'fib_entry_offset_pct': 0.15, 'reset_pct_above_fib_0': 0.15}}

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

# --- Function to get last processed count ---
def get_last_processed_count():
    """Get the number of records already processed in price_savant.json"""
    try:
        if not os.path.exists(PRICE_SAVANT_FILE):
            return 0
        with open(PRICE_SAVANT_FILE, 'r') as f:
            existing_data = json.load(f)
        return len(existing_data) if isinstance(existing_data, list) else 0
    except:
        return 0

# --- Function to create enhanced record ---
# --- Function to create enhanced record ---
def create_enhanced_record(price_record, fib_data_map, trade_state, previous_trigger_state=None, wallet_data=None):
    """Create a single enhanced price record with proper trigger logic and wallet data"""
    enhanced_record = price_record.copy()
    
    try:
        # Parse the timestamp to find matching 5-minute window
        record_time = pd.to_datetime(price_record['timestamp'])
        window_time = record_time.floor('5min')
        window_key = window_time.strftime('%Y-%m-%d %H:%M:%S')
        
        # Add Fibonacci and technical data if available
        if window_key in fib_data_map:
            fib_data = fib_data_map[window_key]
            enhanced_record.update({
                'ohlc_open': fib_data['open'],
                'ohlc_high': fib_data['high'],
                'ohlc_low': fib_data['low'],
                'ohlc_close': fib_data['close'],
                'wma_fib_0': fib_data['wma_fib_0'],
                'wma_fib_50': fib_data['wma_fib_50'],
                'fib_entry': fib_data['fib_entry'],
                'atr': fib_data['atr'],
                'highest_high_42': fib_data['highest_high'],
                'lowest_low_42': fib_data['lowest_low']
            })
            
            # Calculate trigger states for this specific record
            current_price = price_record['price']
            wma_fib_0 = fib_data['wma_fib_0']
            fib_entry = fib_data['fib_entry']
            
            if wma_fib_0 is not None and fib_entry is not None:
                reset_threshold = wma_fib_0 * 1.05
                
                # Use previous trigger state or default to False
                trigger_armed = previous_trigger_state if previous_trigger_state is not None else False
                buy_signal = False
                
                # Update trigger state based on price action
                if current_price > reset_threshold:
                    trigger_armed = False
                elif current_price < fib_entry:
                    trigger_armed = True
                
                # Check for buy signal - trigger must be armed AND price above fib_0
                if trigger_armed and current_price > wma_fib_0:
                    buy_signal = True
                
                enhanced_record.update({
                    'trigger_armed': trigger_armed,
                    'buy_signal': buy_signal,
                    'reset_threshold': reset_threshold,
                    'price_above_reset': current_price > reset_threshold if reset_threshold else None,
                    'price_below_entry': current_price < fib_entry if fib_entry else None,
                    'price_above_fib_0': current_price > wma_fib_0 if wma_fib_0 else None,
                    'in_buy_zone': (fib_entry <= current_price <= wma_fib_0) if (fib_entry and wma_fib_0) else None
                })
                
                # NEW: Add wallet position data
                if wallet_data and wallet_data.get('has_position'):
                    # Calculate percentage to entry (how much price needs to drop)
                    if fib_entry and current_price > fib_entry:
                        drop_to_entry_pct = ((current_price - fib_entry) / current_price) * 100
                    else:
                        drop_to_entry_pct = 0  # Already at or below entry
                    
                    enhanced_record.update({
                        'wallet_position_pnl_percentage': wallet_data.get('pnl_percentage', 0),
                        'wallet_position_pnl_sol': wallet_data.get('pnl_sol', 0),
                        'wallet_entry_price_sol': wallet_data.get('avg_entry_price_sol', 0),
                        'wallet_total_tokens': wallet_data.get('current_tokens', 0),
                        'wallet_drop_to_entry_pct': drop_to_entry_pct
                    })
                else:
                    enhanced_record.update({
                        'wallet_position_pnl_percentage': None,
                        'wallet_position_pnl_sol': None,
                        'wallet_entry_price_sol': None,
                        'wallet_total_tokens': None,
                        'wallet_drop_to_entry_pct': None
                    })
                
                # Return the updated trigger state for the next record
                return enhanced_record, trigger_armed
            else:
                enhanced_record.update({
                    'trigger_armed': None, 'buy_signal': False, 'reset_threshold': None,
                    'price_above_reset': None, 'price_below_entry': None, 'price_above_fib_0': None, 'in_buy_zone': None,
                    'wallet_position_pnl_percentage': None, 'wallet_position_pnl_sol': None,
                    'wallet_entry_price_sol': None, 'wallet_total_tokens': None, 'wallet_drop_to_entry_pct': None
                })
        else:
            # No matching OHLC window found, add empty fib and wallet fields
            enhanced_record.update({
                'ohlc_open': None, 'ohlc_high': None, 'ohlc_low': None, 'ohlc_close': None,
                'wma_fib_0': None, 'wma_fib_50': None, 'fib_entry': None, 'atr': None,
                'highest_high_42': None, 'lowest_low_42': None,
                'trigger_armed': None, 'buy_signal': False, 'reset_threshold': None,
                'price_above_reset': None, 'price_below_entry': None, 'price_above_fib_0': None, 'in_buy_zone': None,
                'wallet_position_pnl_percentage': None, 'wallet_position_pnl_sol': None,
                'wallet_entry_price_sol': None, 'wallet_total_tokens': None, 'wallet_drop_to_entry_pct': None
            })
        
        # Add current trading state
        enhanced_record.update({
            'current_in_position': trade_state.get('in_position', False),
            'current_trigger_on': trade_state.get('trigger_on', False),
            'entry_price': trade_state.get('entry_price'),
            'position_size': trade_state.get('position_size', 0.0)
        })
        
    except Exception as e:
        print(f"❌ Error processing record: {e}")
        # Add empty fields if there's an error
        enhanced_record.update({
            'ohlc_open': None, 'ohlc_high': None, 'ohlc_low': None, 'ohlc_close': None,
            'wma_fib_0': None, 'wma_fib_50': None, 'fib_entry': None, 'atr': None,
            'highest_high_42': None, 'lowest_low_42': None,
            'trigger_armed': None, 'buy_signal': False, 'reset_threshold': None,
            'price_above_reset': None, 'price_below_entry': None, 'price_above_fib_0': None, 'in_buy_zone': None,
            'current_in_position': trade_state.get('in_position', False),
            'current_trigger_on': trade_state.get('trigger_on', False),
            'entry_price': trade_state.get('entry_price'), 'position_size': trade_state.get('position_size', 0.0),
            'wallet_position_pnl_percentage': None, 'wallet_position_pnl_sol': None,
            'wallet_entry_price_sol': None, 'wallet_total_tokens': None, 'wallet_drop_to_entry_pct': None
        })
    
    return enhanced_record, previous_trigger_state

# --- Function to save most recent trigger data ---
def save_latest_trigger_data(enhanced_records):
    """Save the most recent enhanced record to trigger.json"""
    try:
        if not enhanced_records:
            return
        
        # Get the most recent record
        latest_record = enhanced_records[-1]
        
        # Save to trigger.json
        with open(TRIGGER_FILE, 'w') as f:
            json.dump(latest_record, f, indent=2)
        
        print(f"📍 Updated {TRIGGER_FILE} with latest trigger data from {latest_record.get('timestamp')}")
        
    except Exception as e:
        print(f"❌ Error saving trigger data: {e}")

# --- Incremental price savant update function ---
# --- Incremental price savant update function ---
def update_price_savant_incremental(original_data, df_with_fibs, trade_state, wallet_analysis=None):
    """Update price_savant.json incrementally - only process new records"""
    global last_processed_count
    
    try:
        current_count = len(original_data)
        
        # Check if we need to process anything
        if current_count <= last_processed_count:
            print(f"📊 No new records to process. Current: {current_count}, Last processed: {last_processed_count}")
            return
        
        # Create fib data mapping
        fib_data_map = {}
        for timestamp, row in df_with_fibs.iterrows():
            window_start = timestamp.strftime('%Y-%m-%d %H:%M:%S')
            fib_data_map[window_start] = {
                'open': float(row['open']) if not pd.isna(row['open']) else None,
                'high': float(row['high']) if not pd.isna(row['high']) else None,
                'low': float(row['low']) if not pd.isna(row['low']) else None,
                'close': float(row['close']) if not pd.isna(row['close']) else None,
                'wma_fib_0': float(row['wma_fib_0']) if not pd.isna(row['wma_fib_0']) else None,
                'wma_fib_50': float(row['wma_fib_50']) if not pd.isna(row['wma_fib_50']) else None,
                'fib_entry': float(row['fib_entry']) if not pd.isna(row['fib_entry']) else None,
                'atr': float(row['atr']) if not pd.isna(row['atr']) else None,
                'highest_high': float(row['highest_high']) if 'highest_high' in row and not pd.isna(row['highest_high']) else None,
                'lowest_low': float(row['lowest_low']) if 'lowest_low' in row and not pd.isna(row['lowest_low']) else None
            }
        
        # Load existing data or create empty list
        if os.path.exists(PRICE_SAVANT_FILE) and last_processed_count > 0:
            with open(PRICE_SAVANT_FILE, 'r') as f:
                existing_data = json.load(f)
            # Get the last trigger state to maintain continuity
            last_trigger_state = None
            if existing_data:
                last_record = existing_data[-1]
                last_trigger_state = last_record.get('trigger_armed')
        else:
            existing_data = []
            last_processed_count = 0
            last_trigger_state = False  # Default starting state
            print("🆕 Creating price_savant.json from scratch...")
        
        # Process only new records
        new_records = original_data[last_processed_count:]
        print(f"🔄 Processing {len(new_records)} new records (from {last_processed_count} to {current_count})")
        
        # Process new records sequentially to maintain trigger state
        current_trigger_state = last_trigger_state
        new_enhanced_records = []
        
        for i, record in enumerate(new_records):
            enhanced_record, current_trigger_state = create_enhanced_record(
                record, fib_data_map, trade_state, current_trigger_state, wallet_analysis
            )
            existing_data.append(enhanced_record)
            new_enhanced_records.append(enhanced_record)
            
            # Debug output for buy signals
            if enhanced_record.get('buy_signal'):
                print(f"🚀 BUY SIGNAL DETECTED at {record.get('timestamp')} - Price: {record.get('price')}")
            
            if (i + 1) % 1000 == 0:
                print(f"📝 Processed {i + 1}/{len(new_records)} records")
        
        # Save updated data
        with open(PRICE_SAVANT_FILE, 'w') as f:
            json.dump(existing_data, f, indent=2)
        
        # NEW: Save the most recent record to trigger.json
        save_latest_trigger_data(existing_data)
        
        # Update our tracking counter
        last_processed_count = current_count
        
        # Count total buy signals for debugging
        total_buy_signals = sum(1 for record in existing_data if record.get('buy_signal', False))
        print(f"✅ Updated {PRICE_SAVANT_FILE} - Total records: {len(existing_data)}, New records added: {len(new_records)}, Total buy signals: {total_buy_signals}")
        
    except Exception as e:
        print(f"❌ Error in incremental update: {e}")

# --- Dash App Initialization ---
app = dash.Dash(__name__)
app.title = f"{COIN_TO_TRACK} Price Dashboard"
initial_state = get_initial_trade_state(LOG_FILE)

# Initialize last processed count
last_processed_count = get_last_processed_count()
print(f"🚀 Starting with {last_processed_count} already processed records")

# --- App Layout ---
app.layout = html.Div(style={'backgroundColor': '#111111', 'color': '#FFFFFF', 'fontFamily': 'sans-serif', 'height': '100vh', 'display': 'flex', 'flexDirection': 'column'}, children=[
    dcc.Store(id='trade-state-storage', data={'trigger_on': False, 'in_position': initial_state['in_position'], 'entry_price': initial_state['entry_price'], 'position_size': initial_state['position_size']}),
    html.H1(f"{COIN_TO_TRACK} - 5-Minute Bottomfeeder Bot", style={'textAlign': 'center', 'padding': '20px'}),
    dcc.Graph(id='live-candlestick-chart', style={'flex-grow': '1'}),
    html.Div(id='indicator-display', style={'textAlign': 'center', 'padding': '20px', 'fontSize': '18px'}),
    dcc.Interval(id='interval-component', interval=APP_REFRESH_SECONDS * 1000, n_intervals=0)
])

def simple_wallet_test():
    try:
        print("🧪 Testing basic wallet functionality...")
        result = get_wallet_analysis(0.000002)  # Test with dummy price
        print(f"🧪 Test result: {result}")
        return result is not None
    except Exception as e:
        print(f"🧪 Test failed with error: {e}")
        return False

# Call the test when app starts
print("🚀 Running wallet test on startup...")
simple_wallet_test()

# --- Main Callback ---
@app.callback(
    [Output('live-candlestick-chart', 'figure'), Output('indicator-display', 'children'), Output('trade-state-storage', 'data')],
    Input('interval-component', 'n_intervals'),
    [State('trade-state-storage', 'data'), State('live-candlestick-chart', 'relayoutData')]
)
def update_chart_and_indicators(n, trade_state, relayout_data):
    try:
        with open(DATA_FILE, 'r') as f: 
            data = json.load(f)
        if not data: 
            raise ValueError("No data in file")

        df = pd.DataFrame(data)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)
        ohlc_df = df['price'].resample('5min').ohlc()
        ohlc_df.dropna(inplace=True)

        fib_calculator = FibonacciCalculator()
        df_with_fibs = fib_calculator.calculate_fib_levels(ohlc_df)

        # ATR calculation FIRST (before fib_entry)
        high_low = df_with_fibs['high'] - df_with_fibs['low']
        high_prev_close = np.abs(df_with_fibs['high'] - df_with_fibs['close'].shift())
        low_prev_close = np.abs(df_with_fibs['low'] - df_with_fibs['close'].shift())
        tr = pd.concat([high_low, high_prev_close, low_prev_close], axis=1).max(axis=1)
        df_with_fibs['atr'] = tr.rolling(window=ATR_PERIOD).mean()

        # ATR-based dynamic fib entry calculation (AFTER ATR is calculated)
        atr_multiplier = 1.5  # Adjust this value as needed (1.0 to 3.0 typically)
        df_with_fibs['fib_entry'] = df_with_fibs['wma_fib_0'] - (df_with_fibs['atr'] * atr_multiplier)

        # Make sure fib_entry doesn't go negative or too far below
        df_with_fibs['fib_entry'] = np.maximum(
            df_with_fibs['fib_entry'], 
            df_with_fibs['wma_fib_0'] * 0.85  # Never go below 15% of fib_0
        )
        
        latest_close, latest_wma_0, latest_fib_entry, latest_atr, latest_wma_50 = [df_with_fibs[col].iloc[-1] for col in ['close', 'wma_fib_0', 'fib_entry', 'atr', 'wma_fib_50']]
        
        print(f"🔍 About to call get_wallet_analysis with price: {latest_close}")
        try:
            wallet_analysis = get_wallet_analysis(latest_close)
            print(f"🔍 Wallet analysis completed: {wallet_analysis}")
        except Exception as e:
            print(f"❌ Wallet analysis failed: {e}")
            wallet_analysis = None

        trigger_on, in_position, entry_price, position_size = [trade_state.get(k) for k in ['trigger_on', 'in_position', 'entry_price', 'position_size']]
        buy_signal = False
        reset_threshold = latest_wma_0 * (1 + fib_calculator.config['trading']['reset_pct_above_fib_0'])

        # --- Trading Logic ---
        if not in_position:
            if latest_close > reset_threshold:
                trigger_on = False
                print(f"🔴 Trigger DISARMED - Price {latest_close:.2f} above reset threshold {reset_threshold:.2f}")
            elif latest_close < latest_fib_entry:
                trigger_on = True
                print(f"🟡 Trigger ARMED - Price {latest_close:.2f} below entry level {latest_fib_entry:.2f}")
            
            if trigger_on and latest_close > latest_wma_0:
                buy_signal = True
                in_position = True
                entry_price = latest_close
                print(f"🟢 BUY SIGNAL FIRED - Price {latest_close:.2f} above fib_0 {latest_wma_0:.2f} with trigger armed")

        # --- Charting Logic ---
        fig = go.Figure(data=[go.Candlestick(x=df_with_fibs.index, open=df_with_fibs['open'], high=df_with_fibs['high'], low=df_with_fibs['low'], close=df_with_fibs['close'], name='Candles')])
        fig.add_trace(go.Scatter(x=df_with_fibs.index, y=df_with_fibs['wma_fib_0'], mode='lines', name='WMA Fib 0', line=dict(color='lime', width=1)))
        fig.add_trace(go.Scatter(x=df_with_fibs.index, y=df_with_fibs['fib_entry'], mode='lines', name='Fib Entry', line=dict(color='cyan', width=1, dash='dash')))
        fig.add_trace(go.Scatter(x=df_with_fibs.index, y=df_with_fibs['wma_fib_50'], mode='lines', name='WMA Fib 50', line=dict(color='red', width=1)))
        
        if in_position:
            all_logs = read_trade_logs(LOG_FILE)
            last_sell_index = -1
            for i in range(len(all_logs) - 1, -1, -1):
                if all_logs[i].get('trade_type') == 'sell':
                    last_sell_index = i
                    break
            current_buys = [t for t in all_logs[last_sell_index + 1:] if t.get('trade_type') == 'buy' or 'trade_type' not in t]
            
            buy_times = [pd.to_datetime(trade['log_timestamp']) for trade in current_buys]
            buy_prices = [float(trade['exchange_response']['response']['data']['statuses'][0]['filled']['avgPx']) for trade in current_buys]

            fig.add_trace(go.Scatter(x=buy_times, y=buy_prices, mode='markers', name='Buy Trades', marker=dict(color='lime', size=10, symbol='triangle-up')))
            
            if entry_price:
                fig.add_hline(y=entry_price, line_dash="dash", line_color="purple", annotation_text=f"Avg Entry {entry_price:.2f}", annotation_position="bottom left", annotation_font=dict(color="purple"))
        
        fig.update_layout(title_text=f'Last Updated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}', yaxis_title='Price (USD)', xaxis_rangeslider_visible=False, template='plotly_dark')
        if relayout_data and 'xaxis.range[0]' in relayout_data: 
            fig.update_layout(xaxis_range=[relayout_data['xaxis.range[0]'], relayout_data['xaxis.range[1]']])
        if relayout_data and 'yaxis.range[0]' in relayout_data: 
            fig.update_layout(yaxis_range=[relayout_data['yaxis.range[0]'], relayout_data['yaxis.range[1]']])

        # --- Enhanced Display Logic with Drop-to-Zone Calculations ---
        # Check if we have Fibonacci data available
        if pd.isna(latest_fib_entry) or pd.isna(latest_wma_0):
            # No Fibonacci data yet - show basic price info
            candles_needed = 66 - len(df_with_fibs)
            indicator_text = [
                html.Span(f"Latest Price: {format_small_price(latest_close)}", style={'fontWeight': 'bold'}),
                html.Span(" | ", style={'color': '#BBBBBB'}),
                html.Span("⏳ Waiting for Fibonacci levels...", style={'color': 'yellow'}),
                html.Span(f" (Need {candles_needed} more 5min candles)", style={'color': '#BBBBBB', 'fontSize': '14px'}),
                html.Br()
            ]
        else:
            # Determine position relative to buy zone and calculate drop needed
            if latest_close < latest_fib_entry:
                zone_status = "Below Entry 📉"
                zone_color = 'cyan'
                entry_status = "✅ Ready for signals"
                fib0_status = "✅ Ready for signals"
            elif latest_fib_entry <= latest_close <= latest_wma_0:
                zone_status = "In Buy Zone 🎯"
                zone_color = 'lime'
                entry_status = "✅ In Zone"
                fib0_status = "✅ In Zone"
            else:
                zone_status = "Above Zone 📈"
                zone_color = 'orange'
                # Calculate drops needed
                drop_to_entry = calculate_drop_needed_percentage(latest_close, latest_fib_entry)
                drop_to_fib0 = calculate_drop_needed_percentage(latest_close, latest_wma_0)
                entry_status = f"Need -{drop_to_entry} drop"
                fib0_status = f"Need -{drop_to_fib0} drop"
            
            indicator_text = [
                html.Span(f"Price: {format_small_price(latest_close)}", style={'fontWeight': 'bold'}),
                html.Span(" | ", style={'color': '#BBBBBB'}),
                html.Span(f"Entry: {entry_status}", style={'color': 'cyan', 'fontWeight': 'bold'}),
                html.Span(" | ", style={'color': '#BBBBBB'}),
                html.Span(f"Fib 0: {fib0_status}", style={'color': 'lime', 'fontWeight': 'bold'}),
                html.Span(" | ", style={'color': '#BBBBBB'}),
                html.Span(zone_status, style={'color': zone_color, 'fontWeight': 'bold'}),
                html.Br()
            ]

        status_line = [html.Span("STATUS: ", style={'fontWeight': 'bold'})]
        
        if in_position:
            position_value_usd = position_size * latest_close
            status_line.append(html.Span("In Position", style={'fontWeight': 'bold', 'color': 'orange'}))
            status_line.append(html.Span(f" | Size: {position_size:.4f} {COIN_TO_TRACK} ({format_small_price(position_value_usd)})", style={'color': 'orange'}))
        
            if entry_price:
                status_line.append(html.Span(f" | Entry: {format_small_price(entry_price)}", style={'color': 'orange'}))
                pnl_pct = ((latest_close - entry_price) / entry_price) * 100
                pnl_usd = (latest_close - entry_price) * position_size
                pnl_color = 'lime' if pnl_pct >= 0 else 'red'
                pnl_sign = '+' if pnl_pct >= 0 else ''
                status_line.append(html.Span(f" | PnL: {pnl_sign}{pnl_pct:.2f}% ({format_small_price(pnl_usd)})", style={'color': pnl_color, 'fontWeight': 'bold'}))
        else:
            status_line.append(html.Span(f"Trigger Armed: {trigger_on}", style={'color': 'lime' if trigger_on else '#BBBBBB', 'marginRight': '15px'}))
            status_line.append(html.Span(f"| BUY SIGNAL: {buy_signal}", style={'color': 'lime' if buy_signal else '#BBBBBB', 'fontWeight': 'bold' if buy_signal else 'normal'}))
        
        # Add wallet analysis to display
        # In the wallet display section, replace the USD display with:
        if wallet_analysis and wallet_analysis.get('has_position'):
            wallet_line = [
                html.Br(),
                html.Span("🔍 TRACKED WALLET: ", style={'fontWeight': 'bold', 'color': 'yellow'}),
                html.Span(f"Entry: {wallet_analysis['avg_entry_price_sol']:.10f} SOL", style={'color': 'cyan'}),
                html.Span(" | ", style={'color': '#BBBBBB'}),
                html.Span(f"Size: {wallet_analysis['current_tokens']:,.0f} tokens", style={'color': 'white'}),
                html.Span(" | ", style={'color': '#BBBBBB'}),
                html.Span(f"P&L: {wallet_analysis['pnl_percentage']:+.2f}% ({wallet_analysis['pnl_sol']:+.4f} SOL)", 
                        style={'color': 'lime' if wallet_analysis['pnl_percentage'] >= 0 else 'red', 'fontWeight': 'bold'}),
                html.Span(f" | Trades: {wallet_analysis['total_trades']}", style={'color': '#BBBBBB'})
            ]
            indicator_text.extend(wallet_line)
        
        indicator_text.extend(status_line)

        # --- State Saving ---
        new_state = {'trigger_on': trigger_on, 'in_position': in_position, 'entry_price': entry_price, 'position_size': position_size}
        
        # --- Save original signal data ---
        signal_data = {
            "timestamp": datetime.now().isoformat(),
            "coin": COIN_TO_TRACK,
            "latest_price": latest_close,
            "fib_entry_level": latest_fib_entry,
            "fib_0_level": latest_wma_0,
            "fib_50_level": latest_wma_50,
            "atr": latest_atr,
            "state": {
                "trigger_on": trigger_on,
                "buy_signal": buy_signal
            }
        }
        with open(SIGNAL_FILE, 'w') as f: 
            json.dump(signal_data, f, indent=4)
        
        # --- Incremental update to price_savant.json ---
        update_price_savant_incremental(data, df_with_fibs, new_state, wallet_analysis)
        
        return fig, indicator_text, new_state

    except (FileNotFoundError, json.JSONDecodeError, ValueError, IndexError) as e:
        error_data = {"timestamp": datetime.now().isoformat(), "coin": COIN_TO_TRACK, "error": str(e), "state": {"trigger_on": False, "buy_signal": False}}
        with open(SIGNAL_FILE, 'w') as f: 
            json.dump(error_data, f, indent=4)
        
        fig = go.Figure().update_layout(title_text=f"Waiting for data... ({e})", template='plotly_dark')
        return fig, f"Error: {e}", trade_state

if __name__ == '__main__':
    app.run(debug=True, port=8051)