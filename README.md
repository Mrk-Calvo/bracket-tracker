# Bracket Inventory Tracker

A real-time inventory management system for tracking 3D printed brackets and managing work orders.

## Features

- **Real-time Inventory Tracking**: Live updates across all connected clients
- **Work Order Management**: Create and track manufacturing orders
- **Multi-station Workflow**: Printing Station, Picking Station, and Inventory Management
- **Slack Integration**: Get notifications for low stock and work order status
- **Role-based Access Control**: Admin, Operator, and Viewer roles
- **Export Capabilities**: Export data to Excel, PDF, and JSON formats
- **Set Completion Analysis**: See how many complete sets can be built from current inventory

## Component Sets

### H6 Set (requires all 3 components)
- H6-623A
- H6-623B  
- H6-623C

### H7 Sets
- H7-282 Set (H7-282 only)
- H7-304 Set (H7-304 only)

### H9 Set (requires all 3 components + optional spacer)
- H9-923A
- H9-923B
- H9-923C
- H9-SPACER (optional)

## User Roles

### Admin
- Full system access
- User management
- System settings configuration
- Slack integration setup

### Operator  
- Inventory management
- Work order creation and completion
- Printing and picking station operations

### Viewer
- Read-only access
- View inventory and work orders
- Export data

## Deployment on Render.com

### 1. Fork/Upload to GitHub
Ensure your code is in a GitHub repository.

### 2. Create Render.com Account
Sign up at [render.com](https://render.com)

### 3. Create New Web Service
- Connect your GitHub repository
- Use the following settings:
  - **Name**: `bracket-inventory-tracker` (or your preferred name)
  - **Environment**: `Python`
  - **Region**: Choose closest to your location
  - **Branch**: `main` (or your default branch)
  - **Root Directory**: (leave empty if root)
  - **Build Command**: `pip install -r requirements.txt`
  - **Start Command**: `gunicorn --worker-class eventlet -w 1 wsgi:app`

### 4. Environment Variables
Add these environment variables in Render.com dashboard:

- `SECRET_KEY`: Generate a secure random key
- `SLACK_WEBHOOK_URL`: Your Slack webhook URL for notifications (optional)

### 5. Deploy
Click "Create Web Service" and wait for deployment to complete.

## Default Login Credentials

After first deployment, use these credentials:

- **Admin**: `admin` / `admin123`
- **Operator**: `operator` / `operator123` 
- **Viewer**: `viewer` / `viewer123`

**Important**: Change default passwords after first login!

## Local Development

### Prerequisites
- Python 3.8+
- pip

### Installation
1. Clone the repository
2. Create virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
