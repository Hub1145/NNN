import json
import time
import logging
from datetime import datetime, timedelta, timezone
import pandas as pd
import numpy as np
import websocket
import ta
import threading
from collections import deque
import os # Added for file path operations

OPTIMIZED_PARAMS_DB_FILE = 'optimized_params_db.json'
TRADE_LOG_FILE = 'trade_log.txt' # New: Define trade log file
BACKTEST_LOG_FILE = 'backtest_log.txt' # New: Define backtest log file

class TradingBotEngine:
    def __init__(self, config_path, emit_callback):
        self.config_path = config_path
        self.emit = emit_callback
        
        self.console_logs = deque(maxlen=500) # Initialize console_logs first
        self.config = self._load_config() # Then load config, which might use self.log

        self.ws = None
        self.ws_thread = None
        self.is_running = False
        self.stop_event = threading.Event() # Added a stop event
        
        self.best_params = {}
        self.params_lock = threading.Lock()
        self.current_balance = 0.0
        self.open_trades = []
        self.historical_data_live = {'high': [], 'low': [], 'close': [], 'open': [], 'datetime': []}
        self.is_bot_initialized = threading.Event()
        self.last_stake_amount = 0.0
        self.last_trade_was_loss = False
        self.ml_strategy_results = {} # New attribute to store ML strategy results
        
        self.session_stats = {
            'trades_won': 0,
            'trades_lost': 0,
            'total_profit': 0.0,
            'total_loss': 0.0,
            'current_win_streak': 0,
            'current_loss_streak': 0,
            'max_win_streak': 0,
            'max_loss_streak': 0,
            'session_start_balance': 0.0,
            'balance_history': []
        }
        self.optimization_scheduler_thread = None
        self.last_optimization_date = None # To track when optimization last ran for the current context
        
    def log(self, message, level='info', to_file=False, filename=None): # Added filename parameter
        timestamp = datetime.now().strftime('%H:%M:%S')
        log_entry = {'timestamp': timestamp, 'message': message, 'level': level}
        self.console_logs.append(log_entry)
        self.emit('console_log', log_entry)
        
        if level == 'info':
            logging.info(message)
        elif level == 'warning':
            logging.warning(message)
        elif level == 'error':
            logging.error(message)

        if to_file and filename: # New: Write to specified file if to_file is True and filename is provided
            try:
                with open(filename, 'a') as f:
                    f.write(f"[{timestamp}] {level.upper()}: {message}\n")
            except Exception as e:
                logging.error(f"Error writing to log file {filename}: {e}")
    
    def update_stats(self, profit):
        if profit > 0:
            self.session_stats['trades_won'] += 1
            self.session_stats['total_profit'] += profit
            self.session_stats['current_win_streak'] += 1
            self.session_stats['current_loss_streak'] = 0
            self.session_stats['max_win_streak'] = max(
                self.session_stats['max_win_streak'], 
                self.session_stats['current_win_streak']
            )
        elif profit < 0:
            self.session_stats['trades_lost'] += 1
            self.session_stats['total_loss'] += abs(profit)
            self.session_stats['current_loss_streak'] += 1
            self.session_stats['current_win_streak'] = 0
            self.session_stats['max_loss_streak'] = max(
                self.session_stats['max_loss_streak'],
                self.session_stats['current_loss_streak']
            )
        
        self.session_stats['balance_history'].append({
            'timestamp': datetime.now().isoformat(),
            'balance': self.current_balance
        })
        
        self.emit('stats_update', self.get_stats())
    
    def get_stats(self):
        total_trades = self.session_stats['trades_won'] + self.session_stats['trades_lost']
        win_rate = (self.session_stats['trades_won'] / total_trades * 100) if total_trades > 0 else 0
        profit_factor = (self.session_stats['total_profit'] / self.session_stats['total_loss']) if self.session_stats['total_loss'] > 0 else self.session_stats['total_profit']
        net_profit = self.current_balance - self.session_stats['session_start_balance'] if self.session_stats['session_start_balance'] > 0 else 0
        
        return {
            'total_trades': total_trades,
            'trades_won': self.session_stats['trades_won'],
            'trades_lost': self.session_stats['trades_lost'],
            'win_rate': round(win_rate, 2),
            'profit_factor': round(profit_factor, 2),
            'max_win_streak': self.session_stats['max_win_streak'],
            'max_loss_streak': self.session_stats['max_loss_streak'],
            'net_profit': round(net_profit, 2),
            'total_profit': round(self.session_stats['total_profit'], 2),
            'total_loss': round(self.session_stats['total_loss'], 2)
        }
    
    def start(self):
        if self.is_running:
            self.log('Bot is already running', 'warning')
            return
        
        self.is_running = True
        self.session_stats['session_start_balance'] = 0.0
        self.log('Bot starting...', 'info')
        
        # Check if optimized parameters exist for today and current configuration context
        if self._load_optimized_params():
            self.log(f"Loaded optimized parameters for context '{self._get_config_context_key()}' for today. Starting live trading.", 'info')
            self.ws_thread = threading.Thread(target=self.connect, daemon=True)
            self.ws_thread.start()
        else:
            self.log(f"No valid optimized parameters found for context '{self._get_config_context_key()}' for today. Running optimization and then connecting.", 'info')
            self.ws_thread = threading.Thread(target=self._run_optimization_and_connect, daemon=True)
            self.ws_thread.start()
        
        # Start the daily optimization scheduler if it's not already running
        if not self.optimization_scheduler_thread or not self.optimization_scheduler_thread.is_alive():
            self.optimization_scheduler_thread = threading.Thread(target=self._daily_optimization_scheduler, daemon=True)
            self.optimization_scheduler_thread.start()
    
    def stop(self):
        if not self.is_running:
            self.log('Bot is not running', 'warning')
            return
        
        self.is_running = False
        self.log('Bot stopping...', 'info')
        
        self.stop_event.set() # Signal all threads to stop
        if self.ws:
            self.ws.close()
        if self.optimization_scheduler_thread and self.optimization_scheduler_thread.is_alive():
            self.optimization_scheduler_thread.join(timeout=5) # Give it a chance to clean up
        
        self.emit('bot_status', {'running': False})
    
    def _run_optimization_and_connect(self):
        self.log('Running initial optimization...', 'info')
        self.stop_event.clear() # Clear the stop event before starting
        self.run_daily_optimization()
        
        if self.is_running and not self.stop_event.is_set() and self.best_params:
            self.log('Optimization successful. Starting live trading connection...', 'info')
            self.connect()
        else:
            self.log('Optimization failed or aborted. Live trading will not start.', 'warning')
            self.is_running = False # Ensure bot status is stopped if optimization fails
            self.emit('bot_status', {'running': False})

    def _daily_optimization_scheduler(self):
        """Schedules daily optimization at 00:00 UTC."""
        self.log("Daily optimization scheduler started.", 'info')
        while not self.stop_event.is_set():
            now_utc = datetime.now(timezone.utc)
            # Schedule for next 00:00 UTC
            next_midnight_utc = (now_utc + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            time_to_wait = (next_midnight_utc - now_utc).total_seconds()

            self.log(f"Next optimization check in {time_to_wait:.0f} seconds (at {next_midnight_utc.isoformat()}).", 'info')
            self.stop_event.wait(time_to_wait) # Wait until next midnight or until stop event is set

            if self.stop_event.is_set():
                break

            self.log("Checking for daily optimization...", 'info')
            if not self._load_optimized_params(): # Attempt to load for current day and context
                self.log("No valid optimized parameters for today, initiating optimization.", 'info')
                self.run_daily_optimization()
            else:
                self.log("Optimized parameters already available for today.", 'info')
        self.log("Daily optimization scheduler stopped.", 'info')

    def run_daily_optimization(self):
        try:
            self.log("="*50 + f"\nBACKGROUND OPTIMIZATION for past {self.config['optimization_data_days']} days STARTED for {self.config['active_strategy']} strategy, symbol {self.config['symbol']}, granularity {self.config['granularity']}...\n" + "="*50, 'info')
            fetcher = DerivHistoricalDataFetcher(
                symbol=self.config['symbol'],
                url=self.config['ws_url']
            )
            
            df_hist = fetcher.fetch_data_for_days(
                self.config['optimization_data_days'],
                self.config['granularity']
            )
            
            if df_hist.empty:
                self.log('Could not fetch data for optimization', 'error')
                return
            
            self.log(f"Successfully fetched {len(df_hist)} candles. Starting optimization runs...", 'info')
            
            opt_results = []
            base_df = df_hist[['open', 'high', 'low', 'close']].copy()
    
            if self.config['active_strategy'] == "Mean Reversion":
                strategy_ranges = self.config['mean_reversion_ranges']
                total_runs = 0
                for bb_w in range(strategy_ranges['bb_window_min'], strategy_ranges['bb_window_max'] + 1, strategy_ranges['bb_window_step']):
                    for bb_s in np.arange(strategy_ranges['bb_std_min'], strategy_ranges['bb_std_max'] + 0.1, strategy_ranges['bb_std_step']):
                        for macd_f in range(strategy_ranges['macd_fast_min'], strategy_ranges['macd_fast_max'] + 1, strategy_ranges['macd_fast_step']):
                            for macd_s in range(strategy_ranges['macd_slow_min'], strategy_ranges['macd_slow_max'] + 1, strategy_ranges['macd_slow_step']):
                                if macd_f >= macd_s:
                                    continue
                                for macd_sig in range(strategy_ranges['macd_signal_min'], strategy_ranges['macd_signal_max'] + 1, strategy_ranges['macd_signal_step']):
                                    total_runs += 1
    
                current_run = 0
                for bb_w in range(strategy_ranges['bb_window_min'], strategy_ranges['bb_window_max'] + 1, strategy_ranges['bb_window_step']):
                    for bb_s in np.arange(strategy_ranges['bb_std_min'], strategy_ranges['bb_std_max'] + 0.1, strategy_ranges['bb_std_step']):
                        for macd_f in range(strategy_ranges['macd_fast_min'], strategy_ranges['macd_fast_max'] + 1, strategy_ranges['macd_fast_step']):
                            for macd_s in range(strategy_ranges['macd_slow_min'], strategy_ranges['macd_slow_max'] + 1, strategy_ranges['macd_slow_step']):
                                if macd_f >= macd_s:
                                    continue
                                for macd_sig in range(strategy_ranges['macd_signal_min'], strategy_ranges['macd_signal_max'] + 1, strategy_ranges['macd_signal_step']):
                                    if self.stop_event.is_set():
                                        self.log('Optimization aborted by stop signal.', 'warning')
                                        return
                                    current_run += 1
                                    df_processed = base_df.copy()
                                    df_processed = self.calculate_indicators_mean_reversion(df_processed, macd_f, macd_s, macd_sig, bb_w, bb_s)
                                    df_processed.dropna(inplace=True)
                                    df_signals = self.generate_signals_mean_reversion(df_processed)
                                    results = self.backtest_strategy(df_signals)
                                    
                                    self.log(f"Mean Reversion Run {current_run}/{total_runs} | PnL: ${results['Net Profit']:.2f}, Trades: {results['Total Trades']}, WinRate: {results['Win Rate']:.1f}%, MaxLoss: {results['Max Loss Streak']}", 'info')
                                    
                                    if results['Total Trades'] > 20:
                                        opt_results.append({
                                            'Strategy': 'Mean Reversion',
                                            'BB_Window': bb_w,
                                            'BB_Std_Dev': bb_s,
                                            'MACD_Fast': macd_f,
                                            'MACD_Slow': macd_s,
                                            'MACD_Signal': macd_sig,
                                            **results
                                        })
                
                if not opt_results:
                    self.log("Mean Reversion optimization found no valid strategies. Resetting best_params.", 'error', to_file=True, filename=BACKTEST_LOG_FILE)
                    with self.params_lock:
                        self.best_params.clear()
                    return # Exit without setting best_params
                
                self.log("Mean Reversion optimization runs complete. Applying ML model to find the best strategy...", 'info', to_file=True, filename=BACKTEST_LOG_FILE)
                opt_results_df = pd.DataFrame(opt_results)
                best_ml_strategy = self.find_best_strategy_with_ml(opt_results_df) # Use original name
                
                if best_ml_strategy is None:
                    self.log("ML model could not determine a best Mean Reversion strategy. Resetting best_params.", 'error', to_file=True, filename=BACKTEST_LOG_FILE)
                    with self.params_lock:
                        self.best_params.clear()
                    return # Exit without setting best_params
                
                new_best_params = {
                    'strategy': 'Mean Reversion',
                    'bb_window': int(best_ml_strategy['BB_Window']),
                    'bb_std': best_ml_strategy['BB_Std_Dev'],
                    'macd_fast': int(best_ml_strategy['MACD_Fast']),
                    'macd_slow': int(best_ml_strategy['MACD_Slow']),
                    'macd_signal': int(best_ml_strategy['MACD_Signal'])
                }
                
                with self.params_lock:
                    self.best_params.clear()
                    self.best_params.update(new_best_params)
                
                self.ml_strategy_results = best_ml_strategy # Store ML results directly
                log_message_mr = ("\n" + "="*50 + "\n--- MEAN REVERSION OPTIMIZATION COMPLETE ---\n" +
                              f"ML Selected Strategy Score: {best_ml_strategy['ML_Score']:.4f}\n" +
                              f"  - Net Profit: ${best_ml_strategy['Net Profit']:.2f}\n" +
                              f"  - Win Rate: {best_ml_strategy['Win Rate']:.2f}%\n" +
                              f"  - Max Loss Streak: {best_ml_strategy['Max Loss Streak']}\n" +
                              f"  - Profit Factor: {best_ml_strategy['Profit Factor']}\n" +
                              f"NEW PARAMS FOUND: {new_best_params}\n" + "="*50 + "\n")
                self.log(log_message_mr, 'info', to_file=True, filename=BACKTEST_LOG_FILE) # Log summary to file
                
                # Log detailed backtest trades for the best strategy
                for trade_log_entry in best_ml_strategy['Detailed Trades']:
                    self.log(json.dumps(trade_log_entry), 'debug', to_file=True, filename=BACKTEST_LOG_FILE)

                self.emit('params_update', {'best_params': new_best_params, 'ml_strategy_results': best_ml_strategy})
                self._save_optimized_params(new_best_params, best_ml_strategy)
    
            elif self.config['active_strategy'] == "Trend Following":
                strategy_ranges = self.config['trend_following_ranges']
                total_runs = 0
                for ema_w in range(strategy_ranges['ema_window_min'], strategy_ranges['ema_window_max'] + 1, strategy_ranges['ema_window_step']):
                    for rsi_w in range(strategy_ranges['rsi_window_min'], strategy_ranges['rsi_window_max'] + 1, strategy_ranges['rsi_window_step']):
                        rsi_ob_level = self.config['trend_following_ranges']['rsi_overbought_level']
                        rsi_os_level = self.config['trend_following_ranges']['rsi_oversold_level']
                        for macd_f in range(strategy_ranges['macd_fast_min'], strategy_ranges['macd_fast_max'] + 1, strategy_ranges['macd_fast_step']):
                            for macd_s in range(strategy_ranges['macd_slow_min'], strategy_ranges['macd_slow_max'] + 1, strategy_ranges['macd_slow_step']):
                                if macd_f >= macd_s:
                                    continue
                                for macd_sig in range(strategy_ranges['macd_signal_min'], strategy_ranges['macd_signal_max'] + 1, strategy_ranges['macd_signal_step']):
                                    total_runs += 1

                current_run = 0
                for ema_w in range(strategy_ranges['ema_window_min'], strategy_ranges['ema_window_max'] + 1, strategy_ranges['ema_window_step']):
                    for rsi_w in range(strategy_ranges['rsi_window_min'], strategy_ranges['rsi_window_max'] + 1, strategy_ranges['rsi_window_step']):
                        # RSI overbought/oversold are fixed, not optimized
                        rsi_ob_level = strategy_ranges['rsi_overbought_level']
                        rsi_os_level = strategy_ranges['rsi_oversold_level']
                        for macd_f in range(strategy_ranges['macd_fast_min'], strategy_ranges['macd_fast_max'] + 1, strategy_ranges['macd_fast_step']):
                            for macd_s in range(strategy_ranges['macd_slow_min'], strategy_ranges['macd_slow_max'] + 1, strategy_ranges['macd_slow_step']):
                                if macd_f >= macd_s:
                                    continue
                                for macd_sig in range(strategy_ranges['macd_signal_min'], strategy_ranges['macd_signal_max'] + 1, strategy_ranges['macd_signal_step']):
                                    if self.stop_event.is_set():
                                        self.log('Optimization aborted by stop signal.', 'warning', to_file=True, filename=BACKTEST_LOG_FILE)
                                        return
                                    current_run += 1
                                    df_processed = base_df.copy()
                                    df_processed = self.calculate_indicators_trend_following(df_processed, ema_w, rsi_w, macd_f, macd_s, macd_sig)
                                    df_processed.dropna(inplace=True)
                                    df_signals = self.generate_signals_trend_following(df_processed, rsi_ob_level, rsi_os_level)
                                    results = self.backtest_strategy(df_signals)
                                    
                                    self.log(f"Trend Following Run {current_run}/{total_runs} | PnL: ${results['Net Profit']:.2f}, Trades: {results['Total Trades']}, WinRate: {results['Win Rate']:.1f}%, MaxLoss: {results['Max Loss Streak']}", 'info')
                                    
                                    if results['Total Trades'] > 20:
                                        opt_results.append({
                                            'Strategy': 'Trend Following',
                                            'EMA_Window': ema_w,
                                            'RSI_Window': rsi_w,
                                            'RSI_Overbought': rsi_ob_level,
                                            'RSI_Oversold': rsi_os_level,
                                            'MACD_Fast': macd_f,
                                            'MACD_Slow': macd_s,
                                            'MACD_Signal': macd_sig,
                                            **results # Include all results
                                        })
                
                if not opt_results:
                    self.log("Trend Following optimization found no valid strategies. Resetting best_params.", 'error', to_file=True, filename=BACKTEST_LOG_FILE)
                    with self.params_lock:
                        self.best_params.clear()
                    return # Exit without setting best_params
                
                self.log("Trend Following optimization runs complete. Applying ML model to find the best strategy...", 'info', to_file=True, filename=BACKTEST_LOG_FILE)
                opt_results_df = pd.DataFrame(opt_results)
                best_ml_strategy = self.find_best_strategy_with_ml(opt_results_df) # Use original name
                
                if best_ml_strategy is None:
                    self.log("ML model could not determine a best Trend Following strategy. Resetting best_params.", 'error', to_file=True, filename=BACKTEST_LOG_FILE)
                    with self.params_lock:
                        self.best_params.clear()
                    return # Exit without setting best_params
                
                new_best_params = {
                    'strategy': 'Trend Following',
                    'ema_window': int(best_ml_strategy['EMA_Window']),
                    'rsi_window': int(best_ml_strategy['RSI_Window']),
                    'rsi_overbought': int(best_ml_strategy['RSI_Overbought']), # Corrected access
                    'rsi_oversold': int(best_ml_strategy['RSI_Oversold']), # Corrected access
                    'macd_fast': int(best_ml_strategy['MACD_Fast']),
                    'macd_slow': int(best_ml_strategy['MACD_Slow']),
                    'macd_signal': int(best_ml_strategy['MACD_Signal'])
                }
                
                with self.params_lock:
                    self.best_params.clear()
                    self.best_params.update(new_best_params)
                
                self.ml_strategy_results = best_ml_strategy # Store ML results directly
                log_message_tf = ("\n" + "="*50 + "\n--- TREND FOLLOWING OPTIMIZATION COMPLETE ---\n" +
                              f"ML Selected Strategy Score: {best_ml_strategy['ML_Score']:.4f}\n" +
                              f"  - Net Profit: ${best_ml_strategy['Net Profit']:.2f}\n" +
                              f"  - Win Rate: {best_ml_strategy['Win Rate']:.2f}%\n" +
                              f"  - Max Loss Streak: {best_ml_strategy['Max Loss Streak']}\n" +
                              f"  - Profit Factor: {best_ml_strategy['Profit Factor']}\n" +
                              f"NEW PARAMS FOUND: {new_best_params}\n" + "="*50 + "\n")
                self.log(log_message_tf, 'info', to_file=True, filename=BACKTEST_LOG_FILE) # Log summary to file

                # Log detailed backtest trades for the best strategy
                for trade_log_entry in best_ml_strategy['Detailed Trades']:
                    self.log(json.dumps(trade_log_entry), 'debug', to_file=True, filename=BACKTEST_LOG_FILE)
                    
                self.emit('params_update', {'best_params': new_best_params, 'ml_strategy_results': best_ml_strategy})
                self._save_optimized_params(new_best_params, best_ml_strategy)
            else:
                self.log(f"Unknown strategy: {self.config['active_strategy']}", 'error', to_file=True, filename=BACKTEST_LOG_FILE)
        
        except Exception as e:
            self.log(f'Optimization error: {str(e)}', 'error', to_file=True, filename=BACKTEST_LOG_FILE)
            with self.params_lock:
                self.best_params.clear() # Clear params on error
    
    def calculate_indicators_mean_reversion(self, df, macd_fast, macd_slow, macd_signal, bb_window, bb_std):
        df_copy = df.copy() # Make an explicit copy to avoid SettingWithCopyWarning
        df_copy['MACD_Histogram'] = ta.trend.MACD(
            close=df_copy['close'],
            window_fast=macd_fast,
            window_slow=macd_slow,
            window_sign=macd_signal
        ).macd_diff()
        
        bb = ta.volatility.BollingerBands(
            close=df_copy['close'],
            window=bb_window,
            window_dev=bb_std
        )
        df_copy['bb_upper'] = bb.bollinger_hband()
        df_copy['bb_lower'] = bb.bollinger_lband()
        
        return df_copy # Return the modified copy
    
    def generate_signals_mean_reversion(self, df):
        df_copy = df.copy() # Make an explicit copy to avoid SettingWithCopyWarning
        prev_low = df_copy['low'].shift(1)
        prev_high = df_copy['high'].shift(1)
        prev_bb_lower = df_copy['bb_lower'].shift(1)
        prev_bb_upper = df_copy['bb_upper'].shift(1)
        prev_macd_hist = df_copy['MACD_Histogram'].shift(1)
        
        buy_conditions = (
            (prev_low < prev_bb_lower) &
            (df_copy['close'] > df_copy['bb_lower']) &
            (df_copy['MACD_Histogram'] > prev_macd_hist) &
            (df_copy['close'] > df_copy['open']) # Corrected: close > open for bullish candle (buy signal)
        )
        
        sell_conditions = (
            (prev_high > prev_bb_upper) &
            (df_copy['close'] < df_copy['bb_upper']) &
            (df_copy['MACD_Histogram'] < prev_macd_hist) &
            (df_copy['close'] < df_copy['open']) # Corrected: close < open for bearish candle (sell signal)
        )
        
        df_copy['Signal'] = np.select([buy_conditions, sell_conditions], [1, -1], default=0)
        return df_copy # Return the modified copy


    def calculate_indicators_trend_following(self, df, ema_window, rsi_window, macd_fast, macd_slow, macd_signal):
        df_copy = df.copy()
        df_copy['EMA'] = ta.trend.ema_indicator(close=df_copy['close'], window=ema_window)
        df_copy['RSI'] = ta.momentum.rsi(close=df_copy['close'], window=rsi_window)
        df_copy['MACD_Histogram'] = ta.trend.MACD(
            close=df_copy['close'],
            window_fast=macd_fast,
            window_slow=macd_slow,
            window_sign=macd_signal
        ).macd_diff()
        return df_copy

    def generate_signals_trend_following(self, df, rsi_overbought, rsi_oversold):
        df_copy = df.copy()
        prev_macd_hist = df_copy['MACD_Histogram'].shift(1)

        buy_conditions = (
            (df_copy['close'] > df_copy['EMA']) & # Price close above EMA
            (df_copy['RSI'] > rsi_oversold) &     # RSI has moved above oversold, indicating strength
            (df_copy['MACD_Histogram'] > prev_macd_hist) & # MACD rising
            (df_copy['close'] > df_copy['open']) # Bullish candle
        )

        sell_conditions = (
            (df_copy['close'] < df_copy['EMA']) & # Price close below EMA
            (df_copy['RSI'] < rsi_overbought) &    # RSI has moved below overbought, indicating weakness
            (df_copy['MACD_Histogram'] < prev_macd_hist) & # MACD falling
            (df_copy['close'] < df_copy['open']) # Bearish candle
        )

        df_copy['Signal'] = np.select([buy_conditions, sell_conditions], [1, -1], default=0)

        return df_copy
    
    def backtest_strategy(self, df):
        balance = self.config['start_balance_backtest']
        trades_won, trades_lost = 0, 0
        bt_last_stake = 0.0
        bt_last_trade_loss = False
        current_win_streak, max_win_streak = 0, 0
        current_loss_streak, max_loss_streak = 0, 0
        total_profit, total_loss = 0.0, 0.0
        
        # New: List to store detailed backtest trade logs
        detailed_trade_logs = []

        i = 0
        while i < len(df) - 1:
            signal = df.iloc[i]['Signal']
            if signal != 0:
                base_stake = self.config['fixed_stake_amount'] if self.config['use_fixed_stake_amount'] else (self.config['start_balance_backtest'] * (self.config['trade_stake_percent'] / 100)) # Changed 'balance' to 'self.config['start_balance_backtest']'
                stake = (bt_last_stake * self.config['martingale_multiplier']) if (self.config['use_martingale'] and bt_last_trade_loss) else base_stake
                
                if stake > balance or stake < 0.35: # 'balance' here still refers to the current simulated balance for comparison
                    i += 1
                    continue
                
                entry_candle = df.iloc[i]
                entry_time = entry_candle.name.strftime('%Y-%m-%d %H:%M:%S') # Get timestamp from index
                entry_price = df.iloc[i + 1]['open'] # Entry price is open of next candle
                trade_type = 'BUY' if signal == 1 else 'SELL'

                trade_open_log = {
                    'timestamp': entry_time,
                    'type': trade_type,
                    'action': 'ENTRY',
                    'entry_price': round(entry_price, 4),
                    'stake': round(stake, 2),
                    'tp_percent': self.config['take_profit_percent'],
                    'sl_percent': self.config['stop_loss_percent'],
                    'result': 'OPEN'
                }
                detailed_trade_logs.append(trade_open_log)

                if signal == 1:
                    tp_price = entry_price * (1 + self.config['take_profit_percent'] / 100)
                    sl_price = entry_price * (1 - self.config['stop_loss_percent'] / 100)
                else:
                    tp_price = entry_price * (1 - self.config['take_profit_percent'] / 100)
                    sl_price = entry_price * (1 + self.config['stop_loss_percent'] / 100)
                
                j = i
                trade_closed_reason = 'UNKNOWN'
                pnl = 0.0 # Initialize pnl for the trade
                for j in range(i + 1, len(df)):
                    candle = df.iloc[j]
                    exit_time = candle.name.strftime('%Y-%m-%d %H:%M:%S')
                    exit_price = 0.0 # Will be actual exit price

                    if signal == 1: # BUY trade
                        if candle['high'] >= tp_price:
                            pnl = (tp_price - entry_price) / entry_price * stake * self.config['multiplier']
                            balance += pnl
                            trades_won += 1
                            bt_last_trade_loss = False
                            current_win_streak += 1
                            current_loss_streak = 0
                            trade_closed_reason = 'TP'
                            exit_price = tp_price
                            break
                        if candle['low'] <= sl_price:
                            pnl = (sl_price - entry_price) / entry_price * stake * self.config['multiplier']
                            balance += pnl # pnl is negative here
                            total_loss += abs(pnl)
                            trades_lost += 1
                            bt_last_trade_loss = True
                            current_loss_streak += 1
                            current_win_streak = 0
                            trade_closed_reason = 'SL'
                            exit_price = sl_price
                            break
                    else: # SELL trade
                        if candle['low'] <= tp_price:
                            pnl = (entry_price - tp_price) / entry_price * stake * self.config['multiplier']
                            balance += pnl
                            trades_won += 1
                            bt_last_trade_loss = False
                            current_win_streak += 1
                            current_loss_streak = 0
                            trade_closed_reason = 'TP'
                            exit_price = tp_price
                            break
                        if candle['high'] >= sl_price:
                            pnl = (entry_price - sl_price) / entry_price * stake * self.config['multiplier']
                            balance += pnl # pnl is negative here
                            total_loss += abs(pnl)
                            trades_lost += 1
                            bt_last_trade_loss = True
                            current_loss_streak += 1
                            current_win_streak = 0
                            trade_closed_reason = 'SL'
                            exit_price = sl_price
                            break
                    
                    if candle['Signal'] == -signal: # Reversal signal, close trade
                        close_price = candle['open']
                        pnl = (close_price - entry_price) / entry_price * stake * self.config['multiplier'] * signal
                        
                        if pnl > 0:
                            total_profit += pnl
                        elif pnl < 0:
                            total_loss += abs(pnl)
                        
                        balance += pnl
                        
                        if pnl < 0:
                            trades_lost += 1
                            bt_last_trade_loss = True
                            current_loss_streak += 1
                            current_win_streak = 0
                        else:
                            trades_won += 1
                            bt_last_trade_loss = False
                            current_win_streak += 1
                            current_loss_streak = 0
                        trade_closed_reason = 'REVERSAL'
                        exit_price = close_price
                        break
                
                trade_close_log = {
                    'timestamp': exit_time,
                    'type': trade_type,
                    'action': 'EXIT',
                    'exit_price': round(exit_price, 4),
                    'pnl': round(pnl, 2), # PnL for this specific trade
                    'reason': trade_closed_reason
                }
                detailed_trade_logs.append(trade_close_log)

                i = j + 1
                bt_last_stake = stake
                max_win_streak = max(max_win_streak, current_win_streak)
                max_loss_streak = max(max_loss_streak, current_loss_streak)
            else:
                i += 1
        
        total_trades = trades_won + trades_lost
        win_rate = (trades_won / total_trades * 100) if total_trades > 0 else 0
        profit_factor = total_profit / total_loss if total_loss > 0 else total_profit
        
        return {
            'Net Profit': round(balance - self.config['start_balance_backtest'], 2),
            'Total Trades': total_trades,
            'Win Rate': win_rate,
            'Max Win Streak': max_win_streak,
            'Max Loss Streak': max_loss_streak,
            'Profit Factor': round(profit_factor, 2),
            'Detailed Trades': detailed_trade_logs # New: Return detailed trade logs
        }
    
    def find_best_strategy_with_ml(self, opt_results_df):
        if opt_results_df.empty:
            return None
        
        ml_weights = self.config['ml_weights']
        
        max_profit = opt_results_df['Net Profit'].max()
        max_win_rate = opt_results_df['Win Rate'].max()
        max_profit_factor = opt_results_df['Profit Factor'].max()
        max_loss_streak = opt_results_df['Max Loss Streak'].max()
        
        df = opt_results_df.copy()
        df['norm_profit'] = (df['Net Profit'] / max_profit) if max_profit > 0 else 0
        df['norm_win_rate'] = (df['Win Rate'] / max_win_rate) if max_win_rate > 0 else 0
        df['norm_profit_factor'] = (df['Profit Factor'] / max_profit_factor) if max_profit_factor > 0 else 0
        df['norm_loss_streak_desire'] = 1 - (df['Max Loss Streak'] / max_loss_streak) if max_loss_streak > 0 else 1
        
        df['ML_Score'] = (
            ml_weights['net_profit'] * df['norm_profit'] +
            ml_weights['win_rate'] * df['norm_win_rate'] +
            ml_weights['profit_factor'] * df['norm_profit_factor'] +
            ml_weights['loss_streak'] * df['norm_loss_streak_desire']
        )
        
        return df.sort_values(by='ML_Score', ascending=False).iloc[0].to_dict()
    
    def connect(self):
        self.ws = websocket.WebSocketApp(
            self.config['ws_url'],
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close
        )
        
        self.emit('bot_status', {'running': True})
        self.ws.run_forever()
    
    def on_open(self, ws):
        self.log('WebSocket connected. Authorizing...', 'info')
        self.send_message({"authorize": self.config['api_token']})
    
    def on_close(self, ws, close_status_code, close_msg):
        self.log(f'WebSocket closed: {close_msg}', 'warning')
        if self.is_running and not self.stop_event.is_set(): # Only attempt reconnect if bot is still running and not explicitly stopped
            self.log('Attempting to reconnect WebSocket...', 'info')
            time.sleep(5)
            self.connect()
        else:
            self.log('WebSocket will not reconnect as bot is stopped.', 'info')
    
    def on_error(self, ws, error):
        self.log(f'WebSocket error: {str(error)}', 'error')
    
    def on_message(self, ws, message):
        try:
            data = json.loads(message)
            
            if 'error' in data:
                self.log(f'API Error: {data["error"].get("message", "Unknown Error")}', 'error')
            elif data.get('msg_type') == 'authorize':
                self.log('Authorization successful. Subscribing...', 'info')
                self.send_message({"balance": 1, "subscribe": 1})
                self.send_message({
                    "ticks_history": self.config['symbol'],
                    "end": "latest",
                    "count": 500,
                    "style": "candles",
                    "granularity": self.config['granularity']
                })
            elif 'balance' in data:
                self.current_balance = data['balance'].get('balance', 0.0)
                if self.session_stats['session_start_balance'] == 0.0:
                    self.session_stats['session_start_balance'] = self.current_balance
                self.log(f'Balance updated: ${self.current_balance:.2f}', 'info')
                self.emit('balance_update', {'balance': self.current_balance})
            elif 'candles' in data:
                for c in data['candles']:
                    self.historical_data_live['high'].append(float(c['high']))
                    self.historical_data_live['low'].append(float(c['low']))
                    self.historical_data_live['close'].append(float(c['close']))
                    self.historical_data_live['open'].append(float(c['open']))
                    self.historical_data_live['datetime'].append(pd.to_datetime(c['epoch'], unit='s'))
                
                self.log(f'Historical data loaded: {len(data["candles"])} candles', 'info')
                self.is_bot_initialized.set()
                self.log('Bot initialized. Subscribing to real-time ticks...', 'info')
                self.send_message({"ticks": self.config['symbol'], "subscribe": 1})
            elif 'tick' in data:
                self.handle_tick(ws, data['tick'])
            elif data.get('msg_type') == 'buy':
                self.handle_buy_response(data)
            elif data.get('msg_type') == 'proposal_open_contract': # Handle proposal_open_contract for entry spot price
                self.handle_proposal_open_contract(data)
            elif 'sell' in data:
                self.handle_trade_update(ws, data)
        
        except Exception as e:
            self.log(f'Message handling error: {str(e)}', 'error')
    
    def send_message(self, message):
        if self.ws and self.ws.sock and self.ws.sock.connected:
            self.ws.send(json.dumps(message))
    
    def handle_tick(self, ws, tick):
        if not self.is_bot_initialized.is_set():
            return
        
        tick_time = pd.to_datetime(tick['epoch'], unit='s')
        price = float(tick['quote'])
        
        # monitor_open_trades is no longer needed as trade closure is handled by API messages
        # self.monitor_open_trades(ws, price)
        
        if not self.historical_data_live['datetime']:
            return
        
        last_candle_time = self.historical_data_live['datetime'][-1]
        
        if tick_time >= last_candle_time + timedelta(seconds=self.config['granularity']):
            self.historical_data_live['open'].append(price)
            self.historical_data_live['high'].append(price)
            self.historical_data_live['low'].append(price)
            self.historical_data_live['close'].append(price)
            self.historical_data_live['datetime'].append(tick_time.replace(second=0, microsecond=0))
            
            for key in self.historical_data_live:
                self.historical_data_live[key] = self.historical_data_live[key][-500:]
            
            self.log(f'New candle closed at {tick_time.strftime("%H:%M:%S")}. Checking for signals...', 'info')
            self.check_for_signal(ws)
        else:
            self.historical_data_live['high'][-1] = max(self.historical_data_live['high'][-1], price)
            self.historical_data_live['low'][-1] = min(self.historical_data_live['low'][-1], price)
            self.historical_data_live['close'][-1] = price
        
        self.emit('price_update', {'price': price, 'timestamp': tick_time.isoformat()})
    
    def check_for_signal(self, ws):
        with self.params_lock:
            active_params = self.best_params.copy()
        
        if not active_params or 'strategy' not in active_params:
            return
        
        df_live = pd.DataFrame(self.historical_data_live).set_index('datetime')
        
        # Exclude the last (currently forming) candle for signal generation
        if len(df_live) < 2: # Need at least two candles (one closed, one forming)
            return
        
        df_closed_candles = df_live.iloc[:-1] # All candles except the last one
        
        if active_params['strategy'] == "Mean Reversion":
            df_indicators = self.calculate_indicators_mean_reversion(
                df_closed_candles,
                macd_fast=active_params['macd_fast'],
                macd_slow=active_params['macd_slow'],
                macd_signal=active_params['macd_signal'],
                bb_window=active_params['bb_window'],
                bb_std=active_params['bb_std']
            )
            df_with_signals = self.generate_signals_mean_reversion(df_indicators)
        elif active_params['strategy'] == "Trend Following":
            df_indicators = self.calculate_indicators_trend_following(
                df_closed_candles,
                ema_window=active_params['ema_window'],
                rsi_window=active_params['rsi_window'],
                macd_fast=active_params['macd_fast'],
                macd_slow=active_params['macd_slow'],
                macd_signal=active_params['macd_signal']
            )
            df_with_signals = self.generate_signals_trend_following(
                df_indicators,
                rsi_overbought=active_params['rsi_overbought'], # Corrected access
                rsi_oversold=active_params['rsi_oversold'] # Corrected access
            )
        else:
            self.log(f"Unknown active strategy: {active_params['strategy']}", 'error', to_file=True, filename=BACKTEST_LOG_FILE)
            return
        
        if len(df_indicators) < 1: # Need at least one closed candle for indicators
            return
        
        last_signal = df_with_signals['Signal'].iloc[-1]
        candle_time = df_with_signals.index[-1]

        # Log relevant values for debugging (using the last *closed* candle)
        current_close = df_indicators['close'].iloc[-1]
        current_open = df_indicators['open'].iloc[-1]
        debug_msg = f"DEBUG - Candle Time: {candle_time}, Close: {current_close:.4f}, Open: {current_open:.4f}\n"

        if active_params['strategy'] == "Mean Reversion":
            prev_low = df_indicators['low'].shift(1).iloc[-1] if len(df_indicators) > 1 else None
            prev_high = df_indicators['high'].shift(1).iloc[-1] if len(df_indicators) > 1 else None
            prev_bb_lower = df_indicators['bb_lower'].shift(1).iloc[-1] if len(df_indicators) > 1 else None
            prev_bb_upper = df_indicators['bb_upper'].shift(1).iloc[-1] if len(df_indicators) > 1 else None
            current_macd_hist = df_indicators['MACD_Histogram'].iloc[-1]
            prev_macd_hist = df_indicators['MACD_Histogram'].shift(1).iloc[-1] if len(df_indicators) > 1 else None
            debug_msg += f"  Mean Reversion - Prev Low: {prev_low:.4f}, Prev High: {prev_high:.4f}\n"
            debug_msg += f"  Mean Reversion - Prev BB Lower: {prev_bb_lower:.4f}, Prev BB Upper: {prev_bb_upper:.4f}\n"
            debug_msg += f"  Mean Reversion - Current MACD Hist: {current_macd_hist:.4f}, Prev MACD Hist: {prev_macd_hist:.4f}\n"
        elif active_params['strategy'] == "Trend Following":
            current_ema = df_indicators['EMA'].iloc[-1]
            current_rsi = df_indicators['RSI'].iloc[-1]
            current_macd_hist = df_indicators['MACD_Histogram'].iloc[-1]
            prev_macd_hist = df_indicators['MACD_Histogram'].shift(1).iloc[-1] if len(df_indicators) > 1 else None
            debug_msg += f"  Trend Following - Current EMA: {current_ema:.4f}, Current RSI: {current_rsi:.2f}\n"
            debug_msg += f"  Trend Following - Current MACD Hist: {current_macd_hist:.4f}, Prev MACD Hist: {prev_macd_hist:.4f}\n"
        
        self.log(debug_msg, 'info')
        
        if last_signal != 0:
            signal_type = 'BUY' if last_signal == 1 else 'SELL'
            self.log(f'*** {signal_type} SIGNAL DETECTED on candle {candle_time} ***', 'info')
            self.execute_trade(ws, last_signal)
        else:
            self.log(f'No signal on candle {candle_time}', 'info')
    
    def calculate_next_stake(self):
        base_stake = self.config['fixed_stake_amount'] if self.config['use_fixed_stake_amount'] else round(self.current_balance * (self.config['trade_stake_percent'] / 100), 2)
        
        if self.config['use_martingale'] and self.last_trade_was_loss:
            next_stake = round(self.last_stake_amount * self.config['martingale_multiplier'], 2)
            self.log(f'Martingale active: Next stake is ${next_stake:.2f}', 'info')
            return next_stake
        
        return base_stake
    
    def execute_trade(self, ws, signal):
        trade_type_str = 'BUY' if signal == 1 else 'SELL'
        opposite_trade_type = 'SELL' if signal == 1 else 'BUY'
        
        for trade in self.open_trades:
            if trade['type'] == opposite_trade_type:
                self.log(f'Closing opposite {opposite_trade_type} trade {trade["id"]}', 'warning')
                self.send_message({"sell": trade['id'], "price": 0}) # Send sell message directly
                # Continue to open the new trade after closing the opposite one
        
        if any(t['type'] == trade_type_str for t in self.open_trades):
            self.log(f'{trade_type_str} trade already open. Skipping.', 'info')
            return
        
        stake = self.calculate_next_stake()
        
        if stake > self.current_balance:
            self.log(f'Stake ${stake:.2f} exceeds balance ${self.current_balance:.2f}', 'warning')
            return
        
        if stake < 1.0:
            self.log(f'Stake ${stake:.2f} is too low', 'warning')
            return
        
        self.last_stake_amount = stake
        
        contract_type = "MULTUP" if signal == 1 else "MULTDOWN"
        self.log(f'Executing {trade_type_str} ({contract_type}) with stake ${stake:.2f}', 'info')
        
        trade_params = {
            "buy": "1",
            "price": stake * self.config['multiplier'], # Maximum payout as per Deriv API for multiplier contracts
            "parameters": {
                "amount": stake,
                "basis": "stake",
                "contract_type": contract_type,
                "symbol": self.config['symbol'],
                "currency": "USD",
                "multiplier": self.config['multiplier']
            },
            "subscribe": 1 # Subscribe to updates as per user's example
        }
        
        self.send_message(trade_params)
    
    def handle_buy_response(self, data):
        if 'error' in data:
            self.log(f'Trade execution error: {data["error"].get("message")}', 'error')
            return
        
        buy_info = data.get('buy', {})
        contract_id = buy_info.get('contract_id')
        stake_amount = buy_info.get('buy_price') # This is the stake, not the entry spot price
        
        if not contract_id or not stake_amount:
            self.log(f'Invalid buy response: contract_id or stake_amount missing', 'error')
            return
        
        trade_type = 'BUY' if 'MULTUP' in buy_info.get('shortcode', '') else 'SELL'
        
        # Initialize trade with known info, entry_spot_price and TP/SL will be updated by proposal_open_contract
        trade = {
            'id': contract_id,
            'type': trade_type,
            'entry_spot_price': None, # To be filled by proposal_open_contract
            'tp_price': None, # To be filled
            'sl_price': None, # To be filled
            'stake': self.last_stake_amount,
            'contract_details': buy_info # Store full buy_info for later reference if needed
        }
        
        self.open_trades.append(trade)
        trade_log_message = (
            f'{trade_type} trade {contract_id} opened with stake ${stake_amount:.2f}. '
            f'Awaiting entry spot price for TP/SL.'
        )
        self.log(trade_log_message, 'info', to_file=True, filename=TRADE_LOG_FILE) # Log to file
        self.emit('trades_update', {'trades': self.open_trades})
        
        # Explicitly subscribe to updates for this contract to get entry_tick_quote
    
    def handle_proposal_open_contract(self, data):
        contract_info = data.get('proposal_open_contract', {})
        if not contract_info:
            return

        contract_id = contract_info.get('contract_id')
        if not contract_id:
            return

        trade = next((t for t in self.open_trades if t['id'] == contract_id), None)
        if trade is None: # If trade is None, it means it was already closed and removed.
            # self.log(f"Received proposal_open_contract for already closed trade ID {contract_id}", 'debug') # Optional: log at debug level
            return

        # Update entry spot price and TP/SL if not already set
        if trade['entry_spot_price'] is None:
            entry_spot_price = contract_info.get('entry_spot') or contract_info.get('entry_tick')
            if entry_spot_price is None:
                self.log(f"Trade {contract_id}: entry_spot or entry_tick is None in this update. Waiting for full entry.", 'debug', to_file=True, filename=TRADE_LOG_FILE)
            else:
                entry_spot_price = float(entry_spot_price)
                trade_type = trade['type']

                if trade_type == 'BUY':
                    tp_price = entry_spot_price * (1 + self.config['take_profit_percent'] / 100)
                    sl_price = entry_spot_price * (1 - self.config['stop_loss_percent'] / 100)
                else: # SELL
                    tp_price = entry_spot_price * (1 - self.config['take_profit_percent'] / 100)
                    sl_price = entry_spot_price * (1 + self.config['stop_loss_percent'] / 100)
                
                trade['entry_spot_price'] = entry_spot_price
                trade['tp_price'] = tp_price
                trade['sl_price'] = sl_price
                self.log(f'Trade {contract_id} entry confirmed at {entry_spot_price:.4f}. TP: {tp_price:.4f}, SL: {sl_price:.4f}', 'info', to_file=True, filename=TRADE_LOG_FILE)
                self.emit('trades_update', {'trades': self.open_trades})

        # Check for trade closure from proposal_open_contract
        if contract_info.get('is_sold') or contract_info.get('is_expired'):
            profit = float(contract_info.get('profit', 0.0))
            exit_price = float(contract_info.get('exit_tick', contract_info.get('current_spot', 0.0))) # Get actual exit price
            self.handle_trade_closed(contract_id, profit, exit_price) # Pass exit_price

    def handle_trade_closed(self, contract_id, profit, exit_price=None): # Added exit_price parameter
        trade_to_close = next((t for t in self.open_trades if t['id'] == contract_id), None)
        if trade_to_close:
            self.open_trades.remove(trade_to_close)
            
            calculated_pnl = 0.0
            if trade_to_close['entry_spot_price'] and exit_price:
                entry_price = trade_to_close['entry_spot_price']
                stake = trade_to_close['stake']
                signal = 1 if trade_to_close['type'] == 'BUY' else -1
                calculated_pnl = (exit_price - entry_price) / entry_price * stake * self.config['multiplier'] * signal

            trade_log_message = (
                f"Trade {contract_id} closed. "
                f"Type: {trade_to_close.get('type', 'N/A')}, "
                f"Entry Price: {trade_to_close.get('entry_spot_price', 'N/A')}, "
                f"Exit Price: {exit_price:.4f}, " # Include exit_price
                f"Stake: ${trade_to_close.get('stake', 0.0):.2f}, "
                f"API Profit: ${profit:.2f}, " # Differentiate API profit
                f"Calculated PnL: ${calculated_pnl:.2f}" # Add calculated PnL
            )
            self.log(trade_log_message, 'info', to_file=True, filename=TRADE_LOG_FILE) # Log to file
            
            if self.config['use_martingale']:
                if profit < 0:
                    self.last_trade_was_loss = True
                    self.log('Trade was a LOSS. Martingale will apply on next trade.', 'warning', to_file=True, filename=TRADE_LOG_FILE) # Log to file
                else:
                    self.last_trade_was_loss = False
                    self.log('Trade was a WIN. Stake reset.', 'info', to_file=True, filename=TRADE_LOG_FILE) # Log to file
            
            self.update_stats(profit)
            self.emit('trades_update', {'trades': self.open_trades})
            self.emit('stats_update', self.get_stats())
        else:
            self.log(f'Attempted to close unknown trade {contract_id}', 'warning', to_file=True, filename=TRADE_LOG_FILE) # Log to file

    def handle_trade_update(self, ws, data):
        # This method will now primarily handle the final 'sell' message confirmation
        # The actual closure logic (TP/SL/Expiry) is handled by handle_proposal_open_contract
        sell_info = data.get('sell', {})
        if sell_info and sell_info.get('sold_for'): # 'sold_for' indicates a final sell confirmation
            contract_id = sell_info.get('contract_id')
            profit = float(sell_info.get('profit', 0.0))
            exit_price = float(sell_info.get('sell_price', 0.0)) # Get actual exit price from sell message
            self.log(f"Final sell confirmation received for trade {contract_id}. Profit: ${profit:.2f}", 'info', to_file=True, filename=TRADE_LOG_FILE)
            # The trade should ideally already be removed by handle_proposal_open_contract
            # But as a fallback, ensure it's removed if still present and update stats
            self.handle_trade_closed(contract_id, profit, exit_price) # Pass exit_price
        else:
            self.log(f"Received unexpected trade update: {data}", 'warning', to_file=True, filename=TRADE_LOG_FILE)
        
    def _get_config_context_key(self):
        """Generates a unique key for the current configuration context."""
        return f"{self.config['active_strategy']}-{self.config['symbol']}-{self.config['granularity']}-{self.config['take_profit_percent']}-{self.config['stop_loss_percent']}"

    def _save_optimized_params(self, params, ml_results):
        try:
            all_optimized_params = {}
            if os.path.exists(OPTIMIZED_PARAMS_DB_FILE):
                with open(OPTIMIZED_PARAMS_DB_FILE, 'r') as f:
                    all_optimized_params = json.load(f)

            context_key = self._get_config_context_key()
            today_utc = datetime.now(timezone.utc).strftime('%Y-%m-%d')

            all_optimized_params[context_key] = {
                'date': today_utc,
                'params': params,
                'ml_results': ml_results
            }

            with open(OPTIMIZED_PARAMS_DB_FILE, 'w') as f:
                json.dump(all_optimized_params, f, indent=2)
            # Create a copy of ml_results and remove 'Detailed Trades' before saving
            ml_results_to_save = ml_results.copy()
            if 'Detailed Trades' in ml_results_to_save:
                del ml_results_to_save['Detailed Trades']

            all_optimized_params[context_key] = {
                'date': today_utc,
                'params': params,
                'ml_results': ml_results_to_save # Save the modified ml_results
            }

            with open(OPTIMIZED_PARAMS_DB_FILE, 'w') as f:
                json.dump(all_optimized_params, f, indent=2)
            self.log('Optimized parameters saved successfully.', 'info')
        except Exception as e:
            self.log(f'Error saving optimized parameters: {str(e)}', 'error')
            
    def _load_optimized_params(self):
        try:
            if os.path.exists(OPTIMIZED_PARAMS_DB_FILE):
                with open(OPTIMIZED_PARAMS_DB_FILE, 'r') as f:
                    all_optimized_params = json.load(f)
                
                context_key = self._get_config_context_key()
                today_utc = datetime.now(timezone.utc).strftime('%Y-%m-%d')
                
                if context_key in all_optimized_params:
                    data = all_optimized_params[context_key]
                    if data.get('date') == today_utc:
                        with self.params_lock:
                            self.best_params.clear()
                            self.best_params.update(data['params'])
                        self.ml_strategy_results = data['ml_results'] # Store ML results
                        self.emit('params_update', {'best_params': data['params'], 'ml_strategy_results': data['ml_results']})
                        self.log(f"Successfully loaded optimized parameters for context '{context_key}' for today.", 'info')
                        return True
                    else:
                        self.log(f"Optimized parameters for context '{context_key}' are from a previous day. Re-optimization needed.", 'info')
                else:
                    self.log(f"No saved optimized parameters found for context '{context_key}'.", 'info')
            else:
                self.log('No saved optimized parameters database file found.', 'info')
        except Exception as e:
            self.log(f'Error loading optimized parameters: {str(e)}', 'error')
        return False

    def _load_config(self):
        try:
            with open(self.config_path, 'r') as f:
                config = json.load(f)
                return config
        except FileNotFoundError:
            self.log(f"Config file not found: {self.config_path}", 'error')
            raise
        except json.JSONDecodeError as e:
            self.log(f"Error decoding config file {self.config_path}: {e}", 'error')
            raise
        except Exception as e:
            self.log(f"An unexpected error occurred while loading config: {e}", 'error')
            raise


class DerivHistoricalDataFetcher:
    def __init__(self, symbol, url):
        self.symbol = symbol
        self.url = url
        self._data_received = False
        self._received_candles = []
        self._ws = None
    
    def _on_message(self, ws, message):
        data = json.loads(message)
        if 'error' in data:
            logging.error(f"Deriv API Error: {data['error']['message']}")
        elif 'candles' in data:
            self._received_candles = data['candles']
        self._data_received = True
        ws.close()
    
    def _on_error(self, ws, error):
        logging.error(f"WebSocket Error: {error}")
        self._data_received = True
    
    def _on_close(self, ws, close_status_code, close_msg):
        self._data_received = True
    
    def _on_open(self, ws):
        if ws: # The 'ws' argument is the active WebSocket connection
            ws.send(self._request_str)
    
    def _fetch_batch(self, request_str):
        self._request_str = request_str
        self._received_candles = []
        self._data_received = False
        
        self._ws = websocket.WebSocketApp(
            self.url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close
        )
        
        self._ws.run_forever()
        
        if not self._received_candles:
            return pd.DataFrame()
        
        df = pd.DataFrame(self._received_candles)
        df['datetime'] = pd.to_datetime(df['epoch'], unit='s')
        df.set_index('datetime', inplace=True)
        
        for col in ['open', 'high', 'low', 'close']:
            df[col] = pd.to_numeric(df[col])
        
        return df.drop(['epoch'], axis=1).sort_index()
    
    def fetch_data_for_days(self, num_days, granularity):
        end_time = int(datetime.now(timezone.utc).timestamp())
        candles_per_day = int(24 * 60 * 60 / granularity)
        total_candles_needed = num_days * candles_per_day
        
        BATCH_SIZE = 5000
        all_dfs = []
        
        logging.info(f"Fetching {num_days} days ({total_candles_needed} candles)...")
        
        while total_candles_needed > 0:
            count = min(total_candles_needed, BATCH_SIZE)
            request = {
                "ticks_history": self.symbol,
                "end": end_time,
                "style": "candles",
                "granularity": granularity,
                "count": count
            }
            
            df_batch = self._fetch_batch(json.dumps(request))
            
            if df_batch.empty:
                logging.warning("No more data received.")
                break
            
            all_dfs.append(df_batch)
            total_candles_needed -= len(df_batch)
            end_time = int(df_batch.index.min().timestamp()) - 1
            
            logging.info(f"Fetched {len(df_batch)} candles. Remaining: {total_candles_needed}")
            time.sleep(0.2)
        
        if not all_dfs:
            return pd.DataFrame()
        
        return pd.concat(all_dfs).drop_duplicates().sort_index()
