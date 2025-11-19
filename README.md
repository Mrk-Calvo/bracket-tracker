# Bracket Inventory Tracker

A real-time inventory management system for tracking 3D printed brackets and managing work orders.

## Features

- **Real-time Inventory Tracking**: Live updates across all connected clients
- **Work Order Management**: Create and track manufacturing orders
- **Multi-station Workflow**: Printing Station, Picking Station, and Inventory Management
- **Slack Integration**: Get notifications for low stock and work order status
- **Role-based Access Control**: Admin, Operator, and Viewer roles
- **Export Capabilities**: Export data to CSV, PDF, and JSON formats
- **Set Completion Analysis**: See how many complete sets can be built from current inventory

## Deployment on Render.com

### 1. Fork/Upload to GitHub
Ensure your code is in a GitHub repository with these files:
- `app.py` (main application)
- `wsgi.py` (WSGI entry point)
- `requirements.txt` (dependencies)
- `runtime.txt` (Python version)
- `render.yaml` (deployment config)

### 2. Create Render.com Account
Sign up at [render.com](https://render.com)

### 3. Create New Web Service
- Connect your GitHub repository
- Use the following settings:
  - **Name**: `bracket-inventory-tracker`
  - **Environment**: `Python`
  - **Region**: Choose closest to your location
  - **Build Command**: `pip install -r requirements.txt`
  - **Start Command**: `gunicorn --worker-class eventlet -w 1 -b 0.0.0.0:$PORT wsgi:app`

### 4. Environment Variables
Add these environment variables in Render.com dashboard:
- `SECRET_KEY`: (Render will auto-generate this)
- `SLACK_WEBHOOK_URL`: Your Slack webhook URL for notifications (optional)

### 5. Deploy
Click "Create Web Service" and wait for deployment to complete.

## Default Login Credentials

After first deployment, use these credentials:
- **Admin**: `admin` / `admin123`
- **Operator**: `operator` / `operator123` 
- **Viewer**: `viewer` / `viewer123`

**Important**: Change default passwords after first login!

## Support

For issues and questions:
- Email: mark.calvo@premioinc.com

## Version

v2.1 - Real-time Bracket Inventory Management System
