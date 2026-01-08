"""
Simple script to start the web API server.
Run this to start the dashboard server.
"""

import uvicorn
from web_api_server import app, PORT, get_lan_ip

if __name__ == "__main__":
    # Get LAN IP
    lan_ip = get_lan_ip()
    
    # Print access information
    print("=" * 60)
    print("FastAPI Web Server Starting...")
    print("=" * 60)
    print(f"Local access: http://localhost:{PORT}")
    if lan_ip:
        print(f"LAN access: http://{lan_ip}:{PORT}")
        print(f"Open from another PC: http://{lan_ip}:{PORT}")
    else:
        print("Warning: Could not detect LAN IP address")
    print("=" * 60)
    print("Press Ctrl+C to stop the server")
    print("=" * 60)
    
    # Start server
    try:
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=PORT,
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\n\nServer stopped by user")
    except Exception as e:
        print(f"\n\nError starting server: {e}")
        import traceback
        traceback.print_exc()

