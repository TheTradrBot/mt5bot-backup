
"""
MT5 Bridge Server - Run this on your Windows VM with MT5 installed.
It receives HTTP requests from Replit and executes them on MT5.

Installation on Windows:
1. pip install MetaTrader5 flask flask-cors
2. python mt5_bridge_server.py
"""

import MetaTrader5 as mt5
from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime, timezone
import time

app = Flask(__name__)
CORS(app)

# MT5 connection state
mt5_connected = False
mt5_account_info = {}


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({
        'status': 'online',
        'mt5_connected': mt5_connected,
        'timestamp': datetime.now(timezone.utc).isoformat()
    })


@app.route('/connect', methods=['POST'])
def connect():
    """Connect to MT5 terminal."""
    global mt5_connected, mt5_account_info
    
    data = request.json
    server = data.get('server')
    login = data.get('login')
    password = data.get('password')
    
    if not mt5.initialize():
        return jsonify({'error': 'MT5 initialize failed', 'code': mt5.last_error()}), 500
    
    authorized = mt5.login(login, password=password, server=server)
    
    if not authorized:
        error = mt5.last_error()
        mt5.shutdown()
        return jsonify({'error': 'Login failed', 'code': error}), 401
    
    mt5_connected = True
    account_info = mt5.account_info()
    
    mt5_account_info = {
        'login': account_info.login,
        'balance': account_info.balance,
        'equity': account_info.equity,
        'margin': account_info.margin,
        'leverage': account_info.leverage,
        'server_time': datetime.now(timezone.utc).isoformat()
    }
    
    return jsonify({'success': True, 'account': mt5_account_info})


@app.route('/symbols', methods=['POST'])
def get_symbols():
    """Get available symbols and map them."""
    if not mt5_connected:
        return jsonify({'error': 'Not connected to MT5'}), 400
    
    data = request.json
    our_symbols = data.get('symbols', [])
    
    all_symbols = mt5.symbols_get()
    broker_symbols = [s.name for s in all_symbols] if all_symbols else []
    
    symbol_map = {}
    
    for our_sym in our_symbols:
        candidates = [
            our_sym.replace("_", ""),
            our_sym.replace("_", "."),
            our_sym,
        ]
        
        for candidate in candidates:
            if candidate in broker_symbols:
                info = mt5.symbol_info(candidate)
                symbol_map[our_sym] = {
                    'broker_symbol': candidate,
                    'digits': info.digits,
                    'point': info.point,
                    'min_lot': info.volume_min,
                    'max_lot': info.volume_max,
                    'spread': info.spread
                }
                break
    
    return jsonify({'symbols': symbol_map})


@app.route('/market_data', methods=['POST'])
def get_market_data():
    """Get current market data for a symbol."""
    if not mt5_connected:
        return jsonify({'error': 'Not connected to MT5'}), 400
    
    data = request.json
    symbol = data.get('symbol')
    
    tick = mt5.symbol_info_tick(symbol)
    info = mt5.symbol_info(symbol)
    
    if not tick or not info:
        return jsonify({'error': f'Symbol {symbol} not found'}), 404
    
    return jsonify({
        'bid': tick.bid,
        'ask': tick.ask,
        'spread': tick.ask - tick.bid,
        'time': datetime.fromtimestamp(tick.time, tz=timezone.utc).isoformat()
    })


@app.route('/execute_trade', methods=['POST'])
def execute_trade():
    """Execute a market order."""
    if not mt5_connected:
        return jsonify({'error': 'Not connected to MT5'}), 400
    
    data = request.json
    symbol = data.get('symbol')
    direction = data.get('direction')
    volume = data.get('volume')
    sl = data.get('sl')
    tp = data.get('tp')
    
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        return jsonify({'error': f'Failed to get tick for {symbol}'}), 404
    
    if direction == 'bullish':
        order_type = mt5.ORDER_TYPE_BUY
        price = tick.ask
    else:
        order_type = mt5.ORDER_TYPE_SELL
        price = tick.bid
    
    request_obj = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": 20,
        "magic": 234000,
        "comment": "Blueprint Remote",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    start_time = time.time()
    result = mt5.order_send(request_obj)
    execution_time_ms = (time.time() - start_time) * 1000
    
    if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
        error_code = result.retcode if result else mt5.last_error()
        error_msg = result.comment if result else "Order send failed"
        return jsonify({'error': error_msg, 'code': error_code}), 500
    
    account_info = mt5.account_info()
    
    return jsonify({
        'success': True,
        'order_id': result.order,
        'deal_id': result.deal,
        'executed_price': result.price,
        'volume': result.volume,
        'slippage': result.price - price,
        'execution_time_ms': execution_time_ms,
        'balance': account_info.balance if account_info else 0,
        'timestamp': datetime.now(timezone.utc).isoformat()
    })


@app.route('/close_position', methods=['POST'])
def close_position():
    """Close an open position."""
    if not mt5_connected:
        return jsonify({'error': 'Not connected to MT5'}), 400
    
    data = request.json
    symbol = data.get('symbol')
    volume = data.get('volume')
    direction = data.get('direction')
    
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        return jsonify({'error': f'Symbol {symbol} not found'}), 404
    
    if direction == 'bullish':
        order_type = mt5.ORDER_TYPE_SELL
        price = tick.bid
    else:
        order_type = mt5.ORDER_TYPE_BUY
        price = tick.ask
    
    request_obj = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        "deviation": 20,
        "magic": 234000,
        "comment": "Blueprint Close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    result = mt5.order_send(request_obj)
    
    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
        return jsonify({
            'success': True,
            'executed_price': result.price,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
    else:
        error_code = result.retcode if result else mt5.last_error()
        return jsonify({'error': 'Close failed', 'code': error_code}), 500


@app.route('/disconnect', methods=['POST'])
def disconnect():
    """Disconnect from MT5."""
    global mt5_connected
    
    if mt5_connected:
        mt5.shutdown()
        mt5_connected = False
    
    return jsonify({'success': True})


if __name__ == '__main__':
    print("MT5 Bridge Server starting...")
    print("Make sure MT5 terminal is running on this machine!")
    print("Starting server on http://0.0.0.0:5555")
    app.run(host='0.0.0.0', port=5555, debug=False)
