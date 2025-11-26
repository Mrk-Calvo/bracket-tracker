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

# HTML Template (only showing the JavaScript part that changed)
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Bracket Inventory Tracker</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.2/socket.io.min.js"></script>
    <style>
        /* ... (same CSS styles as before) ... */
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
        <!-- ... (same HTML structure as before) ... -->
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
        
        // ... (rest of the JavaScript functions remain the same as before, but updated to use database persistence)

        // Printing Station Functions - UPDATED to clear database values
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
        
        // Picking Station Functions - UPDATED to clear database values
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

        // ... (rest of the functions remain similar but use the new database persistence)

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

# ... (rest of your existing Flask routes remain the same)

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

# ... (all your other existing routes remain exactly the same)

if __name__ == '__main__':
    print("🚀 Starting Bracket Inventory Tracker...")
    init_database()
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
