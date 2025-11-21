from app import app, socketio, init_database
import os

if __name__ == "__main__":
    print("🚀 Starting Bracket Inventory Tracker...")
    print("👨‍💻 Developed by Your Name")
    init_database()
    print("✅ Database initialized")
    print("🌐 Server starting...")
    
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False, allow_unsafe_werkzeug=True)
