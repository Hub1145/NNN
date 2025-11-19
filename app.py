from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import json
import logging
import os
from bot_engine import TradingBotEngine

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SESSION_SECRET', 'dev-secret-key-change-in-production')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

config_file = 'config.json'
bot_engine = None

def load_config():
    with open(config_file, 'r') as f:
        return json.load(f)

def save_config(config):
    with open(config_file, 'w') as f:
        json.dump(config, f, indent=2)

def emit_to_client(event, data):
    socketio.emit(event, data)

@app.before_request
def log_config_on_request():
    if request.path.startswith('/api/config'):
        config = load_config()

@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/api/config', methods=['GET'])
def get_config():
    config = load_config()
    return jsonify(config)

@app.route('/api/config', methods=['POST'])
def update_config():
    global bot_engine
    
    try:
        new_config = request.json
        
        if bot_engine and bot_engine.is_running:
            return jsonify({'success': False, 'message': 'Please stop the bot before updating configuration'}), 400
        
        save_config(new_config)
        
        return jsonify({'success': True, 'message': 'Configuration updated successfully'})
    
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/status', methods=['GET'])
def get_status():
    if not bot_engine:
        return jsonify({
            'running': False,
            'balance': 0.0,
            'open_trades': [],
            'stats': {},
            'best_params': {},
            'ml_strategy_results': {} # Include empty ML results
        })
    
    return jsonify({
        'running': bot_engine.is_running,
        'balance': bot_engine.current_balance,
        'open_trades': bot_engine.open_trades,
        'stats': bot_engine.get_stats(),
        'best_params': bot_engine.best_params,
        'ml_strategy_results': bot_engine.ml_strategy_results # Include ML results
    })

@socketio.on('connect')
def handle_connect():
    logging.info('Client connected')
    emit('connection_status', {'connected': True})
    
    if bot_engine:
        emit('bot_status', {'running': bot_engine.is_running})
        emit('balance_update', {'balance': bot_engine.current_balance})
        emit('trades_update', {'trades': bot_engine.open_trades})
        emit('stats_update', bot_engine.get_stats())
        emit('params_update', bot_engine.best_params)
        
        for log in list(bot_engine.console_logs):
            emit('console_log', log)

@socketio.on('disconnect')
def handle_disconnect():
    logging.info('Client disconnected')

@socketio.on('start_bot')
def handle_start_bot():
    global bot_engine
    
    try:
        config = load_config() # This is line 111
        
        if bot_engine and bot_engine.is_running:
            emit('error', {'message': 'Bot is already running'})
            return
        
        try:
            bot_engine = TradingBotEngine(config_file, emit_to_client) # Pass config_file
            bot_engine.start()
            
            emit('bot_status', {'running': True})
            emit('success', {'message': 'Bot started successfully'})
        except Exception as e:
            logging.error(f'Error during TradingBotEngine instantiation or start: {str(e)}', exc_info=True)
            emit('error', {'message': f'Failed to start bot: {str(e)}'})
    except Exception as e: # Catch errors from load_config()
        logging.error(f'Error loading configuration in handle_start_bot: {str(e)}', exc_info=True)
        emit('error', {'message': f'Failed to start bot due to config error: {str(e)}'})

@socketio.on('stop_bot')
def handle_stop_bot():
    global bot_engine
    
    try:
        if not bot_engine or not bot_engine.is_running:
            emit('error', {'message': 'Bot is not running'})
            return
        
        bot_engine.stop()
        
        emit('bot_status', {'running': False})
        emit('success', {'message': 'Bot stopped successfully'})
    
    except Exception as e:
        logging.error(f'Error stopping bot: {str(e)}')
        emit('error', {'message': f'Failed to stop bot: {str(e)}'})

@socketio.on('clear_console')
def handle_clear_console():
    if bot_engine:
        bot_engine.console_logs.clear()
    emit('console_cleared', {})

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, use_reloader=False, log_output=True, allow_unsafe_werkzeug=True)
