# Jupiter Signal Bot - Discord Bot with Commands & Trade Triggering + GPT
import discord
from discord.ext import commands, tasks
import asyncio
import json
import os
import time
import subprocess
import openai
from datetime import datetime, timezone, timedelta
import schedule

# --- Bot Configuration ---
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
config = None
OWNER_ID = None
openai_client = None

# --- Bot Setup ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)
bot.remove_command('help')

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
    """Load wallet statistics with intelligent position tracking through transaction history"""
    try:
        if not os.path.exists(WALLET_STATS_FILE):
            return None
        
        with open(WALLET_STATS_FILE, 'r') as f:
            stats = json.load(f)
        
        # Get token acquisitions list
        acquisitions = stats.get('token_acquisitions', [])
        if not acquisitions:
            return stats
        
        # Sort acquisitions by timestamp to process chronologically
        sorted_acquisitions = sorted(acquisitions, key=lambda x: x.get('timestamp', ''))
        current_reported_balance = stats.get('current_position', {}).get('token_balance', 0)
        
        print(f"[DEBUG] Analyzing {len(sorted_acquisitions)} token acquisitions...")
        print(f"[DEBUG] Current reported balance: {current_reported_balance:,.0f}")
        
        # Find which single transaction most closely matches the current balance
        best_match_index = -1
        best_match_diff = float('inf')
        
        for i, acquisition in enumerate(sorted_acquisitions):
            tokens_received = acquisition.get('tokens_received', 0)
            diff = abs(tokens_received - current_reported_balance)
            
            print(f"[DEBUG] Transaction {i+1}: {tokens_received:,.0f} tokens, diff from current: {diff:,.0f}")
            
            if diff < best_match_diff:
                best_match_diff = diff
                best_match_index = i
        
        # If we found a close match (within 5% or 1000 tokens), this is likely the current position
        if best_match_index >= 0 and (best_match_diff < current_reported_balance * 0.05 or best_match_diff < 1000):
            current_transaction = sorted_acquisitions[best_match_index]
            
            print(f"[DEBUG] Best match: Transaction {best_match_index + 1}")
            print(f"[DEBUG] Match tokens: {current_transaction.get('tokens_received', 0):,.0f}")
            print(f"[DEBUG] Match SOL spent: {current_transaction.get('sol_spent', 0):.4f}")
            print(f"[DEBUG] This appears to be the current position after bailout")
            
            # This single transaction represents the current position
            current_position_sol_spent = current_transaction.get('sol_spent', 0)
            current_position_tokens = current_transaction.get('tokens_received', 0)
            current_avg_price = current_position_sol_spent / current_position_tokens if current_position_tokens > 0 else 0
            
            # Add current position metadata
            stats['_position_corrected'] = True
            stats['_correction_timestamp'] = datetime.now().isoformat()
            stats['_correction_reason'] = f"Matched current balance {current_reported_balance:,.0f} to transaction {best_match_index + 1}"
            stats['_current_position_start_index'] = best_match_index
            
            # Calculate stats for just this single transaction (current position)
            stats['_current_position_stats'] = {
                'sol_spent': current_position_sol_spent,
                'tokens_acquired': current_position_tokens,
                'average_price': current_avg_price,
                'transactions': 1,  # Only one transaction in current position
                'start_timestamp': current_transaction.get('timestamp'),
                'transaction_signature': current_transaction.get('transaction_signature')
            }
            
            print(f"[DEBUG] Current position stats:")
            print(f"[DEBUG] - SOL spent: {current_position_sol_spent:.4f}")
            print(f"[DEBUG] - Tokens: {current_position_tokens:,.0f}")
            print(f"[DEBUG] - Avg price: {current_avg_price:.10f}")
            print(f"[DEBUG] - Transactions: 1")
        
        else:
            # Fallback: use running balance method but look for major discrepancies
            running_balance = 0
            position_resets = []
            
            for i, acquisition in enumerate(sorted_acquisitions):
                tokens_received = acquisition.get('tokens_received', 0)
                timestamp = acquisition.get('timestamp', '')
                
                running_balance += tokens_received
                
                # Check for time gaps that might indicate bailouts
                if i > 0:
                    prev_timestamp = sorted_acquisitions[i-1].get('timestamp', '')
                    
                    try:
                        current_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        prev_time = datetime.fromisoformat(prev_timestamp.replace('Z', '+00:00'))
                        time_gap_hours = (current_time - prev_time).total_seconds() / 3600
                        
                        # If there's a significant time gap (>1 hour), might be after bailout
                        if time_gap_hours > 1:
                            print(f"[DEBUG] Time gap of {time_gap_hours:.1f} hours before transaction {i+1}")
                            position_resets.append({
                                'reset_index': i,
                                'timestamp': timestamp,
                                'reason': 'time_gap_detected',
                                'time_gap_hours': time_gap_hours
                            })
                            
                    except Exception as e:
                        print(f"[DEBUG] Could not parse timestamps: {e}")
            
            # Major discrepancy check
            if abs(running_balance - current_reported_balance) > current_reported_balance * 0.5:
                print(f"[DEBUG] Major discrepancy: calculated {running_balance:,.0f} vs reported {current_reported_balance:,.0f}")
                stats['_stale_data_warning'] = True
                stats['_stale_detected_at'] = datetime.now().isoformat()
                stats['_stale_reason'] = f"Calculated {running_balance:,.0f} vs reported {current_reported_balance:,.0f}"
        
        return stats
        
    except Exception as e:
        print(f"[!] Error loading wallet stats: {e}")
        import traceback
        traceback.print_exc()
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

def get_recent_savant_records(count=10):
    """Get the last N records from the savant file for context"""
    if not os.path.exists(PRICE_SAVANT_FILE): 
        return []
    
    try:
        with open(PRICE_SAVANT_FILE, 'r') as f:
            content = f.read()
        
        # Split by lines and find JSON objects
        lines = content.strip().split('\n')
        records = []
        
        for line in reversed(lines[-count*2:]):  # Get more lines to find JSON objects
            if line.strip():
                try:
                    record = json.loads(line)
                    records.append(record)
                    if len(records) >= count:
                        break
                except json.JSONDecodeError:
                    continue
        
        return list(reversed(records))  # Return in chronological order
    except Exception as e:
        print(f"[!] Error getting recent records: {e}")
        return []

def load_bot_config():
    """Load bot_config.json for trading settings"""
    try:
        if not os.path.exists('bot_config.json'):
            return None
        with open('bot_config.json', 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"[!] Error loading bot config: {e}")
        return None

def load_bailout_logs():
    """Load recent bailout/trade logs if available"""
    logs = {}
    
    # Load bailout logs
    try:
        if os.path.exists('bailout_sales_log.json'):
            with open('bailout_sales_log.json', 'r') as f:
                logs['bailout_history'] = json.load(f)[-5:]  # Last 5 bailouts
    except:
        pass
    
    # Load pending trades
    try:
        if os.path.exists('pending_trades.json'):
            with open('pending_trades.json', 'r') as f:
                logs['pending_trades'] = json.load(f)
    except:
        pass
    
    return logs

async def ask_gpt_about_trading_data(question, user_name="User"):
    """Use GPT to analyze trading data and answer questions"""
    global openai_client
    
    if not openai_client:
        return {
            'success': False,
            'error': 'OpenAI API key not configured. Add "openai_api_key" to config.json'
        }
    
    try:
        # Gather all available data
        latest_savant = read_last_savant_record()
        recent_records = get_recent_savant_records(10)
        wallet_stats = load_wallet_stats()
        bot_config = load_bot_config()
        logs = load_bailout_logs()
        
        # Create comprehensive data summary
        data_summary = {
            "current_time": datetime.now().isoformat(),
            "trading_asset": TRADE_ASSET,
            "current_price_data": latest_savant,
            "recent_price_history": recent_records,
            "wallet_statistics": wallet_stats,
            "bot_configuration": bot_config,
            "recent_logs": logs
        }
        
        # Create system prompt with context
        system_prompt = f"""You are an AI assistant for a Jupiter trading bot monitoring {TRADE_ASSET} on Solana. 
        
You have access to comprehensive trading data including:
- Real-time price data with technical indicators (Fibonacci levels, ATR, buy signals)
- Wallet statistics and performance metrics
- Trading configuration and settings
- Recent transaction history
- Bot operational status

Key Trading Concepts:
- "Trigger Armed" means price has dropped to entry zone and bot is watching for reversal
- "Buy Signal" occurs when price crosses above Fib 0 after being armed
- Fibonacci levels (fib_entry, wma_fib_0) are key support/resistance levels
- ATR (Average True Range) measures volatility
- P&L is calculated from initial wallet balance vs current value

Respond in a helpful, informative way about trading performance, market conditions, signals, or any bot-related questions. 
Be concise but thorough. Use emojis appropriately. If data is missing, mention what's not available.
"""

        user_prompt = f"""User Question: {question}

Current Trading Data:
{json.dumps(data_summary, indent=2, default=str)}

Please analyze this data and provide a helpful response to the user's question."""

        # Make GPT API call
        response = await asyncio.to_thread(
            openai_client.chat.completions.create,
            model="gpt-4o-mini",  # Using cheaper model for cost efficiency
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=1500,
            temperature=0.7
        )
        
        return {
            'success': True,
            'response': response.choices[0].message.content,
            'tokens_used': response.usage.total_tokens if response.usage else 0
        }
        
    except Exception as e:
        print(f"[!] Error in GPT request: {e}")
        return {
            'success': False,
            'error': f'GPT API error: {str(e)}'
        }

def trigger_buy_trade(price, savant_data):
    """Write a buy command for the Jupiter executor to process"""
    try:
        print(f"[DEBUG] Attempting to trigger buy trade...")
        print(f"[DEBUG] Price: {price}")
        print(f"[DEBUG] Looking for bot_config.json...")
        
        if not os.path.exists('bot_config.json'):
            print("[ERROR] bot_config.json file not found!")
            return False
        
        with open('bot_config.json', 'r') as f:
            bot_config = json.load(f)
        
        print(f"[DEBUG] Bot config loaded successfully")
        print(f"[DEBUG] Trading enabled: {bot_config.get('trading', {}).get('enabled', 'NOT FOUND')}")
        
        if not bot_config.get('trading', {}).get('enabled', False):
            print("[!] Trading disabled in bot_config.json")
            return False
        
        print(f"[DEBUG] Creating trade command...")
        
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

async def execute_bailout_sell():
    """Execute the bailout.js script and capture output"""
    try:
        print("[DEBUG] Starting bailout sell process...")
        
        # Check if bailout.js exists
        if not os.path.exists('bailout.js'):
            return {
                'success': False,
                'error': 'bailout.js file not found in current directory'
            }
        
        # Check if node_modules exists (dependencies installed)
        if not os.path.exists('node_modules'):
            return {
                'success': False,
                'error': 'Node.js dependencies not installed. Run: npm install @solana/web3.js node-fetch'
            }
        
        # Create a modified bailout script that runs without interactive prompts
        auto_bailout_script = '''
const BailoutSeller = require('./bailout.js');

async function autoSell() {
    try {
        const bailout = new BailoutSeller();
        
        // Get current position
        console.log('🚨 EMERGENCY BAILOUT INITIATED FROM DISCORD BOT');
        console.log('====================================');
        
        const positionData = await bailout.displayCurrentPosition();
        
        // Find tokens with balance
        const tokensWithBalance = [];
        for (const [tokenSymbol, tokenAddress] of positionData.tokens) {
            const balance = await bailout.getTokenBalance(tokenAddress);
            if (balance > 0) {
                tokensWithBalance.push({ symbol: tokenSymbol, address: tokenAddress, balance });
            }
        }
        
        if (tokensWithBalance.length === 0) {
            console.log('✅ No tokens to sell - wallet only contains SOL');
            console.log('\\n===BAILOUT_SUMMARY===');
            console.log(JSON.stringify({
                success: true,
                totalTransactions: 0,
                successfulSales: 0,
                failedSales: 0,
                totalSolReceived: 0,
                message: 'No tokens to sell'
            }));
            process.exit(0);
        }
        
        console.log(`🎯 Found ${tokensWithBalance.length} token(s) to sell:`);
        tokensWithBalance.forEach((token, index) => {
            console.log(`   ${index + 1}. ${token.symbol}: ${token.balance.toLocaleString()}`);
        });
        
        // Auto-execute with 10% slippage for reliability
        const slippageBps = 1000; // 10%
        console.log(`\\n🚀 Starting auto-bailout with ${slippageBps/100}% slippage tolerance...`);
        
        // Execute sells
        const results = [];
        let totalSolReceived = 0;
        
        for (let i = 0; i < tokensWithBalance.length; i++) {
            const token = tokensWithBalance[i];
            console.log(`\\n[${i + 1}/${tokensWithBalance.length}] Selling ${token.symbol}...`);
            
            const result = await bailout.executeSellTransaction(
                token.address, 
                token.symbol, 
                token.balance,
                slippageBps
            );
            
            results.push({
                ...result,
                tokenSymbol: token.symbol,
                tokenAddress: token.address
            });
            
            if (result.success) {
                totalSolReceived += result.expectedSol;
                console.log(`✅ Successfully sold ${token.symbol}`);
            } else {
                console.log(`❌ Failed to sell ${token.symbol}: ${result.error}`);
            }
            
            // Small delay between transactions
            if (i < tokensWithBalance.length - 1) {
                console.log('⏳ Waiting 5 seconds before next transaction...');
                await new Promise(resolve => setTimeout(resolve, 5000));
            }
        }
        
        // Final summary
        console.log('\\n🏁 === BAILOUT COMPLETE ===');
        console.log(`📊 Transactions: ${results.length}`);
        console.log(`✅ Successful: ${results.filter(r => r.success).length}`);
        console.log(`❌ Failed: ${results.filter(r => !r.success).length}`);
        console.log(`💰 Est. SOL received: ${totalSolReceived.toFixed(6)} SOL`);
        
        // Log the bailout
        await bailout.logBailoutSale(results);
        
        console.log('\\n🎉 Auto-bailout operation completed!');
        
        // Output summary as JSON for the bot to parse
        console.log('\\n===BAILOUT_SUMMARY===');
        console.log(JSON.stringify({
            success: true,
            totalTransactions: results.length,
            successfulSales: results.filter(r => r.success).length,
            failedSales: results.filter(r => !r.success).length,
            totalSolReceived: totalSolReceived,
            results: results
        }));
        
    } catch (error) {
        console.error('❌ Auto-bailout failed:', error);
        console.log('\\n===BAILOUT_SUMMARY===');
        console.log(JSON.stringify({
            success: false,
            error: error.message
        }));
    }
}

autoSell();
'''
        
        # Write the auto-bailout script
        with open('auto_bailout.js', 'w') as f:
            f.write(auto_bailout_script)
        
        # Execute the script
        print("[DEBUG] Executing auto-bailout script...")
        process = await asyncio.create_subprocess_exec(
            'node', 'auto_bailout.js',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=os.getcwd()
        )
        
        stdout, stderr = await process.communicate()
        
        # Clean up the temporary script
        try:
            os.remove('auto_bailout.js')
        except:
            pass
        
        output = stdout.decode() if stdout else ""
        error_output = stderr.decode() if stderr else ""
        
        print(f"[DEBUG] Process exit code: {process.returncode}")
        print(f"[DEBUG] STDOUT length: {len(output)} chars")
        print(f"[DEBUG] STDERR length: {len(error_output)} chars")
        
        # Parse the summary from the output
        if "===BAILOUT_SUMMARY===" in output:
            summary_start = output.find("===BAILOUT_SUMMARY===") + len("===BAILOUT_SUMMARY===")
            summary_json = output[summary_start:].strip()
            try:
                summary = json.loads(summary_json)
                summary['full_output'] = output
                summary['error_output'] = error_output
                return summary
            except json.JSONDecodeError as e:
                print(f"[ERROR] Could not parse bailout summary: {e}")
                return {
                    'success': False,
                    'error': f'Could not parse bailout results: {e}',
                    'full_output': output,
                    'error_output': error_output
                }
        else:
            return {
                'success': False,
                'error': 'No bailout summary found in output',
                'full_output': output,
                'error_output': error_output
            }
        
    except Exception as e:
        print(f"[ERROR] Exception in execute_bailout_sell: {e}")
        import traceback
        traceback.print_exc()
        return {
            'success': False,
            'error': f'Exception during bailout: {str(e)}'
        }

# --- Owner Check Decorator ---
def is_owner():
    def predicate(ctx):
        return ctx.author.id == OWNER_ID
    return commands.check(predicate)

async def send_discord_embed(channel, message, color=0x00ff00, savant_data=None, wallet_stats=None):
    """Send a Discord embed with optional price/signal data and wallet statistics"""
    embed = discord.Embed(
        title=f"🤖 {TRADE_ASSET} Jupiter Signal Bot",
        description=message,
        color=color,
        timestamp=datetime.now()
    )
    embed.set_footer(text="Jupiter Signal Bot")
    
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
                embed.add_field(name="💰 Current Price", value=f"`{price:.10f} SOL`", inline=True)
                embed.add_field(name="🎯 Trigger Armed", value=f"**`{trigger_armed}`**", inline=True)
                embed.add_field(name="🚀 Buy Signal", value=f"**`{buy_signal}`**", inline=True)
                
                if fib_entry and fib_entry > 0:
                    embed.add_field(name="📊 Fib Entry", value=f"`{fib_entry:.10f} SOL`", inline=True)
                if wma_fib_0 and wma_fib_0 > 0:
                    embed.add_field(name="📈 Fib 0", value=f"`{wma_fib_0:.10f} SOL`", inline=True)
                if atr and atr > 0:
                    embed.add_field(name="📏 ATR", value=f"`{atr:.8f}`", inline=True)
                    
        except Exception as e:
            print(f"[!] Error processing savant data: {e}")
            embed.add_field(name="⚠️ Data Error", value=f"Error reading price data: {str(e)[:100]}", inline=False)
    
    # Add wallet statistics if available
    if wallet_stats and isinstance(wallet_stats, dict):
        try:
            current_pos = wallet_stats.get('current_position', {})
            performance = wallet_stats.get('performance', {})
            
            token_balance = current_pos.get('token_balance', 0)
            sol_balance = current_pos.get('sol_balance', 0)
            
            # Check for stale data warning
            if wallet_stats.get('_stale_data_warning'):
                embed.add_field(
                    name="⚠️ Data Warning",
                    value="Wallet statistics may be outdated after bailout. Consider using `!reset_stats` command.",
                    inline=False
                )
            
            if token_balance > 0:
                embed.add_field(name="💼 Position Size", value=f"`{token_balance:,.0f} {TRADE_ASSET}`", inline=True)
                
                # Use current position stats if available (after position correction)
                current_position_stats = wallet_stats.get('_current_position_stats')
                if current_position_stats:
                    # Use corrected current position data
                    current_avg_price = current_position_stats.get('average_price', 0)
                    current_sol_spent = current_position_stats.get('sol_spent', 0)
                    current_trades = current_position_stats.get('transactions', 0)
                    
                    embed.add_field(name="🎯 Avg Entry Price", value=f"`{current_avg_price:.10f} SOL`", inline=True)
                    
                    # Calculate current position P&L
                    current_token_price = performance.get('current_token_price', 0)
                    current_price_from_savant = savant_data.get('price', 0) if savant_data else 0
                    
                    display_current_price = current_price_from_savant if current_price_from_savant > 0 else current_token_price
                    
                    if display_current_price > 0 and current_avg_price > 0:
                        price_change = ((display_current_price - current_avg_price) / current_avg_price) * 100
                        price_emoji = "📈" if price_change >= 0 else "📉"
                        price_color = "🟢" if price_change >= 0 else "🔴"
                        
                        embed.add_field(
                            name=f"{price_emoji} Price vs Entry",
                            value=f"{price_color} **{price_change:+.2f}%**\n`{display_current_price:.10f}` vs `{current_avg_price:.10f}`",
                            inline=True
                        )
                    
                    # Calculate current position value and P&L
                    if display_current_price > 0:
                        current_token_value = token_balance * display_current_price
                    else:
                        current_token_value = 0
                    
                    # Current position P&L (only for this position)
                    if current_sol_spent > 0 and current_token_value > 0:
                        current_pnl = current_token_value - current_sol_spent
                        current_pnl_pct = (current_pnl / current_sol_spent) * 100
                        current_emoji = "💎" if current_pnl >= 0 else "💔"
                        current_color = "🟢" if current_pnl >= 0 else "🔴"
                        
                        embed.add_field(
                            name=f"{current_emoji} Current Position P&L",
                            value=f"{current_color} **{current_pnl_pct:+.2f}%**\n`{current_pnl:+.4f} SOL`",
                            inline=True
                        )
                    
                    # Show current position trading stats
                    embed.add_field(
                        name="📊 Current Position Stats",
                        value=f"**{current_trades}** trades\n`{current_sol_spent:.4f}` SOL invested",
                        inline=True
                    )
                    
                    # Total portfolio value (SOL + current token value)
                    total_portfolio_value = sol_balance + current_token_value
                    embed.add_field(
                        name="💰 Portfolio Value",
                        value=f"`{total_portfolio_value:.4f} SOL`\n(SOL: `{sol_balance:.4f}` + Tokens: `{current_token_value:.4f}`)",
                        inline=True
                    )
                    
                else:
                    # Fallback to old method if no current position stats
                    avg_entry = wallet_stats.get('average_entry_price', 0)
                    if avg_entry > 0:
                        embed.add_field(name="🎯 Avg Entry Price", value=f"`{avg_entry:.10f} SOL`", inline=True)
                    
                    current_token_price = performance.get('current_token_price', 0)
                    current_price_from_savant = savant_data.get('price', 0) if savant_data else 0
                    
                    display_current_price = current_price_from_savant if current_price_from_savant > 0 else current_token_price
                    
                    # Check for extremely low token values that might indicate stale data
                    token_value_in_sol = performance.get('token_value_in_sol', 0)
                    if token_balance > 1000 and token_value_in_sol < 0.001:
                        embed.add_field(
                            name="⚠️ Possible Stale Data",
                            value=f"High token balance ({token_balance:,.0f}) but very low value ({token_value_in_sol:.6f} SOL)",
                            inline=False
                        )
                    
                    if display_current_price > 0 and avg_entry > 0:
                        price_change = ((display_current_price - avg_entry) / avg_entry) * 100
                        price_emoji = "📈" if price_change >= 0 else "📉"
                        price_color = "🟢" if price_change >= 0 else "🔴"
                        
                        embed.add_field(
                            name=f"{price_emoji} Price vs Entry",
                            value=f"{price_color} **{price_change:+.2f}%**\n`{display_current_price:.10f}` vs `{avg_entry:.10f}`",
                            inline=True
                        )
                    
                    # Calculate values and P&L
                    if display_current_price > 0:
                        token_value_in_sol = token_balance * display_current_price
                    elif 'token_value_in_sol' in performance:
                        token_value_in_sol = performance['token_value_in_sol']
                    else:
                        token_value_in_sol = 0
                    
                    initial_sol = wallet_stats.get('initial_sol_balance', 0)
                    total_current_value = sol_balance + token_value_in_sol
                    
                    if initial_sol > 0:
                        total_pnl = total_current_value - initial_sol
                        total_pnl_pct = (total_pnl / initial_sol) * 100
                        
                        pnl_emoji = "📈" if total_pnl >= 0 else "📉"
                        pnl_color = "🟢" if total_pnl >= 0 else "🔴"
                        
                        embed.add_field(
                            name=f"{pnl_emoji} Total P&L",
                            value=f"{pnl_color} **{total_pnl_pct:+.2f}%**\n`{total_pnl:+.4f} SOL`",
                            inline=True
                        )
                    
                    total_sol_spent = wallet_stats.get('total_sol_spent', 0)
                    if total_sol_spent > 0 and token_value_in_sol > 0:
                        unrealized_pnl = token_value_in_sol - total_sol_spent
                        unrealized_pnl_pct = (unrealized_pnl / total_sol_spent) * 100
                        unrealized_emoji = "💎" if unrealized_pnl >= 0 else "💔"
                        unrealized_color = "🟢" if unrealized_pnl >= 0 else "🔴"
                        
                        embed.add_field(
                            name=f"{unrealized_emoji} Token P&L",
                            value=f"{unrealized_color} **{unrealized_pnl_pct:+.2f}%**\n`{unrealized_pnl:+.4f} SOL`",
                            inline=True
                        )
                    
                    total_trades = wallet_stats.get('total_trades_executed', 0)
                    
                    if total_trades > 0:
                        embed.add_field(
                            name="📊 Trading Stats",
                            value=f"**{total_trades}** trades\n`{total_sol_spent:.4f}` SOL invested",
                            inline=True
                        )
                    
                    embed.add_field(
                        name="💰 Portfolio Value",
                        value=f"`{total_current_value:.4f} SOL`\n(SOL: `{sol_balance:.4f}` + Tokens: `{token_value_in_sol:.4f}`)",
                        inline=True
                    )
            else:
                # No tokens - show SOL balance only
                embed.add_field(name="💰 SOL Balance", value=f"`{sol_balance:.4f} SOL`", inline=True)
                embed.add_field(name="💼 Position", value="No tokens held", inline=True)
                    
        except Exception as e:
            print(f"[!] Error processing wallet stats: {e}")
            import traceback
            traceback.print_exc()
            embed.add_field(name="⚠️ Wallet Error", value=f"Error reading wallet data: {str(e)[:100]}", inline=False)
    else:
        embed.add_field(
            name="📊 Wallet Status",
            value="⏳ Waiting for Jupiter executor to generate wallet statistics...",
            inline=False
        )
    
    try:
        await channel.send(embed=embed)
    except Exception as e:
        print(f"[!] Error sending Discord message: {e}")
        
# --- Bot Events ---
@bot.event
async def on_ready():
    print(f"[*] Bot logged in as {bot.user} (ID: {bot.user.id})")
    
    # Load config
    global config, OWNER_ID, openai_client
    config = load_config()
    if not config:
        print("[!!!] Could not load config - bot will not function properly")
        return
    
    # Set owner ID from config
    OWNER_ID = config.get("owner_id")
    if not OWNER_ID:
        print("[!!!] WARNING: owner_id not set in config.json - owner commands will not work")
    else:
        print(f"[*] Owner ID set to: {OWNER_ID}")
    
    # Initialize OpenAI client if API key is provided
    openai_api_key = config.get("openai_api_key")
    if openai_api_key:
        openai_client = openai.OpenAI(api_key=openai_api_key)
        print("[*] OpenAI GPT integration enabled")
    else:
        print("[!] WARNING: openai_api_key not found in config.json - /talk command will not work")
    
    # Check trading status
    trading_enabled = False
    sol_amount = 0.1
    try:
        with open('bot_config.json', 'r') as f:
            bot_config = json.load(f)
            trading_enabled = bot_config['trading']['enabled']
            sol_amount = bot_config['trading']['sol_amount_per_trade']
    except:
        print("[!] Warning: bot_config.json not found - trading disabled")

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

    # Start monitoring task
    monitor_signals.start()
    
    # Send startup message
    channel_id = config.get("discord_channel_id")
    if channel_id:
        channel = bot.get_channel(int(channel_id))
        if channel:
            startup_msg = (f"🚀 **Jupiter Signal Bot Started!** Monitoring **{TRADE_ASSET}**\n" 
                          f"**Mode:** `{mode_text}`")
            if trading_enabled:
                startup_msg += f"\n**Trade Size:** `{sol_amount} SOL per signal`"
            if openai_client:
                startup_msg += f"\n**GPT Analysis:** Enabled - Use `/talk` to ask questions!"
            
            await send_discord_embed(channel, startup_msg, 0x888888, 
                              savant_data=None, wallet_stats=wallet_stats)
    
    print(f"\n[*] Signal bot running...")
    print(f"[*] {'Live trading active!' if trading_enabled else 'Alert-only mode - no trades will be executed'}")
    print("-" * 50)

# --- Bot Commands ---
@bot.command(name='status')
async def status_command(ctx):
    """Get current bot status and wallet information"""
    latest_savant_data = read_last_savant_record()
    wallet_stats = load_wallet_stats()
    
    # Check trading status
    trading_enabled = False
    try:
        with open('bot_config.json', 'r') as f:
            bot_config = json.load(f)
            trading_enabled = bot_config['trading']['enabled']
    except:
        pass
    
    mode_msg = "🤖 **TRADING MODE**" if trading_enabled else "🔔 **ALERT-ONLY MODE**"
    
    message_parts = [f"✅ **Current Status** - {mode_msg}"]
    
    if wallet_stats:
        performance = wallet_stats.get('performance', {})
        current_pos = wallet_stats.get('current_position', {})
        
        total_pnl_pct = performance.get('total_pnl_percent', 0)
        token_balance = current_pos.get('token_balance', 0)
        
        if token_balance > 0:
            pnl_status = f"📈 **+{total_pnl_pct:.2f}%**" if total_pnl_pct >= 0 else f"📉 **{total_pnl_pct:.2f}%**"
            message_parts.append(f"{pnl_status} portfolio performance")
            
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
    
    if not latest_savant_data:
        message_parts.append(f"⚠️ Waiting for price data from `{PRICE_SAVANT_FILE}`")
    
    message = "\n".join(message_parts)
    
    await send_discord_embed(ctx.channel, message, 0x3498db, 
                      savant_data=latest_savant_data, wallet_stats=wallet_stats)

@bot.command(name='price')
async def price_command(ctx):
    """Get current price information"""
    latest_savant_data = read_last_savant_record()
    
    if not latest_savant_data:
        embed = discord.Embed(
            title="❌ Price Data Not Available",
            description=f"No price data found in `{PRICE_SAVANT_FILE}`",
            color=0xff0000
        )
        await ctx.send(embed=embed)
        return
    
    message = f"💰 **Current {TRADE_ASSET} Price Data**"
    await send_discord_embed(ctx.channel, message, 0x00ff00, savant_data=latest_savant_data)

@bot.command(name='wallet')
async def wallet_command(ctx):
    """Get wallet statistics"""
    wallet_stats = load_wallet_stats()
    
    if not wallet_stats:
        embed = discord.Embed(
            title="❌ Wallet Data Not Available",
            description=f"No wallet statistics found in `{WALLET_STATS_FILE}`",
            color=0xff0000
        )
        await ctx.send(embed=embed)
        return
    
    message = f"💼 **Wallet Statistics**"
    await send_discord_embed(ctx.channel, message, 0x3498db, wallet_stats=wallet_stats)

@bot.command(name='talk')
async def talk_command(ctx, *, question: str = None):
    """Ask GPT to analyze your trading data and answer questions"""
    if not openai_client:
        embed = discord.Embed(
            title="🤖 GPT Not Available",
            description="OpenAI API key not configured. Add `openai_api_key` to config.json to enable GPT analysis.",
            color=0xff0000
        )
        await ctx.send(embed=embed)
        return
    
    if not question:
        embed = discord.Embed(
            title="❓ Ask a Question",
            description="Usage: `/talk What's my current P&L?`\n\nExample questions:\n• How is my trading performance?\n• Should I be worried about the current price?\n• What do the signals mean?\n• Analyze my recent trades\n• What's the market situation?",
            color=0x3498db
        )
        await ctx.send(embed=embed)
        return
    
    # Show thinking message
    thinking_embed = discord.Embed(
        title="🧠 GPT Analyzing...",
        description=f"**Question:** {question[:200]}{'...' if len(question) > 200 else ''}\n\n⏳ Analyzing your trading data and market conditions...",
        color=0xffa500
    )
    thinking_msg = await ctx.send(embed=thinking_embed)
    
    # Get GPT response
    print(f"[*] GPT query from {ctx.author.name}: {question}")
    result = await ask_gpt_about_trading_data(question, ctx.author.name)
    
    if result['success']:
        # Success - send GPT response
        embed = discord.Embed(
            title="🤖 GPT Analysis",
            description=result['response'][:4000],  # Discord embed description limit
            color=0x00ff00,
            timestamp=datetime.now()
        )
        embed.add_field(
            name="❓ Your Question", 
            value=f"*{question[:500]}{'...' if len(question) > 500 else ''}*", 
            inline=False
        )
        embed.set_footer(text=f"Tokens used: {result.get('tokens_used', 0)} • Powered by GPT-4o-mini")
        
        await thinking_msg.edit(embed=embed)
        
    else:
        # Error
        embed = discord.Embed(
            title="❌ GPT Error",
            description=f"Sorry, I couldn't analyze your question:\n\n**Error:** {result['error']}",
            color=0xff0000
        )
        await thinking_msg.edit(embed=embed)

@bot.command(name='sell')
@is_owner()
async def sell_command(ctx):
    """OWNER ONLY - Emergency sell all tokens"""
    # Confirmation embed
    embed = discord.Embed(
        title="🚨 EMERGENCY BAILOUT SELL",
        description="⚠️ **WARNING: This will sell ALL tokens immediately!**\n⚠️ **This action cannot be undone!**\n\nReact with ✅ to confirm or ❌ to cancel.",
        color=0xff6600,
        timestamp=datetime.now()
    )
    embed.add_field(name="🎯 Action", value="Sell all token positions to SOL", inline=False)
    embed.add_field(name="🔧 Slippage", value="10% (aggressive for reliability)", inline=True)
    embed.add_field(name="⏰ Timeout", value="60 seconds to confirm", inline=True)
    embed.set_footer(text="Owner-only command")
    
    confirmation_msg = await ctx.send(embed=embed)
    await confirmation_msg.add_reaction("✅")
    await confirmation_msg.add_reaction("❌")
    
    def check(reaction, user):
        return (user == ctx.author and 
                str(reaction.emoji) in ["✅", "❌"] and 
                reaction.message.id == confirmation_msg.id)
    
    try:
        reaction, user = await bot.wait_for('reaction_add', timeout=60.0, check=check)
        
        if str(reaction.emoji) == "❌":
            embed = discord.Embed(
                title="❌ Bailout Cancelled",
                description="Emergency sell operation was cancelled by owner.",
                color=0x888888
            )
            await confirmation_msg.edit(embed=embed)
            return
        
        elif str(reaction.emoji) == "✅":
            # Execute the bailout
            embed = discord.Embed(
                title="🚀 Bailout In Progress...",
                description="⏳ Executing emergency sell... This may take several minutes.\n🔄 Please wait for completion message.",
                color=0xffa500
            )
            await confirmation_msg.edit(embed=embed)
            
            # Execute the bailout
            print(f"[*] Owner {ctx.author.name}#{ctx.author.discriminator} requested emergency bailout sell")
            result = await execute_bailout_sell()
            
            if result['success']:
                # Success embed
                embed = discord.Embed(
                    title="✅ Bailout Completed Successfully!",
                    description="🎉 Emergency sell operation completed successfully",
                    color=0x00ff00,
                    timestamp=datetime.now()
                )
                
                embed.add_field(
                    name="📊 Transaction Summary",
                    value=(f"**Total Transactions:** {result.get('totalTransactions', 0)}\n"
                          f"**Successful:** {result.get('successfulSales', 0)}\n"
                          f"**Failed:** {result.get('failedSales', 0)}"),
                    inline=True
                )
                
                embed.add_field(
                    name="💰 Est. SOL Received",
                    value=f"`{result.get('totalSolReceived', 0):.6f} SOL`",
                    inline=True
                )
                
                # Add individual results if available
                if 'results' in result and result['results']:
                    successful_sales = [r for r in result['results'] if r.get('success')]
                    if successful_sales:
                        sales_summary = []
                        for sale in successful_sales[:5]:  # Show first 5
                            token_symbol = sale.get('tokenSymbol', 'Unknown')
                            expected_sol = sale.get('expectedSol', 0)
                            sales_summary.append(f"• {token_symbol}: `{expected_sol:.6f} SOL`")
                        
                        embed.add_field(
                            name="💎 Successful Sales",
                            value="\n".join(sales_summary[:5]),
                            inline=False
                        )
                
                embed.add_field(
                    name="📝 Logs",
                    value="Check `bailout_sales_log.json` for detailed transaction records",
                    inline=False
                )
                
            else:
                # Failure embed
                embed = discord.Embed(
                    title="❌ Bailout Failed",
                    description="🚨 Emergency sell operation encountered errors",
                    color=0xff0000,
                    timestamp=datetime.now()
                )
                
                error_msg = result.get('error', 'Unknown error occurred')
                embed.add_field(name="🐛 Error Details", value=f"```{error_msg[:1000]}```", inline=False)
                
                if result.get('error_output'):
                    embed.add_field(
                        name="🔍 Debug Info", 
                        value=f"```{result.get('error_output')[:500]}```", 
                        inline=False
                    )
            
            await confirmation_msg.edit(embed=embed)
            
    except asyncio.TimeoutError:
        embed = discord.Embed(
            title="⏰ Confirmation Timeout",
            description="Emergency sell confirmation timed out after 60 seconds.",
            color=0x888888
        )
        await confirmation_msg.edit(embed=embed)

@bot.command(name='help')
async def help_command(ctx):
    """Show available commands"""
    embed = discord.Embed(
        title="🤖 Jupiter Signal Bot Commands",
        description="Available commands for the trading bot",
        color=0x3498db
    )
    
    # Regular commands for everyone
    commands_info = [
        ("!status", "Get current bot status and full portfolio overview"),
        ("!price", "Show current price data and technical indicators"),
        ("!wallet", "Display wallet statistics and performance"),
        ("!talk <question>", "🧠 Ask GPT to analyze your trading data"),
        ("!help", "Show this help message")
    ]
    
    # Add owner-only commands if user is owner
    if ctx.author.id == OWNER_ID:
        commands_info.append(("!sell", "🔴 **OWNER ONLY** - Emergency sell all tokens"))
    
    for cmd, desc in commands_info:
        embed.add_field(name=cmd, value=desc, inline=False)
    
    # Add note about GPT
    if openai_client:
        embed.add_field(
            name="💡 GPT Examples",
            value="• `!talk How is my portfolio performing?`\n• `!talk Should I be worried about current price?`\n• `!talk What do these signals mean?`\n• `!talk Analyze my recent trades`",
            inline=False
        )
    else:
        embed.add_field(
            name="⚠️ GPT Disabled",
            value="Add `openai_api_key` to config.json to enable AI analysis",
            inline=False
        )
    
    await ctx.send(embed=embed)

# Handle errors for owner-only commands
@sell_command.error
async def sell_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        embed = discord.Embed(
            title="🔒 Access Denied",
            description="This command can only be used by the bot owner.",
            color=0xff0000
        )
        await ctx.send(embed=embed)

@talk_command.error
async def talk_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        embed = discord.Embed(
            title="❓ Missing Question",
            description="Please provide a question!\n\nUsage: `!talk How is my trading going?`",
            color=0xff6600
        )
        await ctx.send(embed=embed)

# --- Background Task for Signal Monitoring ---
@tasks.loop(seconds=CHECK_INTERVAL_SECONDS)
async def monitor_signals():
    global last_traded_signal_timestamp, last_known_trigger_state
    
    if not config:
        return
        
    channel_id = config.get("discord_channel_id")
    if not channel_id:
        return
        
    channel = bot.get_channel(int(channel_id))
    if not channel:
        return

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
                await send_discord_embed(channel, message, 0xffff00, 
                                 savant_data=latest_record, wallet_stats=wallet_stats)
                print("[🟡] Trigger ARMED - monitoring for buy signal")
            else:
                message = "🔴 **Trigger DISARMED.** Price crossed reset threshold."
                await send_discord_embed(channel, message, 0xff6347, 
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
            
            # Check if trading is enabled
            trading_enabled = False
            try:
                with open('bot_config.json', 'r') as f:
                    bot_config = json.load(f)
                    trading_enabled = bot_config['trading']['enabled']
            except:
                pass
            
            if trading_enabled:
                print(f"[DEBUG] Trading is enabled - attempting to trigger trade...")
                trade_result = trigger_buy_trade(latest_record.get('price', 0), latest_record)
                print(f"[DEBUG] Trade trigger result: {trade_result}")
                
                if trade_result:
                    alert_message = (f"🚀 **BUY SIGNAL EXECUTED!**\n"
                                f"Price: **{latest_record.get('price', 0):.10f} SOL**\n"
                                f"Trade command sent to Jupiter executor\n"
                                f"🤖 *Live trading mode active*")
                    await send_discord_embed(channel, alert_message, 0x00ff00, 
                                     savant_data=latest_record, wallet_stats=wallet_stats)
                else:
                    alert_message = "🚨 **BUY SIGNAL FAILED** - Could not write trade command"
                    await send_discord_embed(channel, alert_message, 0xff0000, 
                                     savant_data=latest_record, wallet_stats=wallet_stats)
            else:
                print(f"[DEBUG] Trading is disabled - sending alert only...")
                alert_message = (f"🚀 **BUY SIGNAL DETECTED!**\n"
                            f"Price: **{latest_record.get('price', 0):.10f} SOL**\n"
                            f"⚠️ *Alert-only mode - no trade executed*")
                await send_discord_embed(channel, alert_message, 0x00ff00, 
                                 savant_data=latest_record, wallet_stats=wallet_stats)
            
            last_traded_signal_timestamp = latest_record.get('timestamp')
            print(f"[DEBUG] Updated last_traded_signal_timestamp to: {last_traded_signal_timestamp}")

@monitor_signals.before_loop
async def before_monitor_signals():
    await bot.wait_until_ready()

# --- Run the Bot ---
if __name__ == "__main__":
    config = load_config()
    if not config:
        print("[!!!] Cannot start bot without config.json")
        exit(1)
    
    bot_token = config.get("discord_bot_token2")
    if not bot_token:
        print("[!!!] discord_bot_token2 not found in config.json")
        exit(1)
    
    try:
        bot.run(bot_token)
    except KeyboardInterrupt:
        print("\n[*] Bot stopped by user.")
    except Exception as e:
        print(f"[!!!] CRITICAL ERROR: {e}")