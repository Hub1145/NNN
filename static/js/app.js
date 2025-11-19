const socket = io();

let currentConfig = null;
const configModal = new bootstrap.Modal(document.getElementById('configModal'));

document.addEventListener('DOMContentLoaded', () => {
    initializeTheme();
    loadConfig().then(() => {
        setupEventListeners();
        setupSocketListeners();
        updateIndicatorVisibility(); // Initial visibility setup
    });
});

function initializeTheme() {
    const savedTheme = localStorage.getItem('theme') || 'dark';
    document.body.setAttribute('data-theme', savedTheme);
    document.getElementById('themeToggle').checked = savedTheme === 'light';
    updateThemeIcon(savedTheme);
}

function updateThemeIcon(theme) {
    const icon = document.getElementById('themeIcon');
    icon.className = theme === 'light' ? 'bi bi-sun-fill' : 'bi bi-moon-stars';
}

function setupEventListeners() {
    document.getElementById('themeToggle').addEventListener('change', (e) => {
        const theme = e.target.checked ? 'light' : 'dark';
        document.body.setAttribute('data-theme', theme);
        localStorage.setItem('theme', theme);
        updateThemeIcon(theme);
    });

    document.getElementById('startBtn').addEventListener('click', () => {
        socket.emit('start_bot');
        document.getElementById('startBtn').disabled = true;
    });

    document.getElementById('stopBtn').addEventListener('click', () => {
        socket.emit('stop_bot');
        document.getElementById('stopBtn').disabled = true;
    });

    document.getElementById('configBtn').addEventListener('click', () => {
        loadConfigToModal();
        configModal.show();
    });

    document.getElementById('saveConfigBtn').addEventListener('click', () => {
        saveConfig();
    });

    document.getElementById('clearConsoleBtn').addEventListener('click', () => {
        socket.emit('clear_console');
        document.getElementById('consoleOutput').innerHTML = '<p class="text-muted">Console cleared</p>';
    });

    document.getElementById('activeStrategy').addEventListener('change', () => {
        updateIndicatorVisibility();
    });
}

function updateIndicatorVisibility() {
    const activeStrategy = document.getElementById('activeStrategy').value;
    document.getElementById('meanReversionConfig').classList.remove('show');
    document.getElementById('trendFollowingConfig').classList.remove('show');

    if (activeStrategy === 'Mean Reversion') {
        document.getElementById('meanReversionConfig').classList.add('show');
        document.querySelector('[data-bs-target="#meanReversionConfig"]').classList.remove('collapsed');
    } else if (activeStrategy === 'Trend Following') {
        document.getElementById('trendFollowingConfig').classList.add('show');
        document.querySelector('[data-bs-target="#trendFollowingConfig"]').classList.remove('collapsed');
    }
}

function setupSocketListeners() {
    socket.on('connection_status', (data) => {
        console.log('Connected to server:', data);
    });

    socket.on('bot_status', (data) => {
        updateBotStatus(data.running);
    });

    socket.on('balance_update', (data) => {
        updateBalance(data.balance);
    });

    socket.on('trades_update', (data) => {
        updateOpenTrades(data.trades);
    });

    socket.on('stats_update', (data) => {
        updateStats(data);
    });

    socket.on('params_update', (data) => {
        updateParams(data.best_params);
        updateMLStrategyResults(data.ml_strategy_results);
    });

    socket.on('console_log', (data) => {
        addConsoleLog(data);
    });

    socket.on('console_cleared', () => {
        document.getElementById('consoleOutput').innerHTML = '<p class="text-muted">Console cleared</p>';
    });

    socket.on('price_update', (data) => {
    });

    socket.on('success', (data) => {
        showNotification(data.message, 'success');
    });

    socket.on('error', (data) => {
        showNotification(data.message, 'error');
    });

    socket.on('connect', () => {
        console.log('WebSocket connected');
        loadStatus();
    });

    socket.on('disconnect', () => {
        console.log('WebSocket disconnected');
    });
}

function updateBotStatus(running) {
    const statusBadge = document.getElementById('botStatus');
    const startBtn = document.getElementById('startBtn');
    const stopBtn = document.getElementById('stopBtn');

    if (running) {
        statusBadge.textContent = 'Running';
        statusBadge.className = 'badge status-badge running';
        startBtn.disabled = true;
        stopBtn.disabled = false;
    } else {
        statusBadge.textContent = 'Stopped';
        statusBadge.className = 'badge status-badge stopped';
        startBtn.disabled = false;
        stopBtn.disabled = true;
    }
}

function updateBalance(balance) {
    document.getElementById('balance').textContent = `$${balance.toFixed(2)}`;
}

function updateStats(stats) {
    // Ensure all stats keys are present, defaulting to 0 or appropriate values
    const defaultStats = {
        net_profit: 0,
        win_rate: 0,
        total_trades: 0,
        profit_factor: 0, // Default to 0, will be updated by backend's calculation
        trades_won: 0,
        trades_lost: 0,
        max_win_streak: 0,
        max_loss_streak: 0,
        total_profit: 0,
        total_loss: 0 // Added default for total_loss
    };
    stats = { ...defaultStats, ...stats }; // Merge default stats with received stats
    
    document.getElementById('netProfit').textContent = `$${stats.net_profit.toFixed(2)}`;
    document.getElementById('netProfit').className = `stat-value ${stats.net_profit >= 0 ? 'text-success' : 'text-danger'}`;
    
    document.getElementById('winRate').textContent = `${stats.win_rate.toFixed(1)}%`;
    document.getElementById('totalTrades').textContent = stats.total_trades;
    document.getElementById('profitFactor').textContent = stats.profit_factor.toFixed(2);
    document.getElementById('tradesWon').textContent = stats.trades_won;
    document.getElementById('tradesLost').textContent = stats.trades_lost;
    document.getElementById('maxWinStreak').textContent = stats.max_win_streak;
    document.getElementById('maxLossStreak').textContent = stats.max_loss_streak;
    document.getElementById('totalProfitValue').textContent = `$${stats.total_profit.toFixed(2)}`;
    document.getElementById('totalLossValue').textContent = `$${stats.total_loss.toFixed(2)}`; // Display total_loss
}

function updateParams(params) {
    const paramsContainer = document.getElementById('currentParams');
    
    if (!params || Object.keys(params).length === 0 || !params.strategy) {
        paramsContainer.innerHTML = '<p class="text-muted">No parameters loaded yet. Start the bot to run optimization.</p>';
        return;
    }

    let html = `
        <div class="param-item">
            <span class="param-label">Strategy:</span>
            <span class="param-value">${params.strategy}</span>
        </div>
    `;

    if (params.strategy === 'Mean Reversion') {
        html += `
            <div class="param-item">
                <span class="param-label">MACD Fast:</span>
                <span class="param-value">${params.macd_fast}</span>
            </div>
            <div class="param-item">
                <span class="param-label">MACD Slow:</span>
                <span class="param-value">${params.macd_slow}</span>
            </div>
            <div class="param-item">
                <span class="param-label">MACD Signal:</span>
                <span class="param-value">${params.macd_signal}</span>
            </div>
            <div class="param-item">
                <span class="param-label">BB Window:</span>
                <span class="param-value">${params.bb_window}</span>
            </div>
            <div class="param-item">
                <span class="param-label">BB Std Dev:</span>
                <span class="param-value">${params.bb_std.toFixed(1)}</span>
            </div>
        `;
    } else if (params.strategy === 'Trend Following') {
        html += `
            <div class="param-item">
                <span class="param-label">EMA Window:</span>
                <span class="param-value">${params.ema_window}</span>
            </div>
            <div class="param-item">
                <span class="param-label">RSI Window:</span>
                <span class="param-value">${params.rsi_window}</span>
            </div>
            <div class="param-item">
                <span class="param-label">RSI Overbought:</span>
                <span class="param-value">${params.rsi_overbought}</span>
            </div>
            <div class="param-item">
                <span class="param-label">RSI Oversold:</span>
                <span class="param-value">${params.rsi_oversold}</span>
            </div>
            <div class="param-item">
                <span class="param-label">RSI Overbought:</span>
                <span class="param-value">${params.rsi_overbought}</span>
            </div>
            <div class="param-item">
                <span class="param-label">RSI Oversold:</span>
                <span class="param-value">${params.rsi_oversold}</span>
            </div>
            <div class="param-item">
                <span class="param-label">MACD Fast:</span>
                <span class="param-value">${params.macd_fast}</span>
            </div>
            <div class="param-item">
                <span class="param-label">MACD Slow:</span>
                <span class="param-value">${params.macd_slow}</span>
            </div>
            <div class="param-item">
                <span class="param-label">MACD Signal:</span>
                <span class="param-value">${params.macd_signal}</span>
            </div>
        `;
    }
    paramsContainer.innerHTML = html;
}

function updateMLStrategyResults(results) {
    const mlResultsContainer = document.getElementById('mlStrategyResults');
    if (!results || Object.keys(results).length === 0 || !results.Strategy) {
        mlResultsContainer.innerHTML = '<p class="text-muted">No ML strategy results available.</p>';
        return;
    }

    let html = `
        <div class="param-item">
            <span class="param-label">Strategy:</span>
            <span class="param-value">${results.Strategy}</span>
        </div>
        <div class="param-item">
            <span class="param-label">ML Score:</span>
            <span class="param-value">${results.ML_Score.toFixed(4)}</span>
        </div>
        <div class="param-item">
            <span class="param-label">Net Profit:</span>
            <span class="param-value">$${results['Net Profit'].toFixed(2)}</span>
        </div>
        <div class="param-item">
            <span class="param-label">Win Rate:</span>
            <span class="param-value">${results['Win Rate'].toFixed(2)}%</span>
        </div>
        <div class="param-item">
            <span class="param-label">Max Loss Streak:</span>
            <span class="param-value">${results['Max Loss Streak']}</span>
        </div>
        <div class="param-item">
            <span class="param-label">Profit Factor:</span>
            <span class="param-value">${results['Profit Factor'].toFixed(2)}</span>
        </div>
    `;
    mlResultsContainer.innerHTML = html;
}

function updateOpenTrades(trades) {
    const tradesContainer = document.getElementById('openTrades');
    
    if (!trades || trades.length === 0) {
        tradesContainer.innerHTML = '<p class="text-muted">No open positions</p>';
        return;
    }

    tradesContainer.innerHTML = trades.map(trade => `
        <div class="trade-card ${trade.type.toLowerCase()}">
            <div class="trade-header">
                <span class="trade-type ${trade.type.toLowerCase()}">${trade.type}</span>
                <span class="trade-id">ID: ${trade.id}</span>
            </div>
            <div class="trade-details">
                <div class="trade-detail-item">
                    <span class="trade-detail-label">Entry:</span>
                    <span class="trade-detail-value">${trade.entry_spot_price.toFixed(4)}</span>
                </div>
                <div class="trade-detail-item">
                    <span class="trade-detail-label">Stake:</span>
                    <span class="trade-detail-value">$${trade.stake.toFixed(2)}</span>
                </div>
                <div class="trade-detail-item">
                    <span class="trade-detail-label">TP:</span>
                    <span class="trade-detail-value text-success">${trade.tp_price.toFixed(4)}</span>
                </div>
                <div class="trade-detail-item">
                    <span class="trade-detail-label">SL:</span>
                    <span class="trade-detail-value text-danger">${trade.sl_price.toFixed(4)}</span>
                </div>
            </div>
        </div>
    `).join('');
}

function addConsoleLog(log) {
    const consoleOutput = document.getElementById('consoleOutput');
    
    if (consoleOutput.querySelector('.text-muted')) {
        consoleOutput.innerHTML = '';
    }

    const logLine = document.createElement('div');
    logLine.className = `console-line ${log.level}`;
    logLine.innerHTML = `
        <span class="console-timestamp">[${log.timestamp}]</span>
        <span class="console-message">${escapeHtml(log.message)}</span>
    `;

    consoleOutput.appendChild(logLine);
    consoleOutput.scrollTop = consoleOutput.scrollHeight;

    if (consoleOutput.children.length > 500) {
        consoleOutput.removeChild(consoleOutput.firstChild);
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

async function loadConfig() {
    try {
        const response = await fetch('/api/config');
        currentConfig = await response.json();
    } catch (error) {
        console.error('Error loading config:', error);
        showNotification('Failed to load configuration', 'error');
    }
}

async function loadStatus() {
    try {
        const response = await fetch('/api/status');
        const status = await response.json();
        
        updateBotStatus(status.running);
        updateBalance(status.balance);
        updateOpenTrades(status.open_trades);
        updateStats(status.stats);
        updateParams(status.best_params);
        updateMLStrategyResults(status.ml_strategy_results); // Add this line
    } catch (error) {
        console.error('Error loading status:', error);
    }
}

function loadConfigToModal() {
    if (!currentConfig) return;

    document.getElementById('activeStrategy').value = currentConfig.active_strategy;
    document.getElementById('apiToken').value = currentConfig.api_token;
    document.getElementById('symbol').value = currentConfig.symbol;
    document.getElementById('granularity').value = currentConfig.granularity;
    document.getElementById('optimizationDataDays').value = currentConfig.optimization_data_days;
    document.getElementById('multiplier').value = currentConfig.multiplier;
    document.getElementById('takeProfitPercent').value = currentConfig.take_profit_percent;
    document.getElementById('stopLossPercent').value = currentConfig.stop_loss_percent;
    document.getElementById('tradeStakePercent').value = currentConfig.trade_stake_percent;
    document.getElementById('useFixedStakeAmount').checked = currentConfig.use_fixed_stake_amount;
    document.getElementById('fixedStakeAmount').value = currentConfig.fixed_stake_amount;
    document.getElementById('useMartingale').checked = currentConfig.use_martingale;
    document.getElementById('martingaleMultiplier').value = currentConfig.martingale_multiplier;
    
    // Mean Reversion ranges
    document.getElementById('mrMacdFastMin').value = currentConfig.mean_reversion_ranges.macd_fast_min;
    document.getElementById('mrMacdFastMax').value = currentConfig.mean_reversion_ranges.macd_fast_max;
    document.getElementById('mrMacdFastStep').value = currentConfig.mean_reversion_ranges.macd_fast_step;
    document.getElementById('mrMacdSlowMin').value = currentConfig.mean_reversion_ranges.macd_slow_min;
    document.getElementById('mrMacdSlowMax').value = currentConfig.mean_reversion_ranges.macd_slow_max;
    document.getElementById('mrMacdSlowStep').value = currentConfig.mean_reversion_ranges.macd_slow_step;
    document.getElementById('mrMacdSignalMin').value = currentConfig.mean_reversion_ranges.macd_signal_min;
    document.getElementById('mrMacdSignalMax').value = currentConfig.mean_reversion_ranges.macd_signal_max;
    document.getElementById('mrMacdSignalStep').value = currentConfig.mean_reversion_ranges.macd_signal_step;
    
    document.getElementById('mrBbWindowMin').value = currentConfig.mean_reversion_ranges.bb_window_min;
    document.getElementById('mrBbWindowMax').value = currentConfig.mean_reversion_ranges.bb_window_max;
    document.getElementById('mrBbWindowStep').value = currentConfig.mean_reversion_ranges.bb_window_step;
    document.getElementById('mrBbStdMin').value = currentConfig.mean_reversion_ranges.bb_std_min;
    document.getElementById('mrBbStdMax').value = currentConfig.mean_reversion_ranges.bb_std_max;
    document.getElementById('mrBbStdStep').value = currentConfig.mean_reversion_ranges.bb_std_step;

    // Trend Following ranges
    document.getElementById('tfEmaWindowMin').value = currentConfig.trend_following_ranges.ema_window_min;
    document.getElementById('tfEmaWindowMax').value = currentConfig.trend_following_ranges.ema_window_max;
    document.getElementById('tfEmaWindowStep').value = currentConfig.trend_following_ranges.ema_window_step;
    document.getElementById('tfRsiWindowMin').value = currentConfig.trend_following_ranges.rsi_window_min;
    document.getElementById('tfRsiWindowMax').value = currentConfig.trend_following_ranges.rsi_window_max;
    document.getElementById('tfRsiWindowStep').value = currentConfig.trend_following_ranges.rsi_window_step;
    // RSI overbought/oversold levels are fixed, no min/max/step to load
    document.getElementById('tfMacdFastMin').value = currentConfig.trend_following_ranges.macd_fast_min;
    document.getElementById('tfMacdFastMax').value = currentConfig.trend_following_ranges.macd_fast_max;
    document.getElementById('tfMacdFastStep').value = currentConfig.trend_following_ranges.macd_fast_step;
    document.getElementById('tfMacdSlowMin').value = currentConfig.trend_following_ranges.macd_slow_min;
    document.getElementById('tfMacdSlowMax').value = currentConfig.trend_following_ranges.macd_slow_max;
    document.getElementById('tfMacdSlowStep').value = currentConfig.trend_following_ranges.macd_slow_step;
    document.getElementById('tfMacdSignalMin').value = currentConfig.trend_following_ranges.macd_signal_min;
    document.getElementById('tfMacdSignalMax').value = currentConfig.trend_following_ranges.macd_signal_max;
    document.getElementById('tfMacdSignalStep').value = currentConfig.trend_following_ranges.macd_signal_step;

    updateIndicatorVisibility(); // Update visibility after loading config
}

async function saveConfig() {
    const newConfig = {
        active_strategy: document.getElementById('activeStrategy').value,
        api_token: document.getElementById('apiToken').value,
        symbol: document.getElementById('symbol').value,
        granularity: parseInt(document.getElementById('granularity').value),
        optimization_data_days: parseInt(document.getElementById('optimizationDataDays').value),
        multiplier: parseInt(document.getElementById('multiplier').value),
        take_profit_percent: parseFloat(document.getElementById('takeProfitPercent').value),
        stop_loss_percent: parseFloat(document.getElementById('stopLossPercent').value),
        trade_stake_percent: parseFloat(document.getElementById('tradeStakePercent').value),
        use_fixed_stake_amount: document.getElementById('useFixedStakeAmount').checked,
        fixed_stake_amount: parseFloat(document.getElementById('fixedStakeAmount').value),
        use_martingale: document.getElementById('useMartingale').checked,
        martingale_multiplier: parseFloat(document.getElementById('martingaleMultiplier').value),
        ml_weights: currentConfig.ml_weights, // Keep existing ML weights
        start_balance_backtest: currentConfig.start_balance_backtest, // Keep existing start balance
        ws_url: currentConfig.ws_url, // Keep existing WS URL
        
        mean_reversion_ranges: {
            macd_fast_min: parseInt(document.getElementById('mrMacdFastMin').value),
            macd_fast_max: parseInt(document.getElementById('mrMacdFastMax').value),
            macd_fast_step: parseInt(document.getElementById('mrMacdFastStep').value),
            macd_slow_min: parseInt(document.getElementById('mrMacdSlowMin').value),
            macd_slow_max: parseInt(document.getElementById('mrMacdSlowMax').value),
            macd_slow_step: parseInt(document.getElementById('mrMacdSlowStep').value),
            macd_signal_min: parseInt(document.getElementById('mrMacdSignalMin').value),
            macd_signal_max: parseInt(document.getElementById('mrMacdSignalMax').value),
            macd_signal_step: parseInt(document.getElementById('mrMacdSignalStep').value),
            
            bb_window_min: parseInt(document.getElementById('mrBbWindowMin').value),
            bb_window_max: parseInt(document.getElementById('mrBbWindowMax').value),
            bb_window_step: parseInt(document.getElementById('mrBbWindowStep').value),
            bb_std_min: parseFloat(document.getElementById('mrBbStdMin').value),
            bb_std_max: parseFloat(document.getElementById('mrBbStdMax').value),
            bb_std_step: parseFloat(document.getElementById('mrBbStdStep').value)
        },
        trend_following_ranges: {
            ema_window_min: parseInt(document.getElementById('tfEmaWindowMin').value),
            ema_window_max: parseInt(document.getElementById('tfEmaWindowMax').value),
            ema_window_step: parseInt(document.getElementById('tfEmaWindowStep').value),
            rsi_window_min: parseInt(document.getElementById('tfRsiWindowMin').value),
            rsi_window_max: parseInt(document.getElementById('tfRsiWindowMax').value),
            rsi_window_step: parseInt(document.getElementById('tfRsiWindowStep').value),
            // RSI overbought/oversold levels are fixed, no min/max/step to save
            macd_fast_min: parseInt(document.getElementById('tfMacdFastMin').value),
            macd_fast_max: parseInt(document.getElementById('tfMacdFastMax').value),
            macd_fast_step: parseInt(document.getElementById('tfMacdFastStep').value),
            macd_slow_min: parseInt(document.getElementById('tfMacdSlowMin').value),
            macd_slow_max: parseInt(document.getElementById('tfMacdSlowMax').value),
            macd_slow_step: parseInt(document.getElementById('tfMacdSlowStep').value),
            macd_signal_min: parseInt(document.getElementById('tfMacdSignalMin').value),
            macd_signal_max: parseInt(document.getElementById('tfMacdSignalMax').value),
            macd_signal_step: parseInt(document.getElementById('tfMacdSignalStep').value)
        }
    };

    try {
        const response = await fetch('/api/config', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(newConfig),
        });

        const result = await response.json();

        if (result.success) {
            currentConfig = newConfig;
            configModal.hide();
            showNotification('Configuration saved successfully', 'success');
        } else {
            showNotification(result.message, 'error');
        }
    } catch (error) {
        console.error('Error saving config:', error);
        showNotification('Failed to save configuration', 'error');
    }
}

function showNotification(message, type) {
    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${type === 'success' ? 'success' : 'danger'} alert-dismissible fade show position-fixed top-0 start-50 translate-middle-x mt-3`;
    alertDiv.style.zIndex = '9999';
    alertDiv.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;

    document.body.appendChild(alertDiv);

    setTimeout(() => {
        alertDiv.remove();
    }, 5000);
}
