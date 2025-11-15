from flask import Flask, render_template_string, request, jsonify
from flask_socketio import SocketIO
import sqlite3
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'nzxt-bracket-tracker-2024')
socketio = SocketIO(app, cors_allowed_origins="*")

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>NZXT Bracket Inventory</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.2/socket.io.min.js"></script>
    <style>
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
            background: #007acc; 
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
            background: #28a745;
            color: white;
        }
        .btn-remove {
            background: #dc3545;
            color: white;
        }
        .btn-complete {
            background: #17a2b8;
            color: white;
        }
        .btn-delete {
            background: #6c757d;
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
            border: 1px solid #28a745;
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
            border: 1px solid #17a2b8;
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
            border-left: 2px solid #28a745;
            background: #d4edda;
        }
        .component-missing {
            border-left: 2px solid #dc3545;
            background: #f8d7da;
        }
        
        .set-analysis {
            background: #fff3cd;
            padding: 10px;
            border-radius: 6px;
            margin: 12px 0;
            border: 1px solid #ffc107;
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
            border: 1px solid #28a745;
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
            color: #28a745;
        }
        .status-disconnected {
            color: #dc3545;
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
            border-left: 2px solid #dc3545;
        }
        
        .completion-alert {
            background: #d4edda;
            color: #155724;
            padding: 8px;
            border-radius: 3px;
            margin: 8px 0;
            border-left: 3px solid #28a745;
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
            border-left: 2px solid #28a745;
        }
        .history-remove {
            border-left: 2px solid #dc3545;
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
            color: #007acc;
            text-decoration: none;
            font-weight: bold;
        }
        .developer-credit a:hover {
            text-decoration: underline;
        }
        
        @media (max-width: 768px) {
            .tab { min-width: 90px; padding: 10px 12px; }
            .form-row { flex-direction: column; }
            .form-group { min-width: 100%; }
            .bracket-item, .component-list {
                grid-template-columns: 1fr;
                gap: 6px;
            }
            .status-bar {
                flex-direction: column;
                gap: 10px;
                text-align: center;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1 style="margin: 0; font-size: 20px;">NZXT Bracket Inventory Tracker</h1>
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
        
        <div class="tabs">
            <button class="tab active" onclick="showTab('printing')">Printing Station</button>
            <button class="tab" onclick="showTab('picking')">Picking Station</button>
            <button class="tab" onclick="showTab('inventory')">Inventory Management</button>
            <button class="tab" onclick="showTab('history')">Movement History</button>
        </div>
        
        <!-- Printing Station Tab -->
        <div id="printing" class="tab-content active">
            <h2 style="margin-bottom: 8px; font-size: 18px;">Printing Station - Add/Remove Printed Brackets</h2>
            <p style="margin-bottom: 15px; font-size: 13px;">Add quantities when brackets are printed. Remove for corrections.</p>
            
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
        </div>
        
        <!-- Picking Station Tab -->
        <div id="picking" class="tab-content">
            <h2 style="margin-bottom: 8px; font-size: 18px;">Picking Station - Manage Orders & Inventory</h2>
            
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
        </div>
        
        <!-- Inventory Management Tab -->
        <div id="inventory" class="tab-content">
            <h2 style="margin-bottom: 8px; font-size: 18px;">Inventory Management</h2>
            
            <div class="form-section">
                <h3 style="margin: 0 0 11px 0; font-size: 16px;">Add Work Order</h3>
                <div class="form-row">
                    <div class="form-group">
                        <label>Work Order #</label>
                        <input type="text" id="workOrderNumber" placeholder="WO-001">
                    </div>
                    <div class="form-group">
                        <label>Set Type</label>
                        <select id="workOrderSetType">
                            <option value="H6">H6 Set (requires H6-1, H6-2, H6-3)</option>
                            <option value="H7-282">H7-282 Set (requires H7-282 only)</option>
                            <option value="H7-304">H7-304 Set (requires H7-304 only)</option>
                            <option value="H9">H9 Set (requires H9-1, H9-2, H9-3)</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Required Sets</label>
                        <input type="number" id="workOrderQty" value="0" min="0" style="width: 80%">
                    </div>
                    <div class="form-group">
                        <label>&nbsp;</label>
                        <button class="btn-add" onclick="addWorkOrder()" style="width: 80%">Add Work Order</button>
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
        
        <!-- Developer Credit -->
        <div class="developer-credit">
            Developed by <strong>Mark Calvo</strong> | 
            <a href="mailto:mark.calvo@premioinc.com">Contact</a> | 
            Version 1.0 | 
            
        </div>
    </div>

    <script>
        const socket = io();
        let currentInventory = [];
        let workOrders = [];
        let recentlyCompletedOrders = [];
        
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
            }
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
                        const components = getComponentsForSet(workOrder.set_type);
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
                                    <div class="work-order-title">${workOrder.order_number} - ${workOrder.required_sets} sets</div>
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
                const components = getComponentsForSet(workOrder.set_type);
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
                const components = getComponentsForSet(setType);
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
        function getComponentsForSet(setType) {
            const componentMap = {
                'H6': ['H6-1', 'H6-2', 'H6-3'],
                'H7-282': ['H7-282'],
                'H7-304': ['H7-304'],
                'H9': ['H9-1', 'H9-2', 'H9-3']
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
                const components = getComponentsForSet(workOrder.set_type);
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
                    required_sets: quantity
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert('Work order added successfully!');
                    document.getElementById('workOrderNumber').value = '';
                    document.getElementById('workOrderQty').value = '0';
                    
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
                            <small>${time}</small>
                        </div>
                        <div style="text-align: right;">
                            ${record.notes ? `<small>${record.notes}</small>` : ''}
                        </div>
                    </div>
                `;
            });
        }
        
        // Load history when page loads
        window.onload = function() {
            loadHistory();
        };
    </script>
</body>
</html>
'''

def init_database():
    conn = sqlite3.connect('nzxt_inventory.db')
    c = conn.cursor()
    
    # Drop and recreate all tables to ensure clean schema
    c.execute("DROP TABLE IF EXISTS items")
    c.execute("DROP TABLE IF EXISTS transactions")
    c.execute("DROP TABLE IF EXISTS work_orders")
    
    # Create items table
    c.execute('''CREATE TABLE items
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT NOT NULL UNIQUE,
                  description TEXT,
                  case_type TEXT,
                  quantity INTEGER DEFAULT 0,
                  min_stock INTEGER DEFAULT 5,
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    
    # Create transactions table
    c.execute('''CREATE TABLE transactions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  item_id INTEGER,
                  change INTEGER,
                  station TEXT,
                  notes TEXT,
                  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                  FOREIGN KEY (item_id) REFERENCES items (id))''')
    
    # Create work_orders table with correct schema
    c.execute('''CREATE TABLE work_orders
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  order_number TEXT NOT NULL,
                  set_type TEXT NOT NULL,
                  required_sets INTEGER NOT NULL,
                  status TEXT DEFAULT 'active',
                  created_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    
    # Add initial brackets with case types - updated H7 components
    initial_items = [
        ('H6-1', 'H6 Bracket 1', 'H6', 15, 10),
        ('H6-2', 'H6 Bracket 2', 'H6', 12, 10),
        ('H6-3', 'H6 Bracket 3', 'H6', 8, 5),
        ('H7-282', 'H7 Bracket 282', 'H7', 5, 5),
        ('H7-304', 'H7 Bracket 304', 'H7', 5, 5),
        ('H9-1', 'H9 Bracket 1', 'H9', 20, 8),
        ('H9-2', 'H9 Bracket 2', 'H9', 18, 8),
        ('H9-3', 'H9 Bracket 3', 'H9', 6, 5)
    ]
    
    for item in initial_items:
        c.execute('INSERT OR IGNORE INTO items (name, description, case_type, quantity, min_stock) VALUES (?, ?, ?, ?, ?)', item)
    
    # Add sample work orders
    sample_work_orders = [
        ('WO-001', 'H6', 10),
        ('WO-002', 'H7-282', 5),
        ('WO-003', 'H7-304', 5),
        ('WO-004', 'H9', 8)
    ]
    
    for wo in sample_work_orders:
        c.execute('INSERT OR IGNORE INTO work_orders (order_number, set_type, required_sets) VALUES (?, ?, ?)', wo)
    
    conn.commit()
    conn.close()
    print("✅ Database initialized successfully with clean schema")

def get_db():
    conn = sqlite3.connect('nzxt_inventory.db')
    conn.row_factory = sqlite3.Row
    return conn

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
    
    conn.close()
    
    items_data = [dict(item) for item in items]
    activity_data = [dict(act) for act in recent_activity]
    work_orders_data = [dict(wo) for wo in work_orders]
    
    # Remove server timestamp - client will use local time instead
    socketio.emit('inventory_update', {
        'items': items_data,
        'recent_activity': activity_data,
        'work_orders': work_orders_data
        # No 'timestamp' field - client handles time locally
    })

# SocketIO events
@socketio.on('connect')
def handle_connect():
    print(f"🔗 Client connected: {request.sid}")
    broadcast_update()

@socketio.on('inventory_change')
def handle_inventory_change(data):
    try:
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
        
        conn.execute('''
            INSERT INTO transactions (item_id, change, station, notes, timestamp)
            VALUES (?, ?, ?, ?, ?)
        ''', (item_id, change, station, notes, datetime.now()))
        
        conn.commit()
        conn.close()
        
        broadcast_update()
        
        print(f"📊 {station}: {item['name']} {change:+d} = {new_quantity}")
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        socketio.emit('error', {'message': f'Error: {str(e)}'}, room=request.sid)

# Flask routes
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/add_work_order', methods=['POST'])
def add_work_order():
    data = request.get_json()
    order_number = data.get('order_number', '').strip()
    set_type = data.get('set_type', '')
    required_sets = data.get('required_sets', 0)
    
    if not order_number or not set_type or not required_sets:
        return jsonify({'success': False, 'error': 'Order number, set type, and quantity are required'})
    
    conn = get_db()
    
    try:
        conn.execute('INSERT INTO work_orders (order_number, set_type, required_sets) VALUES (?, ?, ?)', 
                    (order_number, set_type, required_sets))
        conn.commit()
        conn.close()
        
        broadcast_update()
        return jsonify({'success': True, 'message': f'Work order {order_number} added successfully'})
        
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({'success': False, 'error': 'Work order with this number already exists'})

@app.route('/api/complete_work_order', methods=['POST'])
def complete_work_order():
    data = request.get_json()
    work_order_id = data.get('work_order_id')
    
    if not work_order_id:
        return jsonify({'success': False, 'error': 'Work order ID is required'})
    
    conn = get_db()
    
    try:
        # Get work order details
        work_order = conn.execute('SELECT * FROM work_orders WHERE id = ?', (work_order_id,)).fetchone()
        if not work_order:
            return jsonify({'success': False, 'error': 'Work order not found'})
        
        set_type = work_order['set_type']
        required_sets = work_order['required_sets']
        
        # Get components for this set type
        components_map = {
            'H6': ['H6-1', 'H6-2', 'H6-3'],
            'H7-282': ['H7-282'],
            'H7-304': ['H7-304'],
            'H9': ['H9-1', 'H9-2', 'H9-3']
        }
        
        components = components_map.get(set_type, [])
        
        # Check if we have enough components
        for component_name in components:
            component = conn.execute('SELECT * FROM items WHERE name = ?', (component_name,)).fetchone()
            if not component or component['quantity'] < required_sets:
                return jsonify({'success': False, 'error': f'Not enough {component_name} to complete work order'})
        
        # Deduct components from inventory
        for component_name in components:
            conn.execute('UPDATE items SET quantity = quantity - ? WHERE name = ?', 
                        (required_sets, component_name))
            
            # Log the transaction
            component = conn.execute('SELECT id FROM items WHERE name = ?', (component_name,)).fetchone()
            conn.execute('''
                INSERT INTO transactions (item_id, change, station, notes, timestamp)
                VALUES (?, ?, ?, ?, ?)
            ''', (component['id'], -required_sets, 'Picking Station', 
                  f'Work order {work_order["order_number"]} completed', datetime.now()))
        
        # Mark work order as completed
        conn.execute('UPDATE work_orders SET status = "completed" WHERE id = ?', (work_order_id,))
        
        conn.commit()
        conn.close()
        
        broadcast_update()
        return jsonify({'success': True, 'message': f'Work order {work_order["order_number"]} completed successfully'})
        
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/delete_work_order', methods=['POST'])
def delete_work_order():
    data = request.get_json()
    work_order_id = data.get('work_order_id')
    
    if not work_order_id:
        return jsonify({'success': False, 'error': 'Work order ID is required'})
    
    conn = get_db()
    
    try:
        conn.execute('DELETE FROM work_orders WHERE id = ?', (work_order_id,))
        conn.commit()
        conn.close()
        
        broadcast_update()
        return jsonify({'success': True, 'message': 'Work order deleted successfully'})
        
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/history')
def get_history():
    limit = request.args.get('limit', 50, type=int)
    filter_type = request.args.get('filter', 'all')
    
    conn = get_db()
    
    query = '''
        SELECT t.*, i.name as item_name 
        FROM transactions t 
        JOIN items i ON t.item_id = i.id 
    '''
    
    params = []
    
    if filter_type != 'all':
        query += ' WHERE i.case_type = ? '
        params.append(filter_type)
    
    query += ' ORDER BY t.timestamp DESC LIMIT ?'
    params.append(limit)
    
    history = conn.execute(query, params).fetchall()
    conn.close()
    
    return jsonify({'history': [dict(h) for h in history]})

@app.route('/api/inventory')
def api_inventory():
    conn = get_db()
    items = conn.execute('SELECT * FROM items ORDER BY name').fetchall()
    conn.close()
    return jsonify([dict(item) for item in items])

if __name__ == '__main__':
    print("🚀 Starting NZXT Bracket Inventory Tracker...")
    print("👨‍💻 Developed by Your Name")
    init_database()
    print("✅ Database initialized")
    print("🌐 Server starting...")
    
    # Get port from environment variable or default to 5000
    port = int(os.environ.get('PORT', 5000))

    socketio.run(app, host='0.0.0.0', port=port, debug=False)
