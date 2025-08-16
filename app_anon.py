# Hyperliquid Candlestick Dashboard (app_anon.py)
#
# This Dash application reads price data, calculates signals, and determines
# its initial position state by reading a trade log file on startup.
# It now displays the PnL %, plots individual trades, shows the average entry price,
# and passes the ATR value to the signal file.
# Additionally creates price_savant.json with incremental updates to avoid
# reprocessing enormous datasets.
# Now also saves the most recent savant data to trigger.json
# NOTE: Wallet tracking is now handled by Jupiter executor - removed hardcoded trades
#
# Prerequisites:
# pip install dash pandas plotly numpy
#
# To Run:
# 1. Ensure your price data collection is running.
# 2. Save this file as 'app_anon.py'.
# 3. Run from your terminal: python app_anon.py

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

# --- Configuration ---
DATA_FILE = "token_price_data_v3.json"
SIGNAL_FILE = "trade_signals.json"
PRICE_SAVANT_FILE = "price_savant_anon.json"  # Enhanced price data file
TRIGGER_FILE = "trigger2.json"  # Most recent savant data
COIN_TO_TRACK = "ANON"
APP_REFRESH_SECONDS = 5
ATR_PERIOD = 14

# ATR Reactivity Configuration
# Higher values = less reactive (wider entry zones)
# Lower values = more reactive (tighter entry zones)
ATR_MULTIPLIER = 2  # Default: 1.5 (adjust between 0.5-3.0)
#   0.5-1.0 = Very reactive (tight entry zones, more frequent signals)
#   1.0-1.5 = Balanced reactivity 
#   1.5-2.0 = Less reactive (wider entry zones, fewer but stronger signals)
#   2.0-3.0 = Very conservative (very wide entry zones)

# Global variable to track last processed record
last_processed_count = 0

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

# --- Fibonacci Calculator Class ---
class FibonacciCalculator:
    def __init__(self, config=None):
        self.config = config or {
            'trading': {
                'atr_multiplier': ATR_MULTIPLIER,
                'fib_entry_floor_pct': 0.85,  # Never go below 85% of fib_0
                'reset_pct_above_fib_0': 0.05  # 5% above fib_0 for reset
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

def create_enhanced_record(price_record, fib_data_map, trade_state, previous_trigger_state=None):
    """Create a single enhanced price record with proper trigger logic"""
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
                'atr_multiplier': fib_data.get('atr_multiplier', ATR_MULTIPLIER),
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
                
                # Return the updated trigger state for the next record
                return enhanced_record, trigger_armed
            else:
                enhanced_record.update({
                    'trigger_armed': None, 'buy_signal': False, 'reset_threshold': None,
                    'price_above_reset': None, 'price_below_entry': None, 
                    'price_above_fib_0': None, 'in_buy_zone': None
                })
        else:
            # No matching OHLC window found, add empty fib fields
            enhanced_record.update({
                'ohlc_open': None, 'ohlc_high': None, 'ohlc_low': None, 'ohlc_close': None,
                'wma_fib_0': None, 'wma_fib_50': None, 'fib_entry': None, 'atr': None,
                'atr_multiplier': None, 'highest_high_42': None, 'lowest_low_42': None,
                'trigger_armed': None, 'buy_signal': False, 'reset_threshold': None,
                'price_above_reset': None, 'price_below_entry': None, 
                'price_above_fib_0': None, 'in_buy_zone': None
            })
        
        # Add current trading state (for compatibility)
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
            'atr_multiplier': None, 'highest_high_42': None, 'lowest_low_42': None,
            'trigger_armed': None, 'buy_signal': False, 'reset_threshold': None,
            'price_above_reset': None, 'price_below_entry': None, 
            'price_above_fib_0': None, 'in_buy_zone': None,
            'current_in_position': trade_state.get('in_position', False),
            'current_trigger_on': trade_state.get('trigger_on', False),
            'entry_price': trade_state.get('entry_price'), 
            'position_size': trade_state.get('position_size', 0.0)
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

def update_price_savant_incremental(original_data, df_with_fibs, trade_state):
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
                'atr_multiplier': ATR_MULTIPLIER,
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
                record, fib_data_map, trade_state, current_trigger_state
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
        
        # Save the most recent record to trigger.json
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

# Initialize last processed count
last_processed_count = get_last_processed_count()
print(f"🚀 Starting with {last_processed_count} already processed records")
print(f"🎛️ ATR Multiplier: {ATR_MULTIPLIER} ({'Reactive' if ATR_MULTIPLIER < 1.5 else 'Balanced' if ATR_MULTIPLIER <= 2.0 else 'Conservative'})")

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
        atr_multiplier = fib_calculator.config['trading']['atr_multiplier']
        df_with_fibs['fib_entry'] = df_with_fibs['wma_fib_0'] - (df_with_fibs['atr'] * atr_multiplier)

        # Make sure fib_entry doesn't go negative or too far below
        floor_multiplier = fib_calculator.config['trading']['fib_entry_floor_pct']
        df_with_fibs['fib_entry'] = np.maximum(
            df_with_fibs['fib_entry'], 
            df_with_fibs['wma_fib_0'] * floor_multiplier
        )
        
        latest_close, latest_wma_0, latest_fib_entry, latest_atr, latest_wma_50 = [
            df_with_fibs[col].iloc[-1] for col in ['close', 'wma_fib_0', 'fib_entry', 'atr', 'wma_fib_50']
        ]

        trigger_on, in_position, entry_price, position_size = [
            trade_state.get(k) for k in ['trigger_on', 'in_position', 'entry_price', 'position_size']
        ]
        buy_signal = False
        reset_threshold = latest_wma_0 * (1 + fib_calculator.config['trading']['reset_pct_above_fib_0'])

        # --- Trading Logic ---
        if not in_position:
            if latest_close > reset_threshold:
                trigger_on = False
                print(f"🔴 Trigger DISARMED - Price {latest_close:.8f} above reset threshold {reset_threshold:.8f}")
            elif latest_close < latest_fib_entry:
                trigger_on = True
                print(f"🟡 Trigger ARMED - Price {latest_close:.8f} below entry level {latest_fib_entry:.8f}")
            
            if trigger_on and latest_close > latest_wma_0:
                buy_signal = True
                in_position = True
                entry_price = latest_close
                print(f"🟢 BUY SIGNAL FIRED - Price {latest_close:.8f} above fib_0 {latest_wma_0:.8f} with trigger armed")

        # --- Charting Logic ---
        fig = go.Figure(data=[go.Candlestick(
            x=df_with_fibs.index, 
            open=df_with_fibs['open'], 
            high=df_with_fibs['high'], 
            low=df_with_fibs['low'], 
            close=df_with_fibs['close'], 
            name='Candles'
        )])
        
        fig.add_trace(go.Scatter(
            x=df_with_fibs.index, 
            y=df_with_fibs['wma_fib_0'], 
            mode='lines', 
            name='WMA Fib 0', 
            line=dict(color='lime', width=2)
        ))
        
        fig.add_trace(go.Scatter(
            x=df_with_fibs.index, 
            y=df_with_fibs['fib_entry'], 
            mode='lines', 
            name=f'Fib Entry (ATR×{atr_multiplier})', 
            line=dict(color='cyan', width=2, dash='dash')
        ))
        
        fig.add_trace(go.Scatter(
            x=df_with_fibs.index, 
            y=df_with_fibs['wma_fib_50'], 
            mode='lines', 
            name='WMA Fib 50', 
            line=dict(color='red', width=1)
        ))
        
        fig.update_layout(
            title_text=f'Last Updated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} | ATR Multiplier: {atr_multiplier}', 
            yaxis_title='Price (SOL)', 
            xaxis_rangeslider_visible=False, 
            template='plotly_dark'
        )
        
        if relayout_data and 'xaxis.range[0]' in relayout_data: 
            fig.update_layout(xaxis_range=[relayout_data['xaxis.range[0]'], relayout_data['xaxis.range[1]']])
        if relayout_data and 'yaxis.range[0]' in relayout_data: 
            fig.update_layout(yaxis_range=[relayout_data['yaxis.range[0]'], relayout_data['yaxis.range[1]']])

        # --- Enhanced Display Logic ---
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
                html.Br(),
                html.Span(f"ATR: {latest_atr:.8f}", style={'color': '#BBBBBB', 'fontSize': '14px'}),
                html.Span(f" | Multiplier: {atr_multiplier}x", style={'color': '#BBBBBB', 'fontSize': '14px'}),
                html.Span(f" | Reactivity: {'High' if atr_multiplier < 1.5 else 'Medium' if atr_multiplier <= 2.0 else 'Low'}", 
                         style={'color': '#BBBBBB', 'fontSize': '14px'}),
                html.Br()
            ]

        status_line = [html.Span("SIGNAL STATUS: ", style={'fontWeight': 'bold'})]
        status_line.append(html.Span(f"Trigger Armed: {trigger_on}", style={'color': 'lime' if trigger_on else '#BBBBBB', 'marginRight': '15px'}))
        status_line.append(html.Span(f"| BUY SIGNAL: {buy_signal}", style={'color': 'lime' if buy_signal else '#BBBBBB', 'fontWeight': 'bold' if buy_signal else 'normal'}))
        
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
            "atr_multiplier": atr_multiplier,
            "state": {
                "trigger_on": trigger_on,
                "buy_signal": buy_signal
            }
        }
        with open(SIGNAL_FILE, 'w') as f: 
            json.dump(signal_data, f, indent=4)
        
        # --- Incremental update to price_savant.json ---
        update_price_savant_incremental(data, df_with_fibs, new_state)
        
        return fig, indicator_text, new_state

    except (FileNotFoundError, json.JSONDecodeError, ValueError, IndexError) as e:
        error_data = {
            "timestamp": datetime.now().isoformat(), 
            "coin": COIN_TO_TRACK, 
            "error": str(e), 
            "state": {"trigger_on": False, "buy_signal": False}
        }
        with open(SIGNAL_FILE, 'w') as f: 
            json.dump(error_data, f, indent=4)
        
        fig = go.Figure().update_layout(title_text=f"Waiting for data... ({e})", template='plotly_dark')
        return fig, f"Error: {e}", trade_state

if __name__ == '__main__':
    app.run(debug=True, port=8051)