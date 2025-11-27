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
import atexit
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'bracket-tracker-2024-secure-key')

# Use threading instead of gevent for Render.com compatibility
socketio = SocketIO(app, 
                   cors_allowed_origins="*", 
                   async_mode='threading',
                   logger=True,
                   engineio_logger=True)

# Slack webhook URL for alerts
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL', '')

# SKU to Bracket Mapping - UPDATED WITH REAL EXAMPLES
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

# Enhanced User roles with tab permissions
ROLES = {
    'admin': {
        'level': 3,
        'tabs': ['printing', 'picking', 'assembly', 'inventory', 'external', 'history', 'admin']
    },
    'operator': {
        'level': 2, 
        'tabs': ['printing', 'picking', 'assembly', 'inventory', 'external', 'history']
    },
    'viewer': {
        'level': 1,
        'tabs': ['printing', 'picking', 'assembly', 'inventory', 'external', 'history']
    }
}

# Database configuration for persistence
DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///nzxt_inventory.db')

def get_database_path():
    """Get the database path, ensuring it's in a persistent location"""
    if DATABASE_URL.startswith('sqlite:///'):
        return DATABASE_URL.replace('sqlite:///', '')
    elif DATABASE_URL.startswith('postgresql://'):
        # PostgreSQL connection string
        return DATABASE_URL
    else:
        # Default SQLite with persistent path
        return 'nzxt_inventory.db'

def get_db_connection():
    """Get database connection with persistent storage"""
    db_path = get_database_path()
    
    if db_path.startswith('postgresql://'):
        # PostgreSQL connection
        try:
            import psycopg2
            conn = psycopg2.connect(db_path, sslmode='require')
            conn.autocommit = False
            return conn
        except ImportError:
            logger.warning("PostgreSQL driver not available, falling back to SQLite")
            db_path = 'nzxt_inventory.db'
    
    # SQLite connection with WAL mode for better concurrency
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Enable WAL mode for better performance and concurrency
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=5000')
    return conn

def backup_database():
    """Create a backup of the database"""
    try:
        source_path = get_database_path()
        if source_path.startswith('postgresql://'):
            logger.info("PostgreSQL backup requires manual setup")
            return
            
        backup_path = f"{source_path}.backup.{int(time.time())}"
        
        import shutil
        shutil.copy2(source_path, backup_path)
        
        # Keep only last 5 backups
        backup_dir = os.path.dirname(source_path) or '.'
        backup_files = [f for f in os.listdir(backup_dir) if f.startswith(os.path.basename(source_path) + '.backup.')]
        backup_files.sort(reverse=True)
        
        for old_backup in backup_files[5:]:
            os.remove(os.path.join(backup_dir, old_backup))
            
        logger.info(f"Database backed up to {backup_path}")
    except Exception as e:
        logger.error(f"Backup failed: {e}")

# Register backup on exit
atexit.register(backup_database)

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
            position: relative;
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
        .qty-controls {
            display: flex;
            gap: 8px;
            align-items: center;
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
        .btn-sync {
            background: var(--warning);
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
        .btn-assemble {
            background: #20c997;
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
        .work-order-category {
            margin-bottom: 15px;
        }
        .work-order-category-header {
            font-size: 14px;
            font-weight: bold;
            color: #1a1a1a;
            margin-bottom: 8px;
            padding: 6px;
            background: #d4edda;
            border-radius: 3px;
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
        
        .external-orders-section {
            background: #fff3cd;
            padding: 12px;
            border-radius: 6px;
            margin: 12px 0;
            border: 1px solid var(--warning);
        }
        .external-order-item {
            padding: 10px;
            border: 1px solid var(--warning);
            margin-bottom: 8px;
            background: white;
            border-radius: 5px;
        }
        .external-order-info {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 10px;
            margin-top: 8px;
            font-size: 12px;
        }
        .external-order-detail {
            background: #f8f9fa;
            padding: 8px;
            border-radius: 4px;
            text-align: center;
        }
        .external-order-detail strong {
            display: block;
            margin-bottom: 4px;
            color: #333;
        }
        
        .set-analysis {
            background: #fff3cd;
            padding: 10px;
            border-radius: 6px;
            margin: 12px 0;
            border: 1px solid var(--warning);
        }
        .set-item {
            margin: 6px 0;
            padding: 6px;
            background: white;
            border-radius: 3px;
            font-size: 12px;
        }
        .set-header {
            font-weight: bold;
            margin-bottom: 4px;
            color: #1a1a1a;
            font-size: 13px;
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
        
        .missing-warning {
            background: #f8d7da;
            color: #721c24;
            padding: 6px;
            border-radius: 3px;
            margin-top: 6px;
            font-size: 11px;
            border-left: 2px solid var(--danger);
        }
        
        .completion-alert {
            background: #d4edda;
            color: #155724;
            padding: 8px;
            border-radius: 3px;
            margin: 8px 0;
            border-left: 3px solid var(--success);
            font-weight: bold;
            font-size: 12px;
        }
        
        .history-section {
            margin-top: 20px;
        }
        .history-item {
            padding: 8px;
            border-bottom: 1px solid #eee;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 12px;
        }
        .history-item:nth-child(even) {
            background: #f9f9f9;
        }
        .history-add {
            border-left: 2px solid var(--success);
        }
        .history-remove {
            border-left: 2px solid var(--danger);
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
        
        .admin-section {
            background: #f0f8ff;
            padding: 15px;
            border-radius: 6px;
            margin: 15px 0;
            border: 1px solid var(--primary);
        }
        .user-list {
            margin-top: 15px;
        }
        .user-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px;
            border-bottom: 1px solid #e9ecef;
        }
        .user-actions {
            display: flex;
            gap: 8px;
        }
        
        .export-section {
            background: #e8f5e8;
            padding: 12px;
            border-radius: 6px;
            margin: 12px 0;
        }
        .export-buttons {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
        }
        
        .developer-credit {
            text-align: center;
            margin-top: 25px;
            padding: 15px;
            color: #6c757d;
            font-size: 13px;
            border-top: 1px solid #e9ecef;
            background: #f8f9fa;
            border-radius: 6px;
        }
        .developer-credit a {
            color: var(--primary);
            text-decoration: none;
            font-weight: bold;
        }
        .developer-credit a:hover {
            text-decoration: underline;
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
        
        .api-section {
            background: #e6f3ff;
            padding: 12px;
            border-radius: 6px;
            margin: 12px 0;
            border: 1px solid var(--info);
        }
        
        .checkbox-group {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-top: 8px;
        }
        .checkbox-group input[type="checkbox"] {
            width: auto;
        }
        
        .upload-section {
            background: #e8f5e8;
            padding: 15px;
            border-radius: 6px;
            margin: 15px 0;
            border: 1px solid var(--success);
        }
        
        .file-upload {
            border: 2px dashed #ddd;
            padding: 20px;
            text-align: center;
            border-radius: 6px;
            margin: 10px 0;
        }
        
        .sample-csv {
            background: #f8f9fa;
            padding: 10px;
            border-radius: 4px;
            margin: 10px 0;
            font-family: monospace;
            font-size: 12px;
        }
        
        .assembly-section {
            background: #e6f7ff;
            padding: 12px;
            border-radius: 6px;
            margin: 12px 0;
            border: 1px solid var(--info);
        }
        
        .assembly-ready {
            background: #d4edda;
            border: 1px solid var(--success);
        }
        
        .assembly-building {
            background: #fff3cd;
            border: 1px solid var(--warning);
        }
        
        .assembly-completed {
            background: #e8f5e8;
            border: 1px solid var(--success);
            opacity: 0.8;
        }
        
        .assembly-status {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: bold;
            margin-left: 8px;
        }
        
        .status-ready {
            background: var(--success);
            color: white;
        }
        
        .status-building {
            background: var(--warning);
            color: black;
        }
        
        .status-completed {
            background: var(--info);
            color: white;
        }
        
        .assembly-actions {
            display: flex;
            gap: 6px;
            margin-top: 8px;
        }
        
        .assembly-info {
            margin-top: 8px;
            font-size: 12px;
            color: #666;
        }
        
        .print-section {
            background: #fff3cd;
            padding: 12px;
            border-radius: 6px;
            margin: 12px 0;
            border: 1px solid var(--warning);
        }
        
        .printable-order {
            background: white;
            padding: 15px;
            margin: 10px 0;
            border-radius: 6px;
            border: 1px solid #ddd;
        }
        
        .print-header {
            text-align: center;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 2px solid #333;
        }
        
        .print-components {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 10px;
            margin: 15px 0;
        }
        
        .print-component {
            padding: 8px;
            background: #f8f9fa;
            border-radius: 4px;
            text-align: center;
        }
        
        .print-footer {
            margin-top: 20px;
            padding-top: 10px;
            border-top: 1px solid #ddd;
            text-align: center;
            font-size: 12px;
            color: #666;
        }
        
        .print-all-container {
            page-break-after: always;
            margin-bottom: 30px;
        }
        
        .print-all-container:last-child {
            page-break-after: avoid;
        }
        
        /* Chat System Styles */
        .chat-container {
            position: fixed;
            bottom: 20px;
            right: 20px;
            width: 350px;
            height: 500px;
            background: white;
            border-radius: 10px;
            box-shadow: 0 5px 25px rgba(0,0,0,0.2);
            display: flex;
            flex-direction: column;
            z-index: 1000;
            border: 1px solid #ddd;
        }
        
        .chat-header {
            background: var(--primary);
            color: white;
            padding: 12px 15px;
            border-radius: 10px 10px 0 0;
            display: flex;
            justify-content: space-between;
            align-items: center;
            cursor: move;
        }
        
        .chat-title {
            font-weight: bold;
            font-size: 14px;
        }
        
        .chat-controls {
            display: flex;
            gap: 8px;
        }
        
        .chat-btn {
            background: none;
            border: none;
            color: white;
            cursor: pointer;
            font-size: 12px;
            padding: 4px;
        }
        
        .chat-messages {
            flex: 1;
            padding: 15px;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 10px;
            background: #f8f9fa;
        }
        
        .chat-message {
            max-width: 85%;
            padding: 8px 12px;
            border-radius: 15px;
            font-size: 12px;
            line-height: 1.4;
        }
        
        .message-sent {
            align-self: flex-end;
            background: var(--primary);
            color: white;
            border-bottom-right-radius: 5px;
        }
        
        .message-received {
            align-self: flex-start;
            background: white;
            color: #333;
            border: 1px solid #ddd;
            border-bottom-left-radius: 5px;
        }
        
        .message-system {
            align-self: center;
            background: #fff3cd;
            color: #856404;
            font-style: italic;
            font-size: 11px;
            max-width: 95%;
        }
        
        .message-sender {
            font-weight: bold;
            font-size: 10px;
            margin-bottom: 2px;
            opacity: 0.8;
        }
        
        .message-time {
            font-size: 9px;
            opacity: 0.7;
            margin-top: 3px;
            text-align: right;
        }
        
        .chat-input-area {
            padding: 12px;
            border-top: 1px solid #ddd;
            background: white;
            border-radius: 0 0 10px 10px;
        }
        
        .chat-input-row {
            display: flex;
            gap: 8px;
        }
        
        .chat-input {
            flex: 1;
            padding: 8px 12px;
            border: 1px solid #ddd;
            border-radius: 20px;
            font-size: 12px;
            outline: none;
        }
        
        .chat-input:focus {
            border-color: var(--primary);
        }
        
        .chat-send-btn {
            background: var(--primary);
            color: white;
            border: none;
            border-radius: 50%;
            width: 35px;
            height: 35px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        
        .chat-minimized {
            height: 40px;
        }
        
        .chat-minimized .chat-messages,
        .chat-minimized .chat-input-area {
            display: none;
        }
        
        .notification-badge {
            background: var(--danger);
            color: white;
            border-radius: 50%;
            width: 18px;
            height: 18px;
            font-size: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            position: absolute;
            top: -5px;
            right: -5px;
        }
        
        .chat-tab-btn {
            position: fixed;
            bottom: 20px;
            right: 20px;
            background: var(--primary);
            color: white;
            border: none;
            border-radius: 50%;
            width: 60px;
            height: 60px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 3px 15px rgba(0,0,0,0.2);
            z-index: 999;
        }
        
        .chat-tab-btn:hover {
            background: #0056b3;
        }
        
        .chat-hidden {
            display: none;
        }
        
        .system-alert {
            background: #fff3cd;
            border: 1px solid var(--warning);
            padding: 10px;
            border-radius: 5px;
            margin: 10px 0;
            font-size: 12px;
        }
        
        .system-alert.success {
            background: #d4edda;
            border-color: var(--success);
            color: #155724;
        }
        
        .system-alert.error {
            background: #f8d7da;
            border-color: var(--danger);
            color: #721c24;
        }
        
        .system-alert.info {
            background: #cce7ff;
            border-color: var(--info);
            color: #004085;
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
            .export-buttons {
                flex-direction: column;
            }
            .external-order-info {
                grid-template-columns: 1fr;
            }
            .work-order-actions, .assembly-actions {
                flex-direction: column;
            }
            .chat-container {
                width: 300px;
                height: 400px;
            }
        }
        
        @media print {
            body * {
                visibility: hidden;
            }
            .printable-order, .printable-order * {
                visibility: visible;
            }
            .printable-order {
                position: relative;
                left: 0;
                top: 0;
                width: 100%;
                box-shadow: none;
                border: none;
                page-break-inside: avoid;
            }
            .print-all-container {
                page-break-inside: avoid;
            }
            .no-print {
                display: none !important;
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
                        <div class="status-label">PST TIME</div>
                        <div class="status-value" id="currentTime">--:--:-- --</div>
                    </div>
                    <div class="status-item">
                        <div class="status-label">DATABASE</div>
                        <div class="status-value" id="databaseStatus">
                            {% if using_postgres %}PostgreSQL{% else %}SQLite{% endif %}
                        </div>
                    </div>
                </div>
            </div>
            <div class="user-info">
                <div>Welcome, <strong>{{ session.username }}</strong></div>
                <div class="user-role">{{ session.role|upper }}</div>
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
            <h2 style="margin-bottom: 8px; font-size: 18px;">Printing Station - Add/Remove Printed Brackets</h2>
            <p style="margin-bottom: 15px; font-size: 13px;">Add quantities when brackets are printed. Remove for corrections.</p>
            
            {% if session.role in ['admin', 'operator', 'viewer'] %}
            <div class="bracket-list">
                <div class="bracket-item header">
                    <div>Component</div>
                    <div>Current Qty</div>
                    <div>Adjust Quantity</div>
                    <div>Actions</div>
                </div>
                
                <div class="bracket-category">
                    <div class="category-header">H6 Components (Need all 3 for 1 H6 Set)</div>
                    <div id="h6-printing-list">
                        <!-- H6 items will be loaded here -->
                    </div>
                </div>
                
                <div class="bracket-category">
                    <div class="category-header">H7 Components</div>
                    <div id="h7-printing-list">
                        <!-- H7 items will be loaded here -->
                    </div>
                </div>
                
                <div class="bracket-category">
                    <div class="category-header">H9 Components (Need all 3 for 1 H9 Set)</div>
                    <div id="h9-printing-list">
                        <!-- H9 items will be loaded here -->
                    </div>
                </div>
            </div>
            {% else %}
            <div class="permission-denied">
                <h3>Permission Denied</h3>
                <p>You need operator or admin privileges to access the Printing Station.</p>
            </div>
            {% endif %}
        </div>
        
        <!-- Picking Station Tab -->
        <div id="picking" class="tab-content">
            <h2 style="margin-bottom: 8px; font-size: 18px;">Picking Station - Prepare Orders for Assembly</h2>
            
            {% if session.role in ['admin', 'operator', 'viewer'] %}
            <!-- Print Section -->
            <div class="print-section">
                <h3 style="margin: 0 0 10px 0; font-size: 16px;">Print Picking List</h3>
                <p style="margin-bottom: 10px; font-size: 13px;">Print picking lists for orders ready for assembly.</p>
                <button class="btn btn-print" onclick="printAllPickingLists()">Print All Picking Lists</button>
                
                <div id="printable-picking-list" style="display: none;">
                    <!-- Printable content will be loaded here -->
                </div>
            </div>
            
            <!-- Work Orders Section -->
            <div class="work-order-section">
                <h3 style="margin: 0 0 10px 0; font-size: 16px;">Ready for Assembly</h3>
                <p style="margin-bottom: 10px; font-size: 13px;">Orders with all components available can be moved to Assembly Line.</p>
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
                
                <div class="bracket-category">
                    <div class="category-header">H6 Components</div>
                    <div id="h6-picking-list">
                        <!-- H6 items will be loaded here -->
                    </div>
                </div>
                
                <div class="bracket-category">
                    <div class="category-header">H7 Components</div>
                    <div id="h7-picking-list">
                        <!-- H7 items will be loaded here -->
                    </div>
                </div>
                
                <div class="bracket-category">
                    <div class="category-header">H9 Components</div>
                    <div id="h9-picking-list">
                        <!-- H9 items will be loaded here -->
                    </div>
                </div>
            </div>
            {% else %}
            <div class="permission-denied">
                <h3>Permission Denied</h3>
                <p>You need operator or admin privileges to access the Picking Station.</p>
            </div>
            {% endif %}
        </div>
        
        <!-- Assembly Line Tab -->
        <div id="assembly" class="tab-content">
            <h2 style="margin-bottom: 8px; font-size: 18px;">Assembly Line - Build and Complete Orders</h2>
            
            {% if session.role in ['admin', 'operator', 'viewer'] %}
            <!-- Orders Ready for Assembly -->
            <div class="assembly-section">
                <h3 style="margin: 0 0 10px 0; font-size: 16px;">Orders Ready for Assembly</h3>
                <p style="margin-bottom: 10px; font-size: 13px;">Orders moved from Picking Station for assembly.</p>
                <div id="assembly-ready-list">
                    <!-- Ready orders will be loaded here -->
                </div>
            </div>
            {% else %}
            <div class="permission-denied">
                <h3>Permission Denied</h3>
                <p>You need operator or admin privileges to access the Assembly Line.</p>
            </div>
            {% endif %}
        </div>
        
        <!-- Inventory Management Tab -->
        <div id="inventory" class="tab-content">
            <h2 style="margin-bottom: 8px; font-size: 18px;">Inventory Management</h2>
            
            {% if session.role in ['admin', 'operator', 'viewer'] %}
            <div class="export-section">
                <h3 style="margin: 0 0 10px 0; font-size: 16px;">Export Data</h3>
                <div class="export-buttons">
                    <button class="btn btn-export" onclick="exportToCSV()">Export to CSV</button>
                    <button class="btn btn-export" onclick="exportInventoryJSON()">Export JSON (API)</button>
                    <button class="btn btn-export" onclick="generateWorkOrderAnalysis()">Work Order Analysis</button>
                    <button class="btn btn-export" onclick="backupDatabase()">Backup Database</button>
                </div>
            </div>
            
            <div class="form-section">
                <h3 style="margin: 0 0 11px 0; font-size: 16px;">Add Work Order</h3>
                <div class="form-row">
                    <div class="form-group">
                        <label>Work Order #</label>
                        <input type="text" id="workOrderNumber" placeholder="WO-001">
                    </div>
                    <div class="form-group">
                        <label>Set Type</label>
                        <select id="workOrderSetType" onchange="toggleSpacerOption()">
                            <option value="H6">H6 Set (requires H6-623A, H6-623B, H6-623C)</option>
                            <option value="H7-282">H7-282 Set (requires H7-282 only)</option>
                            <option value="H7-304">H7-304 Set (requires H7-304 only)</option>
                            <option value="H9">H9 Set (requires H9-923A, H9-923B, H9-923C)</option>
                        </select>
                    </div>
                    <div class="form-group-small">
                        <label>Required Sets</label>
                        <input type="number" id="workOrderQty" value="0" min="0">
                    </div>
                    <div class="form-group-small" id="spacerOption" style="display: none;">
                        <label>Include Spacer?</label>
                        <div class="checkbox-group">
                            <input type="checkbox" id="includeSpacer">
                            <label for="includeSpacer" style="margin: 0;">Yes</label>
                        </div>
                    </div>
                    <div class="form-group-small">
                        <label>&nbsp;</label>
                        <button class="btn-add" onclick="addWorkOrder()">Add Work Order</button>
                    </div>
                </div>
            </div>
            
            <!-- Set Analysis -->
            <div class="set-analysis">
                <h3 style="margin: 0 0 8px 0; font-size: 16px;">Set Completion Analysis</h3>
                <div id="set-analysis-list">
                    <!-- Set analysis will be loaded here -->
                </div>
            </div>
            
            <div class="bracket-list">
                <div class="bracket-item header">
                    <div>Component</div>
                    <div>Current Qty</div>
                    <div>Set Actual Count</div>
                    <div>Action</div>
                </div>
                
                <div class="bracket-category">
                    <div class="category-header">H6 Components</div>
                    <div id="h6-inventory-list">
                        <!-- H6 items will be loaded here -->
                    </div>
                </div>
                
                <div class="bracket-category">
                    <div class="category-header">H7 Components</div>
                    <div id="h7-inventory-list">
                        <!-- H7 items will be loaded here -->
                    </div>
                </div>
                
                <div class="bracket-category">
                    <div class="category-header">H9 Components</div>
                    <div id="h9-inventory-list">
                        <!-- H9 items will be loaded here -->
                    </div>
                </div>
            </div>
            {% else %}
            <div class="permission-denied">
                <h3>Permission Denied</h3>
                <p>You need operator or admin privileges to access Inventory Management.</p>
            </div>
            {% endif %}
        </div>
        
        <!-- External Work Orders Tab -->
        <div id="external" class="tab-content">
            <h2 style="margin-bottom: 8px; font-size: 18px;">External Work Orders</h2>
            <p style="margin-bottom: 15px; font-size: 13px;">Work orders manually added or imported via CSV.</p>
            
            {% if session.role in ['admin', 'operator', 'viewer'] %}
            <div class="external-orders-section">
                <!-- CSV Upload Section -->
                <div class="upload-section">
                    <h3 style="margin: 0 0 10px 0; font-size: 16px;">Upload CSV File</h3>
                    <p style="margin-bottom: 10px; font-size: 13px;">Upload a CSV file with work orders.</p>
                    
                    <div class="file-upload">
                        <input type="file" id="csvFile" accept=".csv" style="margin-bottom: 10px;">
                        <button class="btn btn-upload" onclick="uploadCSV()">Upload CSV</button>
                    </div>
                    
                    <div class="sample-csv">
                        <strong>CSV Format (required columns):</strong><br>
                        OrderNumber,SKU,Quantity<br>
                        WO-001,PB1-28A0113-BL,10<br>
                        WO-002,PB1-X101-BL,5<br>
                        WO-003,PB1-18A0101-WH,8
                    </div>
                </div>
                
                <h3 style="margin: 15px 0 10px 0; font-size: 16px;">External Work Orders</h3>
                <div id="external-orders-list">
                    <!-- External orders will be loaded here -->
                </div>
            </div>
            {% else %}
            <div class="permission-denied">
                <h3>Permission Denied</h3>
                <p>You need operator or admin privileges to access External Work Orders.</p>
            </div>
            {% endif %}
        </div>
        
        <!-- History Tab -->
        <div id="history" class="tab-content">
            <h2 style="margin-bottom: 8px; font-size: 18px;">Movement History</h2>
            <div class="form-section">
                <div class="form-row">
                    <div class="form-group">
                        <label>Filter by Component</label>
                        <select id="historyFilter" onchange="filterHistory()">
                            <option value="all">All Components</option>
                            <option value="H6">H6 Components</option>
                            <option value="H7">H7 Components</option>
                            <option value="H9">H9 Components</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Show Last</label>
                        <select id="historyLimit" onchange="loadHistory()">
                            <option value="50">50 Records</option>
                            <option value="100">100 Records</option>
                            <option value="200">200 Records</option>
                        </select>
                    </div>
                </div>
            </div>
            
            <div id="historyList">
                <div class="history-item">
                    Loading history...
                </div>
            </div>
        </div>
        
        <!-- Admin Tab -->
        {% if session.role == 'admin' %}
        <div id="admin" class="tab-content">
            <h2 style="margin-bottom: 8px; font-size: 18px;">Administration</h2>
            
            <div class="admin-section">
                <h3 style="margin: 0 0 10px 0; font-size: 16px;">User Management</h3>
                <div class="form-row">
                    <div class="form-group">
                        <label>Username</label>
                        <input type="text" id="newUsername" placeholder="Enter username">
                    </div>
                    <div class="form-group">
                        <label>Password</label>
                        <input type="password" id="newPassword" placeholder="Enter password">
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
                
                <div class="user-list">
                    <h4 style="margin: 15px 0 10px 0;">Existing Users</h4>
                    <div id="userList">
                        <!-- Users will be loaded here -->
                    </div>
                </div>
            </div>
            
            <div class="admin-section">
                <h3 style="margin: 0 0 10px 0; font-size: 16px;">Stock Settings</h3>
                <div class="form-row">
                    <div class="form-group">
                        <label>Low Stock Threshold</label>
                        <input type="number" id="lowStockThreshold" value="5" min="1">
                    </div>
                    <div class="form-group">
                        <label>Critical Stock Threshold</label>
                        <input type="number" id="criticalStockThreshold" value="2" min="0">
                    </div>
                    <div class="form-group">
                        <label>&nbsp;</label>
                        <button class="btn-add" onclick="updateStockSettings()">Update Settings</button>
                    </div>
                </div>
            </div>
            
            <div class="admin-section">
                <h3 style="margin: 0 0 10px 0; font-size: 16px;">SKU Mapping</h3>
                <div class="form-row">
                    <div class="form-group">
                        <label>SKU to Bracket Mapping</label>
                        <textarea id="skuMapping" placeholder='{"PB1-X101-BL": ["H7-282"]}' style="width: 100%; height: 100px; font-family: monospace;"></textarea>
                    </div>
                    <div class="form-group">
                        <label>SKU to Set Type Mapping</label>
                        <textarea id="skuSetMapping" placeholder='{"PB1-X101-BL": "H7-282"}' style="width: 100%; height: 100px; font-family: monospace;"></textarea>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>&nbsp;</label>
                        <button class="btn-add" onclick="saveSkuMapping()">Save SKU Mapping</button>
                    </div>
                </div>
            </div>
            
            <div class="admin-section">
                <h3 style="margin: 0 0 10px 0; font-size: 16px;">Slack Integration</h3>
                <div class="form-row">
                    <div class="form-group">
                        <label>Slack Webhook URL</label>
                        <input type="text" id="slackWebhook" placeholder="https://hooks.slack.com/services/..." value="{{ slack_webhook }}">
                    </div>
                    <div class="form-group">
                        <label>&nbsp;</label>
                        <button class="btn-add" onclick="updateSlackWebhook()">Update Webhook</button>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Test Slack Notification</label>
                        <button class="btn" onclick="testSlackNotification()">Send Test Message</button>
                    </div>
                </div>
            </div>
            
            <div class="admin-section">
                <h3 style="margin: 0 0 10px 0; font-size: 16px;">Database Management</h3>
                <div class="form-row">
                    <div class="form-group">
                        <label>Database Status</label>
                        <div style="padding: 8px; background: #f8f9fa; border-radius: 3px;">
                            {% if using_postgres %}
                            <span style="color: var(--success);">✅ Connected to PostgreSQL</span>
                            {% else %}
                            <span style="color: var(--warning);">⚠️ Using SQLite (persistent)</span>
                            {% endif %}
                        </div>
                    </div>
                    <div class="form-group">
                        <label>Backup Database</label>
                        <button class="btn-export" onclick="backupDatabase()">Download Backup</button>
                    </div>
                    <div class="form-group">
                        <label>Clear Chat History</label>
                        <button class="btn-remove" onclick="clearChatHistory()">Clear All Chat Messages</button>
                    </div>
                </div>
            </div>
        </div>
        {% endif %}
        
        <!-- Developer Credit -->
        <div class="developer-credit">
            Developed by <strong>Mark Calvo</strong> | 
            <a href="mailto:mark.calvo@premioinc.com">Contact</a> | 
            Version 2.6 | 
            Data Persistence Enabled
        </div>
    </div>
    
    <!-- Floating Chat Widget -->
    <button class="chat-tab-btn" id="chatToggleBtn" onclick="toggleChatWindow()">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
        </svg>
        <span class="notification-badge" id="chatNotificationBadge" style="display: none;">0</span>
    </button>
    
    <div class="chat-container chat-hidden" id="chatWindow">
        <div class="chat-header" id="chatHeader">
            <div class="chat-title">Team Chat</div>
            <div class="chat-controls">
                <button class="chat-btn" onclick="toggleChatMinimize()">−</button>
                <button class="chat-btn" onclick="toggleChatWindow()">×</button>
            </div>
        </div>
        <div class="chat-messages" id="chatMessages">
            <!-- Chat messages will be loaded here -->
        </div>
        <div class="chat-input-area">
            <div class="chat-input-row">
                <input type="text" class="chat-input" id="chatInput" placeholder="Type your message..." onkeypress="handleChatInputKeypress(event)">
                <button class="chat-send-btn" onclick="sendChatMessage()">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <line x1="22" y1="2" x2="11" y2="13"></line>
                        <polygon points="22,2 15,22 11,13 2,9"></polygon>
                    </svg>
                </button>
            </div>
        </div>
    </div>
    {% endif %}

    <script>
        const socket = io();
        let currentInventory = [];
        let workOrders = [];
        let assemblyOrders = [];
        let currentUserRole = '{{ session.role }}' || 'viewer';
        let unreadMessages = 0;
        let chatWindowVisible = false;
        let chatMinimized = false;
        
        // Real-time clock function
        function updateClock() {
            const now = new Date();
            // Convert to PST (UTC-8) - Note: This doesn't account for DST
            const pstOffset = -8 * 60; // PST is UTC-8
            const localOffset = now.getTimezoneOffset();
            const pstTime = new Date(now.getTime() + (pstOffset + localOffset) * 60000);
            
            const hours = pstTime.getHours();
            const minutes = pstTime.getMinutes().toString().padStart(2, '0');
            const seconds = pstTime.getSeconds().toString().padStart(2, '0');
            const ampm = hours >= 12 ? 'PM' : 'AM';
            const displayHours = hours % 12 || 12;
            
            const timeString = `${displayHours}:${minutes}:${seconds} ${ampm} PST`;
            document.getElementById('currentTime').textContent = timeString;
        }
        
        // Start the clock and update every second
        updateClock();
        setInterval(updateClock, 1000);
        
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
            
            if (tabName === 'history') {
                loadHistory();
            } else if (tabName === 'external') {
                loadExternalOrders();
            } else if (tabName === 'assembly') {
                loadAssemblyOrders();
            } else if (tabName === 'admin' && currentUserRole === 'admin') {
                loadUsers();
                loadCompanySettings();
            }
        }
        
        // Chat System Functions
        function toggleChatWindow() {
            const chatWindow = document.getElementById('chatWindow');
            const chatBtn = document.getElementById('chatToggleBtn');
            
            if (chatWindowVisible) {
                chatWindow.classList.add('chat-hidden');
                chatBtn.style.display = 'flex';
            } else {
                chatWindow.classList.remove('chat-hidden');
                chatBtn.style.display = 'none';
                resetUnreadCount();
                loadChatMessages();
            }
            
            chatWindowVisible = !chatWindowVisible;
        }
        
        function toggleChatMinimize() {
            const chatWindow = document.getElementById('chatWindow');
            chatMinimized = !chatMinimized;
            
            if (chatMinimized) {
                chatWindow.classList.add('chat-minimized');
            } else {
                chatWindow.classList.remove('chat-minimized');
            }
        }
        
        function resetUnreadCount() {
            unreadMessages = 0;
            const badge = document.getElementById('chatNotificationBadge');
            badge.style.display = 'none';
            badge.textContent = '0';
        }
        
        function incrementUnreadCount() {
            if (!chatWindowVisible) {
                unreadMessages++;
                const badge = document.getElementById('chatNotificationBadge');
                badge.style.display = 'flex';
                badge.textContent = unreadMessages > 9 ? '9+' : unreadMessages.toString();
            }
        }
        
        function loadChatMessages() {
            fetch('/api/chat_messages')
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        updateChatDisplay(data.messages, 'chatMessages');
                    }
                });
        }
        
        function updateChatDisplay(messages, containerId) {
            const container = document.getElementById(containerId);
            container.innerHTML = '';
            
            if (messages.length === 0) {
                container.innerHTML = '<div class="chat-message message-system">No messages yet. Start the conversation!</div>';
                return;
            }
            
            messages.forEach(message => {
                const messageTime = new Date(message.timestamp).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
                let messageClass = 'message-received';
                
                if (message.sender === 'System') {
                    messageClass = 'message-system';
                } else if (message.sender === '{{ session.username }}') {
                    messageClass = 'message-sent';
                }
                
                container.innerHTML += `
                    <div class="chat-message ${messageClass}">
                        ${message.sender !== 'System' && message.sender !== '{{ session.username }}' ? 
                            `<div class="message-sender">${message.sender}</div>` : ''}
                        <div>${message.message}</div>
                        <div class="message-time">${messageTime}</div>
                    </div>
                `;
            });
            
            // Scroll to bottom
            container.scrollTop = container.scrollHeight;
        }
        
        function sendChatMessage() {
            const input = document.getElementById('chatInput');
            const message = input.value.trim();
            
            if (message) {
                socket.emit('chat_message', {
                    message: message,
                    sender: '{{ session.username }}'
                });
                
                input.value = '';
            }
        }
        
        function handleChatInputKeypress(event) {
            if (event.key === 'Enter') {
                sendChatMessage();
            }
        }
        
        // Socket events for chat
        socket.on('chat_message', (data) => {
            incrementUnreadCount();
            loadChatMessages(); // Reload messages to ensure consistency
        });
        
        socket.on('system_notification', (data) => {
            // Show system notification
            showSystemAlert(data.message, data.type || 'info');
            
            // Send to chat as system message
            socket.emit('system_chat_message', {
                message: data.message
            });
        });
        
        function showSystemAlert(message, type = 'info') {
            // Create alert element
            const alert = document.createElement('div');
            alert.className = `system-alert ${type}`;
            alert.innerHTML = message;
            
            // Add to top of container
            const container = document.querySelector('.container');
            container.insertBefore(alert, container.firstChild);
            
            // Remove after 5 seconds
            setTimeout(() => {
                alert.remove();
            }, 5000);
        }
        
        // Toggle spacer option for H9 sets
        function toggleSpacerOption() {
            const setType = document.getElementById('workOrderSetType').value;
            const spacerOption = document.getElementById('spacerOption');
            
            if (setType === 'H9') {
                spacerOption.style.display = 'block';
            } else {
                spacerOption.style.display = 'none';
                document.getElementById('includeSpacer').checked = false;
            }
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
            fetch('/api/logout')
            .then(() => {
                window.location.reload();
            });
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
            currentInventory = data.items;
            workOrders = data.work_orders || [];
            assemblyOrders = data.assembly_orders || [];
            updateAllInventoryDisplays(data.items);
            updateWorkOrderDisplay();
            updateAssemblyDisplay();
            updateSetAnalysis();
        });
        
        // Update inventory displays on all tabs
        function updateAllInventoryDisplays(items) {
            updatePrintingStation(items);
            updatePickingStation(items);
            updateInventoryManagement(items);
        }
        
        // Printing Station - Add and remove functionality
        function updatePrintingStation(items) {
            updateBracketList('h6-printing-list', items.filter(item => item.case_type === 'H6'), 'printing');
            updateBracketList('h7-printing-list', items.filter(item => item.case_type === 'H7'), 'printing');
            updateBracketList('h9-printing-list', items.filter(item => item.case_type === 'H9'), 'printing');
        }
        
        // Picking Station - With work order context
        function updatePickingStation(items) {
            updateBracketList('h6-picking-list', items.filter(item => item.case_type === 'H6'), 'picking');
            updateBracketList('h7-picking-list', items.filter(item => item.case_type === 'H7'), 'picking');
            updateBracketList('h9-picking-list', items.filter(item => item.case_type === 'H9'), 'picking');
        }
        
        // Inventory Management
        function updateInventoryManagement(items) {
            updateBracketList('h6-inventory-list', items.filter(item => item.case_type === 'H6'), 'inventory');
            updateBracketList('h7-inventory-list', items.filter(item => item.case_type === 'H7'), 'inventory');
            updateBracketList('h9-inventory-list', items.filter(item => item.case_type === 'H9'), 'inventory');
        }
        
        function updateBracketList(containerId, items, stationType) {
            const container = document.getElementById(containerId);
            container.innerHTML = '';
            
            items.forEach(item => {
                const stockClass = item.quantity <= 0 ? 'critical' : item.quantity <= item.min_stock ? 'low-stock' : '';
                const isViewer = currentUserRole === 'viewer';
                
                if (stationType === 'printing') {
                    container.innerHTML += `
                        <div class="bracket-item ${stockClass}">
                            <div class="bracket-name">${item.description || item.name}</div>
                            <div class="current-qty">${item.quantity}</div>
                            <div>
                                <input type="number" class="qty-input" id="print-qty-${item.id}" value="0" min="0" ${isViewer ? 'disabled' : ''}>
                            </div>
                            <div>
                                ${!isViewer ? `
                                    <button class="btn-add" onclick="addPrintedBrackets(${item.id})">Add</button>
                                    <button class="btn-remove" onclick="removePrintedBrackets(${item.id})">Remove</button>
                                ` : '<span style="color: #6c757d; font-size: 11px;">View Only</span>'}
                            </div>
                        </div>
                    `;
                } else if (stationType === 'picking') {
                    container.innerHTML += `
                        <div class="bracket-item ${stockClass}">
                            <div class="bracket-name">${item.description || item.name}</div>
                            <div class="current-qty">${item.quantity}</div>
                            <div>
                                <input type="number" class="qty-input" id="pick-qty-${item.id}" value="0" min="0" ${isViewer ? 'disabled' : ''}>
                            </div>
                            <div>
                                ${!isViewer ? `
                                    <button class="btn-remove" onclick="removeBrackets(${item.id})">Remove</button>
                                    <button class="btn-add" onclick="addReturn(${item.id})">Return</button>
                                ` : '<span style="color: #6c757d; font-size: 11px;">View Only</span>'}
                            </div>
                        </div>
                    `;
                } else if (stationType === 'inventory') {
                    container.innerHTML += `
                        <div class="bracket-item ${stockClass}">
                            <div class="bracket-name">${item.description || item.name}</div>
                            <div class="current-qty">${item.quantity}</div>
                            <div>
                                <input type="number" class="qty-input" id="actual-qty-${item.id}" value="${item.quantity}" min="0" ${isViewer ? 'disabled' : ''}>
                            </div>
                            <div>
                                ${!isViewer ? `
                                    <button class="btn" onclick="updateActualCount(${item.id})">Update</button>
                                ` : '<span style="color: #6c757d; font-size: 11px;">View Only</span>'}
                            </div>
                        </div>
                    `;
                }
            });
        }
        
        // Update work order display - manual move to assembly
        function updateWorkOrderDisplay() {
            const container = document.getElementById('work-order-list');
            container.innerHTML = '';
            
            // Filter out orders that are already in assembly
            const activeWorkOrders = workOrders.filter(wo => 
                !assemblyOrders.some(ao => ao.work_order_id === wo.id)
            );
            
            if (activeWorkOrders.length === 0) {
                container.innerHTML = '<div class="work-order-item">No work orders ready for assembly</div>';
                return;
            }
            
            // Group work orders by set type
            const ordersByType = {
                'H6': [],
                'H7-282': [],
                'H7-304': [],
                'H9': []
            };
            
            activeWorkOrders.forEach(order => {
                if (ordersByType[order.set_type]) {
                    ordersByType[order.set_type].push(order);
                }
            });
            
            // Display orders by type in order
            ['H6', 'H7-282', 'H7-304', 'H9'].forEach(setType => {
                if (ordersByType[setType].length > 0) {
                    const categoryDiv = document.createElement('div');
                    categoryDiv.className = 'work-order-category';
                    categoryDiv.innerHTML = `<div class="work-order-category-header">${setType} Sets</div>`;
                    
                    ordersByType[setType].forEach(workOrder => {
                        // Get components for this set type
                        const components = getComponentsForSet(workOrder.set_type, workOrder.include_spacer);
                        let canMoveToAssembly = true;
                        let missingComponents = [];
                        
                        // Check if we have enough of each component
                        components.forEach(componentName => {
                            const component = currentInventory.find(item => item.name === componentName);
                            if (!component || component.quantity < workOrder.required_sets) {
                                canMoveToAssembly = false;
                                missingComponents.push({
                                    name: componentName,
                                    required: workOrder.required_sets,
                                    available: component ? component.quantity : 0,
                                    missing: workOrder.required_sets - (component ? component.quantity : 0)
                                });
                            }
                        });
                        
                        const isViewer = currentUserRole === 'viewer';
                        
                        categoryDiv.innerHTML += `
                            <div class="work-order-item">
                                <div class="work-order-header">
                                    <div class="work-order-title">${workOrder.order_number} - ${workOrder.required_sets} sets ${workOrder.include_spacer ? '(with spacer)' : ''}</div>
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
                                        const available = comp ? comp.quantity : 0;
                                        return `
                                            <div class="component-item ${hasEnough ? 'component-ok' : 'component-missing'}">
                                                <div><strong>${compName}</strong></div>
                                                <div>${available} / ${workOrder.required_sets}</div>
                                                <div>${hasEnough ? 'OK' : 'LOW'}</div>
                                            </div>
                                        `;
                                    }).join('')}
                                </div>
                                ${!canMoveToAssembly ? `
                                    <div class="missing-warning">
                                        <strong>Missing:</strong> ${missingComponents.map(mc => `${mc.name} (need ${mc.missing})`).join(', ')}
                                    </div>
                                ` : ''}
                            </div>
                        `;
                    });
                    
                    container.appendChild(categoryDiv);
                }
            });
        }
        
        // Update assembly line display - only show ready orders
        function updateAssemblyDisplay() {
            updateAssemblyReadyList();
        }
        
        function updateAssemblyReadyList() {
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
                
                const components = getComponentsForSet(workOrder.set_type, workOrder.include_spacer);
                const isViewer = currentUserRole === 'viewer';
                
                container.innerHTML += `
                    <div class="work-order-item assembly-ready">
                        <div class="work-order-header">
                            <div class="work-order-title">
                                ${workOrder.order_number} - ${workOrder.required_sets} sets ${workOrder.include_spacer ? '(with spacer)' : ''}
                                <span class="assembly-status status-ready">READY</span>
                            </div>
                            <div class="work-order-actions">
                                ${!isViewer ? `
                                    <button class="btn-complete" onclick="completeAssembly(${order.id})">Complete</button>
                                ` : ''}
                            </div>
                        </div>
                        <div class="component-list">
                            ${components.map(compName => {
                                return `
                                    <div class="component-item component-ok">
                                        <div><strong>${compName}</strong></div>
                                        <div>${workOrder.required_sets} needed</div>
                                        <div>READY</div>
                                    </div>
                                `;
                            }).join('')}
                        </div>
                        <div class="assembly-info">
                            Moved to assembly: ${new Date(order.moved_at).toLocaleString()}
                        </div>
                    </div>
                `;
            });
        }
        
        // Print all picking lists in one page - IMPROVED VERSION
        function printAllPickingLists() {
            const readyOrders = assemblyOrders.filter(order => order.status === 'ready');
            
            if (readyOrders.length === 0) {
                alert('No orders ready for picking');
                return;
            }
            
            const printContainer = document.getElementById('printable-picking-list');
            printContainer.innerHTML = '';
            
            // Create a container for all printable orders
            const allOrdersContainer = document.createElement('div');
            allOrdersContainer.className = 'print-all-container';
            
            readyOrders.forEach((order, index) => {
                const workOrder = workOrders.find(wo => wo.id === order.work_order_id);
                if (!workOrder) return;
                
                const components = getComponentsForSet(workOrder.set_type, workOrder.include_spacer);
                
                const printableDiv = document.createElement('div');
                printableDiv.className = 'printable-order';
                printableDiv.innerHTML = `
                    <div class="print-header">
                        <h2>PICKING LIST</h2>
                        <h3>Work Order: ${workOrder.order_number}</h3>
                        <p>Set Type: ${workOrder.set_type} | Required Sets: ${workOrder.required_sets}</p>
                        <p>Date: ${new Date().toLocaleDateString()}</p>
                    </div>
                    <div class="print-components">
                        ${components.map(compName => `
                            <div class="print-component">
                                <strong>${compName}</strong><br>
                                Quantity: ${workOrder.required_sets}
                            </div>
                        `).join('')}
                    </div>
                    <div class="print-footer">
                        <p>Generated: ${new Date().toLocaleString()}</p>
                        <p>Bracket Inventory Tracker</p>
                    </div>
                `;
                
                allOrdersContainer.appendChild(printableDiv);
                
                // Add page break except for the last order
                if (index < readyOrders.length - 1) {
                    allOrdersContainer.innerHTML += '<div style="page-break-after: always;"></div>';
                }
            });
            
            printContainer.appendChild(allOrdersContainer);
            
            // Show print dialog
            printContainer.style.display = 'block';
            
            // Use a small delay to ensure the content is rendered before printing
            setTimeout(() => {
                window.print();
                // Hide after printing
                setTimeout(() => {
                    printContainer.style.display = 'none';
                }, 100);
            }, 100);
        }
        
        // Update set analysis display
        function updateSetAnalysis() {
            const container = document.getElementById('set-analysis-list');
            container.innerHTML = '';
            
            const setTypes = ['H6', 'H7-282', 'H7-304', 'H9'];
            
            setTypes.forEach(setType => {
                const components = getComponentsForSet(setType, false); // Base analysis without spacer
                const componentQtys = components.map(compName => {
                    const comp = currentInventory.find(item => item.name === compName);
                    return comp ? comp.quantity : 0;
                });
                
                // The maximum number of complete sets we can build
                const maxSets = Math.min(...componentQtys);
                
                container.innerHTML += `
                    <div class="set-item">
                        <div class="set-header">${setType} Set Analysis</div>
                        <div class="component-list">
                            ${components.map((compName, index) => {
                                const comp = currentInventory.find(item => item.name === compName);
                                const qty = comp ? comp.quantity : 0;
                                const setsPossible = Math.floor(qty);
                                const isLimiting = setsPossible === maxSets;
                                return `
                                    <div class="component-item ${isLimiting ? 'component-missing' : 'component-ok'}">
                                        <div>${compName}</div>
                                        <div>${qty} available</div>
                                        <div>${setsPossible} sets</div>
                                    </div>
                                `;
                            }).join('')}
                        </div>
                        <div style="margin-top: 6px; font-weight: bold; font-size: 12px;">
                            Maximum ${setType} Sets Possible: <span style="color: ${maxSets > 0 ? '#28a745' : '#dc3545'}">${maxSets}</span>
                        </div>
                    </div>
                `;
            });
        }
        
        // Get components for each set type
        function getComponentsForSet(setType, includeSpacer = false) {
            const componentMap = {
                'H6': ['H6-623A', 'H6-623B', 'H6-623C'],
                'H7-282': ['H7-282'],
                'H7-304': ['H7-304'],
                'H9': includeSpacer ? ['H9-923A', 'H9-923B', 'H9-923C', 'H9-SPACER'] : ['H9-923A', 'H9-923B', 'H9-923C']
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
            
            // Reset input
            qtyInput.value = '0';
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
            
            // Reset input
            qtyInput.value = '0';
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
            
            // Reset input
            qtyInput.value = '0';
        }
        
        function addReturn(itemId) {
            const qtyInput = document.getElementById(`pick-qty-${itemId}`);
            const quantity = parseInt(qtyInput.value);
            
            if (!quantity || quantity < 1) {
                alert('Please enter a valid quantity greater than 0');
                return;
            }
            
            socket.emit('inventory_change', {
                item_id: itemId,
                change: quantity,
                station: 'Picking Station',
                notes: 'Return'
            });
            
            // Reset input
            qtyInput.value = '0';
        }
        
        // Work Order Functions
        function addWorkOrder() {
            const orderNumber = document.getElementById('workOrderNumber').value;
            const setType = document.getElementById('workOrderSetType').value;
            const quantity = parseInt(document.getElementById('workOrderQty').value);
            const includeSpacer = setType === 'H9' ? document.getElementById('includeSpacer').checked : false;
            
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
                    include_spacer: includeSpacer
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('Work order added successfully!');
                    document.getElementById('workOrderNumber').value = '';
                    document.getElementById('workOrderQty').value = '0';
                    document.getElementById('includeSpacer').checked = false;
                    
                    // Refresh data
                    socket.emit('get_inventory');
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }
        
        function moveToAssembly(workOrderId) {
            if (!confirm('Move this work order to Assembly Line? This will deduct components from inventory.')) {
                return;
            }
            
            fetch('/api/move_to_assembly', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    work_order_id: workOrderId
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('Work order moved to Assembly Line! Components deducted from inventory.');
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
                body: JSON.stringify({
                    work_order_id: workOrderId
                })
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
        function loadAssemblyOrders() {
            fetch('/api/assembly_orders')
                .then(response => response.json())
                .then(data => {
                    assemblyOrders = data.assembly_orders || [];
                    updateAssemblyDisplay();
                });
        }
        
        function completeAssembly(assemblyOrderId) {
            if (!confirm('Mark this assembly as complete?')) {
                return;
            }
            
            fetch('/api/complete_assembly', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    assembly_order_id: assemblyOrderId
                })
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
                alert('No change needed - quantity matches current');
                return;
            }
            
            const notes = `Physical count adjustment: ${currentItem.quantity} → ${actualQty}`;
            
            socket.emit('inventory_change', {
                item_id: itemId,
                change: adjustment,
                station: 'Inventory Management',
                notes: notes
            });
        }
        
        // Export Functions
        function exportToCSV() {
            window.open('/api/export/csv', '_blank');
        }
        
        function exportInventoryJSON() {
            window.open('/api/inventory_json', '_blank');
        }
        
        function backupDatabase() {
            window.open('/api/backup_database', '_blank');
        }
        
        function generateWorkOrderAnalysis() {
            fetch('/api/work_order_analysis', {
                method: 'POST'
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('Work order analysis sent to Slack!');
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }
        
        // External Orders Functions
        function uploadCSV() {
            const fileInput = document.getElementById('csvFile');
            const file = fileInput.files[0];
            
            if (!file) {
                alert('Please select a CSV file to upload');
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
                    alert('CSV uploaded successfully! ' + data.message);
                    document.getElementById('csvFile').value = '';
                    loadExternalOrders();
                    socket.emit('get_inventory');
                } else {
                    alert('Error: ' + data.error);
                }
            })
            .catch(error => {
                alert('Upload failed: ' + error);
            });
        }
        
        function loadExternalOrders() {
            fetch('/api/external_orders')
                .then(response => response.json())
                .then(data => {
                    updateExternalOrdersDisplay(data.orders);
                });
        }
        
        function updateExternalOrdersDisplay(orders) {
            const container = document.getElementById('external-orders-list');
            container.innerHTML = '';
            
            if (orders.length === 0) {
                container.innerHTML = '<div class="external-order-item">No external work orders found</div>';
                return;
            }
            
            orders.forEach(order => {
                const requiredBrackets = Array.isArray(order.required_brackets) ? order.required_brackets : JSON.parse(order.required_brackets || '[]');
                const isViewer = currentUserRole === 'viewer';
                
                container.innerHTML += `
                    <div class="external-order-item">
                        <div class="work-order-header">
                            <div class="work-order-title">${order.external_order_number}</div>
                            <div class="work-order-actions">
                                ${!isViewer ? `
                                    <button class="btn-convert" onclick="convertExternalOrder(${order.id})">Convert to Work Order</button>
                                    <button class="btn-complete" onclick="completeExternalOrder(${order.id})">Complete</button>
                                    <button class="btn-delete" onclick="deleteExternalOrder(${order.id})">Delete</button>
                                ` : ''}
                            </div>
                        </div>
                        <div class="external-order-info">
                            <div class="external-order-detail">
                                <strong>SKU</strong>
                                ${order.sku}
                            </div>
                            <div class="external-order-detail">
                                <strong>Quantity</strong>
                                ${order.quantity} sets
                            </div>
                            <div class="external-order-detail">
                                <strong>GPU Brackets</strong>
                                ${requiredBrackets.join(', ')}
                            </div>
                        </div>
                        <div style="margin-top: 6px; font-size: 12px;">
                            <strong>Status:</strong> ${order.status} | 
                            <strong>Created:</strong> ${new Date(order.created_at).toLocaleString()}
                        </div>
                    </div>
                `;
            });
        }
        
        function convertExternalOrder(orderId) {
            if (!confirm('Convert this external order to a regular work order?')) {
                return;
            }
            
            fetch('/api/convert_external_order', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ external_order_id: orderId })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('External order converted to work order successfully!');
                    loadExternalOrders();
                    socket.emit('get_inventory');
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }
        
        function completeExternalOrder(orderId) {
            if (!confirm('Mark this external work order as complete?')) {
                return;
            }
            
            fetch('/api/complete_external_order', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ order_id: orderId })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('External work order completed successfully!');
                    loadExternalOrders();
                    socket.emit('get_inventory');
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }
        
        function deleteExternalOrder(orderId) {
            if (!confirm('Delete this external work order?')) {
                return;
            }
            
            fetch('/api/delete_external_order', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ order_id: orderId })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('External work order deleted successfully!');
                    loadExternalOrders();
                    socket.emit('get_inventory');
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }
        
        // History functions
        function loadHistory() {
            const limit = document.getElementById('historyLimit').value;
            const filter = document.getElementById('historyFilter').value;
            
            fetch(`/api/history?limit=${limit}&filter=${filter}`)
                .then(response => response.json())
                .then(data => {
                    updateHistoryDisplay(data.history);
                });
        }
        
        function filterHistory() {
            loadHistory();
        }
        
        function updateHistoryDisplay(history) {
            const container = document.getElementById('historyList');
            container.innerHTML = '';
            
            if (history.length === 0) {
                container.innerHTML = '<div class="history-item">No history found</div>';
                return;
            }
            
            history.forEach(record => {
                const typeClass = record.change > 0 ? 'history-add' : 'history-remove';
                const sign = record.change > 0 ? '+' : '';
                const time = new Date(record.timestamp).toLocaleString();
                
                container.innerHTML += `
                    <div class="history-item ${typeClass}">
                        <div>
                            <strong>${record.station}</strong><br>
                            ${record.item_name}: ${sign}${record.change}<br>
                            <small>By: ${record.username || 'System'} | ${time}</small>
                        </div>
                        <div style="text-align: right;">
                            ${record.notes ? `<small>${record.notes}</small>` : ''}
                        </div>
                    </div>
                `;
            });
        }
        
        // Admin Functions
        function loadUsers() {
            if (currentUserRole !== 'admin') return;
            
            fetch('/api/users')
                .then(response => response.json())
                .then(data => {
                    updateUserList(data.users);
                });
        }
        
        function updateUserList(users) {
            const container = document.getElementById('userList');
            container.innerHTML = '';
            
            users.forEach(user => {
                container.innerHTML += `
                    <div class="user-item">
                        <div>
                            <strong>${user.username}</strong> - ${user.role}
                            ${user.username === '{{ session.username }}' ? ' <em>(current user)</em>' : ''}
                        </div>
                        <div class="user-actions">
                            <button class="btn" onclick="changeUserRole(${user.id})">Change Role</button>
                            ${user.username !== '{{ session.username }}' ? 
                                `<button class="btn-remove" onclick="deleteUser(${user.id})">Delete</button>` : 
                                ''
                            }
                        </div>
                    </div>
                `;
            });
        }
        
        function addUser() {
            const username = document.getElementById('newUsername').value;
            const password = document.getElementById('newPassword').value;
            const role = document.getElementById('newUserRole').value;
            
            if (!username || !password) {
                alert('Please enter both username and password');
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
            if (!newRole || !['admin', 'operator', 'viewer'].includes(newRole)) {
                alert('Invalid role. Must be admin, operator, or viewer.');
                return;
            }
            
            fetch('/api/users/role', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: userId, role: newRole })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('User role updated successfully!');
                    loadUsers();
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }
        
        function deleteUser(userId) {
            if (!confirm('Are you sure you want to delete this user?')) {
                return;
            }
            
            fetch('/api/users', {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_id: userId })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('User deleted successfully!');
                    loadUsers();
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }
        
        function updateStockSettings() {
            const lowStock = document.getElementById('lowStockThreshold').value;
            const criticalStock = document.getElementById('criticalStockThreshold').value;
            
            fetch('/api/stock_settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    low_stock: parseInt(lowStock),
                    critical_stock: parseInt(criticalStock)
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('Stock settings updated successfully!');
                    socket.emit('get_inventory');
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }
        
        function loadCompanySettings() {
            if (currentUserRole !== 'admin') return;
            
            fetch('/api/company_settings')
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        document.getElementById('skuMapping').value = JSON.stringify(data.sku_mapping || {}, null, 2);
                        document.getElementById('skuSetMapping').value = JSON.stringify(data.sku_set_mapping || {}, null, 2);
                        document.getElementById('lowStockThreshold').value = data.low_stock_threshold || 5;
                        document.getElementById('criticalStockThreshold').value = data.critical_stock_threshold || 2;
                        document.getElementById('slackWebhook').value = data.slack_webhook_url || '';
                    }
                });
        }
        
        function saveSkuMapping() {
            const skuMappingText = document.getElementById('skuMapping').value;
            const skuSetMappingText = document.getElementById('skuSetMapping').value;
            
            try {
                const skuMapping = JSON.parse(skuMappingText);
                const skuSetMapping = JSON.parse(skuSetMappingText);
                
                fetch('/api/sku_mapping', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ 
                        sku_mapping: skuMapping,
                        sku_set_mapping: skuSetMapping
                    })
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        alert('SKU mapping saved successfully!');
                        socket.emit('get_inventory');
                        loadExternalOrders();
                        } else {
                        alert('Error: ' + data.error);
                    }
                });
            } catch (e) {
                alert('Invalid JSON format for SKU mapping');
            }
        }
        
        function updateSlackWebhook() {
            const webhook = document.getElementById('slackWebhook').value;
            
            fetch('/api/slack_webhook', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ webhook_url: webhook })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('Slack webhook updated successfully!');
                    } else {
                    alert('Error: ' + data.error);
                }
            });
        }
        
        function testSlackNotification() {
            fetch('/api/test_slack', {
                method: 'POST'
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('Test notification sent!');
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }
        
        function clearChatHistory() {
            if (!confirm('Are you sure you want to clear all chat messages? This action cannot be undone.')) {
                return;
            }
            
            fetch('/api/clear_chat_history', {
                method: 'POST'
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('Chat history cleared successfully!');
                    loadChatMessages();
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }
        
        // Load history when page loads
        window.onload = function() {
            if (currentUserRole !== 'viewer') {
                loadHistory();
                loadExternalOrders();
                loadAssemblyOrders();
                loadChatMessages();
            } else {
                // Viewer can still see these, just not edit
                loadHistory();
                loadExternalOrders();
                loadAssemblyOrders();
                loadChatMessages();
            }
            
            // Make chat window draggable
            makeChatDraggable();
        };
        
        // Make chat window draggable
        function makeChatDraggable() {
            const chatHeader = document.getElementById('chatHeader');
            const chatWindow = document.getElementById('chatWindow');
            
            let pos1 = 0, pos2 = 0, pos3 = 0, pos4 = 0;
            
            chatHeader.onmousedown = dragMouseDown;
            
            function dragMouseDown(e) {
                e = e || window.event;
                e.preventDefault();
                // get the mouse cursor position at startup:
                pos3 = e.clientX;
                pos4 = e.clientY;
                document.onmouseup = closeDragElement;
                // call a function whenever the cursor moves:
                document.onmousemove = elementDrag;
            }
            
            function elementDrag(e) {
                e = e || window.event;
                e.preventDefault();
                // calculate the new cursor position:
                pos1 = pos3 - e.clientX;
                pos2 = pos4 - e.clientY;
                pos3 = e.clientX;
                pos4 = e.clientY;
                // set the element's new position:
                chatWindow.style.top = (chatWindow.offsetTop - pos2) + "px";
                chatWindow.style.left = (chatWindow.offsetLeft - pos1) + "px";
            }
            
            function closeDragElement() {
                // stop moving when mouse button is released:
                document.onmouseup = null;
                document.onmousemove = null;
            }
        }
    </script>
</body>
</html>
'''

def hash_password(password):
    """Hash a password for storing."""
    return hashlib.sha256(password.encode()).hexdigest()

def init_database():
    """Initialize the database with proper persistence"""
    conn = get_db_connection()
    
    try:
        # Check if we're using PostgreSQL
        is_postgres = 'postgresql' in str(conn)
        
        if is_postgres:
            logger.info("🔗 Using PostgreSQL database")
            c = conn.cursor()
            
            # Enable UUID extension if needed
            c.execute("CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";")
            
            # Create tables with PostgreSQL syntax
            c.execute('''
                CREATE TABLE IF NOT EXISTS items
                (id SERIAL PRIMARY KEY,
                 name TEXT NOT NULL UNIQUE,
                 description TEXT,
                 case_type TEXT,
                 quantity INTEGER DEFAULT 0,
                 min_stock INTEGER DEFAULT 5,
                 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
            ''')
            
            c.execute('''
                CREATE TABLE IF NOT EXISTS transactions
                (id SERIAL PRIMARY KEY,
                 item_id INTEGER,
                 change INTEGER,
                 station TEXT,
                 notes TEXT,
                 username TEXT,
                 timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
            ''')
            
            c.execute('''
                CREATE TABLE IF NOT EXISTS work_orders
                (id SERIAL PRIMARY KEY,
                 order_number TEXT NOT NULL,
                 set_type TEXT NOT NULL,
                 required_sets INTEGER NOT NULL,
                 include_spacer BOOLEAN DEFAULT FALSE,
                 status TEXT DEFAULT 'active',
                 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
            ''')
            
            c.execute('''
                CREATE TABLE IF NOT EXISTS external_work_orders
                (id SERIAL PRIMARY KEY,
                 external_order_number TEXT NOT NULL UNIQUE,
                 sku TEXT NOT NULL,
                 quantity INTEGER NOT NULL,
                 required_brackets TEXT NOT NULL,
                 status TEXT DEFAULT 'active',
                 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                 last_synced TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
            ''')
            
            c.execute('''
                CREATE TABLE IF NOT EXISTS assembly_orders
                (id SERIAL PRIMARY KEY,
                 work_order_id INTEGER NOT NULL,
                 status TEXT DEFAULT 'ready',
                 moved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                 started_at TIMESTAMP,
                 completed_at TIMESTAMP,
                 assembled_by TEXT,
                 notes TEXT)
            ''')
            
            c.execute('''
                CREATE TABLE IF NOT EXISTS users
                (id SERIAL PRIMARY KEY,
                 username TEXT NOT NULL UNIQUE,
                 password_hash TEXT NOT NULL,
                 role TEXT NOT NULL DEFAULT 'viewer',
                 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
            ''')
            
            c.execute('''
                CREATE TABLE IF NOT EXISTS settings
                (id SERIAL PRIMARY KEY,
                 key TEXT NOT NULL UNIQUE,
                 value TEXT NOT NULL)
            ''')
            
            c.execute('''
                CREATE TABLE IF NOT EXISTS chat_messages
                (id SERIAL PRIMARY KEY,
                 sender TEXT NOT NULL,
                 message TEXT NOT NULL,
                 timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
            ''')
            
        else:
            logger.info("🔗 Using SQLite database with persistence")
            c = conn.cursor()
            
            # Create tables with SQLite syntax
            c.execute('''
                CREATE TABLE IF NOT EXISTS items
                (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 name TEXT NOT NULL UNIQUE,
                 description TEXT,
                 case_type TEXT,
                 quantity INTEGER DEFAULT 0,
                 min_stock INTEGER DEFAULT 5,
                 created_at DATETIME DEFAULT CURRENT_TIMESTAMP)
            ''')
            
            c.execute('''
                CREATE TABLE IF NOT EXISTS transactions
                (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 item_id INTEGER,
                 change INTEGER,
                 station TEXT,
                 notes TEXT,
                 username TEXT,
                 timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)
            ''')
            
            c.execute('''
                CREATE TABLE IF NOT EXISTS work_orders
                (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 order_number TEXT NOT NULL,
                 set_type TEXT NOT NULL,
                 required_sets INTEGER NOT NULL,
                 include_spacer BOOLEAN DEFAULT 0,
                 status TEXT DEFAULT 'active',
                 created_at DATETIME DEFAULT CURRENT_TIMESTAMP)
            ''')
            
            c.execute('''
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
            
            c.execute('''
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
            
            c.execute('''
                CREATE TABLE IF NOT EXISTS users
                (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 username TEXT NOT NULL UNIQUE,
                 password_hash TEXT NOT NULL,
                 role TEXT NOT NULL DEFAULT 'viewer',
                 created_at DATETIME DEFAULT CURRENT_TIMESTAMP)
            ''')
            
            c.execute('''
                CREATE TABLE IF NOT EXISTS settings
                (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 key TEXT NOT NULL UNIQUE,
                 value TEXT NOT NULL)
            ''')
            
            c.execute('''
                CREATE TABLE IF NOT EXISTS chat_messages
                (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 sender TEXT NOT NULL,
                 message TEXT NOT NULL,
                 timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)
            ''')
        
        # Add initial brackets with updated names
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
            if is_postgres:
                c.execute('INSERT INTO items (name, description, case_type, quantity, min_stock) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (name) DO NOTHING', item)
            else:
                c.execute('INSERT OR IGNORE INTO items (name, description, case_type, quantity, min_stock) VALUES (?, ?, ?, ?, ?)', item)
        
        # Add sample work orders
        sample_work_orders = [
            ('WO-001', 'H6', 10, False),
            ('WO-002', 'H7-282', 5, False),
            ('WO-003', 'H7-304', 5, False),
            ('WO-004', 'H9', 8, True)
        ]
        
        for wo in sample_work_orders:
            if is_postgres:
                c.execute('INSERT INTO work_orders (order_number, set_type, required_sets, include_spacer) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING', wo)
            else:
                c.execute('INSERT OR IGNORE INTO work_orders (order_number, set_type, required_sets, include_spacer) VALUES (?, ?, ?, ?)', wo)
        
        # Add default users
        default_users = [
            ('admin', hash_password('admin123'), 'admin'),
            ('operator', hash_password('operator123'), 'operator'),
            ('viewer', hash_password('viewer123'), 'viewer')
        ]
        
        for user in default_users:
            if is_postgres:
                c.execute('INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s) ON CONFLICT (username) DO NOTHING', user)
            else:
                c.execute('INSERT OR IGNORE INTO users (username, password_hash, role) VALUES (?, ?, ?)', user)
        
        # Add default settings
        default_settings = [
            ('low_stock_threshold', '5'),
            ('critical_stock_threshold', '2'),
            ('slack_webhook_url', SLACK_WEBHOOK_URL),
            ('sku_mapping', json.dumps(SKU_BRACKET_MAPPING)),
            ('sku_set_mapping', json.dumps(SKU_SET_MAPPING))
        ]
        
        for setting in default_settings:
            if is_postgres:
                c.execute('INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value', setting)
            else:
                c.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', setting)
        
        # Add welcome chat message
        welcome_message = ('System', 'Welcome to the Bracket Inventory Tracker! Use this chat to communicate with your team.')
        if is_postgres:
            c.execute('INSERT INTO chat_messages (sender, message) VALUES (%s, %s)', welcome_message)
        else:
            c.execute('INSERT INTO chat_messages (sender, message) VALUES (?, ?)', welcome_message)
        
        conn.commit()
        logger.info("✅ Database initialized successfully with persistent storage")
        
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()

def get_setting(key, default=None):
    conn = get_db_connection()
    is_postgres = 'postgresql' in str(conn)
    
    try:
        if is_postgres:
            setting = conn.execute('SELECT value FROM settings WHERE key = %s', (key,)).fetchone()
        else:
            setting = conn.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
        
        return setting['value'] if setting else default
    finally:
        conn.close()

def update_setting(key, value):
    conn = get_db_connection()
    is_postgres = 'postgresql' in str(conn)
    
    try:
        if is_postgres:
            conn.execute('INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value', (key, value))
        else:
            conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
        
        conn.commit()
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

def get_pst_time():
    """Get current time in PST timezone without pytz dependency"""
    utc_now = datetime.now(timezone.utc)
    # PST is UTC-8 (no DST handling for simplicity)
    pst_offset = timedelta(hours=-8)
    pst_time = utc_now + pst_offset
    return pst_time.strftime("%I:%M:%S %p").lstrip('0')

def send_slack_notification(message):
    """Send notification to Slack with improved error handling"""
    webhook_url = get_setting('slack_webhook_url')
    if not webhook_url:
        logger.info("❌ No Slack webhook URL configured")
        return False
    
    # Validate webhook URL format
    if not webhook_url.startswith('https://hooks.slack.com/services/'):
        logger.error("❌ Invalid Slack webhook URL format")
        return False
    
    try:
        payload = {
            "text": message,
            "username": "Bracket Inventory Tracker",
            "icon_emoji": ":package:"
        }
        
        # Add timeout and better error handling
        response = requests.post(
            webhook_url, 
            json=payload, 
            timeout=10,
            headers={'Content-Type': 'application/json'}
        )
        
        if response.status_code == 200:
            logger.info("✅ Slack notification sent successfully")
            return True
        else:
            logger.error(f"❌ Slack notification failed with status: {response.status_code}")
            logger.error(f"Response: {response.text}")
            return False
            
    except requests.exceptions.Timeout:
        logger.error("❌ Slack notification timed out")
        return False
    except requests.exceptions.ConnectionError:
        logger.error("❌ Slack notification connection error")
        return False
    except Exception as e:
        logger.error(f"❌ Slack notification failed: {e}")
        return False

# ... (rest of your existing functions remain the same - send_work_order_analysis_notification, convert_external_to_work_order, etc.)

def broadcast_update():
    """Broadcast inventory updates to all connected clients"""
    conn = get_db_connection()
    is_postgres = 'postgresql' in str(conn)
    
    try:
        items = conn.execute('SELECT * FROM items ORDER BY name').fetchall()
        
        if is_postgres:
            recent_activity = conn.execute('''
                SELECT t.*, i.name as item_name 
                FROM transactions t 
                JOIN items i ON t.item_id = i.id 
                ORDER BY t.timestamp DESC 
                LIMIT 10
            ''').fetchall()
            
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
        else:
            recent_activity = conn.execute('''
                SELECT t.*, i.name as item_name 
                FROM transactions t 
                JOIN items i ON t.item_id = i.id 
                ORDER BY t.timestamp DESC 
                LIMIT 10
            ''').fetchall()
            
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
        activity_data = [dict(act) for act in recent_activity]
        work_orders_data = [dict(wo) for wo in work_orders]
        assembly_orders_data = [dict(ao) for ao in assembly_orders]
        
        socketio.emit('inventory_update', {
            'items': items_data,
            'recent_activity': activity_data,
            'work_orders': work_orders_data,
            'assembly_orders': assembly_orders_data
        })
        
    except Exception as e:
        logger.error(f"Error broadcasting update: {e}")
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
    logger.info(f"🔗 Client connected: {request.sid}")
    broadcast_update()

@socketio.on('inventory_change')
@login_required
def handle_inventory_change(data):
    try:
        # Check if user has operator or admin role
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
        is_postgres = 'postgresql' in str(conn)
        
        try:
            if is_postgres:
                item = conn.execute('SELECT * FROM items WHERE id = %s', (item_id,)).fetchone()
            else:
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
            
            if is_postgres:
                conn.execute('UPDATE items SET quantity = %s WHERE id = %s', (new_quantity, item_id))
                
                # Record transaction with username
                conn.execute('''
                    INSERT INTO transactions (item_id, change, station, notes, username, timestamp)
                    VALUES (%s, %s, %s, %s, %s, %s)
                ''', (item_id, change, station, notes, session['username'], datetime.now()))
            else:
                conn.execute('UPDATE items SET quantity = ? WHERE id = ?', (new_quantity, item_id))
                
                # Record transaction with username
                conn.execute('''
                    INSERT INTO transactions (item_id, change, station, notes, username, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (item_id, change, station, notes, session['username'], datetime.now()))
            
            # Send Slack notification for inventory changes
            if station == 'Printing Station':
                send_printing_notification(item['name'], change, new_quantity)
            else:
                send_inventory_change_notification(item['name'], change, station, notes)
            
            # Check for low stock and send additional Slack notification
            low_threshold = int(get_setting('low_stock_threshold', 5))
            critical_threshold = int(get_setting('critical_stock_threshold', 2))
            
            if new_quantity <= critical_threshold:
                message = f"🔴 *CRITICAL STOCK ALERT*\n\n*Component:* {item['name']}\n*Current Stock:* {new_quantity} units\n*Critical Threshold:* {critical_threshold} units\n\n*Action Required:* Please restock immediately!"
                send_slack_notification(message)
            elif new_quantity <= low_threshold:
                message = f"🟡 *LOW STOCK WARNING*\n\n*Component:* {item['name']}\n*Current Stock:* {new_quantity} units\n*Low Threshold:* {low_threshold} units\n\n*Action Suggested:* Consider restocking soon."
                send_slack_notification(message)
            
            conn.commit()
            logger.info(f"📊 {session['username']} at {station}: {item['name']} {change:+d} = {new_quantity}")
            
        except Exception as e:
            logger.error(f"Database error in inventory change: {e}")
            conn.rollback()
            socketio.emit('error', {'message': f'Database error: {str(e)}'}, room=request.sid)
        finally:
            conn.close()
        
        broadcast_update()
        
    except Exception as e:
        logger.error(f"Error in inventory_change: {str(e)}")
        socketio.emit('error', {'message': f'Error: {str(e)}'}, room=request.sid)

# ... (rest of your existing routes remain the same - they should work with the new database connection)

@app.route('/')
def index():
    if 'user_id' not in session:
        return render_template_string(HTML_TEMPLATE, 
                                   slack_webhook=get_setting('slack_webhook_url', ''),
                                   using_postgres='postgresql' in DATABASE_URL)
    
    return render_template_string(HTML_TEMPLATE, 
                                username=session['username'],
                                role=session['role'],
                                slack_webhook=get_setting('slack_webhook_url', ''),
                                using_postgres='postgresql' in DATABASE_URL)

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    
    if not username or not password:
        return jsonify({'success': False, 'error': 'Username and password are required'})
    
    conn = get_db_connection()
    is_postgres = 'postgresql' in str(conn)
    
    try:
        if is_postgres:
            user = conn.execute('SELECT * FROM users WHERE username = %s', (username,)).fetchone()
        else:
            user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        
        if user and user['password_hash'] == hash_password(password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            return jsonify({'success': True, 'message': 'Login successful'})
        else:
            return jsonify({'success': False, 'error': 'Invalid username or password'})
    finally:
        conn.close()

@app.route('/api/logout')
def logout():
    session.clear()
    return jsonify({'success': True, 'message': 'Logout successful'})

# Add this new route for database status
@app.route('/api/database_status')
@login_required
def database_status():
    """Get database status information"""
    db_path = get_database_path()
    is_postgres = 'postgresql' in db_path
    
    status_info = {
        'type': 'PostgreSQL' if is_postgres else 'SQLite',
        'path': db_path,
        'persistent': True
    }
    
    return jsonify({'success': True, 'status': status_info})

if __name__ == '__main__':
    print("🚀 Starting Bracket Inventory Tracker...")
    print("👨‍💻 Developed by Mark Calvo")
    print("🌐 Render.com Compatible Version 2.6")
    print("💾 Data Persistence Enabled")
    print("🔗 Database:", "PostgreSQL" if 'postgresql' in DATABASE_URL else "SQLite")
    
    # Initialize database
    init_database()
    print("✅ Database initialized with persistent storage")
    print("🌐 Server starting...")
    
    port = int(os.environ.get('PORT', 5000))
    
    # Use 0.0.0.0 for Render.com compatibility
    socketio.run(app, 
                host='0.0.0.0', 
                port=port, 
                debug=False,
                allow_unsafe_werkzeug=True)
