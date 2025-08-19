# Jupiter Signal Bot - MODIFIED to read from SQLite database
import discord
from discord.ext import commands, tasks
import asyncio
import json
import os
import time
import subprocess
from datetime import datetime, timezone, timedelta
from collections import deque
import sqlite3 # ADDED

# --- Bot Configuration ---
PRICE_SAVANT_DB = "price_savant.db" # CHANGED: Using SQLite database now
CONFIG_FILE = "config.json"
WALLET_STATS_FILE = "wallet_statistics.json"
CHECK_INTERVAL_SECONDS = 5
TRADE_ASSET = "ANON"

# --- State Tracking ---
last_traded_signal_timestamp = None
last_known_trigger_state = None
config = None
OWNER_ID = None

# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)
bot.remove_command('help')

# --- Helper Functions ---
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
    """
    MODIFIED: Load wallet statistics and override performance metrics to track P&L
    from the single most recent 'buy' transaction.
    """
    try:
        if not os.path.exists(WALLET_STATS_FILE):
            return None
        with open(WALLET_STATS_FILE, 'r') as f:
            stats = json.load(f)

        acquisitions = stats.get('token_acquisitions', [])
        if not acquisitions:
            return stats

        sorted_acquisitions = sorted(acquisitions, key=lambda x: x.get('timestamp', ''), reverse=True)
        last_buy = sorted_acquisitions[0]

        last_buy_sol_spent = last_buy.get('sol_spent', 0)
        last_buy_tokens_received = last_buy.get('tokens_received', 0)
        last_buy_timestamp = last_buy.get('timestamp', 'N/A')

        if last_buy_tokens_received > 0:
            last_buy_entry_price = last_buy_sol_spent / last_buy_tokens_received
            stats['average_entry_price'] = last_buy_entry_price
            stats['tracking_from_timestamp'] = last_buy_timestamp
            stats['total_sol_spent'] = last_buy_sol_spent
            
    except Exception as e:
        print(f"[!] Error processing wallet stats for last buy: {e}")
        try:
            with open(WALLET_STATS_FILE, 'r') as f: return json.load(f)
        except: return None
            
    return stats

def db_query(query, params=(), fetch_one=False):
    """Helper function to query the SQLite database."""
    if not os.path.exists(PRICE_SAVANT_DB):
        print(f"[!] Database file not found: {PRICE_SAVANT_DB}")
        return None
    try:
        conn = sqlite3.connect(PRICE_SAVANT_DB)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(query, params)
        if fetch_one:
            result = cursor.fetchone()
        else:
            result = cursor.fetchall()
        conn.close()
        return result
    except Exception as e:
        print(f"❌ Database query error: {e}")
        return None

def read_last_savant_record():
    """MODIFIED: Reads the single most recent record from the database."""
    row = db_query("SELECT * FROM price_data ORDER BY timestamp DESC LIMIT 1", fetch_one=True)
    return dict(row) if row else None

def read_recent_savant_records(num_records_to_get=100):
    """MODIFIED: Reads the last N records from the database."""
    rows = db_query("SELECT * FROM price_data ORDER BY timestamp DESC LIMIT ?", (num_records_to_get,))
    return [dict(row) for row in rows] if rows else []


def get_price_trend_from_savant():
    """
    OPTIMIZED & MORE ROBUST: Calculates price trend using the last ~100 records from the DB.
    """
    recent_records = read_recent_savant_records(num_records_to_get=100)
    if len(recent_records) < 2:
        return None

    for record in recent_records:
        try:
            record['datetime'] = datetime.fromisoformat(record['timestamp'].replace('Z', '+00:00'))
        except (ValueError, TypeError, KeyError):
            record['datetime'] = None
    
    valid_records = [r for r in recent_records if r['datetime'] is not None]
    if len(valid_records) < 2:
        return None

    valid_records.sort(key=lambda x: x['datetime'])
    
    oldest_record = valid_records[0]
    newest_record = valid_records[-1]
    old_price = oldest_record.get('price')
    new_price = newest_record.get('price')
    time_delta_minutes = round((newest_record['datetime'] - oldest_record['datetime']).total_seconds() / 60)

    if old_price is None or new_price is None or old_price == 0 or time_delta_minutes <= 0:
        return None

    percentage_change = ((new_price - old_price) / old_price) * 100
    return {"change_pct": percentage_change, "timeframe": f"last {time_delta_minutes} minutes"}

def trigger_buy_trade(price, savant_data):
    """Write a buy command for the Jupiter executor to process"""
    try:
        if not os.path.exists('bot_config.json'):
            print("[ERROR] bot_config.json file not found!")
            return False

        with open('bot_config.json', 'r') as f:
            bot_config = json.load(f)

        if not bot_config.get('trading', {}).get('enabled', False):
            print("[!] Trading disabled in bot_config.json")
            return False

        trade_command = {
            "command": "BUY", "timestamp": datetime.now().isoformat(),
            "token_symbol": TRADE_ASSET, "token_address": bot_config['tokens'][TRADE_ASSET],
            "sol_amount": bot_config['trading']['sol_amount_per_trade'], "current_price": price,
            "trigger_data": {
                "fib_0": savant_data.get('wma_fib_0'), "fib_entry": savant_data.get('fib_entry'),
                "trigger_armed": savant_data.get('trigger_armed')
            }, "processed": False
        }

        pending_file = "pending_trades.json"
        pending_trades = []
        if os.path.exists(pending_file):
            with open(pending_file, 'r') as f: pending_trades = json.load(f)

        pending_trades.append(trade_command)
        with open(pending_file, 'w') as f: json.dump(pending_trades, f, indent=2)

        print(f"[SUCCESS] Buy command written to {pending_file}")
        return True

    except Exception as e:
        print(f"[ERROR] Error writing trade command: {e}")
        return False

async def execute_bailout_sell():
    """Execute the bailout.js script and capture output"""
    try:
        if not os.path.exists('bailout.js'): return {'success': False, 'error': 'bailout.js file not found'}
        if not os.path.exists('node_modules'): return {'success': False, 'error': 'Node.js dependencies not installed. Run: npm install'}

        auto_bailout_script = '''
const BailoutSeller = require('./bailout.js');
async function autoSell() {
    try {
        const bailout = new BailoutSeller();
        console.log('🚨 EMERGENCY BAILOUT INITIATED FROM DISCORD BOT');
        const positionData = await bailout.displayCurrentPosition();
        const tokensWithBalance = [];
        for (const [tokenSymbol, tokenAddress] of positionData.tokens) {
            const balance = await bailout.getTokenBalance(tokenAddress);
            if (balance > 0) { tokensWithBalance.push({ symbol: tokenSymbol, address: tokenAddress, balance }); }
        }
        if (tokensWithBalance.length === 0) {
            console.log('✅ No tokens to sell');
            console.log('\\n===BAILOUT_SUMMARY===');
            console.log(JSON.stringify({ success: true, message: 'No tokens to sell' }));
            process.exit(0);
        }
        const slippageBps = 1000; const results = []; let totalSolReceived = 0;
        for (let i = 0; i < tokensWithBalance.length; i++) {
            const token = tokensWithBalance[i];
            const result = await bailout.executeSellTransaction(token.address, token.symbol, token.balance, slippageBps);
            results.push({ ...result, tokenSymbol: token.symbol });
            if (result.success) { totalSolReceived += result.expectedSol; }
            if (i < tokensWithBalance.length - 1) { await new Promise(resolve => setTimeout(resolve, 5000)); }
        }
        await bailout.logBailoutSale(results);
        console.log('\\n===BAILOUT_SUMMARY===');
        console.log(JSON.stringify({
            success: true, totalTransactions: results.length, successfulSales: results.filter(r => r.success).length,
            failedSales: results.filter(r => !r.success).length, totalSolReceived: totalSolReceived, results: results
        }));
    } catch (error) {
        console.error('❌ Auto-bailout failed:', error);
        console.log('\\n===BAILOUT_SUMMARY===');
        console.log(JSON.stringify({ success: false, error: error.message }));
    }
}
autoSell();
'''
        with open('auto_bailout.js', 'w') as f: f.write(auto_bailout_script)

        process = await asyncio.create_subprocess_exec('node', 'auto_bailout.js', stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=os.getcwd())
        stdout, stderr = await process.communicate()
        os.remove('auto_bailout.js')

        output = stdout.decode() if stdout else ""
        error_output = stderr.decode() if stderr else ""

        if "===BAILOUT_SUMMARY===" in output:
            summary_start = output.find("===BAILOUT_SUMMARY===") + len("===BAILOUT_SUMMARY===")
            summary_json = output[summary_start:].strip()
            try:
                summary = json.loads(summary_json)
                summary['full_output'] = output; summary['error_output'] = error_output
                return summary
            except json.JSONDecodeError as e:
                return {'success': False, 'error': f'Could not parse bailout results: {e}', 'full_output': output, 'error_output': error_output}
        else:
            return {'success': False, 'error': 'No bailout summary found in output', 'full_output': output, 'error_output': error_output}
    except Exception as e:
        return {'success': False, 'error': f'Exception during bailout: {str(e)}'}

# --- Owner Check Decorator ---
def is_owner():
    def predicate(ctx): return ctx.author.id == OWNER_ID
    return commands.check(predicate)

async def send_discord_embed(channel_or_message, message_text, color=0x00ff00, savant_data=None, wallet_stats=None, trend_data=None, trend_failed=False):
    """
    MODIFIED: Can now edit an existing message and show a trend failure message.
    """
    embed = discord.Embed(title=f"🤖 {TRADE_ASSET} Jupiter Signal Bot", description=message_text, color=color, timestamp=datetime.now())
    embed.set_footer(text="Jupiter Signal Bot")

    if savant_data and isinstance(savant_data, dict):
        price = savant_data.get('price', 0)
        if price > 0:
            embed.add_field(name="💰 Current Price", value=f"`{price:.10f} SOL`", inline=True)
            embed.add_field(name="🎯 Trigger Armed", value=f"**`{savant_data.get('trigger_armed', 'N/A')}`**", inline=True)
            embed.add_field(name="🚀 Buy Signal", value=f"**`{savant_data.get('buy_signal', 'N/A')}`**", inline=True)
            embed.add_field(name="📊 Fib Entry", value=f"`{savant_data.get('fib_entry', 0):.10f} SOL`", inline=True)
            embed.add_field(name="📈 Fib 0", value=f"`{savant_data.get('wma_fib_0', 0):.10f} SOL`", inline=True)
            embed.add_field(name="📏 ATR", value=f"`{savant_data.get('atr', 0):.8f}`", inline=True)

    if trend_data:
        change = trend_data.get("change_pct", 0)
        timeframe = trend_data.get("timeframe", "N/A")
        trend_emoji = "📈" if change >= 0 else "📉"
        embed.add_field(name=f"{trend_emoji} Price Trend", value=f"**{change:+.2f}%**\n({timeframe})", inline=False)
    elif trend_failed:
        embed.add_field(name="⚠️ Price Trend", value="Not enough recent data to calculate.", inline=False)


    if wallet_stats and isinstance(wallet_stats, dict):
        try:
            current_pos = wallet_stats.get('current_position', {})
            performance = wallet_stats.get('performance', {})
            token_balance = current_pos.get('token_balance', 0)
            sol_balance = current_pos.get('sol_balance', 0)
            
            if token_balance > 0:
                entry_price_last_buy = wallet_stats.get('average_entry_price', 0)
                embed.add_field(name="💼 Position Size", value=f"`{token_balance:,.0f} {TRADE_ASSET}`", inline=True)
                if entry_price_last_buy > 0:
                    embed.add_field(name="🎯 Entry Price (Last Buy)", value=f"`{entry_price_last_buy:.10f} SOL`", inline=True)
                current_price = savant_data.get('price', 0) if savant_data else performance.get('current_token_price', 0)
                if entry_price_last_buy > 0 and current_price > 0:
                    pnl_pct = ((current_price - entry_price_last_buy) / entry_price_last_buy) * 100
                    pnl_emoji = "💎" if pnl_pct >= 0 else "💔"
                    embed.add_field(name=f"{pnl_emoji} P&L (from last buy)", value=f"**{pnl_pct:+.2f}%**", inline=True)
                token_value_in_sol = token_balance * current_price if current_price > 0 else 0
                total_portfolio_value = sol_balance + token_value_in_sol
                embed.add_field(name="💰 Portfolio Value", value=f"`{total_portfolio_value:.4f} SOL`", inline=True)
            else:
                embed.add_field(name="💰 SOL Balance", value=f"`{sol_balance:.4f} SOL`", inline=True)
                embed.add_field(name="💼 Position", value="No tokens held", inline=True)
        except Exception as e:
            print(f"[!] Error processing wallet stats: {e}")
            embed.add_field(name="⚠️ Wallet Error", value=f"Error reading wallet data.", inline=False)
    
    if isinstance(channel_or_message, discord.Message):
        await channel_or_message.edit(content=None, embed=embed)
    else:
        await channel_or_message.send(embed=embed)


# --- Bot Events ---
@bot.event
async def on_ready():
    print(f"[*] Bot logged in as {bot.user}")
    global config, OWNER_ID
    config = load_config()
    if not config:
        print("[!!!] Could not load config - bot will not function properly")
        return

    OWNER_ID = config.get("owner_id")
    if not OWNER_ID: print("[!!!] WARNING: owner_id not set in config.json")
    else: print(f"[*] Owner ID set to: {OWNER_ID}")

    monitor_signals.start()
    channel_id = config.get("discord_channel_id")
    if channel_id:
        channel = bot.get_channel(int(channel_id))
        if channel: await channel.send("🚀 **Jupiter Signal Bot Started!** (P&L tracking from last buy)")
    print("[*] Signal bot running...")

# --- Bot Commands ---
@bot.command(name='status')
async def status_command(ctx):
    """Get current bot status and wallet information"""
    thinking_msg = await ctx.send("⏳ *Calculating status...*")
    latest_savant_data = read_last_savant_record()
    wallet_stats = load_wallet_stats()
    price_trend_data = get_price_trend_from_savant()
    await send_discord_embed(thinking_msg, "✅ **Current Bot Status**", 0x3498db, latest_savant_data, wallet_stats, price_trend_data, trend_failed=(price_trend_data is None))

@bot.command(name='price')
async def price_command(ctx):
    """Get current price information and trend"""
    thinking_msg = await ctx.send("⏳ *Fetching price and calculating trend...*")
    latest_savant_data = read_last_savant_record()
    price_trend_data = get_price_trend_from_savant()

    if not latest_savant_data:
        await thinking_msg.edit(content="❌ Price data not available.")
        return
    await send_discord_embed(thinking_msg, f"💰 **Current {TRADE_ASSET} Price Data**", 0x00ff00, savant_data=latest_savant_data, trend_data=price_trend_data, trend_failed=(price_trend_data is None))

@bot.command(name='wallet')
async def wallet_command(ctx):
    """Get wallet statistics"""
    thinking_msg = await ctx.send("⏳ *Loading wallet data...*")
    wallet_stats = load_wallet_stats()
    if not wallet_stats:
        await thinking_msg.edit(content="❌ Wallet data not available.")
        return
    await send_discord_embed(thinking_msg, "💼 **Wallet Statistics (Tracking from last buy)**", 0x3498db, wallet_stats=wallet_stats)

@bot.command(name='history') # NEW COMMAND
async def history_command(ctx):
    """Fetches and displays the last 10 records from the price savant database."""
    thinking_msg = await ctx.send("⏳ *Fetching last 10 records from the database...*")
    
    # Fetch the last 10 records, which will be in descending order
    recent_records = read_recent_savant_records(num_records_to_get=10)
    
    if not recent_records:
        await thinking_msg.edit(content="❌ No records found in the database.")
        return
    
    # Reverse the list so the newest record is at the bottom
    recent_records.reverse()
    
    # Format the message
    message_parts = ["**Last 10 Records from `price_savant.db`:**\n"]
    for record in recent_records:
        # Format the timestamp for readability
        try:
            ts = datetime.fromisoformat(record['timestamp'].replace('Z', '+00:00')).strftime('%H:%M:%S')
        except:
            ts = "Invalid Time"
            
        price = record.get('price', 0)
        buy_signal = record.get('buy_signal', False)
        trigger_armed = record.get('trigger_armed', False)
        
        # Add an indicator for buy signals
        signal_emoji = "🚀" if buy_signal else " "
        
        message_parts.append(f"`{ts}` {signal_emoji} Price: `{price:.10f}`, Armed: `{trigger_armed}`")

    # Join the parts and send
    full_message = "\n".join(message_parts)
    
    # Discord has a 2000 character limit per message
    if len(full_message) > 2000:
        full_message = full_message[:1990] + "\n... (truncated)"
        
    await thinking_msg.edit(content=full_message)


@bot.command(name='sell')
@is_owner()
async def sell_command(ctx):
    """OWNER ONLY - Emergency sell all tokens"""
    embed = discord.Embed(title="🚨 EMERGENCY BAILOUT", description="⚠️ This will sell ALL tokens immediately! React with ✅ to confirm or ❌ to cancel.", color=0xff6600)
    confirmation_msg = await ctx.send(embed=embed)
    await confirmation_msg.add_reaction("✅"); await confirmation_msg.add_reaction("❌")

    def check(reaction, user): return user == ctx.author and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == confirmation_msg.id

    try:
        reaction, user = await bot.wait_for('reaction_add', timeout=60.0, check=check)
        if str(reaction.emoji) == "❌":
            await confirmation_msg.edit(embed=discord.Embed(title="❌ Bailout Cancelled", color=0x888888)); return
        
        await confirmation_msg.edit(embed=discord.Embed(title="🚀 Bailout In Progress...", color=0xffa500))
        result = await execute_bailout_sell()
        
        if result['success']:
            embed = discord.Embed(title="✅ Bailout Completed!", color=0x00ff00)
            embed.add_field(name="Successful Sales", value=result.get('successfulSales', 0), inline=True)
            embed.add_field(name="Failed Sales", value=result.get('failedSales', 0), inline=True)
            embed.add_field(name="Est. SOL Received", value=f"`{result.get('totalSolReceived', 0):.6f} SOL`", inline=True)
        else:
            embed = discord.Embed(title="❌ Bailout Failed", description=f"**Error:** {result.get('error', 'Unknown')}", color=0xff0000)
        
        await confirmation_msg.edit(embed=embed)
    except asyncio.TimeoutError:
        await confirmation_msg.edit(embed=discord.Embed(title="⏰ Confirmation Timeout", color=0x888888))

@bot.command(name='help')
async def help_command(ctx):
    embed = discord.Embed(title="🤖 Bot Commands", color=0x3498db)
    embed.add_field(name="!status", value="Get current bot status and portfolio overview.", inline=False)
    embed.add_field(name="!price", value="Show current price data and indicators.", inline=False)
    embed.add_field(name="!wallet", value="Display wallet statistics and performance.", inline=False)
    embed.add_field(name="!history", value="Show the last 10 records from the price database.", inline=False) # ADDED
    if ctx.author.id == OWNER_ID:
        embed.add_field(name="!sell", value="🔴 **OWNER ONLY** - Emergency sell all tokens.", inline=False)
    await ctx.send(embed=embed)

@sell_command.error
async def sell_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("🔒 Access Denied. This command is for the bot owner only.")

# --- Background Task for Signal Monitoring ---
@tasks.loop(seconds=CHECK_INTERVAL_SECONDS)
async def monitor_signals():
    global last_traded_signal_timestamp, last_known_trigger_state
    if not config: return
    channel_id = config.get("discord_channel_id")
    if not channel_id: return
    channel = bot.get_channel(int(channel_id))
    if not channel: return

    latest_record = read_last_savant_record()
    if latest_record:
        wallet_stats = load_wallet_stats()
        current_trigger_armed = latest_record.get('trigger_armed')
        
        if current_trigger_armed is not None and current_trigger_armed != last_known_trigger_state:
            if current_trigger_armed:
                message = "🟡 **Trigger ARMED!** Watching for price to cross above Fib 0."
                await send_discord_embed(channel, message, 0xffff00, latest_record, wallet_stats)
            else:
                message = "🔴 **Trigger DISARMED.** Price crossed reset threshold."
                await send_discord_embed(channel, message, 0xff6347, latest_record, wallet_stats)
            last_known_trigger_state = current_trigger_armed

        if latest_record.get('buy_signal') and latest_record.get('timestamp') != last_traded_signal_timestamp:
            trading_enabled = False
            try:
                with open('bot_config.json', 'r') as f:
                    bot_config = json.load(f)
                    trading_enabled = bot_config['trading']['enabled']
            except: pass
            
            if trading_enabled:
                trade_result = trigger_buy_trade(latest_record.get('price', 0), latest_record)
                if trade_result:
                    alert_message = f"🚀 **BUY SIGNAL EXECUTED!**"
                    await send_discord_embed(channel, alert_message, 0x00ff00, latest_record, wallet_stats)
                else:
                    alert_message = "🚨 **BUY SIGNAL FAILED**"
                    await send_discord_embed(channel, alert_message, 0xff0000, latest_record, wallet_stats)
            else:
                alert_message = f"🚀 **BUY SIGNAL DETECTED!** (Alert-only)"
                await send_discord_embed(channel, alert_message, 0x00ff00, latest_record, wallet_stats)
            
            last_traded_signal_timestamp = latest_record.get('timestamp')

@monitor_signals.before_loop
async def before_monitor_signals():
    await bot.wait_until_ready()

# --- Run the Bot ---
if __name__ == "__main__":
    config = load_config()
    if not config: exit(1)
    
    bot_token = config.get("discord_bot_token2")
    if not bot_token:
        print("[!!!] discord_bot_token2 not found in config.json")
        exit(1)
    
    try:
        bot.run(bot_token)
    except Exception as e:
        print(f"[!!!] CRITICAL ERROR: {e}")
