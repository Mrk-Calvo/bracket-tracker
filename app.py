from flask import Flask, render_template_string, request, jsonify, session, redirect, url_for, send_file
from flask_socketio import SocketIO
import sqlite3
from datetime import datetime, timezone, timedelta
import os
import hashlib
import secrets
from functools import wraps
import json
import io
import requests
import csv
import time

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'bracket-tracker-2024-secure-key')

# SocketIO configuration for Render.com
socketio = SocketIO(
    app, 
    cors_allowed_origins="*", 
    async_mode='threading',
    logger=True,
    engineio_logger=True,
    ping_timeout=60,
    ping_interval=25
)

# Slack webhook URL for alerts
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL', '')

# SKU to Bracket Mapping
SKU_BRACKET_MAPPING = {
    'PB1-X101-BL': ['H7-282'],
    'PB1-28A0113-BL': ['H6-623A', 'H6-623B', 'H6-623C'],
    'PB1-18A0101-WH': ['H9-923A', 'H9-923B', 'H9-923C'],
    'PB1-38A0101-BK': ['H7-304'],
}

# SKU to Set Type Mapping
SKU_SET_MAPPING = {
    'PB1-X101-BL': 'H7-282',
    'PB1-28A0113-BL': 'H6',
    'PB1-18A0101-WH': 'H9',
    'PB1-38A0101-BK': 'H7-304',
}

def hash_password(password):
    """Hash a password for storing."""
    return hashlib.sha256(password.encode()).hexdigest()

def get_db_connection():
    """Get database connection"""
    conn = sqlite3.connect('nzxt_inventory.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    """Initialize the database with required tables and data"""
    conn = get_db_connection()
    
    try:
        # Create tables
        conn.execute('''
            CREATE TABLE IF NOT EXISTS items
            (id INTEGER PRIMARY KEY AUTOINCREMENT,
             name TEXT NOT NULL UNIQUE,
             description TEXT,
             case_type TEXT,
             quantity INTEGER DEFAULT 0,
             min_stock INTEGER DEFAULT 5,
             created_at DATETIME DEFAULT CURRENT_TIMESTAMP)
        ''')
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS transactions
            (id INTEGER PRIMARY KEY AUTOINCREMENT,
             item_id INTEGER,
             change INTEGER,
             station TEXT,
             notes TEXT,
             username TEXT,
             timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)
        ''')
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS work_orders
            (id INTEGER PRIMARY KEY AUTOINCREMENT,
             order_number TEXT NOT NULL,
             set_type TEXT NOT NULL,
             required_sets INTEGER NOT NULL,
             include_spacer BOOLEAN DEFAULT 0,
             status TEXT DEFAULT 'active',
             created_at DATETIME DEFAULT CURRENT_TIMESTAMP)
        ''')
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS external_work_orders
            (id INTEGER PRIMARY KEY AUTOINCREMENT,
             external_order_number TEXT NOT NULL UNIQUE,
             sku TEXT NOT NULL,
             quantity INTEGER NOT NULL,
             required_brackets TEXT NOT NULL,
             status TEXT DEFAULT 'active',
             created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
             last_synced DATETIME DEFAULT CURRENT_TIMESTAMP)
        ''')
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS assembly_orders
            (id INTEGER PRIMARY KEY AUTOINCREMENT,
             work_order_id INTEGER NOT NULL,
             status TEXT DEFAULT 'ready',
             moved_at DATETIME DEFAULT CURRENT_TIMESTAMP,
             started_at DATETIME,
             completed_at DATETIME,
             assembled_by TEXT,
             notes TEXT)
        ''')
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users
            (id INTEGER PRIMARY KEY AUTOINCREMENT,
             username TEXT NOT NULL UNIQUE,
             password_hash TEXT NOT NULL,
             role TEXT NOT NULL DEFAULT 'viewer',
             created_at DATETIME DEFAULT CURRENT_TIMESTAMP)
        ''')
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS settings
            (id INTEGER PRIMARY KEY AUTOINCREMENT,
             key TEXT NOT NULL UNIQUE,
             value TEXT NOT NULL)
        ''')
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS chat_messages
            (id INTEGER PRIMARY KEY AUTOINCREMENT,
             sender TEXT NOT NULL,
             message TEXT NOT NULL,
             timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)
        ''')
        
        # NEW TABLE: Store input values persistently
        conn.execute('''
            CREATE TABLE IF NOT EXISTS input_values
            (id INTEGER PRIMARY KEY AUTOINCREMENT,
             user_id INTEGER NOT NULL,
             input_key TEXT NOT NULL,
             input_value TEXT NOT NULL,
             station TEXT NOT NULL,
             last_updated DATETIME DEFAULT CURRENT_TIMESTAMP,
             UNIQUE(user_id, input_key))
        ''')
        
        # Add initial brackets
        initial_items = [
            ('H6-623A', 'H6 Bracket 623A', 'H6', 15, 10),
            ('H6-623B', 'H6 Bracket 623B', 'H6', 12, 10),
            ('H6-623C', 'H6 Bracket 623C', 'H6', 8, 5),
            ('H7-282', 'H7 Bracket 282', 'H7', 5, 5),
            ('H7-304', 'H7 Bracket 304', 'H7', 5, 5),
            ('H9-923A', 'H9 Bracket 923A', 'H9', 20, 8),
            ('H9-923B', 'H9 Bracket 923B', 'H9', 18, 8),
            ('H9-923C', 'H9 Bracket 923C', 'H9', 6, 5),
            ('H9-SPACER', 'H9 Spacer (Optional)', 'H9', 25, 10)
        ]
        
        for item in initial_items:
            conn.execute('INSERT OR IGNORE INTO items (name, description, case_type, quantity, min_stock) VALUES (?, ?, ?, ?, ?)', item)
        
        # Add sample work orders
        sample_work_orders = [
            ('WO-001', 'H6', 10, False),
            ('WO-002', 'H7-282', 5, False),
            ('WO-003', 'H7-304', 5, False),
            ('WO-004', 'H9', 8, True)
        ]
        
        for wo in sample_work_orders:
            conn.execute('INSERT OR IGNORE INTO work_orders (order_number, set_type, required_sets, include_spacer) VALUES (?, ?, ?, ?)', wo)
        
        # Add default users
        default_users = [
            ('admin', hash_password('admin123'), 'admin'),
            ('operator', hash_password('operator123'), 'operator'),
            ('viewer', hash_password('viewer123'), 'viewer')
        ]
        
        for user in default_users:
            conn.execute('INSERT OR IGNORE INTO users (username, password_hash, role) VALUES (?, ?, ?)', user)
        
        # Add default settings
        default_settings = [
            ('low_stock_threshold', '5'),
            ('critical_stock_threshold', '2'),
            ('slack_webhook_url', SLACK_WEBHOOK_URL),
            ('sku_mapping', json.dumps(SKU_BRACKET_MAPPING)),
            ('sku_set_mapping', json.dumps(SKU_SET_MAPPING))
        ]
        
        for setting in default_settings:
            conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', setting)
        
        # Add welcome chat message
        welcome_message = ('System', 'Welcome to the Bracket Inventory Tracker! Use this chat to communicate with your team.')
        conn.execute('INSERT OR IGNORE INTO chat_messages (sender, message) VALUES (?, ?)', welcome_message)
        
        conn.commit()
        print("✅ Database initialized successfully")
        
    except Exception as e:
        print(f"❌ Database initialization error: {e}")
        conn.rollback()
    finally:
        conn.close()

def get_setting(key, default=None):
    """Get a setting from the database"""
    conn = get_db_connection()
    try:
        setting = conn.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
        return setting['value'] if setting else default
    except Exception as e:
        print(f"❌ Error getting setting {key}: {e}")
        return default
    finally:
        conn.close()

def update_setting(key, value):
    """Update a setting in the database"""
    conn = get_db_connection()
    try:
        conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
        conn.commit()
    except Exception as e:
        print(f"❌ Error updating setting {key}: {e}")
        conn.rollback()
    finally:
        conn.close()

def get_sku_mapping():
    """Get SKU to bracket mapping from settings"""
    mapping_json = get_setting('sku_mapping', '{}')
    try:
        return json.loads(mapping_json)
    except:
        return SKU_BRACKET_MAPPING

def get_sku_set_mapping():
    """Get SKU to set type mapping from settings"""
    mapping_json = get_setting('sku_set_mapping', '{}')
    try:
        return json.loads(mapping_json)
    except:
        return SKU_SET_MAPPING

def send_slack_notification(message):
    """Send notification to Slack"""
    webhook_url = get_setting('slack_webhook_url')
    if not webhook_url:
        return False
    
    try:
        payload = {
            "text": message,
            "username": "Bracket Inventory Tracker",
            "icon_emoji": ":package:"
        }
        
        response = requests.post(
            webhook_url, 
            json=payload, 
            timeout=10,
            headers={'Content-Type': 'application/json'}
        )
        
        return response.status_code == 200
            
    except Exception as e:
        print(f"❌ Slack notification failed: {e}")
        return False

def get_components_for_set_type(set_type, include_spacer=False):
    """Get components for a set type"""
    component_map = {
        'H6': ['H6-623A', 'H6-623B', 'H6-623C'],
        'H7-282': ['H7-282'],
        'H7-304': ['H7-304'],
        'H9': ['H9-923A', 'H9-923B', 'H9-923C'] + (['H9-SPACER'] if include_spacer else [])
    }
    return component_map.get(set_type, [])

def broadcast_update():
    """Broadcast inventory update to all clients"""
    conn = get_db_connection()
    try:
        items = conn.execute('SELECT * FROM items ORDER BY name').fetchall()
        work_orders = conn.execute("SELECT * FROM work_orders WHERE status = 'active' ORDER BY set_type, created_at").fetchall()
        assembly_orders = conn.execute('''
            SELECT ao.*, wo.order_number, wo.set_type, wo.required_sets, wo.include_spacer
            FROM assembly_orders ao
            JOIN work_orders wo ON ao.work_order_id = wo.id
            ORDER BY 
                CASE WHEN ao.status = 'ready' THEN 1
                     WHEN ao.status = 'building' THEN 2
                     WHEN ao.status = 'completed' THEN 3
                     ELSE 4 END,
                ao.moved_at DESC
        ''').fetchall()
        
        items_data = [dict(item) for item in items]
        work_orders_data = [dict(wo) for wo in work_orders]
        assembly_orders_data = [dict(ao) for ao in assembly_orders]
        
        socketio.emit('inventory_update', {
            'items': items_data,
            'work_orders': work_orders_data,
            'assembly_orders': assembly_orders_data
        })
        
    except Exception as e:
        print(f"❌ Error broadcasting update: {e}")
    finally:
        conn.close()

# NEW: Input value management functions
def save_input_value(user_id, input_key, input_value, station):
    """Save input value to database"""
    conn = get_db_connection()
    try:
        conn.execute('''
            INSERT OR REPLACE INTO input_values (user_id, input_key, input_value, station, last_updated)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, input_key, input_value, station, datetime.now()))
        conn.commit()
        return True
    except Exception as e:
        print(f"❌ Error saving input value: {e}")
        return False
    finally:
        conn.close()

def get_input_values(user_id, station=None):
    """Get input values for a user"""
    conn = get_db_connection()
    try:
        if station:
            input_values = conn.execute(
                'SELECT input_key, input_value FROM input_values WHERE user_id = ? AND station = ?',
                (user_id, station)
            ).fetchall()
        else:
            input_values = conn.execute(
                'SELECT input_key, input_value FROM input_values WHERE user_id = ?',
                (user_id,)
            ).fetchall()
        
        return {row['input_key']: row['input_value'] for row in input_values}
    except Exception as e:
        print(f"❌ Error getting input values: {e}")
        return {}
    finally:
        conn.close()

def clear_input_value(user_id, input_key):
    """Clear specific input value"""
    conn = get_db_connection()
    try:
        conn.execute('DELETE FROM input_values WHERE user_id = ? AND input_key = ?', (user_id, input_key))
        conn.commit()
        return True
    except Exception as e:
        print(f"❌ Error clearing input value: {e}")
        return False
    finally:
        conn.close()

def clear_station_inputs(user_id, station):
    """Clear all input values for a specific station"""
    conn = get_db_connection()
    try:
        conn.execute('DELETE FROM input_values WHERE user_id = ? AND station = ?', (user_id, station))
        conn.commit()
        return True
    except Exception as e:
        print(f"❌ Error clearing station inputs: {e}")
        return False
    finally:
        conn.close()

# Authentication decorators
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'success': False, 'error': 'Authentication required'}), 401
        return f(*args, **kwargs)
    return decorated_function

def role_required(role):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                return jsonify({'success': False, 'error': 'Authentication required'}), 401
            if session['role'] not in ['admin', 'operator'] and role in ['admin', 'operator']:
                return jsonify({'success': False, 'error': 'Insufficient permissions'}), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# SocketIO events
@socketio.on('connect')
def handle_connect():
    print(f"🔗 Client connected: {request.sid}")
    broadcast_update()

@socketio.on('inventory_change')
@login_required
def handle_inventory_change(data):
    try:
        if session['role'] not in ['admin', 'operator']:
            socketio.emit('error', {'message': 'Insufficient permissions'}, room=request.sid)
            return
            
        item_id = data.get('item_id')
        change = data.get('change')
        station = data.get('station', 'Unknown')
        notes = data.get('notes', '')
        
        if not item_id:
            socketio.emit('error', {'message': 'Item ID is required'}, room=request.sid)
            return
        
        conn = get_db_connection()
        item = conn.execute('SELECT * FROM items WHERE id = ?', (item_id,)).fetchone()
        
        if not item:
            socketio.emit('error', {'message': 'Item not found'}, room=request.sid)
            return
        
        new_quantity = item['quantity'] + change
        
        if new_quantity < 0:
            socketio.emit('error', {
                'message': f'Cannot remove {abs(change)}. Only {item["quantity"]} available.'
            }, room=request.sid)
            return
        
        conn.execute('UPDATE items SET quantity = ? WHERE id = ?', (new_quantity, item_id))
        conn.execute('''
            INSERT INTO transactions (item_id, change, station, notes, username, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (item_id, change, station, notes, session['username'], datetime.now()))
        
        conn.commit()
        broadcast_update()
        
        print(f"📊 {session['username']} at {station}: {item['name']} {change:+d} = {new_quantity}")
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        socketio.emit('error', {'message': f'Error: {str(e)}'}, room=request.sid)
    finally:
        conn.close()

@socketio.on('save_input_value')
@login_required
def handle_save_input_value(data):
    """Save input value to database"""
    try:
        input_key = data.get('input_key')
        input_value = data.get('input_value')
        station = data.get('station', 'unknown')
        
        if not input_key:
            return
        
        success = save_input_value(session['user_id'], input_key, input_value, station)
        if success:
            socketio.emit('input_value_saved', {'input_key': input_key}, room=request.sid)
        
    except Exception as e:
        print(f"❌ Error saving input value: {e}")

@socketio.on('clear_input_value')
@login_required
def handle_clear_input_value(data):
    """Clear input value from database"""
    try:
        input_key = data.get('input_key')
        
        if not input_key:
            return
        
        success = clear_input_value(session['user_id'], input_key)
        if success:
            socketio.emit('input_value_cleared', {'input_key': input_key}, room=request.sid)
        
    except Exception as e:
        print(f"❌ Error clearing input value: {e}")

@socketio.on('chat_message')
@login_required
def handle_chat_message(data):
    message = data.get('message', '').strip()
    sender = data.get('sender', 'Unknown')
    
    if not message:
        return
    
    conn = get_db_connection()
    try:
        conn.execute('INSERT INTO chat_messages (sender, message) VALUES (?, ?)', (sender, message))
        conn.commit()
        
        socketio.emit('chat_message', {
            'sender': sender,
            'message': message,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        print(f"❌ Error saving chat message: {str(e)}")
        conn.rollback()
    finally:
        conn.close()

@socketio.on('system_chat_message')
def handle_system_chat_message(data):
    message = data.get('message', '').strip()
    
    if not message:
        return
    
    conn = get_db_connection()
    try:
        conn.execute('INSERT INTO chat_messages (sender, message) VALUES (?, ?)', ('System', message))
        conn.commit()
        
        socketio.emit('chat_message', {
            'sender': 'System',
            'message': message,
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        print(f"❌ Error saving system chat message: {str(e)}")
        conn.rollback()
    finally:
        conn.close()

# HTML Template
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Bracket Inventory Tracker</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.2/socket.io.min.js"></script>
    <style>
        :root {
            --primary: #007acc;
            --success: #28a745;
            --danger: #dc3545;
            --warning: #ffc107;
            --info: #17a2b8;
            --dark: #1a1a1a;
            --light: #f8f9fa;
        }
        
        body { 
            font-family: Arial, sans-serif; 
            margin: 0; 
            padding: 15px; 
            background: #f8f9fa;
        }
        .container { 
            max-width: 1400px; 
            margin: 0 auto; 
            background: white; 
            padding: 15px; 
            border-radius: 6px;
            box-shadow: 0 1px 5px rgba(0,0,0,0.1);
        }
        .header { 
            background: #1a1a1a; 
            color: white; 
            padding: 15px; 
            border-radius: 6px;
            margin-bottom: 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
        }
        .user-info {
            display: flex;
            align-items: center;
            gap: 15px;
            font-size: 14px;
        }
        .user-role {
            background: var(--primary);
            padding: 4px 8px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: bold;
        }
        .logout-btn {
            background: var(--danger);
            color: white;
            border: none;
            padding: 6px 12px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 12px;
        }
        .tabs { 
            display: flex; 
            background: #2d2d2d; 
            border-radius: 6px;
            margin-bottom: 15px;
            flex-wrap: wrap;
        }
        .tab { 
            padding: 12px 20px; 
            color: white; 
            cursor: pointer;
            border: none;
            background: none;
            font-size: 13px;
            flex: 1;
            min-width: 110px;
        }
        .tab.active { 
            background: var(--primary); 
        }
        .tab-content { 
            display: none; 
            padding: 15px 0;
        }
        .tab-content.active { 
            display: block; 
        }
        
        .bracket-list {
            display: grid;
            gap: 8px;
            margin-bottom: 20px;
        }
        .bracket-category {
            background: #f8f9fa;
            padding: 12px;
            border-radius: 6px;
            margin-bottom: 15px;
        }
        .category-header {
            font-size: 16px;
            font-weight: bold;
            color: #1a1a1a;
            margin-bottom: 12px;
            padding-bottom: 8px;
            border-bottom: 1px solid #e9ecef;
        }
        .bracket-item {
            display: grid;
            grid-template-columns: 180px 80px 140px 140px;
            gap: 12px;
            padding: 10px;
            border-bottom: 1px solid #e9ecef;
            align-items: center;
            font-size: 13px;
        }
        .bracket-item.header {
            font-weight: bold;
            background: #e9ecef;
            border-radius: 4px;
        }
        .bracket-name {
            font-weight: 500;
            color: #333;
        }
        .current-qty {
            text-align: center;
            font-weight: bold;
            font-size: 14px;
        }
        .qty-input {
            width: 70px;
            padding: 6px;
            border: 1px solid #ddd;
            border-radius: 3px;
            text-align: center;
            font-size: 12px;
        }
        .btn {
            padding: 6px 12px;
            border: none;
            border-radius: 3px;
            cursor: pointer;
            font-size: 11px;
            font-weight: bold;
        }
        .btn-add {
            background: var(--success);
            color: white;
        }
        .btn-remove {
            background: var(--danger);
            color: white;
        }
        .btn-complete {
            background: var(--info);
            color: white;
        }
        .btn-delete {
            background: #6c757d;
            color: white;
        }
        .btn-export {
            background: var(--primary);
            color: white;
        }
        .btn-convert {
            background: var(--info);
            color: white;
        }
        .btn-upload {
            background: var(--success);
            color: white;
        }
        .btn-move {
            background: #6f42c1;
            color: white;
        }
        .btn-print {
            background: #17a2b8;
            color: white;
        }
        
        .form-section {
            background: #f8f9fa;
            padding: 15px;
            border-radius: 6px;
            margin: 15px 0;
        }
        .form-row {
            display: flex;
            gap: 12px;
            margin-bottom: 12px;
            align-items: end;
            flex-wrap: wrap;
        }
        .form-group {
            flex: 1;
            min-width: 180px;
        }
        .form-group-small {
            flex: 0.5;
            min-width: 120px;
        }
        label {
            display: block;
            margin-bottom: 4px;
            font-weight: bold;
            color: #333;
            font-size: 12px;
        }
        input, select {
            width: 100%;
            padding: 8px;
            border: 1px solid #ddd;
            border-radius: 3px;
            font-size: 12px;
        }
        
        .work-order-section {
            background: #e8f5e8;
            padding: 12px;
            border-radius: 6px;
            margin: 12px 0;
            border: 1px solid var(--success);
        }
        .work-order-item {
            padding: 10px;
            border: 1px solid var(--info);
            margin-bottom: 8px;
            background: white;
            border-radius: 5px;
        }
        .work-order-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 6px;
        }
        .work-order-title {
            font-weight: bold;
            font-size: 14px;
            color: #1a1a1a;
        }
        .work-order-actions {
            display: flex;
            gap: 6px;
        }
        .component-list {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 6px;
            margin-top: 6px;
        }
        .component-item {
            padding: 5px;
            background: #f8f9fa;
            border-radius: 3px;
            text-align: center;
            font-size: 11px;
        }
        .component-ok {
            border-left: 2px solid var(--success);
            background: #d4edda;
        }
        .component-missing {
            border-left: 2px solid var(--danger);
            background: #f8d7da;
        }
        
        .missing-warning {
            background: #f8d7da;
            color: #721c24;
            padding: 6px;
            border-radius: 3px;
            margin-top: 6px;
            font-size: 11px;
            border-left: 2px solid var(--danger);
        }
        
        .status-bar {
            display: flex;
            gap: 25px;
            margin-top: 12px;
            padding: 12px;
            background: #e8f5e8;
            border-radius: 6px;
            font-size: 14px;
            font-weight: bold;
            border: 1px solid var(--success);
        }
        .status-item {
            display: flex;
            flex-direction: column;
            align-items: center;
        }
        .status-label {
            font-size: 11px;
            color: #666;
            margin-bottom: 3px;
        }
        .status-value {
            color: #1a1a1a;
        }
        .status-connected {
            color: var(--success);
        }
        .status-disconnected {
            color: var(--danger);
        }
        
        .low-stock {
            background: #fff3cd !important;
        }
        .critical {
            background: #f8d7da !important;
        }
        
        .permission-denied {
            background: #f8d7da;
            color: #721c24;
            padding: 15px;
            border-radius: 6px;
            text-align: center;
            margin: 20px 0;
            border-left: 4px solid var(--danger);
        }
        
        .login-container {
            max-width: 400px;
            margin: 100px auto;
            padding: 30px;
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        .login-title {
            text-align: center;
            margin-bottom: 25px;
            color: var(--dark);
        }
        .login-form {
            display: flex;
            flex-direction: column;
            gap: 15px;
        }
        .login-input {
            padding: 12px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 14px;
        }
        .login-btn {
            background: var(--primary);
            color: white;
            border: none;
            padding: 12px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 16px;
            font-weight: bold;
        }
        
        @media (max-width: 768px) {
            .tab { min-width: 90px; padding: 10px 12px; }
            .form-row { flex-direction: column; }
            .form-group, .form-group-small { min-width: 100%; }
            .bracket-item, .component-list {
                grid-template-columns: 1fr;
                gap: 6px;
            }
            .status-bar {
                flex-direction: column;
                gap: 10px;
                text-align: center;
            }
            .header {
                flex-direction: column;
                gap: 10px;
                align-items: flex-start;
            }
        }
    </style>
</head>
<body>
    {% if not session.user_id %}
    <div class="login-container">
        <h1 class="login-title">Bracket Inventory Tracker</h1>
        <form class="login-form" onsubmit="login(event)">
            <input type="text" class="login-input" id="username" placeholder="Username" required>
            <input type="password" class="login-input" id="password" placeholder="Password" required>
            <button type="submit" class="login-btn">Login</button>
        </form>
        <div id="login-error" style="color: red; margin-top: 10px; text-align: center; display: none;"></div>
    </div>
    {% else %}
    <div class="container">
        <div class="header">
            <div>
                <h1 style="margin: 0; font-size: 20px;">Bracket Inventory Tracker</h1>
                <div class="status-bar">
                    <div class="status-item">
                        <div class="status-label">STATUS</div>
                        <div class="status-value status-connected" id="status">CONNECTED</div>
                    </div>
                    <div class="status-item">
                        <div class="status-label">USER</div>
                        <div class="status-value">{{ session.username }} ({{ session.role }})</div>
                    </div>
                </div>
            </div>
            <div class="user-info">
                <button class="logout-btn" onclick="logout()">Logout</button>
            </div>
        </div>
        
        <div class="tabs">
            <button class="tab active" onclick="showTab('printing')">Printing Station</button>
            <button class="tab" onclick="showTab('picking')">Picking Station</button>
            <button class="tab" onclick="showTab('assembly')">Assembly Line</button>
            <button class="tab" onclick="showTab('inventory')">Inventory Management</button>
            <button class="tab" onclick="showTab('external')">External Work Orders</button>
            <button class="tab" onclick="showTab('history')">Movement History</button>
            {% if session.role == 'admin' %}
            <button class="tab" onclick="showTab('admin')">Admin</button>
            {% endif %}
        </div>
        
        <!-- Printing Station Tab -->
        <div id="printing" class="tab-content active">
            <h2>Printing Station - Add/Remove Printed Brackets</h2>
            {% if session.role in ['admin', 'operator', 'viewer'] %}
            <div class="bracket-list">
                <div class="bracket-item header">
                    <div>Component</div>
                    <div>Current Qty</div>
                    <div>Adjust Quantity</div>
                    <div>Actions</div>
                </div>
                <div id="printing-list">
                    <!-- Items will be loaded here -->
                </div>
            </div>
            {% else %}
            <div class="permission-denied">
                <h3>Permission Denied</h3>
                <p>You need appropriate privileges to access this station.</p>
            </div>
            {% endif %}
        </div>
        
        <!-- Picking Station Tab -->
        <div id="picking" class="tab-content">
            <h2>Picking Station - Prepare Orders for Assembly</h2>
            {% if session.role in ['admin', 'operator', 'viewer'] %}
            <div class="print-section">
                <button class="btn btn-print" onclick="printAllPickingLists()">Print All Picking Lists</button>
                <div id="printable-picking-list" style="display: none;"></div>
            </div>
            
            <div class="work-order-section">
                <h3>Ready for Assembly</h3>
                <div id="work-order-list">
                    <!-- Work orders will be loaded here -->
                </div>
            </div>
            
            <div class="bracket-list">
                <div class="bracket-item header">
                    <div>Component</div>
                    <div>Current Qty</div>
                    <div>Adjust Quantity</div>
                    <div>Action</div>
                </div>
                <div id="picking-list">
                    <!-- Items will be loaded here -->
                </div>
            </div>
            {% else %}
            <div class="permission-denied">
                <h3>Permission Denied</h3>
                <p>You need appropriate privileges to access this station.</p>
            </div>
            {% endif %}
        </div>
        
        <!-- Assembly Line Tab -->
        <div id="assembly" class="tab-content">
            <h2>Assembly Line - Build and Complete Orders</h2>
            {% if session.role in ['admin', 'operator', 'viewer'] %}
            <div id="assembly-ready-list">
                <!-- Assembly orders will be loaded here -->
            </div>
            {% else %}
            <div class="permission-denied">
                <h3>Permission Denied</h3>
                <p>You need appropriate privileges to access this station.</p>
            </div>
            {% endif %}
        </div>
        
        <!-- Inventory Management Tab -->
        <div id="inventory" class="tab-content">
            <h2>Inventory Management</h2>
            {% if session.role in ['admin', 'operator', 'viewer'] %}
            <div class="export-section">
                <button class="btn btn-export" onclick="exportToCSV()">Export to CSV</button>
            </div>
            
            <div class="form-section">
                <h3>Add Work Order</h3>
                <div class="form-row">
                    <div class="form-group">
                        <label>Work Order #</label>
                        <input type="text" id="workOrderNumber" placeholder="WO-001">
                    </div>
                    <div class="form-group">
                        <label>Set Type</label>
                        <select id="workOrderSetType">
                            <option value="H6">H6 Set</option>
                            <option value="H7-282">H7-282 Set</option>
                            <option value="H7-304">H7-304 Set</option>
                            <option value="H9">H9 Set</option>
                        </select>
                    </div>
                    <div class="form-group-small">
                        <label>Required Sets</label>
                        <input type="number" id="workOrderQty" value="1" min="1">
                    </div>
                    <div class="form-group-small">
                        <label>&nbsp;</label>
                        <button class="btn-add" onclick="addWorkOrder()">Add Work Order</button>
                    </div>
                </div>
            </div>
            
            <div class="bracket-list">
                <div class="bracket-item header">
                    <div>Component</div>
                    <div>Current Qty</div>
                    <div>Set Actual Count</div>
                    <div>Action</div>
                </div>
                <div id="inventory-list">
                    <!-- Items will be loaded here -->
                </div>
            </div>
            {% else %}
            <div class="permission-denied">
                <h3>Permission Denied</h3>
                <p>You need appropriate privileges to access this station.</p>
            </div>
            {% endif %}
        </div>
        
        <!-- External Work Orders Tab -->
        <div id="external" class="tab-content">
            <h2>External Work Orders</h2>
            {% if session.role in ['admin', 'operator', 'viewer'] %}
            <div class="upload-section">
                <input type="file" id="csvFile" accept=".csv">
                <button class="btn btn-upload" onclick="uploadCSV()">Upload CSV</button>
            </div>
            <div id="external-orders-list">
                <!-- External orders will be loaded here -->
            </div>
            {% else %}
            <div class="permission-denied">
                <h3>Permission Denied</h3>
                <p>You need appropriate privileges to access this station.</p>
            </div>
            {% endif %}
        </div>
        
        <!-- History Tab -->
        <div id="history" class="tab-content">
            <h2>Movement History</h2>
            <div id="historyList">
                <!-- History will be loaded here -->
            </div>
        </div>
        
        <!-- Admin Tab -->
        {% if session.role == 'admin' %}
        <div id="admin" class="tab-content">
            <h2>Administration</h2>
            <div class="admin-section">
                <h3>User Management</h3>
                <div class="form-row">
                    <div class="form-group">
                        <label>Username</label>
                        <input type="text" id="newUsername">
                    </div>
                    <div class="form-group">
                        <label>Password</label>
                        <input type="password" id="newPassword">
                    </div>
                    <div class="form-group">
                        <label>Role</label>
                        <select id="newUserRole">
                            <option value="viewer">Viewer</option>
                            <option value="operator">Operator</option>
                            <option value="admin">Admin</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>&nbsp;</label>
                        <button class="btn-add" onclick="addUser()">Add User</button>
                    </div>
                </div>
                <div id="userList"></div>
            </div>
        </div>
        {% endif %}
    </div>
    {% endif %}

    <script>
        const socket = io();
        let currentInventory = [];
        let workOrders = [];
        let assemblyOrders = [];
        let currentUserRole = '{{ session.role }}' || 'viewer';
        let currentUserId = {{ session.user_id if session.user_id else 0 }};
        
        // Input persistence functions - NOW USING DATABASE
        function saveInputValue(inputKey, inputValue, station) {
            if (!inputKey || currentUserId === 0) return;
            
            socket.emit('save_input_value', {
                input_key: inputKey,
                input_value: inputValue,
                station: station
            });
        }

        function loadInputValues(station = null) {
            if (currentUserId === 0) return;
            
            fetch(`/api/input_values?station=${station || ''}`)
                .then(response => response.json())
                .then(data => {
                    if (data.success && data.input_values) {
                        Object.keys(data.input_values).forEach(inputKey => {
                            const input = document.getElementById(inputKey);
                            if (input && input.type === 'number') {
                                input.value = data.input_values[inputKey];
                            }
                        });
                    }
                })
                .catch(error => console.error('Error loading input values:', error));
        }

        function clearInputValue(inputKey) {
            if (!inputKey || currentUserId === 0) return;
            
            socket.emit('clear_input_value', {
                input_key: inputKey
            });
        }

        function clearStationInputs(station) {
            if (!station || currentUserId === 0) return;
            
            fetch('/api/clear_station_inputs', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ station: station })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    console.log(`Cleared all ${station} inputs`);
                }
            });
        }

        // Auto-save input values when they change
        document.addEventListener('input', function(e) {
            if (e.target.classList.contains('qty-input')) {
                const inputId = e.target.id;
                const inputValue = e.target.value;
                let station = 'unknown';
                
                // Determine station based on input ID
                if (inputId.includes('print-qty-')) {
                    station = 'printing';
                } else if (inputId.includes('pick-qty-')) {
                    station = 'picking';
                } else if (inputId.includes('actual-qty-')) {
                    station = 'inventory';
                }
                
                saveInputValue(inputId, inputValue, station);
            }
        });

        // Tab management
        function showTab(tabName) {
            document.querySelectorAll('.tab-content').forEach(tab => {
                tab.classList.remove('active');
            });
            document.querySelectorAll('.tab').forEach(tab => {
                tab.classList.remove('active');
            });
            
            document.getElementById(tabName).classList.add('active');
            event.target.classList.add('active');
            
            if (tabName === 'history') loadHistory();
            if (tabName === 'external') loadExternalOrders();
            if (tabName === 'assembly') loadAssemblyOrders();
            if (tabName === 'admin') loadUsers();
            
            // Load saved input values when switching tabs
            setTimeout(() => loadInputValues(tabName), 100);
        }
        
        // Login function
        function login(event) {
            event.preventDefault();
            const username = document.getElementById('username').value;
            const password = document.getElementById('password').value;
            
            fetch('/api/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    window.location.reload();
                } else {
                    document.getElementById('login-error').textContent = data.error;
                    document.getElementById('login-error').style.display = 'block';
                }
            });
        }
        
        // Logout function
        function logout() {
            fetch('/api/logout').then(() => window.location.reload());
        }
        
        // Socket events
        socket.on('connect', () => {
            document.getElementById('status').textContent = 'CONNECTED';
            document.getElementById('status').className = 'status-value status-connected';
        });
        
        socket.on('disconnect', () => {
            document.getElementById('status').textContent = 'DISCONNECTED';
            document.getElementById('status').className = 'status-value status-disconnected';
        });
        
        socket.on('inventory_update', (data) => {
            currentInventory = data.items || [];
            workOrders = data.work_orders || [];
            assemblyOrders = data.assembly_orders || [];
            updateAllDisplays();
            
            // Load saved input values after update
            setTimeout(() => loadInputValues(), 100);
        });

        socket.on('input_value_saved', (data) => {
            console.log('Input value saved:', data.input_key);
        });

        socket.on('input_value_cleared', (data) => {
            console.log('Input value cleared:', data.input_key);
        });
        
        // Update all displays
        function updateAllDisplays() {
            updatePrintingStation();
            updatePickingStation();
            updateInventoryManagement();
            updateWorkOrderDisplay();
            updateAssemblyDisplay();
        }
        
        function updatePrintingStation() {
            const container = document.getElementById('printing-list');
            container.innerHTML = '';
            
            currentInventory.forEach(item => {
                const stockClass = item.quantity <= item.min_stock ? 'low-stock' : '';
                const isViewer = currentUserRole === 'viewer';
                
                container.innerHTML += `
                    <div class="bracket-item ${stockClass}">
                        <div class="bracket-name">${item.name}</div>
                        <div class="current-qty">${item.quantity}</div>
                        <div>
                            <input type="number" class="qty-input" id="print-qty-${item.id}" value="0" min="0" ${isViewer ? 'disabled' : ''}>
                        </div>
                        <div>
                            ${!isViewer ? `
                                <button class="btn-add" onclick="addPrintedBrackets(${item.id})">Add</button>
                                <button class="btn-remove" onclick="removePrintedBrackets(${item.id})">Remove</button>
                            ` : '<span style="color: #6c757d;">View Only</span>'}
                        </div>
                    </div>
                `;
            });

            // Load saved values for this station
            loadInputValues('printing');
        }
        
        function updatePickingStation() {
            const container = document.getElementById('picking-list');
            container.innerHTML = '';
            
            currentInventory.forEach(item => {
                const stockClass = item.quantity <= item.min_stock ? 'low-stock' : '';
                const isViewer = currentUserRole === 'viewer';
                
                container.innerHTML += `
                    <div class="bracket-item ${stockClass}">
                        <div class="bracket-name">${item.name}</div>
                        <div class="current-qty">${item.quantity}</div>
                        <div>
                            <input type="number" class="qty-input" id="pick-qty-${item.id}" value="0" min="0" ${isViewer ? 'disabled' : ''}>
                        </div>
                        <div>
                            ${!isViewer ? `
                                <button class="btn-remove" onclick="removeBrackets(${item.id})">Remove</button>
                            ` : '<span style="color: #6c757d;">View Only</span>'}
                        </div>
                    </div>
                `;
            });

            // Load saved values for this station
            loadInputValues('picking');
        }
        
        function updateInventoryManagement() {
            const container = document.getElementById('inventory-list');
            container.innerHTML = '';
            
            currentInventory.forEach(item => {
                const stockClass = item.quantity <= item.min_stock ? 'low-stock' : '';
                const isViewer = currentUserRole === 'viewer';
                
                container.innerHTML += `
                    <div class="bracket-item ${stockClass}">
                        <div class="bracket-name">${item.name}</div>
                        <div class="current-qty">${item.quantity}</div>
                        <div>
                            <input type="number" class="qty-input" id="actual-qty-${item.id}" value="${item.quantity}" min="0" ${isViewer ? 'disabled' : ''}>
                        </div>
                        <div>
                            ${!isViewer ? `
                                <button class="btn" onclick="updateActualCount(${item.id})">Update</button>
                            ` : '<span style="color: #6c757d;">View Only</span>'}
                        </div>
                    </div>
                `;
            });

            // Load saved values for this station
            loadInputValues('inventory');
        }
        
        function updateWorkOrderDisplay() {
            const container = document.getElementById('work-order-list');
            container.innerHTML = '';
            
            const activeWorkOrders = workOrders.filter(wo => 
                !assemblyOrders.some(ao => ao.work_order_id === wo.id)
            );
            
            if (activeWorkOrders.length === 0) {
                container.innerHTML = '<div class="work-order-item">No work orders ready for assembly</div>';
                return;
            }
            
            activeWorkOrders.forEach(workOrder => {
                const components = getComponentsForSet(workOrder.set_type, workOrder.include_spacer);
                let canMoveToAssembly = true;
                let missingComponents = [];
                
                components.forEach(componentName => {
                    const component = currentInventory.find(item => item.name === componentName);
                    if (!component || component.quantity < workOrder.required_sets) {
                        canMoveToAssembly = false;
                        missingComponents.push(componentName);
                    }
                });
                
                const isViewer = currentUserRole === 'viewer';
                
                container.innerHTML += `
                    <div class="work-order-item">
                        <div class="work-order-header">
                            <div class="work-order-title">${workOrder.order_number} - ${workOrder.required_sets} ${workOrder.set_type} sets</div>
                            <div class="work-order-actions">
                                ${canMoveToAssembly && !isViewer ? 
                                    `<button class="btn-move" onclick="moveToAssembly(${workOrder.id})">Move to Assembly</button>` : 
                                    ''
                                }
                                ${!isViewer ? 
                                    `<button class="btn-delete" onclick="deleteWorkOrder(${workOrder.id})">Delete</button>` : 
                                    ''
                                }
                            </div>
                        </div>
                        <div class="component-list">
                            ${components.map(compName => {
                                const comp = currentInventory.find(item => item.name === compName);
                                const hasEnough = comp && comp.quantity >= workOrder.required_sets;
                                return `
                                    <div class="component-item ${hasEnough ? 'component-ok' : 'component-missing'}">
                                        <div><strong>${compName}</strong></div>
                                        <div>${comp ? comp.quantity : 0} / ${workOrder.required_sets}</div>
                                        <div>${hasEnough ? 'OK' : 'LOW'}</div>
                                    </div>
                                `;
                            }).join('')}
                        </div>
                        ${!canMoveToAssembly ? `
                            <div class="missing-warning">
                                <strong>Missing:</strong> ${missingComponents.join(', ')}
                            </div>
                        ` : ''}
                    </div>
                `;
            });
        }
        
        function updateAssemblyDisplay() {
            const container = document.getElementById('assembly-ready-list');
            container.innerHTML = '';
            
            const readyOrders = assemblyOrders.filter(order => order.status === 'ready');
            
            if (readyOrders.length === 0) {
                container.innerHTML = '<div class="work-order-item">No orders ready for assembly</div>';
                return;
            }
            
            readyOrders.forEach(order => {
                const workOrder = workOrders.find(wo => wo.id === order.work_order_id);
                if (!workOrder) return;
                
                const isViewer = currentUserRole === 'viewer';
                
                container.innerHTML += `
                    <div class="work-order-item">
                        <div class="work-order-header">
                            <div class="work-order-title">
                                ${workOrder.order_number} - ${workOrder.required_sets} ${workOrder.set_type} sets
                                <span style="background: var(--success); color: white; padding: 2px 8px; border-radius: 10px; font-size: 11px;">READY</span>
                            </div>
                            <div class="work-order-actions">
                                ${!isViewer ? `
                                    <button class="btn-complete" onclick="completeAssembly(${order.id})">Complete</button>
                                ` : ''}
                            </div>
                        </div>
                        <div style="margin-top: 8px; font-size: 12px; color: #666;">
                            Moved to assembly: ${new Date(order.moved_at).toLocaleString()}
                        </div>
                    </div>
                `;
            });
        }
        
        function getComponentsForSet(setType, includeSpacer = false) {
            const componentMap = {
                'H6': ['H6-623A', 'H6-623B', 'H6-623C'],
                'H7-282': ['H7-282'],
                'H7-304': ['H7-304'],
                'H9': ['H9-923A', 'H9-923B', 'H9-923C'] + (includeSpacer ? ['H9-SPACER'] : [])
            };
            return componentMap[setType] || [];
        }
        
        // Printing Station Functions
        function addPrintedBrackets(itemId) {
            const qtyInput = document.getElementById(`print-qty-${itemId}`);
            const quantity = parseInt(qtyInput.value);
            
            if (!quantity || quantity < 1) {
                alert('Please enter a valid quantity greater than 0');
                return;
            }
            
            socket.emit('inventory_change', {
                item_id: itemId,
                change: quantity,
                station: 'Printing Station',
                notes: 'Printed'
            });
            
            // Clear the input value after successful operation
            qtyInput.value = '0';
            clearInputValue(`print-qty-${itemId}`);
        }
        
        function removePrintedBrackets(itemId) {
            const qtyInput = document.getElementById(`print-qty-${itemId}`);
            const quantity = parseInt(qtyInput.value);
            
            if (!quantity || quantity < 1) {
                alert('Please enter a valid quantity greater than 0');
                return;
            }
            
            socket.emit('inventory_change', {
                item_id: itemId,
                change: -quantity,
                station: 'Printing Station',
                notes: 'Correction/Removal'
            });
            
            // Clear the input value after successful operation
            qtyInput.value = '0';
            clearInputValue(`print-qty-${itemId}`);
        }
        
        // Picking Station Functions
        function removeBrackets(itemId) {
            const qtyInput = document.getElementById(`pick-qty-${itemId}`);
            const quantity = parseInt(qtyInput.value);
            
            if (!quantity || quantity < 1) {
                alert('Please enter a valid quantity greater than 0');
                return;
            }
            
            socket.emit('inventory_change', {
                item_id: itemId,
                change: -quantity,
                station: 'Picking Station',
                notes: 'Removed'
            });
            
            // Clear the input value after successful operation
            qtyInput.value = '0';
            clearInputValue(`pick-qty-${itemId}`);
        }
        
        // Work Order Functions
        function addWorkOrder() {
            const orderNumber = document.getElementById('workOrderNumber').value;
            const setType = document.getElementById('workOrderSetType').value;
            const quantity = parseInt(document.getElementById('workOrderQty').value);
            
            if (!orderNumber || !quantity || quantity < 1) {
                alert('Please enter Work Order # and valid quantity greater than 0');
                return;
            }
            
            fetch('/api/add_work_order', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    order_number: orderNumber,
                    set_type: setType,
                    required_sets: quantity,
                    include_spacer: false
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('Work order added successfully!');
                    document.getElementById('workOrderNumber').value = '';
                    document.getElementById('workOrderQty').value = '1';
                    socket.emit('get_inventory');
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }
        
        function moveToAssembly(workOrderId) {
            if (!confirm('Move this work order to Assembly Line?')) {
                return;
            }
            
            fetch('/api/move_to_assembly', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ work_order_id: workOrderId })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('Work order moved to Assembly Line!');
                    socket.emit('get_inventory');
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }
        
        function deleteWorkOrder(workOrderId) {
            if (!confirm('Delete this work order?')) {
                return;
            }
            
            fetch('/api/delete_work_order', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ work_order_id: workOrderId })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('Work order deleted successfully!');
                    socket.emit('get_inventory');
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }
        
        // Assembly Line Functions
        function completeAssembly(assemblyOrderId) {
            if (!confirm('Mark this assembly as complete?')) {
                return;
            }
            
            fetch('/api/complete_assembly', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ assembly_order_id: assemblyOrderId })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('Assembly completed successfully!');
                    socket.emit('get_inventory');
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }
        
        // Inventory Management Functions
        function updateActualCount(itemId) {
            const actualInput = document.getElementById(`actual-qty-${itemId}`);
            const actualQty = parseInt(actualInput.value);
            
            if (isNaN(actualQty) || actualQty < 0) {
                alert('Please enter a valid quantity');
                return;
            }
            
            const currentItem = currentInventory.find(item => item.id === itemId);
            if (!currentItem) return;
            
            const adjustment = actualQty - currentItem.quantity;
            
            if (adjustment === 0) {
                alert('No change needed');
                return;
            }
            
            socket.emit('inventory_change', {
                item_id: itemId,
                change: adjustment,
                station: 'Inventory Management',
                notes: 'Physical count adjustment'
            });
        }
        
        // Print Function
        function printAllPickingLists() {
            const readyOrders = assemblyOrders.filter(order => order.status === 'ready');
            
            if (readyOrders.length === 0) {
                alert('No orders ready for picking');
                return;
            }
            
            const printContainer = document.getElementById('printable-picking-list');
            printContainer.innerHTML = '';
            
            readyOrders.forEach(order => {
                const workOrder = workOrders.find(wo => wo.id === order.work_order_id);
                if (!workOrder) return;
                
                const components = getComponentsForSet(workOrder.set_type, workOrder.include_spacer);
                
                const printableDiv = document.createElement('div');
                printableDiv.className = 'work-order-item';
                printableDiv.innerHTML = `
                    <div style="border: 2px solid #000; padding: 20px; margin: 10px 0;">
                        <h2 style="text-align: center;">PICKING LIST</h2>
                        <h3 style="text-align: center;">Work Order: ${workOrder.order_number}</h3>
                        <p style="text-align: center;">Set Type: ${workOrder.set_type} | Required Sets: ${workOrder.required_sets}</p>
                        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin: 20px 0;">
                            ${components.map(compName => `
                                <div style="border: 1px solid #ccc; padding: 10px; text-align: center;">
                                    <strong>${compName}</strong><br>
                                    Quantity: ${workOrder.required_sets}
                                </div>
                            `).join('')}
                        </div>
                        <p style="text-align: center; font-size: 12px; color: #666;">
                            Generated: ${new Date().toLocaleString()}
                        </p>
                    </div>
                `;
                
                printContainer.appendChild(printableDiv);
            });
            
            printContainer.style.display = 'block';
            window.print();
            printContainer.style.display = 'none';
        }
        
        // Export Functions
        function exportToCSV() {
            window.open('/api/export/csv', '_blank');
        }
        
        // External Orders Functions
        function uploadCSV() {
            const fileInput = document.getElementById('csvFile');
            const file = fileInput.files[0];
            
            if (!file) {
                alert('Please select a CSV file');
                return;
            }
            
            const formData = new FormData();
            formData.append('csv_file', file);
            
            fetch('/api/upload_csv', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('CSV uploaded successfully!');
                    fileInput.value = '';
                    loadExternalOrders();
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }
        
        function loadExternalOrders() {
            fetch('/api/external_orders')
                .then(response => response.json())
                .then(data => {
                    const container = document.getElementById('external-orders-list');
                    container.innerHTML = '';
                    
                    if (data.orders.length === 0) {
                        container.innerHTML = '<div class="work-order-item">No external work orders</div>';
                        return;
                    }
                    
                    data.orders.forEach(order => {
                        container.innerHTML += `
                            <div class="work-order-item">
                                <div class="work-order-header">
                                    <div class="work-order-title">${order.external_order_number}</div>
                                    <div class="work-order-actions">
                                        <button class="btn-convert" onclick="convertExternalOrder(${order.id})">Convert</button>
                                        <button class="btn-delete" onclick="deleteExternalOrder(${order.id})">Delete</button>
                                    </div>
                                </div>
                                <div>SKU: ${order.sku} | Qty: ${order.quantity}</div>
                            </div>
                        `;
                    });
                });
        }
        
        function convertExternalOrder(orderId) {
            fetch('/api/convert_external_order', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ external_order_id: orderId })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('External order converted!');
                    loadExternalOrders();
                    socket.emit('get_inventory');
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }
        
        function deleteExternalOrder(orderId) {
            if (!confirm('Delete this external order?')) return;
            
            fetch('/api/delete_external_order', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ order_id: orderId })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('External order deleted!');
                    loadExternalOrders();
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }
        
        // History functions
        function loadHistory() {
            fetch('/api/history?limit=50')
                .then(response => response.json())
                .then(data => {
                    const container = document.getElementById('historyList');
                    container.innerHTML = '';
                    
                    if (data.history.length === 0) {
                        container.innerHTML = '<div class="work-order-item">No history found</div>';
                        return;
                    }
                    
                    data.history.forEach(record => {
                        const typeClass = record.change > 0 ? 'history-add' : 'history-remove';
                        container.innerHTML += `
                            <div class="work-order-item ${typeClass}">
                                <div>
                                    <strong>${record.station}</strong><br>
                                    ${record.item_name}: ${record.change > 0 ? '+' : ''}${record.change}<br>
                                    <small>By: ${record.username} | ${new Date(record.timestamp).toLocaleString()}</small>
                                </div>
                                <div>${record.notes || ''}</div>
                            </div>
                        `;
                    });
                });
        }
        
        // Admin Functions
        function loadUsers() {
            fetch('/api/users')
                .then(response => response.json())
                .then(data => {
                    const container = document.getElementById('userList');
                    container.innerHTML = '';
                    
                    data.users.forEach(user => {
                        container.innerHTML += `
                            <div class="work-order-item">
                                <div>
                                    <strong>${user.username}</strong> - ${user.role}
                                    ${user.username === '{{ session.username }}' ? ' (current)' : ''}
                                </div>
                                <div class="work-order-actions">
                                    <button class="btn" onclick="changeUserRole(${user.id})">Change Role</button>
                                    ${user.username !== '{{ session.username }}' ? 
                                        `<button class="btn-delete" onclick="deleteUser(${user.id})">Delete</button>` : 
                                        ''
                                    }
                                </div>
                            </div>
                        `;
                    });
                });
        }
        
        function addUser() {
            const username = document.getElementById('newUsername').value;
            const password = document.getElementById('newPassword').value;
            const role = document.getElementById('newUserRole').value;
            
            if (!username || !password) {
                alert('Please enter username and password');
                return;
            }
            
            fetch('/api/users', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password, role })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('User added successfully!');
                    document.getElementById('newUsername').value = '';
                    document.getElementById('newPassword').value = '';
                    loadUsers();
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }
        
        function changeUserRole(userId) {
            const newRole = prompt('Enter new role (admin, operator, viewer):');
            if (!newRole) return;
            
            fetch('/api/users/role', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: userId, role: newRole })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('User role updated!');
                    loadUsers();
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }
        
        function deleteUser(userId) {
            if (!confirm('Are you sure you want to delete this user?')) return;
            
            fetch('/api/users', {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: userId })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('User deleted!');
                    loadUsers();
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }
        
        // Load data when page loads
        window.onload = function() {
            loadHistory();
            loadExternalOrders();
            loadAssemblyOrders();
            if (currentUserRole === 'admin') loadUsers();
            
            // Load saved input values on page load
            setTimeout(() => loadInputValues(), 500);
        };
        
        // Request inventory data
        socket.emit('get_inventory');
    </script>
</body>
</html>
'''

# NEW API Routes for input value management
@app.route('/api/input_values')
@login_required
def get_input_values_api():
    """Get saved input values for the current user"""
    station = request.args.get('station', None)
    input_values = get_input_values(session['user_id'], station)
    return jsonify({'success': True, 'input_values': input_values})

@app.route('/api/clear_station_inputs', methods=['POST'])
@login_required
def clear_station_inputs_api():
    """Clear all input values for a specific station"""
    data = request.get_json()
    station = data.get('station')
    
    if not station:
        return jsonify({'success': False, 'error': 'Station is required'})
    
    success = clear_station_inputs(session['user_id'], station)
    return jsonify({'success': success})

# Flask Routes
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    
    if not username or not password:
        return jsonify({'success': False, 'error': 'Username and password are required'})
    
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
    conn.close()
    
    if user and user['password_hash'] == hash_password(password):
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['role'] = user['role']
        return jsonify({'success': True, 'message': 'Login successful'})
    else:
        return jsonify({'success': False, 'error': 'Invalid username or password'})

@app.route('/api/logout')
def logout():
    session.clear()
    return jsonify({'success': True, 'message': 'Logout successful'})

@app.route('/api/add_work_order', methods=['POST'])
@login_required
@role_required('operator')
def add_work_order():
    data = request.get_json()
    order_number = data.get('order_number', '').strip()
    set_type = data.get('set_type')
    required_sets = data.get('required_sets')
    
    if not order_number or not set_type or not required_sets:
        return jsonify({'success': False, 'error': 'All fields are required'})
    
    try:
        required_sets = int(required_sets)
        if required_sets <= 0:
            return jsonify({'success': False, 'error': 'Required sets must be greater than 0'})
    except ValueError:
        return jsonify({'success': False, 'error': 'Invalid required sets value'})
    
    conn = get_db_connection()
    try:
        existing = conn.execute('SELECT id FROM work_orders WHERE order_number = ?', (order_number,)).fetchone()
        if existing:
            return jsonify({'success': False, 'error': 'Work order with this number already exists'})
        
        conn.execute('''
            INSERT INTO work_orders (order_number, set_type, required_sets, include_spacer)
            VALUES (?, ?, ?, ?)
        ''', (order_number, set_type, required_sets, False))
        
        conn.commit()
        broadcast_update()
        return jsonify({'success': True, 'message': 'Work order added successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()

@app.route('/api/move_to_assembly', methods=['POST'])
@login_required
@role_required('operator')
def move_to_assembly():
    data = request.get_json()
    work_order_id = data.get('work_order_id')
    
    if not work_order_id:
        return jsonify({'success': False, 'error': 'Work order ID is required'})
    
    conn = get_db_connection()
    try:
        work_order = conn.execute('SELECT * FROM work_orders WHERE id = ? AND status = ?', (work_order_id, 'active')).fetchone()
        if not work_order:
            return jsonify({'success': False, 'error': 'Active work order not found'})
        
        existing_assembly = conn.execute('SELECT id FROM assembly_orders WHERE work_order_id = ? AND status IN (?, ?)', (work_order_id, 'ready', 'building')).fetchone()
        if existing_assembly:
            return jsonify({'success': False, 'error': 'Work order is already in assembly line'})
        
        components = get_components_for_set_type(work_order['set_type'], work_order['include_spacer'])
        for component in components:
            item = conn.execute('SELECT * FROM items WHERE name = ?', (component,)).fetchone()
            if not item or item['quantity'] < work_order['required_sets']:
                return jsonify({'success': False, 'error': f'Not enough {component} available'})
            
            new_quantity = item['quantity'] - work_order['required_sets']
            conn.execute('UPDATE items SET quantity = ? WHERE id = ?', (new_quantity, item['id']))
            conn.execute('''
                INSERT INTO transactions (item_id, change, station, notes, username, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (item['id'], -work_order['required_sets'], 'Assembly Line', f'Moved {work_order["order_number"]} to assembly', session['username'], datetime.now()))
        
        conn.execute('INSERT INTO assembly_orders (work_order_id, status, moved_at) VALUES (?, ?, ?)', (work_order_id, 'ready', datetime.now()))
        conn.commit()
        broadcast_update()
        return jsonify({'success': True, 'message': 'Work order moved to assembly line'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()

@app.route('/api/complete_assembly', methods=['POST'])
@login_required
@role_required('operator')
def complete_assembly():
    data = request.get_json()
    assembly_order_id = data.get('assembly_order_id')
    
    if not assembly_order_id:
        return jsonify({'success': False, 'error': 'Assembly order ID is required'})
    
    conn = get_db_connection()
    try:
        assembly_order = conn.execute('SELECT * FROM assembly_orders WHERE id = ?', (assembly_order_id,)).fetchone()
        if not assembly_order:
            return jsonify({'success': False, 'error': 'Assembly order not found'})
        
        work_order = conn.execute('SELECT * FROM work_orders WHERE id = ?', (assembly_order['work_order_id'],)).fetchone()
        if not work_order:
            return jsonify({'success': False, 'error': 'Work order not found'})
        
        conn.execute('UPDATE assembly_orders SET status = ?, completed_at = ?, assembled_by = ? WHERE id = ?', 
                    ('completed', datetime.now(), session['username'], assembly_order_id))
        conn.execute('UPDATE work_orders SET status = ? WHERE id = ?', ('completed', work_order['id']))
        conn.commit()
        broadcast_update()
        return jsonify({'success': True, 'message': 'Assembly completed successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()

@app.route('/api/delete_work_order', methods=['POST'])
@login_required
@role_required('operator')
def delete_work_order():
    data = request.get_json()
    work_order_id = data.get('work_order_id')
    
    if not work_order_id:
        return jsonify({'success': False, 'error': 'Work order ID is required'})
    
    conn = get_db_connection()
    try:
        work_order = conn.execute('SELECT * FROM work_orders WHERE id = ?', (work_order_id,)).fetchone()
        if not work_order:
            return jsonify({'success': False, 'error': 'Work order not found'})
        
        conn.execute('DELETE FROM work_orders WHERE id = ?', (work_order_id,))
        conn.commit()
        broadcast_update()
        return jsonify({'success': True, 'message': 'Work order deleted successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()

@app.route('/api/assembly_orders')
@login_required
def get_assembly_orders():
    conn = get_db_connection()
    try:
        assembly_orders = conn.execute('''
            SELECT ao.*, wo.order_number, wo.set_type, wo.required_sets, wo.include_spacer
            FROM assembly_orders ao
            JOIN work_orders wo ON ao.work_order_id = wo.id
            ORDER BY ao.moved_at DESC
        ''').fetchall()
        assembly_orders_data = [dict(order) for order in assembly_orders]
        return jsonify({'assembly_orders': assembly_orders_data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()

@app.route('/api/external_orders')
@login_required
def get_external_orders():
    conn = get_db_connection()
    try:
        orders = conn.execute('SELECT * FROM external_work_orders ORDER BY created_at DESC').fetchall()
        orders_data = [dict(order) for order in orders]
        return jsonify({'orders': orders_data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()

@app.route('/api/history')
@login_required
def get_history():
    limit = request.args.get('limit', 50, type=int)
    conn = get_db_connection()
    try:
        history = conn.execute('''
            SELECT t.*, i.name as item_name
            FROM transactions t 
            JOIN items i ON t.item_id = i.id 
            ORDER BY t.timestamp DESC 
            LIMIT ?
        ''', (limit,)).fetchall()
        history_data = [dict(record) for record in history]
        return jsonify({'history': history_data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()

@app.route('/api/users')
@login_required
@role_required('admin')
def get_users():
    conn = get_db_connection()
    try:
        users = conn.execute('SELECT id, username, role, created_at FROM users ORDER BY username').fetchall()
        users_data = [dict(user) for user in users]
        return jsonify({'users': users_data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()

@app.route('/api/users', methods=['POST'])
@login_required
@role_required('admin')
def create_user():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    role = data.get('role', 'viewer')
    
    if not username or not password:
        return jsonify({'success': False, 'error': 'Username and password are required'})
    
    if role not in ['admin', 'operator', 'viewer']:
        return jsonify({'success': False, 'error': 'Invalid role'})
    
    conn = get_db_connection()
    try:
        existing = conn.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
        if existing:
            return jsonify({'success': False, 'error': 'Username already exists'})
        
        password_hash = hash_password(password)
        conn.execute('INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)', (username, password_hash, role))
        conn.commit()
        return jsonify({'success': True, 'message': 'User created successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()

@app.route('/api/export/csv')
@login_required
def export_csv():
    conn = get_db_connection()
    try:
        items = conn.execute('SELECT * FROM items ORDER BY case_type, name').fetchall()
        output = io.StringIO()
        writer = csv.writer(output)
        
        writer.writerow(['Component', 'Description', 'Case Type', 'Quantity', 'Min Stock'])
        
        for item in items:
            writer.writerow([
                item['name'],
                item['description'],
                item['case_type'],
                item['quantity'],
                item['min_stock']
            ])
        
        response = app.response_class(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment;filename=inventory_export.csv'}
        )
        return response
    finally:
        conn.close()

if __name__ == '__main__':
    print("🚀 Starting Bracket Inventory Tracker...")
    init_database()
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
