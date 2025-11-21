from flask import Flask, render_template_string, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO
import sqlite3
from datetime import datetime, timezone
import os
import hashlib
import secrets
from functools import wraps
import json
import io
import requests
import csv
import time
import pytz

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
                        <div class="status-label">LAST UPDATE</div>
                        <div class="status-value" id="lastUpdate">--:--:-- --</div>
                    </div>
                    <div class="status-item">
                        <div class="status-label">PST TIME</div>
                        <div class="status-value" id="currentTime">--:--:-- --</div>
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
            
            {% if session.role in ['admin', 'operator'] %}
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
            
            {% if session.role in ['admin', 'operator'] %}
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
                <p style="margin-bottom: 10px; font-size: 13px;">Orders automatically move to Assembly Line when components are available.</p>
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
            
            {% if session.role in ['admin', 'operator'] %}
            <!-- Orders Ready for Assembly -->
            <div class="assembly-section">
                <h3 style="margin: 0 0 10px 0; font-size: 16px;">Orders Ready for Assembly</h3>
                <p style="margin-bottom: 10px; font-size: 13px;">Orders automatically moved from Picking Station when components are available.</p>
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
            
            {% if session.role in ['admin', 'operator'] %}
            <div class="export-section">
                <h3 style="margin: 0 0 10px 0; font-size: 16px;">Export Data</h3>
                <div class="export-buttons">
                    <button class="btn btn-export" onclick="exportToCSV()">Export to CSV</button>
                    <button class="btn btn-export" onclick="exportInventoryJSON()">Export JSON (API)</button>
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
            
            {% if session.role in ['admin', 'operator'] %}
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
        </div>
        {% endif %}
        
        <!-- Developer Credit -->
        <div class="developer-credit">
            Developed by <strong>Mark Calvo</strong> | 
            <a href="mailto:mark.calvo@premioinc.com">Contact</a> | 
            Version 1.0 | 
            
        </div>
    </div>
    {% endif %}

    <script>
        const socket = io();
        let currentInventory = [];
        let workOrders = [];
        let assemblyOrders = [];
        let currentUserRole = '{{ session.role }}' || 'viewer';
        
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
                loadApiSettings();
                loadCompanySettings();
            }
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
            document.getElementById('lastUpdate').textContent = data.timestamp;
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
                
                if (stationType === 'printing') {
                    container.innerHTML += `
                        <div class="bracket-item ${stockClass}">
                            <div class="bracket-name">${item.description || item.name}</div>
                            <div class="current-qty">${item.quantity}</div>
                            <div>
                                <input type="number" class="qty-input" id="print-qty-${item.id}" value="0" min="0">
                            </div>
                            <div>
                                <button class="btn-add" onclick="addPrintedBrackets(${item.id})">Add</button>
                                <button class="btn-remove" onclick="removePrintedBrackets(${item.id})">Remove</button>
                            </div>
                        </div>
                    `;
                } else if (stationType === 'picking') {
                    container.innerHTML += `
                        <div class="bracket-item ${stockClass}">
                            <div class="bracket-name">${item.description || item.name}</div>
                            <div class="current-qty">${item.quantity}</div>
                            <div>
                                <input type="number" class="qty-input" id="pick-qty-${item.id}" value="0" min="0">
                            </div>
                            <div>
                                <button class="btn-remove" onclick="removeBrackets(${item.id})">Remove</button>
                                <button class="btn-add" onclick="addReturn(${item.id})">Return</button>
                            </div>
                        </div>
                    `;
                } else if (stationType === 'inventory') {
                    container.innerHTML += `
                        <div class="bracket-item ${stockClass}">
                            <div class="bracket-name">${item.description || item.name}</div>
                            <div class="current-qty">${item.quantity}</div>
                            <div>
                                <input type="number" class="qty-input" id="actual-qty-${item.id}" value="${item.quantity}" min="0">
                            </div>
                            <div>
                                <button class="btn" onclick="updateActualCount(${item.id})">Update</button>
                            </div>
                        </div>
                    `;
                }
            });
        }
        
        // Update work order display - automatically move to assembly when ready
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
                        
                        // Automatically move to assembly if ready
                        if (canMoveToAssembly) {
                            moveToAssembly(workOrder.id);
                            return; // Skip displaying this order as it's being moved
                        }
                        
                        categoryDiv.innerHTML += `
                            <div class="work-order-item">
                                <div class="work-order-header">
                                    <div class="work-order-title">${workOrder.order_number} - ${workOrder.required_sets} sets ${workOrder.include_spacer ? '(with spacer)' : ''}</div>
                                    <div class="work-order-actions">
                                        <button class="btn-delete" onclick="deleteWorkOrder(${workOrder.id})">Delete</button>
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
                
                container.innerHTML += `
                    <div class="work-order-item assembly-ready">
                        <div class="work-order-header">
                            <div class="work-order-title">
                                ${workOrder.order_number} - ${workOrder.required_sets} sets ${workOrder.include_spacer ? '(with spacer)' : ''}
                                <span class="assembly-status status-ready">READY</span>
                            </div>
                            <div class="work-order-actions">
                                <button class="btn-complete" onclick="completeAssembly(${order.id})">Complete</button>
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
                    console.log('Work order moved to Assembly Line automatically');
                    socket.emit('get_inventory');
                } else {
                    console.log('Error moving to assembly: ' + data.error);
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
            if (!confirm('Mark this assembly as complete? This will deduct components from inventory.')) {
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
                    alert('Assembly completed successfully! Components deducted from inventory.');
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
                
                container.innerHTML += `
                    <div class="external-order-item">
                        <div class="work-order-header">
                            <div class="work-order-title">${order.external_order_number}</div>
                            <div class="work-order-actions">
                                <button class="btn-convert" onclick="convertExternalOrder(${order.id})">Convert to Work Order</button>
                                <button class="btn-complete" onclick="completeExternalOrder(${order.id})">Complete</button>
                                <button class="btn-delete" onclick="deleteExternalOrder(${order.id})">Delete</button>
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
        
        // Load history when page loads
        window.onload = function() {
            if (currentUserRole !== 'viewer') {
                loadHistory();
                loadExternalOrders();
                loadAssemblyOrders();
            }
        };
    </script>
</body>
</html>
'''

def hash_password(password):
    """Hash a password for storing."""
    return hashlib.sha256(password.encode()).hexdigest()

def init_database():
    conn = sqlite3.connect('nzxt_inventory.db')
    c = conn.cursor()
    
    # Drop and recreate all tables to ensure clean schema
    c.execute("DROP TABLE IF EXISTS items")
    c.execute("DROP TABLE IF EXISTS transactions")
    c.execute("DROP TABLE IF EXISTS work_orders")
    c.execute("DROP TABLE IF EXISTS users")
    c.execute("DROP TABLE IF EXISTS settings")
    c.execute("DROP TABLE IF EXISTS external_work_orders")
    c.execute("DROP TABLE IF EXISTS assembly_orders")
    
    # Create items table
    c.execute('''CREATE TABLE items
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT NOT NULL UNIQUE,
                  description TEXT,
                  case_type TEXT,
                  quantity INTEGER DEFAULT 0,
                  min_stock INTEGER DEFAULT 5,
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    
    # Create transactions table with username field
    c.execute('''CREATE TABLE transactions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  item_id INTEGER,
                  change INTEGER,
                  station TEXT,
                  notes TEXT,
                  username TEXT,
                  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY (item_id) REFERENCES items (id))''')
    
    # Create work_orders table with updated schema
    c.execute('''CREATE TABLE work_orders
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  order_number TEXT NOT NULL,
                  set_type TEXT NOT NULL,
                  required_sets INTEGER NOT NULL,
                  include_spacer BOOLEAN DEFAULT 0,
                  status TEXT DEFAULT 'active',
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    
    # Create external_work_orders table for scraped orders
    c.execute('''CREATE TABLE external_work_orders
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  external_order_number TEXT NOT NULL UNIQUE,
                  sku TEXT NOT NULL,
                  quantity INTEGER NOT NULL,
                  required_brackets TEXT NOT NULL,
                  status TEXT DEFAULT 'active',
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                  last_synced DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    
    # Create assembly_orders table for assembly line
    c.execute('''CREATE TABLE assembly_orders
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  work_order_id INTEGER NOT NULL,
                  status TEXT DEFAULT 'ready',  -- ready, building, completed, cancelled
                  moved_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                  started_at DATETIME,
                  completed_at DATETIME,
                  assembled_by TEXT,
                  notes TEXT,
                  FOREIGN KEY (work_order_id) REFERENCES work_orders (id))''')
    
    # Create users table
    c.execute('''CREATE TABLE users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT NOT NULL UNIQUE,
                  password_hash TEXT NOT NULL,
                  role TEXT NOT NULL DEFAULT 'viewer',
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    
    # Create settings table
    c.execute('''CREATE TABLE settings
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  key TEXT NOT NULL UNIQUE,
                  value TEXT NOT NULL)''')
    
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
        c.execute('INSERT OR IGNORE INTO items (name, description, case_type, quantity, min_stock) VALUES (?, ?, ?, ?, ?)', item)
    
    # Add sample work orders
    sample_work_orders = [
        ('WO-001', 'H6', 10, 0),
        ('WO-002', 'H7-282', 5, 0),
        ('WO-003', 'H7-304', 5, 0),
        ('WO-004', 'H9', 8, 1)
    ]
    
    for wo in sample_work_orders:
        c.execute('INSERT OR IGNORE INTO work_orders (order_number, set_type, required_sets, include_spacer) VALUES (?, ?, ?, ?)', wo)
    
    # Add default users
    default_users = [
        ('admin', hash_password('admin123'), 'admin'),
        ('operator', hash_password('operator123'), 'operator'),
        ('viewer', hash_password('viewer123'), 'viewer')
    ]
    
    for user in default_users:
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
        c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', setting)
    
    conn.commit()
    conn.close()
    print("✅ Database initialized successfully with clean schema")

def get_db():
    conn = sqlite3.connect('nzxt_inventory.db')
    conn.row_factory = sqlite3.Row
    return conn

def get_setting(key, default=None):
    conn = get_db()
    setting = conn.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
    conn.close()
    return setting['value'] if setting else default

def update_setting(key, value):
    conn = get_db()
    conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
    conn.commit()
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
    """Get current time in PST timezone"""
    utc_now = datetime.now(timezone.utc)
    pst_tz = pytz.timezone('US/Pacific')
    pst_now = utc_now.astimezone(pst_tz)
    return pst_now.strftime("%I:%M:%S %p").lstrip('0')

def send_slack_notification(message):
    """Send notification to Slack with improved error handling"""
    webhook_url = get_setting('slack_webhook_url')
    if not webhook_url:
        print("❌ No Slack webhook URL configured")
        return False
    
    # Validate webhook URL format
    if not webhook_url.startswith('https://hooks.slack.com/services/'):
        print("❌ Invalid Slack webhook URL format")
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
            print("✅ Slack notification sent successfully")
            return True
        else:
            print(f"❌ Slack notification failed with status: {response.status_code}")
            print(f"Response: {response.text}")
            return False
            
    except requests.exceptions.Timeout:
        print("❌ Slack notification timed out")
        return False
    except requests.exceptions.ConnectionError:
        print("❌ Slack notification connection error")
        return False
    except Exception as e:
        print(f"❌ Slack notification failed: {e}")
        return False

def convert_external_to_work_order(external_order):
    """Convert an external work order to a regular work order"""
    conn = get_db()
    
    try:
        # Get SKU to set type mapping
        sku_set_mapping = get_sku_set_mapping()
        
        # Determine set type from SKU
        set_type = sku_set_mapping.get(external_order['sku'], 'H6')  # Default to H6 if not found
        
        # Check if work order already exists
        existing = conn.execute(
            'SELECT id FROM work_orders WHERE order_number = ?',
            (external_order['external_order_number'],)
        ).fetchone()
        
        if existing:
            print(f"⚠️ Work order {external_order['external_order_number']} already exists")
            return False
        
        # Create new work order
        conn.execute('''
            INSERT INTO work_orders (order_number, set_type, required_sets, include_spacer)
            VALUES (?, ?, ?, ?)
        ''', (
            external_order['external_order_number'],
            set_type,
            external_order['quantity'],
            0  # Default to no spacer
        ))
        
        print(f"✅ Converted external order {external_order['external_order_number']} to work order")
        
        # Get current inventory for notification
        items = conn.execute('SELECT * FROM items').fetchall()
        current_inventory = [dict(item) for item in items]
        
        # Get the created work order
        work_order = conn.execute(
            'SELECT * FROM work_orders WHERE order_number = ?', 
            (external_order['external_order_number'],)
        ).fetchone()
        
        conn.commit()
        
        # Send Slack notification for the new work order
        if work_order:
            send_work_order_notification(dict(work_order), current_inventory)
        
        return True
        
    except Exception as e:
        print(f"❌ Error converting external order: {str(e)}")
        conn.rollback()
        return False
    finally:
        conn.close()

def send_work_order_notification(work_order, current_inventory):
    """Send detailed notification when a new work order is created"""
    components = get_components_for_set_type(work_order['set_type'], work_order.get('include_spacer', False))
    
    # Check inventory status
    inventory_status = []
    missing_components = []
    can_complete = True
    
    for component in components:
        item = next((item for item in current_inventory if item['name'] == component), None)
        available = item['quantity'] if item else 0
        required = work_order['required_sets']
        short_by = max(0, required - available)
        
        status_emoji = "✅" if available >= required else "❌"
        inventory_status.append(f"{status_emoji} {component}: {available} / {required} (Short by {short_by})")
        
        if available < required:
            can_complete = False
            missing_components.append(f"• {component}: Need {short_by} more")
    
    # Build the notification message
    message = f":clipboard: *NEW WORK ORDER CREATED*\n\n"
    message += f"*Order #:* {work_order['order_number']}\n"
    message += f"*Set Type:* {work_order['set_type']}\n"
    message += f"*Required Sets:* {work_order['required_sets']}\n\n"
    
    message += f":package: *CURRENT INVENTORY STATUS:*\n"
    message += "\n".join(inventory_status) + "\n\n"
    
    if not can_complete:
        message += f":rotating_light: *MISSING COMPONENTS:*\n"
        message += "\n".join(missing_components) + "\n\n"
    else:
        message += f"✅ *READY TO ASSEMBLE - All components available!*\n\n"
    
    message += f"Work order has been added to the system"
    
    return send_slack_notification(message)

def send_printing_notification(item_name, change, new_quantity):
    """Send notification for printing station updates"""
    message = f":printer: *PRINTING STATION UPDATE*\n\n"
    message += f"*Component:* {item_name}\n"
    message += f"*Added Quantity:* +{change} units\n"
    message += f"*New Total:* {new_quantity} units\n\n"
    message += f"Inventory updated via Printing Station"
    
    return send_slack_notification(message)

def send_inventory_change_notification(item_name, change, station, notes=""):
    """Send notification for any inventory change"""
    action_emoji = "📈" if change > 0 else "📉"
    action_type = "ADDED" if change > 0 else "REMOVED"
    
    message = f"{action_emoji} *INVENTORY UPDATE - {action_type}*\n\n"
    message += f"*Component:* {item_name}\n"
    message += f"*Quantity Change:* {change:+d} units\n"
    message += f"*Station:* {station}\n"
    
    if notes:
        message += f"*Notes:* {notes}\n"
    
    message += f"\nInventory has been updated"
    
    return send_slack_notification(message)

def send_assembly_notification(work_order, action, assembled_by=None):
    """Send notification for assembly line activities"""
    if action == "moved":
        message = f"🏭 *ORDER MOVED TO ASSEMBLY LINE*\n\n"
        message += f"*Order #:* {work_order['order_number']}\n"
        message += f"*Set Type:* {work_order['set_type']}\n"
        message += f"*Required Sets:* {work_order['required_sets']}\n\n"
        message += f"Order is now ready for assembly!"
        
    elif action == "started":
        message = f"🔧 *ASSEMBLY STARTED*\n\n"
        message += f"*Order #:* {work_order['order_number']}\n"
        message += f"*Set Type:* {work_order['set_type']}\n"
        message += f"*Required Sets:* {work_order['required_sets']}\n"
        if assembled_by:
            message += f"*Assembled by:* {assembled_by}\n\n"
        message += f"Assembly process has begun!"
        
    elif action == "completed":
        message = f"🎉 *ASSEMBLY COMPLETED*\n\n"
        message += f"*Order #:* {work_order['order_number']}\n"
        message += f"*Set Type:* {work_order['set_type']}\n"
        message += f"*Completed Sets:* {work_order['required_sets']}\n"
        if assembled_by:
            message += f"*Assembled by:* {assembled_by}\n\n"
        message += f"Great work! Order has been completed successfully! 🎉"
        
    elif action == "cancelled":
        message = f"↩️ *ASSEMBLY CANCELLED*\n\n"
        message += f"*Order #:* {work_order['order_number']}\n"
        message += f"*Set Type:* {work_order['set_type']}\n"
        message += f"*Required Sets:* {work_order['required_sets']}\n\n"
        message += f"Order has been returned to picking station"
    
    return send_slack_notification(message)

def get_components_for_set_type(set_type, include_spacer=False):
    """Get components for a set type"""
    component_map = {
        'H6': ['H6-623A', 'H6-623B', 'H6-623C'],
        'H7-282': ['H7-282'],
        'H7-304': ['H7-304'],
        'H9': ['H9-923A', 'H9-923B', 'H9-923C'] + (['H9-SPACER'] if include_spacer else [])
    }
    return component_map.get(set_type, [])

def process_csv_upload(file_content):
    """Process CSV file upload for external orders"""
    try:
        # Decode the file content
        csv_text = file_content.decode('utf-8')
        csv_reader = csv.DictReader(csv_text.splitlines())
        
        required_columns = ['OrderNumber', 'SKU', 'Quantity']
        
        # Validate CSV structure
        if not all(col in csv_reader.fieldnames for col in required_columns):
            return {'success': False, 'error': f'CSV must contain columns: {", ".join(required_columns)}'}
        
        scraped_orders = []
        
        for row in csv_reader:
            try:
                order_number = row['OrderNumber'].strip()
                sku = row['SKU'].strip()
                quantity = int(row['Quantity'])
                
                if order_number and sku and quantity > 0:
                    scraped_orders.append({
                        'wo_number': order_number,
                        'oem_po_number': order_number,
                        'sku': sku,
                        'qty': str(quantity),
                        'status': 'active'
                    })
            except (ValueError, KeyError) as e:
                print(f"⚠️ Error parsing CSV row: {e}")
                continue
        
        print(f"✅ Processed {len(scraped_orders)} orders from CSV")
        return {'success': True, 'orders': scraped_orders}
        
    except Exception as e:
        print(f"❌ CSV processing error: {str(e)}")
        return {'success': False, 'error': f'Failed to process CSV: {str(e)}'}

def check_bracket_availability(required_brackets, quantity):
    """Check if we have enough brackets for an order"""
    conn = get_db()
    missing_brackets = []
    
    for bracket in required_brackets:
        item = conn.execute('SELECT * FROM items WHERE name = ?', (bracket,)).fetchone()
        if not item or item['quantity'] < quantity:
            missing_brackets.append({
                'name': bracket,
                'required': quantity,
                'available': item['quantity'] if item else 0,
                'missing': quantity - (item['quantity'] if item else 0)
            })
    
    conn.close()
    return missing_brackets

def broadcast_update():
    conn = get_db()
    
    items = conn.execute('SELECT * FROM items ORDER BY name').fetchall()
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
    
    conn.close()
    
    items_data = [dict(item) for item in items]
    activity_data = [dict(act) for act in recent_activity]
    work_orders_data = [dict(wo) for wo in work_orders]
    assembly_orders_data = [dict(ao) for ao in assembly_orders]
    
    # Use PST time for timestamp
    timestamp_pst = get_pst_time()
    
    socketio.emit('inventory_update', {
        'items': items_data,
        'recent_activity': activity_data,
        'work_orders': work_orders_data,
        'assembly_orders': assembly_orders_data,
        'timestamp': timestamp_pst
    })

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
        
        conn = get_db()
        
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
        conn.close()
        
        broadcast_update()
        
        print(f"📊 {session['username']} at {station}: {item['name']} {change:+d} = {new_quantity}")
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        socketio.emit('error', {'message': f'Error: {str(e)}'}, room=request.sid)

# Flask routes
@app.route('/')
def index():
    if 'user_id' not in session:
        return render_template_string(HTML_TEMPLATE, slack_webhook=get_setting('slack_webhook_url', ''))
    
    return render_template_string(HTML_TEMPLATE, 
                                username=session['username'],
                                role=session['role'],
                                slack_webhook=get_setting('slack_webhook_url', ''))

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '')
    
    if not username or not password:
        return jsonify({'success': False, 'error': 'Username and password are required'})
    
    conn = get_db()
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

# Assembly Line API Routes
@app.route('/api/assembly_orders')
@login_required
def get_assembly_orders():
    """Get all assembly orders"""
    conn = get_db()
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
    conn.close()
    
    assembly_orders_data = [dict(order) for order in assembly_orders]
    return jsonify({'assembly_orders': assembly_orders_data})

@app.route('/api/move_to_assembly', methods=['POST'])
@login_required
@role_required('operator')
def move_to_assembly():
    """Move a work order to assembly line"""
    data = request.get_json()
    work_order_id = data.get('work_order_id')
    
    if not work_order_id:
        return jsonify({'success': False, 'error': 'Work order ID is required'})
    
    conn = get_db()
    
    try:
        # Check if work order exists and is active
        work_order = conn.execute('SELECT * FROM work_orders WHERE id = ? AND status = "active"', (work_order_id,)).fetchone()
        if not work_order:
            return jsonify({'success': False, 'error': 'Active work order not found'})
        
        # Check if already in assembly
        existing_assembly = conn.execute('SELECT id FROM assembly_orders WHERE work_order_id = ? AND status IN ("ready", "building")', (work_order_id,)).fetchone()
        if existing_assembly:
            return jsonify({'success': False, 'error': 'Work order is already in assembly line'})
        
        # Check if components are available
        components = get_components_for_set_type(work_order['set_type'], work_order['include_spacer'])
        for component in components:
            item = conn.execute('SELECT * FROM items WHERE name = ?', (component,)).fetchone()
            if not item or item['quantity'] < work_order['required_sets']:
                return jsonify({'success': False, 'error': f'Not enough {component} available'})
        
        # Create assembly order
        conn.execute('''
            INSERT INTO assembly_orders (work_order_id, status, moved_at)
            VALUES (?, 'ready', ?)
        ''', (work_order_id, datetime.now()))
        
        conn.commit()
        conn.close()
        
        # Send Slack notification
        send_assembly_notification(dict(work_order), "moved")
        
        broadcast_update()
        return jsonify({'success': True, 'message': 'Work order moved to assembly line successfully'})
        
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/complete_assembly', methods=['POST'])
@login_required
@role_required('operator')
def complete_assembly():
    """Complete an assembly order and deduct components"""
    data = request.get_json()
    assembly_order_id = data.get('assembly_order_id')
    
    if not assembly_order_id:
        return jsonify({'success': False, 'error': 'Assembly order ID is required'})
    
    conn = get_db()
    
    try:
        # Get assembly order with work order details
        assembly_order = conn.execute('''
            SELECT ao.*, wo.order_number, wo.set_type, wo.required_sets, wo.include_spacer, wo.id as work_order_id
            FROM assembly_orders ao
            JOIN work_orders wo ON ao.work_order_id = wo.id
            WHERE ao.id = ? AND ao.status = 'ready'
        ''', (assembly_order_id,)).fetchone()
        
        if not assembly_order:
            return jsonify({'success': False, 'error': 'Ready assembly order not found'})
        
        # Get components for this set type
        components = get_components_for_set_type(assembly_order['set_type'], assembly_order['include_spacer'])
        
        # Deduct components from inventory
        for component in components:
            conn.execute('UPDATE items SET quantity = quantity - ? WHERE name = ?', 
                        (assembly_order['required_sets'], component))
            
            # Log the transaction
            item = conn.execute('SELECT id FROM items WHERE name = ?', (component,)).fetchone()
            if item:
                conn.execute('''
                    INSERT INTO transactions (item_id, change, station, notes, username, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (item['id'], -assembly_order['required_sets'], 'Assembly Line', 
                      f'Assembly order {assembly_order["order_number"]} completed', session['username'], datetime.now()))
        
        # Update assembly order status
        conn.execute('''
            UPDATE assembly_orders 
            SET status = 'completed', completed_at = ?, assembled_by = ?
            WHERE id = ?
        ''', (datetime.now(), session['username'], assembly_order_id))
        
        # Mark work order as completed
        conn.execute('UPDATE work_orders SET status = "completed" WHERE id = ?', (assembly_order['work_order_id'],))
        
        conn.commit()
        conn.close()
        
        # Send Slack notification
        send_assembly_notification(dict(assembly_order), "completed", session['username'])
        
        broadcast_update()
        return jsonify({'success': True, 'message': 'Assembly completed successfully'})
        
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': str(e)})

# External Orders API Routes
@app.route('/api/upload_csv', methods=['POST'])
@login_required
@role_required('operator')
def upload_csv():
    """Upload and process CSV file for external orders"""
    try:
        if 'csv_file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'})
        
        file = request.files['csv_file']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'})
        
        if not file.filename.lower().endswith('.csv'):
            return jsonify({'success': False, 'error': 'File must be a CSV'})
        
        # Process the CSV file
        file_content = file.read()
        csv_result = process_csv_upload(file_content)
        
        if not csv_result['success']:
            return jsonify({'success': False, 'error': csv_result['error']})
        
        # Process the orders from CSV
        conn = get_db()
        sku_mapping = get_sku_mapping()
        new_orders = []
        converted_count = 0
        
        for order in csv_result['orders']:
            # Check if this order already exists
            existing = conn.execute(
                'SELECT id FROM external_work_orders WHERE external_order_number = ?',
                (order['oem_po_number'],)
            ).fetchone()
            
            if not existing:
                # Create new external work order
                sku = order['sku']
                quantity = int(order['qty'])
                required_brackets = sku_mapping.get(sku, [])
                
                if required_brackets:  # Only create if we have a mapping
                    conn.execute('''
                        INSERT INTO external_work_orders 
                        (external_order_number, sku, quantity, required_brackets, last_synced)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (order['oem_po_number'], sku, quantity, json.dumps(required_brackets), datetime.now()))
                    
                    new_order = {
                        'external_order_number': order['oem_po_number'],
                        'sku': sku,
                        'quantity': quantity,
                        'required_brackets': required_brackets
                    }
                    new_orders.append(new_order)
                    print(f"✅ Created external order: {order['oem_po_number']} for SKU {sku}")
                    
                    # Convert to regular work order
                    if convert_external_to_work_order(new_order):
                        converted_count += 1
        
        conn.commit()
        conn.close()
        
        # Send notifications
        for order in new_orders:
            missing_brackets = check_bracket_availability(order['required_brackets'], order['quantity'])
            
            if missing_brackets:
                missing_list = ", ".join([f"{mb['name']} (need {mb['missing']})" for mb in missing_brackets])
                message = f"🚨 *CSV UPLOAD - MISSING BRACKETS*\n\n*Order #:* {order['external_order_number']}\n*SKU:* {order['sku']}\n*Quantity:* {order['quantity']}\n*Missing Brackets:* {missing_list}\n\n*Action Required:* Please print additional brackets."
                send_slack_notification(message)
            else:
                message = f"✅ *CSV UPLOAD - READY TO PICK*\n\n*Order #:* {order['external_order_number']}\n*SKU:* {order['sku']}\n*Quantity:* {order['quantity']}\n*Brackets Needed:* {', '.join(order['required_brackets'])}\n\nAll brackets are available for picking."
                send_slack_notification(message)
        
        broadcast_update()
        
        result_message = f'Uploaded {len(new_orders)} orders from CSV'
        if converted_count > 0:
            result_message += f' and converted {converted_count} to work orders'
        
        return jsonify({
            'success': True,
            'message': result_message,
            'new_orders': len(new_orders),
            'converted_orders': converted_count
        })
        
    except Exception as e:
        print(f"❌ CSV upload error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/external_orders')
@login_required
def get_external_orders():
    """Get all external work orders"""
    conn = get_db()
    orders = conn.execute('''
        SELECT * FROM external_work_orders 
        ORDER BY created_at DESC
    ''').fetchall()
    conn.close()
    
    orders_data = []
    for order in orders:
        orders_data.append({
            'id': order['id'],
            'external_order_number': order['external_order_number'],
            'sku': order['sku'],
            'quantity': order['quantity'],
            'required_brackets': json.loads(order['required_brackets']),
            'status': order['status'],
            'created_at': order['created_at'],
            'last_synced': order['last_synced']
        })
    
    return jsonify({'orders': orders_data})

@app.route('/api/convert_external_order', methods=['POST'])
@login_required
@role_required('operator')
def convert_external_order():
    """Convert an external order to a regular work order"""
    data = request.get_json()
    external_order_id = data.get('external_order_id')
    
    if not external_order_id:
        return jsonify({'success': False, 'error': 'External order ID is required'})
    
    conn = get_db()
    
    try:
        # Get the external order
        external_order = conn.execute('SELECT * FROM external_work_orders WHERE id = ?', (external_order_id,)).fetchone()
        if not external_order:
            return jsonify({'success': False, 'error': 'External order not found'})
        
        external_order_dict = {
            'external_order_number': external_order['external_order_number'],
            'sku': external_order['sku'],
            'quantity': external_order['quantity'],
            'required_brackets': json.loads(external_order['required_brackets'])
        }
        
        # Convert to work order
        success = convert_external_to_work_order(external_order_dict)
        
        if success:
            # Mark external order as converted
            conn.execute('UPDATE external_work_orders SET status = "converted" WHERE id = ?', (external_order_id,))
            conn.commit()
            conn.close()
            
            broadcast_update()
            return jsonify({'success': True, 'message': 'External order converted to work order successfully'})
        else:
            conn.close()
            return jsonify({'success': False, 'error': 'Failed to convert external order'})
        
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/complete_external_order', methods=['POST'])
@login_required
@role_required('operator')
def complete_external_order():
    """Mark an external work order as completed"""
    data = request.get_json()
    order_id = data.get('order_id')
    
    if not order_id:
        return jsonify({'success': False, 'error': 'Order ID is required'})
    
    conn = get_db()
    
    try:
        # Get the external order
        order = conn.execute('SELECT * FROM external_work_orders WHERE id = ?', (order_id,)).fetchone()
        if not order:
            return jsonify({'success': False, 'error': 'External order not found'})
        
        # Deduct brackets from inventory
        required_brackets = json.loads(order['required_brackets'])
        for bracket in required_brackets:
            conn.execute('UPDATE items SET quantity = quantity - ? WHERE name = ?', 
                        (order['quantity'], bracket))
            
            # Log the transaction
            item = conn.execute('SELECT id FROM items WHERE name = ?', (bracket,)).fetchone()
            if item:
                conn.execute('''
                    INSERT INTO transactions (item_id, change, station, notes, username, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (item['id'], -order['quantity'], 'External Order Completion', 
                      f'External order {order["external_order_number"]} completed', session['username'], datetime.now()))
        
        # Mark external order as completed
        conn.execute('UPDATE external_work_orders SET status = "completed" WHERE id = ?', (order_id,))
        
        conn.commit()
        conn.close()
        
        # Send completion notification
        message = f"✅ *EXTERNAL ORDER COMPLETED*\n\n*Order #:* {order['external_order_number']}\n*SKU:* {order['sku']}\n*Completed Quantity:* {order['quantity']}\n*Brackets Used:* {', '.join(required_brackets)}\n\nComponents have been deducted from inventory."
        send_slack_notification(message)
        
        broadcast_update()
        return jsonify({'success': True, 'message': 'External order completed successfully'})
        
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/delete_external_order', methods=['POST'])
@login_required
@role_required('operator')
def delete_external_order():
    """Delete an external work order"""
    data = request.get_json()
    order_id = data.get('order_id')
    
    if not order_id:
        return jsonify({'success': False, 'error': 'Order ID is required'})
    
    conn = get_db()
    conn.execute('DELETE FROM external_work_orders WHERE id = ?', (order_id,))
    conn.commit()
    conn.close()
    
    broadcast_update()
    return jsonify({'success': True, 'message': 'External order deleted successfully'})

# Company Settings API Routes
@app.route('/api/company_settings', methods=['GET'])
@login_required
@role_required('admin')
def company_settings():
    sku_mapping = get_sku_mapping()
    sku_set_mapping = get_sku_set_mapping()
    
    return jsonify({
        'success': True,
        'sku_mapping': sku_mapping,
        'sku_set_mapping': sku_set_mapping
    })

@app.route('/api/sku_mapping', methods=['POST'])
@login_required
@role_required('admin')
def update_sku_mapping():
    """Update SKU to bracket mapping"""
    data = request.get_json()
    sku_mapping = data.get('sku_mapping', {})
    sku_set_mapping = data.get('sku_set_mapping', {})
    
    update_setting('sku_mapping', json.dumps(sku_mapping))
    update_setting('sku_set_mapping', json.dumps(sku_set_mapping))
    
    return jsonify({'success': True, 'message': 'SKU mapping updated successfully'})

# Slack Integration Routes
@app.route('/api/slack_webhook', methods=['POST'])
@login_required
@role_required('admin')
def update_slack_webhook():
    """Update Slack webhook URL"""
    data = request.get_json()
    webhook_url = data.get('webhook_url', '').strip()
    
    update_setting('slack_webhook_url', webhook_url)
    
    return jsonify({'success': True, 'message': 'Slack webhook updated successfully'})

@app.route('/api/test_slack', methods=['POST'])
@login_required
@role_required('admin')
def test_slack():
    """Send test Slack notification"""
    message = "🧪 *TEST NOTIFICATION*\n\nThis is a test message from your Bracket Inventory Tracker. If you can see this, your Slack integration is working correctly!"
    
    if send_slack_notification(message):
        return jsonify({'success': True, 'message': 'Test notification sent successfully'})
    else:
        return jsonify({'success': False, 'error': 'Failed to send test notification'})

# Work Order Routes
@app.route('/api/add_work_order', methods=['POST'])
@login_required
@role_required('operator')
def add_work_order():
    data = request.get_json()
    order_number = data.get('order_number')
    set_type = data.get('set_type')
    required_sets = data.get('required_sets')
    include_spacer = data.get('include_spacer', False)
    
    if not all([order_number, set_type, required_sets]):
        return jsonify({'success': False, 'error': 'Missing required fields'})
    
    conn = get_db()
    
    try:
        # Get current inventory for notification
        items = conn.execute('SELECT * FROM items').fetchall()
        current_inventory = [dict(item) for item in items]
        
        # Add work order
        cursor = conn.execute('''
            INSERT INTO work_orders (order_number, set_type, required_sets, include_spacer)
            VALUES (?, ?, ?, ?)
        ''', (order_number, set_type, required_sets, include_spacer))
        
        work_order_id = cursor.lastrowid
        
        # Get the created work order
        work_order = conn.execute('SELECT * FROM work_orders WHERE id = ?', (work_order_id,)).fetchone()
        
        conn.commit()
        
        # Send detailed Slack notification
        send_work_order_notification(dict(work_order), current_inventory)
        
        conn.close()
        
        broadcast_update()
        return jsonify({'success': True, 'message': 'Work order added successfully'})
        
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/delete_work_order', methods=['POST'])
@login_required
@role_required('operator')
def delete_work_order():
    data = request.get_json()
    work_order_id = data.get('work_order_id')
    
    if not work_order_id:
        return jsonify({'success': False, 'error': 'Work order ID is required'})
    
    conn = get_db()
    conn.execute('DELETE FROM work_orders WHERE id = ?', (work_order_id,))
    conn.commit()
    conn.close()
    
    broadcast_update()
    return jsonify({'success': True, 'message': 'Work order deleted successfully'})

# History Routes
@app.route('/api/history')
@login_required
def get_history():
    limit = request.args.get('limit', 50)
    filter_type = request.args.get('filter', 'all')
    
    conn = get_db()
    
    query = '''
        SELECT t.*, i.name as item_name, i.case_type 
        FROM transactions t 
        JOIN items i ON t.item_id = i.id 
    '''
    
    if filter_type != 'all':
        query += f" WHERE i.case_type = '{filter_type}'"
    
    query += ' ORDER BY t.timestamp DESC LIMIT ?'
    
    history = conn.execute(query, (limit,)).fetchall()
    conn.close()
    
    history_data = [dict(record) for record in history]
    return jsonify({'history': history_data})

# User Management Routes
@app.route('/api/users', methods=['GET', 'POST', 'DELETE'])
@login_required
@role_required('admin')
def manage_users():
    if request.method == 'GET':
        conn = get_db()
        users = conn.execute('SELECT id, username, role, created_at FROM users ORDER BY username').fetchall()
        conn.close()
        
        users_data = [dict(user) for user in users]
        return jsonify({'users': users_data})
    
    elif request.method == 'POST':
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '')
        role = data.get('role', 'viewer')
        
        if not username or not password:
            return jsonify({'success': False, 'error': 'Username and password are required'})
        
        if role not in ['admin', 'operator', 'viewer']:
            return jsonify({'success': False, 'error': 'Invalid role'})
        
        conn = get_db()
        
        try:
            conn.execute('INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)',
                        (username, hash_password(password), role))
            conn.commit()
            conn.close()
            
            return jsonify({'success': True, 'message': 'User added successfully'})
            
        except sqlite3.IntegrityError:
            conn.close()
            return jsonify({'success': False, 'error': 'Username already exists'})
        except Exception as e:
            conn.close()
            return jsonify({'success': False, 'error': str(e)})
    
    elif request.method == 'DELETE':
        data = request.get_json()
        user_id = data.get('user_id')
        
        if not user_id:
            return jsonify({'success': False, 'error': 'User ID is required'})
        
        conn = get_db()
        
        # Prevent deleting current user
        current_user = conn.execute('SELECT id FROM users WHERE id = ?', (user_id,)).fetchone()
        if current_user and current_user['id'] == session['user_id']:
            conn.close()
            return jsonify({'success': False, 'error': 'Cannot delete your own account'})
        
        conn.execute('DELETE FROM users WHERE id = ?', (user_id,))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'User deleted successfully'})

@app.route('/api/users/role', methods=['POST'])
@login_required
@role_required('admin')
def change_user_role():
    data = request.get_json()
    user_id = data.get('user_id')
    role = data.get('role')
    
    if not user_id or not role:
        return jsonify({'success': False, 'error': 'User ID and role are required'})
    
    if role not in ['admin', 'operator', 'viewer']:
        return jsonify({'success': False, 'error': 'Invalid role'})
    
    conn = get_db()
    conn.execute('UPDATE users SET role = ? WHERE id = ?', (role, user_id))
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': 'User role updated successfully'})

# Stock Settings Routes
@app.route('/api/stock_settings', methods=['POST'])
@login_required
@role_required('admin')
def update_stock_settings():
    data = request.get_json()
    low_stock = data.get('low_stock')
    critical_stock = data.get('critical_stock')
    
    if low_stock is None or critical_stock is None:
        return jsonify({'success': False, 'error': 'Both thresholds are required'})
    
    update_setting('low_stock_threshold', str(low_stock))
    update_setting('critical_stock_threshold', str(critical_stock))
    
    return jsonify({'success': True, 'message': 'Stock settings updated successfully'})

# Export Routes
@app.route('/api/export/csv')
@login_required
def export_csv():
    conn = get_db()
    
    # Get inventory data
    items = conn.execute('SELECT * FROM items ORDER BY case_type, name').fetchall()
    
    # Get transaction history
    transactions = conn.execute('''
        SELECT t.timestamp, i.name, i.case_type, t.change, t.station, t.notes, t.username
        FROM transactions t 
        JOIN items i ON t.item_id = i.id 
        ORDER BY t.timestamp DESC 
        LIMIT 1000
    ''').fetchall()
    
    # Get external orders
    external_orders = conn.execute('SELECT * FROM external_work_orders ORDER BY created_at DESC').fetchall()
    
    # Get assembly orders
    assembly_orders = conn.execute('''
        SELECT ao.*, wo.order_number, wo.set_type, wo.required_sets
        FROM assembly_orders ao
        JOIN work_orders wo ON ao.work_order_id = wo.id
        ORDER BY ao.moved_at DESC
    ''').fetchall()
    
    conn.close()
    
    # Create CSV content
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write inventory section
    writer.writerow(["INVENTORY DATA"])
    writer.writerow([])
    writer.writerow(['Name', 'Description', 'Case Type', 'Quantity', 'Min Stock'])
    for item in items:
        writer.writerow([
            item['name'],
            item['description'],
            item['case_type'],
            item['quantity'],
            item['min_stock']
        ])
    
    writer.writerow([])
    writer.writerow([])
    
    # Write transactions section
    writer.writerow(["TRANSACTION HISTORY"])
    writer.writerow([])
    writer.writerow(['Timestamp', 'Item', 'Case Type', 'Change', 'Station', 'User', 'Notes'])
    for trans in transactions:
        writer.writerow([
            trans['timestamp'],
            trans['name'],
            trans['case_type'],
            trans['change'],
            trans['station'],
            trans['username'],
            trans['notes'] or ''
        ])
    
    writer.writerow([])
    writer.writerow([])
    
    # Write external orders section
    writer.writerow(["EXTERNAL WORK ORDERS"])
    writer.writerow([])
    writer.writerow(['Order Number', 'SKU', 'Quantity', 'Required Brackets', 'Status', 'Created At'])
    for order in external_orders:
        writer.writerow([
            order['external_order_number'],
            order['sku'],
            order['quantity'],
            order['required_brackets'],
            order['status'],
            order['created_at']
        ])
    
    writer.writerow([])
    writer.writerow([])
    
    # Write assembly orders section
    writer.writerow(["ASSEMBLY LINE ORDERS"])
    writer.writerow([])
    writer.writerow(['Order Number', 'Set Type', 'Required Sets', 'Status', 'Moved At', 'Started At', 'Completed At', 'Assembled By'])
    for order in assembly_orders:
        writer.writerow([
            order['order_number'],
            order['set_type'],
            order['required_sets'],
            order['status'],
            order['moved_at'],
            order['started_at'],
            order['completed_at'],
            order['assembled_by'] or ''
        ])
    
    output.seek(0)
    
    return app.response_class(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment;filename=inventory_export.csv'}
    )

@app.route('/api/inventory_json')
@login_required
def inventory_json():
    conn = get_db()
    
    items = conn.execute('SELECT * FROM items ORDER BY case_type, name').fetchall()
    work_orders = conn.execute("SELECT * FROM work_orders WHERE status = 'active'").fetchall()
    external_orders = conn.execute("SELECT * FROM external_work_orders WHERE status = 'active'").fetchall()
    assembly_orders = conn.execute('''
        SELECT ao.*, wo.order_number, wo.set_type, wo.required_sets
        FROM assembly_orders ao
        JOIN work_orders wo ON ao.work_order_id = wo.id
        WHERE ao.status IN ('ready', 'building')
    ''').fetchall()
    
    conn.close()
    
    inventory_data = {
        'timestamp': datetime.now().isoformat(),
        'inventory': [dict(item) for item in items],
        'work_orders': [dict(wo) for wo in work_orders],
        'external_orders': [dict(eo) for eo in external_orders],
        'assembly_orders': [dict(ao) for ao in assembly_orders]
    }
    
    return jsonify(inventory_data)

if __name__ == '__main__':
    print("🚀 Starting Bracket Inventory Tracker...")
    print("👨‍💻 Developed by Mark Calvo")
    print("🌐 Render.com Compatible Version 2.4")
    init_database()
    print("✅ Database initialized")
    print("🌐 Server starting...")
    
    port = int(os.environ.get('PORT', 5000))
    
    # Use 0.0.0.0 for Render.com compatibility
    socketio.run(app, 
                host='0.0.0.0', 
                port=port, 
                debug=False,
                allow_unsafe_werkzeug=True)
