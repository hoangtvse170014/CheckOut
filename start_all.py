"""
Start both main app and FastAPI web server together.
"""

import subprocess
import sys
import time
from pathlib import Path

def main():
    print("=" * 60)
    print("🚀 Starting People Counter System...")
    print("=" * 60)
    
    # Start FastAPI web server
    print("\n1️⃣ Starting FastAPI Web Server (port 8000)...")
    web_server = subprocess.Popen(
        [sys.executable, "start_web_server.py"],
        cwd=Path.cwd()
    )
    print("   ✅ FastAPI server started (PID: {})".format(web_server.pid))
    
    # Wait a bit for web server to start
    time.sleep(2)
    
    # Start main app
    print("\n2️⃣ Starting Main People Counter App...")
    main_app = subprocess.Popen(
        [sys.executable, "scripts/run.py"],
        cwd=Path.cwd()
    )
    print("   ✅ Main app started (PID: {})".format(main_app.pid))
    
    print("\n" + "=" * 60)
    print("✅ Both services are running!")
    print("=" * 60)
    print("📍 Web Dashboard: http://localhost:8000")
    print("📍 Main App: Running in background")
    print("\nPress Ctrl+C to stop both services...")
    print("=" * 60)
    
    try:
        # Wait for both processes
        web_server.wait()
        main_app.wait()
    except KeyboardInterrupt:
        print("\n\n🛑 Stopping services...")
        web_server.terminate()
        main_app.terminate()
        web_server.wait()
        main_app.wait()
        print("✅ Both services stopped")

if __name__ == "__main__":
    main()

