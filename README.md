# Trading Bot Dashboard

A real-time web application for monitoring and controlling a Binary.com trading bot with TP/SL strategy.

## Features

### 🎯 Real-Time Dashboard
- **Live Balance Tracking** - Monitor your account balance in real-time
- **Open Positions** - View all open trades with entry price, TP, and SL levels
- **Performance Metrics** - Track win rate, profit factor, total trades, and streaks
- **Console Output** - Live log stream showing signals, trades, and system events

### ⚙️ Bot Controls
- **Start/Stop** - Control bot execution with one click
- **Configuration Panel** - Modify all trading parameters through the UI
- **Light/Dark Mode** - Toggle between themes with persistent preference

### 📊 Strategy & Optimization
- **MACD + Bollinger Bands** - Technical indicator-based signal generation
- **ML Optimization** - Machine learning scoring to find optimal parameters
- **TP/SL Management** - Percentage-based take profit and stop loss
- **Martingale (Optional)** - Money management with martingale support

## Quick Start

1. **Access the Dashboard** - The app runs automatically on port 5000
2. **Configure Settings** - Click the "Config" button to set your API token and parameters
3. **Start Trading** - Click "Start" to run optimization and begin live trading
4. **Monitor Performance** - Watch real-time updates on the dashboard

## Configuration

### Basic Settings
- **API Token** - Your Binary.com API token
- **Symbol** - Trading pair (default: R_100)
- **Timeframe** - Candle timeframe in seconds
- **Historical Data Days** - Days of data for optimization

### Risk Management
- **Multiplier** - Contract multiplier (e.g., 100)
- **Take Profit %** - TP percentage above/below entry
- **Stop Loss %** - SL percentage above/below entry
- **Trade Stake %** - Percentage of balance per trade
- **Martingale** - Optional martingale with multiplier

### Indicator Ranges
Configure optimization ranges for:
- MACD Fast, Slow, and Signal periods
- Bollinger Bands Window and Standard Deviation

## How It Works

1. **Optimization** - On startup, the bot analyzes historical data using various indicator combinations
2. **ML Scoring** - A machine learning model scores each strategy based on profit, win rate, and risk
3. **Live Trading** - The best strategy is selected and used for live trading
4. **Signal Detection** - Real-time tick data is analyzed for entry signals
5. **Trade Management** - Positions are monitored for TP/SL hits or counter-signals

## Technology Stack

- **Backend**: Flask + Flask-SocketIO
- **Frontend**: Bootstrap 5 + Vanilla JavaScript
- **Data**: pandas, numpy for processing
- **Indicators**: ta (Technical Analysis library)
- **API**: Binary.com/Deriv WebSocket API

## Important Notes

⚠️ **Risk Warning**: Trading carries significant risk. Always test with a demo account first.

🔑 **API Token**: You need a valid Binary.com API token to use this bot.

⏱️ **Optimization Time**: Initial optimization may take a few minutes depending on data range.

🛑 **Configuration Changes**: Stop the bot before modifying configuration.

## Support

For issues or questions about Binary.com API, visit: https://developers.deriv.com/

## License

This is an educational trading bot. Use at your own risk.
