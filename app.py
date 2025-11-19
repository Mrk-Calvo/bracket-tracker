import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template_string, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO
import sqlite3
from datetime import datetime
import os
import hashlib
import secrets
from functools import wraps
import json
import io
import requests
import csv

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'bracket-tracker-2024-secure-key')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Slack webhook URL for alerts
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL', '')

# User roles
ROLES = {
    'admin': ['admin', 'operator', 'viewer'],
    'operator': ['operator', 'viewer'],
    'viewer': ['viewer']
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
            <button class="tab" onclick="showTab('inventory')">Inventory Management</button>
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
            <h2 style="margin-bottom: 8px; font-size: 18px;">Picking Station - Manage Orders & Inventory</h2>
            
            {% if session.role in ['admin', 'operator'] %}
            <!-- Work Orders Section -->
            <div class="work-order-section">
                <h3 style="margin: 0 0 10px 0; font-size: 16px;">Active Work Orders</h3>
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
            
            <div class="api-section">
                <h3 style="margin: 0 0 10px 0; font-size: 16px;">API Integration (Future Use)</h3>
                <div class="form-row">
                    <div class="form-group">
                        <label>External API URL</label>
                        <input type="text" id="externalApiUrl" placeholder="https://api.example.com/inventory">
                    </div>
                    <div class="form-group">
                        <label>API Key</label>
                        <input type="password" id="externalApiKey" placeholder="Enter API key">
                    </div>
                    <div class="form-group">
                        <label>&nbsp;</label>
                        <button class="btn" onclick="saveApiSettings()">Save API Settings</button>
                    </div>
                </div>
                <div class="form-row">
                    <div class="form-group">
                        <label>Sync Inventory from API</label>
                        <button class="btn-add" onclick="syncFromExternalApi()">Sync Now</button>
                    </div>
                </div>
            </div>
        </div>
        {% endif %}
        
        <!-- Developer Credit -->
        <div class="developer-credit">
            Developed by <strong>Mark Calvo</strong> | 
            <a href="mailto:mark.calvo@premioinc.com">Contact</a> | 
            Version 2.1 | 
            
        </div>
    </div>
    {% endif %}

    <script>
        const socket = io();
        let currentInventory = [];
        let workOrders = [];
        let recentlyCompletedOrders = [];
        let currentUserRole = '{{ session.role }}' || 'viewer';
        
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
            } else if (tabName === 'admin' && currentUserRole === 'admin') {
                loadUsers();
                loadApiSettings();
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
            updateAllInventoryDisplays(data.items);
            updateWorkOrderDisplay();
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
        
        // Update work order display with completion options
        function updateWorkOrderDisplay() {
            const container = document.getElementById('work-order-list');
            container.innerHTML = '';
            
            if (workOrders.length === 0) {
                container.innerHTML = '<div class="work-order-item">No active work orders</div>';
                return;
            }
            
            // Group work orders by set type
            const ordersByType = {
                'H6': [],
                'H7-282': [],
                'H7-304': [],
                'H9': []
            };
            
            workOrders.forEach(order => {
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
                        let canComplete = true;
                        let missingComponents = [];
                        
                        // Check if we have enough of each component
                        components.forEach(componentName => {
                            const component = currentInventory.find(item => item.name === componentName);
                            if (!component || component.quantity < workOrder.required_sets) {
                                canComplete = false;
                                missingComponents.push({
                                    name: componentName,
                                    required: workOrder.required_sets,
                                    available: component ? component.quantity : 0,
                                    missing: workOrder.required_sets - (component ? component.quantity : 0)
                                });
                            }
                        });
                        
                        categoryDiv.innerHTML += `
                            <div class="work-order-item">
                                <div class="work-order-header">
                                    <div class="work-order-title">${workOrder.order_number} - ${workOrder.required_sets} sets ${workOrder.include_spacer ? '(with spacer)' : ''}</div>
                                    <div class="work-order-actions">
                                        <button class="btn-complete" onclick="completeWorkOrder(${workOrder.id})" ${canComplete ? '' : 'disabled'}>Complete</button>
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
                                ${!canComplete ? `
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
            
            // Show completion alerts if any orders became completable
            showCompletionAlerts();
        }
        
        // Show alerts for orders that became completable after quantity changes
        function showCompletionAlerts() {
            // Clear any existing alerts
            document.querySelectorAll('.completion-alert').forEach(alert => alert.remove());
            
            const workOrderList = document.getElementById('work-order-list');
            
            workOrders.forEach(workOrder => {
                const components = getComponentsForSet(workOrder.set_type, workOrder.include_spacer);
                let canComplete = true;
                
                // Check if we have enough of each component
                components.forEach(componentName => {
                    const component = currentInventory.find(item => item.name === componentName);
                    if (!component || component.quantity < workOrder.required_sets) {
                        canComplete = false;
                    }
                });
                
                // If this order can be completed and wasn't in the recently completed list
                if (canComplete && !recentlyCompletedOrders.includes(workOrder.id)) {
                    const alertDiv = document.createElement('div');
                    alertDiv.className = 'completion-alert';
                    alertDiv.innerHTML = `
                        <strong>${workOrder.order_number}</strong> is now ready to complete! 
                        All components are available. Click "Complete" to finish this order.
                    `;
                    workOrderList.insertBefore(alertDiv, workOrderList.firstChild);
                    
                    // Add to recently completed to avoid duplicate alerts
                    recentlyCompletedOrders.push(workOrder.id);
                }
            });
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
            
            // Check for newly completable orders
            setTimeout(() => {
                checkForCompletableOrders();
            }, 500);
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
            
            // Check for newly completable orders
            setTimeout(() => {
                checkForCompletableOrders();
            }, 500);
        }
        
        // Check if any orders became completable after inventory changes
        function checkForCompletableOrders() {
            let newlyCompletable = [];
            
            workOrders.forEach(workOrder => {
                const components = getComponentsForSet(workOrder.set_type, workOrder.include_spacer);
                let canComplete = true;
                
                components.forEach(componentName => {
                    const component = currentInventory.find(item => item.name === componentName);
                    if (!component || component.quantity < workOrder.required_sets) {
                        canComplete = false;
                    }
                });
                
                if (canComplete && !recentlyCompletedOrders.includes(workOrder.id)) {
                    newlyCompletable.push(workOrder.order_number);
                }
            });
            
            if (newlyCompletable.length > 0) {
                // Force update of work order display to show alerts
                updateWorkOrderDisplay();
            }
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
        
        function completeWorkOrder(workOrderId) {
            if (!confirm('Mark this work order as complete? This will deduct components from inventory.')) {
                return;
            }
            
            fetch('/api/complete_work_order', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    work_order_id: workOrderId
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('Work order completed successfully! Components deducted from inventory.');
                    socket.emit('get_inventory');
                    
                    // Remove from recently completed list
                    recentlyCompletedOrders = recentlyCompletedOrders.filter(id => id !== workOrderId);
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
        
        // API Integration Functions
        function loadApiSettings() {
            fetch('/api/api_settings')
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        document.getElementById('externalApiUrl').value = data.api_url || '';
                        document.getElementById('externalApiKey').value = data.api_key || '';
                    }
                });
        }
        
        function saveApiSettings() {
            const apiUrl = document.getElementById('externalApiUrl').value;
            const apiKey = document.getElementById('externalApiKey').value;
            
            fetch('/api/api_settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    api_url: apiUrl,
                    api_key: apiKey
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('API settings saved successfully!');
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }
        
        function syncFromExternalApi() {
            if (!confirm('This will sync inventory from the external API. Continue?')) {
                return;
            }
            
            fetch('/api/sync_external', {
                method: 'POST'
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('Inventory synced successfully from external API!');
                    socket.emit('get_inventory');
                } else {
                    alert('Error: ' + data.error);
                }
            });
        }
        
        // Load history when page loads
        window.onload = function() {
            if (currentUserRole !== 'viewer') {
                loadHistory();
            }
        };
    </script>
</body>
</html>
'''

# ... [REST OF THE PYTHON CODE REMAINS EXACTLY THE SAME AS BEFORE, JUST REMOVE THE PDF EXPORT FUNCTION AND ADD CSV EXPORT] ...

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
        ('external_api_url', ''),
        ('external_api_key', '')
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

def send_slack_notification(message):
    """Send notification to Slack"""
    webhook_url = get_setting('slack_webhook_url')
    if not webhook_url:
        print("❌ No Slack webhook URL configured")
        return False
    
    try:
        payload = {
            "text": message,
            "username": "Bracket Inventory Tracker",
            "icon_emoji": ":package:"
        }
        response = requests.post(webhook_url, json=payload)
        if response.status_code == 200:
            print("✅ Slack notification sent successfully")
            return True
        else:
            print(f"❌ Slack notification failed with status: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Slack notification failed: {e}")
        return False

# ... [ALL THE OTHER FUNCTIONS REMAIN EXACTLY THE SAME AS BEFORE] ...

# Replace the PDF export with CSV export
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
    
    output.seek(0)
    
    return app.response_class(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment;filename=inventory_export.csv'}
    )

# ... [ALL OTHER ROUTES AND SOCKET HANDLERS REMAIN EXACTLY THE SAME] ...

if __name__ == '__main__':
    print("🚀 Starting Bracket Inventory Tracker...")
    print("👨‍💻 Developed by Mark Calvo")
    init_database()
    print("✅ Database initialized")
    print("🌐 Server starting...")
    
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
