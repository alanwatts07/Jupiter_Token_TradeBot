# 🤖 Solana Jupiter Trading Bot

A sophisticated automated trading bot for Solana tokens using technical analysis signals and Jupiter DEX integration. The bot monitors Fibonacci retracement levels, ATR-based entry zones, and executes trades automatically while providing comprehensive Discord notifications.

## 🌟 Features

### 📊 Advanced Signal Detection
- **Fibonacci Retracement Analysis**: Monitors WMA Fib 0 and Fib 50 levels
- **ATR-Based Entry Zones**: Dynamic entry calculations based on Average True Range
- **Smart Trigger System**: Arms/disarms based on price action relative to reset thresholds
- **Real-time Signal Processing**: 5-second interval monitoring with live updates

### 🚀 Automated Trading
- **Jupiter DEX Integration**: Seamless token swaps using Jupiter aggregator
- **Trade Confirmation System**: Waits for blockchain confirmation before next trade
- **Configurable Trade Sizes**: Set SOL amount per trade via config
- **Cooldown Protection**: Prevents rapid-fire trades with configurable delays
- **Slippage Management**: Customizable slippage tolerance

### 💰 Comprehensive Wallet Analytics
- **Historical Transaction Analysis**: Scans wallet history to build complete position picture
- **Real-time Portfolio Tracking**: Live SOL and token balance monitoring
- **Performance Metrics**: Total P&L, unrealized gains, price vs entry calculations
- **Trade Statistics**: Complete acquisition history with entry prices and dates
- **Smart Position Sizing**: Tracks average entry price across multiple purchases

### 🔔 Rich Discord Notifications
- **Real-time Signal Alerts**: Instant notifications for trigger states and buy signals
- **Portfolio Status Updates**: Periodic reports with current performance metrics
- **Trade Execution Confirmations**: Detailed trade results with transaction signatures
- **Interactive Embeds**: Rich Discord embeds with comprehensive market data
- **Error Handling**: Clear error messages and status indicators

## 🏗️ Architecture

The bot consists of four main components:

1. **Jupiter Tracker (Python)** - `jupiter_tracker.py`
   - Collects real-time price data from multiple sources
   - Processes and validates market data feeds

2. **Dashboard (Python)** - `app_anon.py`
   - Processes price data and calculates technical indicators
   - Generates trading signals based on Fibonacci levels
   - Provides live web dashboard at http://localhost:8051

3. **Signal Bot (Python)** - `trade_bot_anon.py`
   - Monitors signals from the dashboard
   - Sends Discord notifications
   - Triggers trade commands for execution

4. **Jupiter Executor (Node.js)** - `jupiter-executor.js`
   - Executes actual trades on Jupiter DEX
   - Manages wallet statistics and position tracking
   - Provides real-time portfolio analytics

## 🚦 Quick Start

### Prerequisites
- Node.js 16+ and npm
- Python 3.8+
- Solana wallet keypair
- Discord bot token
- tmux (optional but recommended)

### Installation

1. **Clone the repository**
```bash
git clone https://github.com/yourusername/jupiter-trading-bot
cd jupiter-trading-bot
```

2. **Install Python dependencies**
```bash
pip install dash pandas plotly numpy requests schedule
```

3. **Install Node.js dependencies**
```bash
npm install
```

4. **Configure the bot**

Create `config.json`:
```json
{
  "discord_bot_token": "your_discord_bot_token",
  "discord_channel_id": "your_discord_channel_id"
}
```

Create `bot_config.json`:
```json
{
  "trading": {
    "sol_amount_per_trade": 0.05,
    "slippage_bps": 100,
    "priority_fee_lamports": 100000,
    "cooldown_seconds": 30,
    "enabled": true
  },
  "wallet": {
    "private_key_path": "./wallet-keypair.json"
  },
  "tokens": {
    "ANON": "FhvBDEr46meW6NHWHNeShDzvbXWabNzyT6uGinEgBAGS"
  },
  "jupiter": {
    "api_url": "https://quote-api.jup.ag/v6"
  }
}
```

5. **Add your wallet keypair**
```bash
# Export your wallet private key as JSON array format
# Save as wallet-keypair.json
```

### Running the Bot

#### Option 1: Automated Management (Recommended)

Use the included tmux manager for easy startup and monitoring:

```bash
# Start the entire system
python3 jupiter_main.py

# Stop all processes
python3 jupiter_main.py stop
```

The manager will:
- ✅ Start all 4 components in the correct order
- ✅ Monitor process health and auto-restart failures
- ✅ Skip already running processes (safe restart)
- ✅ Provide detailed status information

**View individual components:**
```bash
tmux attach -t jupiter_tracker    # Price data collection
tmux attach -t dashboard_anon     # Dashboard & signals
tmux attach -t signal_bot_anon    # Discord notifications
tmux attach -t jupiter_executor   # Trade execution

# Detach from tmux session: Ctrl+B then D
# List all sessions: tmux list-sessions
```

#### Option 2: Manual Startup

Start components individually in separate terminals:

```bash
# Terminal 1 - Price Tracking
python3 jupiter_tracker.py

# Terminal 2 - Dashboard & Signal Generation
python3 app_anon.py

# Terminal 3 - Discord Bot & Trade Triggering
python3 trade_bot_anon.py

# Terminal 4 - Jupiter Trade Execution
node jupiter-executor.js
```

## 📊 Configuration Options

### Trading Settings
- `sol_amount_per_trade`: SOL amount per buy signal (default: 0.05)
- `slippage_bps`: Maximum slippage in basis points (default: 100 = 1%)
- `cooldown_seconds`: Minimum time between trades (default: 30)
- `enabled`: Master trading toggle (set to false for alert-only mode)

### Technical Analysis
- `atr_multiplier`: ATR multiplier for entry zone calculation (default: 1.5)
- `reset_pct_above_fib_0`: Reset threshold above Fib 0 level (default: 0.5%)
- `fib_entry_floor_pct`: Minimum entry level as % of Fib 0 (default: 85%)

### Discord Notifications
- `STATUS_UPDATE_MINUTES`: Frequency of status updates (default: 15 min)
- `MESSAGES_TO_KEEP`: Number of status messages to retain (default: 10)
- `CLEANUP_INTERVAL_HOURS`: Cleanup frequency (default: 6 hours)

## 📈 Trading Logic

### Signal Generation
1. **Data Collection**: 5-minute OHLC candles with Fibonacci level calculations
2. **Trigger Arming**: Price drops below ATR-based entry zone
3. **Signal Firing**: Price crosses back above Fib 0 level while trigger is armed
4. **Reset Mechanism**: Price moves significantly above Fib 0 to prevent false signals

### Trade Execution
1. **Signal Detection**: Bot detects buy signal from price savant data
2. **Trade Command**: Creates pending trade command with current market data
3. **Jupiter Quote**: Fetches real-time quote from Jupiter aggregator
4. **Transaction Signing**: Signs and submits transaction to Solana network
5. **Confirmation Wait**: Monitors blockchain for transaction confirmation
6. **Statistics Update**: Updates wallet analytics and position tracking

## 📁 File Structure

```
jupiter-trading-bot/
├── jupiter_main.py              # 🚀 System manager (start here!)
├── jupiter_tracker.py           # Price data collection
├── app_anon.py                  # Dashboard and signal generation
├── trade_bot_anon.py            # Discord notifications and trade triggering
├── jupiter-executor.js          # Trade execution and wallet management
├── package.json                 # Node.js dependencies
├── config.json                  # Discord configuration
├── bot_config.json              # Trading configuration
├── wallet-keypair.json          # Solana wallet private key
├── token_price_data_v3.json     # Raw price data
├── price_savant_anon.json       # Enhanced price data with signals
├── wallet_statistics.json       # Comprehensive wallet analytics
├── jupiter_trade_log.json       # Trade execution history
├── pending_trades.json          # Queued trades for execution
└── README.md                    # This file
```

## 🛡️ Safety Features

### Risk Management
- **Cooldown System**: Prevents rapid successive trades
- **Confirmation Required**: All trades must be blockchain-confirmed
- **Configurable Limits**: Set maximum trade sizes and frequency
- **Alert-Only Mode**: Test signals without executing trades

### Error Handling
- **Rate Limit Management**: Handles API rate limits gracefully
- **Transaction Failures**: Comprehensive error logging and recovery
- **Network Issues**: Automatic retry mechanisms with backoff
- **Data Validation**: Input sanitization and format verification

### Monitoring
- **Real-time Alerts**: Immediate Discord notifications for all events
- **Trade Logging**: Complete audit trail of all transactions
- **Performance Tracking**: Detailed P&L and performance analytics
- **Health Checks**: Regular status updates and system monitoring
- **Process Management**: Automatic restart of failed components

## 📊 Analytics Dashboard

Access the live dashboard at `http://localhost:8051` to view:
- Real-time candlestick charts with Fibonacci levels
- Current trigger states and buy zones
- Portfolio performance metrics
- Trade history and entry points

## 🔧 System Management

### Using the Jupiter Manager

```bash
# Start everything (recommended)
python3 jupiter_main.py

# Stop all processes
python3 jupiter_main.py stop

# View system status
python3 jupiter_main.py
# Then press Ctrl+C to exit manager (processes keep running)
```

### Manual Process Control

```bash
# Check what's running
tmux list-sessions

# Attach to specific components
tmux attach -t jupiter_tracker    # Data collection
tmux attach -t dashboard_anon     # Charts & signals  
tmux attach -t signal_bot_anon    # Discord bot
tmux attach -t jupiter_executor   # Trade execution

# Kill individual sessions
tmux kill-session -t session_name

# Kill all Jupiter sessions
tmux kill-session -t jupiter_tracker
tmux kill-session -t dashboard_anon
tmux kill-session -t signal_bot_anon
tmux kill-session -t jupiter_executor
```

## 🔧 Troubleshooting

### Common Issues

**System won't start:**
- Check all required files are present
- Verify `config.json` and `bot_config.json` exist
- Ensure Node.js and Python are installed
- Run `npm install` to install Node dependencies

**Bot not executing trades:**
- Check `bot_config.json` has `"enabled": true`
- Verify wallet has sufficient SOL balance
- Ensure Jupiter executor is running (`tmux attach -t jupiter_executor`)

**Discord notifications not working:**
- Verify Discord bot token and channel ID in `config.json`
- Check bot permissions in Discord server
- Review signal bot logs (`tmux attach -t signal_bot_anon`)

**Price data not updating:**
- Confirm jupiter_tracker.py is running (`tmux attach -t jupiter_tracker`)
- Check internet connection and API endpoints
- Verify file permissions for data files

### Debug Mode
Enable debug logging by setting environment variables:
```bash
export DEBUG=true
export VERBOSE_LOGGING=true
python3 jupiter_main.py
```

### Process Recovery
The system manager automatically restarts failed processes, but you can manually restart components:

```bash
# Restart a single component
tmux kill-session -t jupiter_executor
# The manager will automatically restart it

# Or manually restart
node jupiter-executor.js
```

## 🤝 Contributing

Contributions are welcome! Please feel free to submit pull requests or open issues for bugs and feature requests.

### Development Setup
1. Fork the repository
2. Create feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open pull request

## ⚠️ Disclaimer

This trading bot is for educational and research purposes. Cryptocurrency trading involves substantial risk of loss. Never invest more than you can afford to lose. The authors are not responsible for any financial losses incurred through the use of this software.

**Always test with small amounts first and use alert-only mode to verify signals before enabling live trading.**

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- Jupiter Protocol for DEX aggregation
- Solana Foundation for blockchain infrastructure
- Discord API for notification system
- Community contributors and testers

---

**⭐ If this project helped you, please consider giving it a star!**

**🚀 Quick Start: `python3 main.py`**