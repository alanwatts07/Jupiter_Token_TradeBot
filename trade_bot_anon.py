# Jupiter Signal Bot - Discord Notifications & Trade Triggering with Real Wallet Stats
import time
import json
import os
import requests
from datetime import datetime, timezone, timedelta
import schedule

# --- Script Configuration ---
PRICE_SAVANT_FILE = "price_savant_anon.json"
CONFIG_FILE = "config.json"
WALLET_STATS_FILE = "wallet_statistics.json"
CHECK_INTERVAL_SECONDS = 5
TRADE_ASSET = "ANON"
STATUS_UPDATE_MINUTES = 15
MESSAGES_TO_KEEP = 10
CLEANUP_INTERVAL_HOURS = 4

# --- State Tracking ---
last_traded_signal_timestamp = None
last_known_trigger_state = None
BOT_USER_ID = None

# --- Helper Functions ---
def format_timedelta(td):
    seconds = int(td.total_seconds())
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    parts = [f"{d}d" for d in [days] if d > 0]
    parts.extend([f"{h}h" for h in [hours] if h > 0])
    parts.extend([f"{m}m" for m in [minutes] if m > 0])
    return " ".join(parts) if parts else "< 1 min"

def load_config():
    """Loads the main config.json file."""
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[!!!] CRITICAL: `{CONFIG_FILE}` not found. Please create it.")
        return None
    except json.JSONDecodeError:
        print(f"[!!!] CRITICAL: Could not decode `{CONFIG_FILE}`. Check for syntax errors.")
        return None

def load_wallet_stats():
    """Load wallet statistics from Jupiter executor"""
    try:
        if not os.path.exists(WALLET_STATS_FILE):
            return None
        with open(WALLET_STATS_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"[!] Error loading wallet stats: {e}")
        return None

def read_last_savant_record():
    """Read the most recent price/signal data from the savant file"""
    if not os.path.exists(PRICE_SAVANT_FILE): 
        return None
    try:
        with open(PRICE_SAVANT_FILE, 'rb') as f:
            f.seek(0, os.SEEK_END)
            file_size = f.tell()
            if file_size == 0: 
                return None
            buffer_size = 4096
            seek_pos = max(0, file_size - buffer_size)
            f.seek(seek_pos)
            buffer = f.read().decode('utf-8', errors='ignore')
            last_obj_start = buffer.rfind('{')
            if last_obj_start == -1: 
                return None
            temp_buffer = buffer[last_obj_start:]
            brace_level = 0
            last_obj_end = -1
            for i, char in enumerate(temp_buffer):
                if char == '{': 
                    brace_level += 1
                elif char == '}':
                    brace_level -= 1
                    if brace_level == 0:
                        last_obj_end = i + 1
                        break
            if last_obj_end != -1: 
                return json.loads(temp_buffer[:last_obj_end])
            return None
    except Exception as e:
        print(f"[!] Error in read_last_savant_record: {e}")
        return None

# --- Discord Functions ---
def discord_api_request(bot_token, endpoint, method="POST", payload=None):
    if not bot_token: 
        return None
    headers = {"Authorization": f"Bot {bot_token}", "Content-Type": "application/json"}
    url = f"https://discord.com/api/v10{endpoint}"
    try:
        if method == "POST": 
            response = requests.post(url, headers=headers, json=payload, timeout=10)
        elif method == "GET": 
            response = requests.get(url, headers=headers, timeout=10)
        elif method == "DELETE": 
            response = requests.delete(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json() if response.content else None
    except requests.exceptions.RequestException as e:
        print(f"[!] Discord API Error on endpoint {endpoint}: {e}")
        if hasattr(e, 'response') and e.response: 
            print(f"    Response: {e.response.text}")
        return None

def trigger_buy_trade(price, savant_data):
    """Write a buy command for the Jupiter executor to process"""
    try:
        print(f"[DEBUG] Attempting to trigger buy trade...")
        print(f"[DEBUG] Price: {price}")
        print(f"[DEBUG] Looking for bot_config.json...")
        
        # Check if bot_config.json exists
        if not os.path.exists('bot_config.json'):
            print("[ERROR] bot_config.json file not found!")
            return False
        
        # Load bot config
        with open('bot_config.json', 'r') as f:
            bot_config = json.load(f)
        
        print(f"[DEBUG] Bot config loaded successfully")
        print(f"[DEBUG] Trading enabled: {bot_config.get('trading', {}).get('enabled', 'NOT FOUND')}")
        
        # Check if trading is enabled
        if not bot_config.get('trading', {}).get('enabled', False):
            print("[!] Trading disabled in bot_config.json")
            return False
        
        print(f"[DEBUG] Creating trade command...")
        
        # Create trade command
        trade_command = {
            "command": "BUY",
            "timestamp": datetime.now().isoformat(),
            "token_symbol": TRADE_ASSET,
            "token_address": bot_config['tokens'][TRADE_ASSET],
            "sol_amount": bot_config['trading']['sol_amount_per_trade'],
            "current_price": price,
            "trigger_data": {
                "fib_0": savant_data.get('wma_fib_0'),
                "fib_entry": savant_data.get('fib_entry'),
                "trigger_armed": savant_data.get('trigger_armed')
            },
            "processed": False
        }
        
        print(f"[DEBUG] Trade command created: {trade_command}")
        
        # Write to pending trades file
        pending_file = "pending_trades.json"
        pending_trades = []
        
        if os.path.exists(pending_file):
            print(f"[DEBUG] Loading existing pending_trades.json...")
            with open(pending_file, 'r') as f:
                pending_trades = json.load(f)
        else:
            print(f"[DEBUG] Creating new pending_trades.json...")
        
        pending_trades.append(trade_command)
        
        with open(pending_file, 'w') as f:
            json.dump(pending_trades, f, indent=2)
        
        print(f"[SUCCESS] Buy command written to {pending_file}")
        print(f"[SUCCESS] Command: {bot_config['trading']['sol_amount_per_trade']} SOL → {TRADE_ASSET}")
        
        # Verify the file was written
        if os.path.exists(pending_file):
            with open(pending_file, 'r') as f:
                verification = json.load(f)
            print(f"[DEBUG] File verification: {len(verification)} pending trades in file")
        
        return True
        
    except Exception as e:
        print(f"[ERROR] Error writing trade command: {e}")
        import traceback
        traceback.print_exc()
        return False

def send_discord_alert(bot_token, channel_id, message, color=0x00ff00, savant_data=None, wallet_stats=None):
    """Send a Discord alert with optional price/signal data and wallet statistics"""
    embed = {
        "title": f"🤖 {TRADE_ASSET} Jupiter Signal Bot", 
        "description": message, 
        "color": color, 
        "timestamp": datetime.now().astimezone().isoformat(), 
        "footer": {"text": "Jupiter Signal Bot"}
    }
    
    fields = []
    
    # Add savant data if available
    if savant_data and isinstance(savant_data, dict):
        try:
            price = savant_data.get('price', 0)
            trigger_armed = savant_data.get('trigger_armed', 'N/A')
            buy_signal = savant_data.get('buy_signal', 'N/A')
            fib_entry = savant_data.get('fib_entry', 0)
            wma_fib_0 = savant_data.get('wma_fib_0', 0)
            atr = savant_data.get('atr', 0)
            
            if price and price > 0:
                # Basic price fields
                fields.extend([
                    {"name": "💰 Current Price", "value": f"`{price:.10f} SOL`", "inline": True},
                    {"name": "🎯 Trigger Armed", "value": f"**`{trigger_armed}`**", "inline": True},
                    {"name": "🚀 Buy Signal", "value": f"**`{buy_signal}`**", "inline": True},
                ])
                
                # Fibonacci levels
                if fib_entry and fib_entry > 0:
                    fields.append({"name": "📊 Fib Entry", "value": f"`{fib_entry:.10f} SOL`", "inline": True})
                if wma_fib_0 and wma_fib_0 > 0:
                    fields.append({"name": "📈 Fib 0", "value": f"`{wma_fib_0:.10f} SOL`", "inline": True})
                
                # ATR info
                if atr and atr > 0:
                    fields.append({"name": "📏 ATR", "value": f"`{atr:.8f}`", "inline": True})
                    
        except Exception as e:
            print(f"[!] Error processing savant data: {e}")
            fields.append({
                "name": "⚠️ Data Error",
                "value": f"Error reading price data: {str(e)[:100]}",
                "inline": False
            })
    
    # Add REAL wallet statistics if available
    if wallet_stats and isinstance(wallet_stats, dict):
        try:
            current_pos = wallet_stats.get('current_position', {})
            performance = wallet_stats.get('performance', {})
            
            # Token balance and SOL balance
            token_balance = current_pos.get('token_balance', 0)
            sol_balance = current_pos.get('sol_balance', 0)
            
            if token_balance > 0:
                fields.append({
                    "name": "💼 Position Size", 
                    "value": f"`{token_balance:,.0f} {TRADE_ASSET}`", 
                    "inline": True
                })
                
                # Average entry price
                avg_entry = wallet_stats.get('average_entry_price', 0)
                if avg_entry > 0:
                    fields.append({
                        "name": "🎯 Avg Entry Price", 
                        "value": f"`{avg_entry:.10f} SOL`", 
                        "inline": True
                    })
                
                # FIXED: Current token price vs entry calculation
                current_token_price = performance.get('current_token_price', 0)
                current_price_from_savant = savant_data.get('price', 0) if savant_data else 0
                
                # Use current price from savant data if available, otherwise from performance
                display_current_price = current_price_from_savant if current_price_from_savant > 0 else current_token_price
                
                if display_current_price > 0 and avg_entry > 0:
                    # FIXED: Proper percentage calculation
                    price_change = ((display_current_price - avg_entry) / avg_entry) * 100
                    price_emoji = "📈" if price_change >= 0 else "📉"
                    price_color = "🟢" if price_change >= 0 else "🔴"
                    
                    fields.append({
                        "name": f"{price_emoji} Price vs Entry", 
                        "value": f"{price_color} **{price_change:+.2f}%**\n`{display_current_price:.10f}` vs `{avg_entry:.10f}`", 
                        "inline": True
                    })
                
                # FIXED: Token value calculation using current price
                token_value_in_sol = 0
                if display_current_price > 0:
                    token_value_in_sol = token_balance * display_current_price
                elif 'token_value_in_sol' in performance:
                    token_value_in_sol = performance['token_value_in_sol']
                
                # FIXED: Total P&L calculation
                initial_sol = wallet_stats.get('initial_sol_balance', 0)
                total_current_value = sol_balance + token_value_in_sol
                
                if initial_sol > 0:
                    total_pnl = total_current_value - initial_sol
                    total_pnl_pct = (total_pnl / initial_sol) * 100
                    
                    pnl_emoji = "📈" if total_pnl >= 0 else "📉"
                    pnl_color = "🟢" if total_pnl >= 0 else "🔴"
                    
                    fields.append({
                        "name": f"{pnl_emoji} Total P&L", 
                        "value": f"{pnl_color} **{total_pnl_pct:+.2f}%**\n`{total_pnl:+.4f} SOL`", 
                        "inline": True
                    })
                
                # FIXED: Unrealized P&L on tokens only
                total_sol_spent = wallet_stats.get('total_sol_spent', 0)
                if total_sol_spent > 0 and token_value_in_sol > 0:
                    unrealized_pnl = token_value_in_sol - total_sol_spent
                    unrealized_pnl_pct = (unrealized_pnl / total_sol_spent) * 100
                    unrealized_emoji = "💎" if unrealized_pnl >= 0 else "💔"
                    unrealized_color = "🟢" if unrealized_pnl >= 0 else "🔴"
                    
                    fields.append({
                        "name": f"{unrealized_emoji} Token P&L", 
                        "value": f"{unrealized_color} **{unrealized_pnl_pct:+.2f}%**\n`{unrealized_pnl:+.4f} SOL`", 
                        "inline": True
                    })
                
                # Trading stats
                total_trades = wallet_stats.get('total_trades_executed', 0)
                
                if total_trades > 0:
                    fields.append({
                        "name": "📊 Trading Stats", 
                        "value": f"**{total_trades}** trades\n`{total_sol_spent:.4f}` SOL invested", 
                        "inline": True
                    })
                
                # FIXED: Current portfolio value with correct token value
                fields.append({
                    "name": "💰 Portfolio Value", 
                    "value": f"`{total_current_value:.4f} SOL`\n(SOL: `{sol_balance:.4f}` + Tokens: `{token_value_in_sol:.4f}`)", 
                    "inline": True
                })
                
                    
        except Exception as e:
            print(f"[!] Error processing wallet stats: {e}")
            import traceback
            traceback.print_exc()
            fields.append({
                "name": "⚠️ Wallet Error",
                "value": f"Error reading wallet data: {str(e)[:100]}",
                "inline": False
            })
    else:
        # No wallet stats available
        fields.append({
            "name": "📊 Wallet Status", 
            "value": "⏳ Waiting for Jupiter executor to generate wallet statistics...", 
            "inline": False
        })
    
    if fields: 
        embed["fields"] = fields
    
    return discord_api_request(bot_token, f"/channels/{channel_id}/messages", payload={"embeds": [embed]})

def cleanup_channel(bot_token, channel_id):
    """Clean up old status messages"""
    global BOT_USER_ID
    if not BOT_USER_ID: 
        return
    print("[*] Running scheduled channel cleanup...")
    messages = discord_api_request(bot_token, f"/channels/{channel_id}/messages?limit=100", method="GET")
    if not messages: 
        return

    status_reports = [
        msg for msg in messages
        if msg['author']['id'] == BOT_USER_ID and msg['embeds'] and "Status Report" in msg['embeds'][0].get('description', '')
    ]
    
    if len(status_reports) > MESSAGES_TO_KEEP:
        to_delete = sorted(status_reports, key=lambda x: x['timestamp'])[:-MESSAGES_TO_KEEP]
        delete_ids = [msg['id'] for msg in to_delete]
        if len(delete_ids) > 1:
            print(f"[*] Deleting {len(delete_ids)} old status reports.")
            discord_api_request(bot_token, f"/channels/{channel_id}/messages/bulk-delete", payload={"messages": delete_ids})
        elif len(delete_ids) == 1:
            print("[*] Deleting 1 old status report.")
            discord_api_request(bot_token, f"/channels/{channel_id}/messages/{delete_ids[0]}", method="DELETE")

def send_status_update(bot_token, channel_id):
    """Send periodic status updates with real wallet data"""
    print(f"[*] Sending {STATUS_UPDATE_MINUTES}-minute status update...")
    latest_savant_data = read_last_savant_record()
    wallet_stats = load_wallet_stats()
    
    # Check if bot_config exists to determine trading status
    trading_enabled = False
    try:
        with open('bot_config.json', 'r') as f:
            bot_config = json.load(f)
            trading_enabled = bot_config['trading']['enabled']
    except:
        pass
    
    mode_msg = "🤖 **TRADING MODE**" if trading_enabled else "🔔 **ALERT-ONLY MODE**"
    
    # Enhanced status message with REAL wallet performance
    message_parts = [f"✅ **{STATUS_UPDATE_MINUTES}-Min Status** - {mode_msg}"]
    
    if wallet_stats:
        performance = wallet_stats.get('performance', {})
        current_pos = wallet_stats.get('current_position', {})
        
        total_pnl_pct = performance.get('total_pnl_percent', 0)
        token_balance = current_pos.get('token_balance', 0)
        
        if token_balance > 0:
            pnl_status = f"📈 **+{total_pnl_pct:.2f}%**" if total_pnl_pct >= 0 else f"📉 **{total_pnl_pct:.2f}%**"
            message_parts.append(f"{pnl_status} portfolio performance")
            
            # Add drop to entry info if available from savant data
            if latest_savant_data:
                current_price = latest_savant_data.get('price', 0)
                fib_entry = latest_savant_data.get('fib_entry', 0)
                
                if current_price and fib_entry:
                    if current_price > fib_entry:
                        drop_needed = ((current_price - fib_entry) / current_price) * 100
                        message_parts.append(f"📉 Need **-{drop_needed:.1f}%** drop to reach entry zone")
                    else:
                        message_parts.append("🎯 **Price at/below entry zone!**")
        else:
            message_parts.append("📭 No position detected")
    else:
        message_parts.append("Bot is alive and monitoring signals")
    
    # Check if savant data is available
    if not latest_savant_data:
        message_parts.append(f"⚠️ Waiting for price data from `{PRICE_SAVANT_FILE}`")
    
    message = "\n".join(message_parts)
    
    send_discord_alert(bot_token, channel_id, message, 0x3498db, 
                      savant_data=latest_savant_data, wallet_stats=wallet_stats)

# --- MAIN EXECUTION ---
def main():
    global last_traded_signal_timestamp, last_known_trigger_state, BOT_USER_ID

    config = load_config()
    if not config: 
        return

    bot_token = config.get("discord_bot_token")
    channel_id = config.get("discord_channel_id")
    if not bot_token or not channel_id:
        print("[!!!] CRITICAL: `discord_bot_token` or `discord_channel_id` not found in config.json.")
        return

    # Authenticate Discord bot
    bot_user_info = discord_api_request(bot_token, "/users/@me", method="GET")
    if bot_user_info:
        BOT_USER_ID = bot_user_info['id']
        print(f"[*] Successfully authenticated Discord Bot: {bot_user_info['username']}")
    else:
        print("[!!!] CRITICAL: Could not authenticate with Discord using the provided bot token.")
        return

    try:
        # Check if Jupiter trading is enabled
        trading_enabled = False
        try:
            with open('bot_config.json', 'r') as f:
                bot_config = json.load(f)
                trading_enabled = bot_config['trading']['enabled']
                sol_amount = bot_config['trading']['sol_amount_per_trade']
        except:
            print("[!] Warning: bot_config.json not found - trading disabled")
            sol_amount = 0.1

        mode_text = "TRADING" if trading_enabled else "ALERT-ONLY"
        print(f"--- Jupiter Signal Bot - {mode_text} Mode ---")
        print(f"[*] Monitoring: {TRADE_ASSET}")
        print(f"[*] Trading: {'ENABLED' if trading_enabled else 'DISABLED'}")
        if trading_enabled:
            print(f"[*] SOL per trade: {sol_amount}")
        
        # Check wallet stats on startup
        wallet_stats = load_wallet_stats()
        if wallet_stats:
            current_pos = wallet_stats.get('current_position', {})
            performance = wallet_stats.get('performance', {})
            token_balance = current_pos.get('token_balance', 0)
            total_pnl_pct = performance.get('total_pnl_percent', 0)
            print(f"[*] Wallet position: {token_balance:,.0f} {TRADE_ASSET}")
            print(f"[*] Portfolio P&L: {total_pnl_pct:+.2f}%")
        else:
            print(f"[!] No wallet statistics found - waiting for Jupiter executor")

        # Schedule periodic tasks
        schedule.every(STATUS_UPDATE_MINUTES).minutes.do(send_status_update, bot_token=bot_token, channel_id=channel_id)
        schedule.every(CLEANUP_INTERVAL_HOURS).hours.do(cleanup_channel, bot_token=bot_token, channel_id=channel_id)

        # Send startup message
        startup_msg = (f"🚀 **Jupiter Signal Bot Started!** Monitoring **{TRADE_ASSET}**\n" 
                      f"**Mode:** `{mode_text}`")
        if trading_enabled:
            startup_msg += f"\n**Trade Size:** `{sol_amount} SOL per signal`"
        
        wallet_stats = load_wallet_stats()
        send_discord_alert(bot_token, channel_id, startup_msg, 0x888888, 
                          savant_data=None, wallet_stats=wallet_stats)
        
        print(f"\n[*] Signal bot running...")
        print(f"[*] {'Live trading active!' if trading_enabled else 'Alert-only mode - no trades will be executed'}")
        print("-" * 50)
        
        # Send initial status
        send_status_update(bot_token, channel_id)

        # Main monitoring loop
        while True:
            schedule.run_pending()

            # Monitor signals from the price savant file
            latest_record = read_last_savant_record()
            if latest_record:
                current_trigger_armed = latest_record.get('trigger_armed')
                
                # Load fresh wallet stats for each alert
                wallet_stats = load_wallet_stats()
                
                # Alert on trigger state changes
                if current_trigger_armed is not None and current_trigger_armed != last_known_trigger_state:
                    if current_trigger_armed:
                        message = "🟡 **Trigger ARMED!** Watching for price to cross above Fib 0."
                        send_discord_alert(bot_token, channel_id, message, 0xffff00, 
                                         savant_data=latest_record, wallet_stats=wallet_stats)
                        print("[🟡] Trigger ARMED - monitoring for buy signal")
                    else:
                        message = "🔴 **Trigger DISARMED.** Price crossed reset threshold."
                        send_discord_alert(bot_token, channel_id, message, 0xff6347, 
                                         savant_data=latest_record, wallet_stats=wallet_stats)
                        print("[🔴] Trigger DISARMED")
                    last_known_trigger_state = current_trigger_armed

                # Handle buy signals
                if (latest_record.get('buy_signal') and 
                    latest_record.get('timestamp') != last_traded_signal_timestamp):
                    
                    print(f"\n[🚀] NEW BUY SIGNAL DETECTED!")
                    print(f"[DEBUG] Signal timestamp: {latest_record.get('timestamp')}")
                    print(f"[DEBUG] Last traded timestamp: {last_traded_signal_timestamp}")
                    print(f"[DEBUG] Price: {latest_record.get('price', 0)}")
                    print(f"[DEBUG] Trading enabled check...")
                    
                    if trading_enabled:
                        print(f"[DEBUG] Trading is enabled - attempting to trigger trade...")
                        # Attempt to trigger trade
                        trade_result = trigger_buy_trade(latest_record.get('price', 0), latest_record)
                        print(f"[DEBUG] Trade trigger result: {trade_result}")
                        
                        if trade_result:
                            alert_message = (f"🚀 **BUY SIGNAL EXECUTED!**\n"
                                        f"Price: **{latest_record.get('price', 0):.10f} SOL**\n"
                                        f"Trade command sent to Jupiter executor\n"
                                        f"🤖 *Live trading mode active*")
                            send_discord_alert(bot_token, channel_id, alert_message, 0x00ff00, 
                                             savant_data=latest_record, wallet_stats=wallet_stats)
                        else:
                            alert_message = "🚨 **BUY SIGNAL FAILED** - Could not write trade command"
                            send_discord_alert(bot_token, channel_id, alert_message, 0xff0000, 
                                             savant_data=latest_record, wallet_stats=wallet_stats)
                    else:
                        print(f"[DEBUG] Trading is disabled - sending alert only...")
                        # Alert-only mode
                        alert_message = (f"🚀 **BUY SIGNAL DETECTED!**\n"
                                    f"Price: **{latest_record.get('price', 0):.10f} SOL**\n"
                                    f"⚠️ *Alert-only mode - no trade executed*")
                        send_discord_alert(bot_token, channel_id, alert_message, 0x00ff00, 
                                         savant_data=latest_record, wallet_stats=wallet_stats)
                    
                    last_traded_signal_timestamp = latest_record.get('timestamp')
                    print(f"[DEBUG] Updated last_traded_signal_timestamp to: {last_traded_signal_timestamp}")

            time.sleep(CHECK_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        send_discord_alert(bot_token, channel_id, f"🛑 **{TRADE_ASSET}** signal bot stopped by user.", 0x888888)
        print("\n[*] Signal bot stopped by user.")
    except Exception as e:
        print(f"[!!!] CRITICAL ERROR: {e}")
        send_discord_alert(bot_token, channel_id, f"❌ CRITICAL BOT ERROR: {e}", 0xff0000)

if __name__ == "__main__":
    main()