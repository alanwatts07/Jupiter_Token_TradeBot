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