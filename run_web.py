#!/usr/bin/env python3
"""
Swim Sync Web UI Launcher

Starts the local web server for the Swim Sync web interface.
Open http://localhost:5000 in your browser after starting.
"""

import sys
import webbrowser
import threading
import time
from pathlib import Path

# Add src to path for imports
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

from swimsync.web_app import run_server


def open_browser():
    """Open the browser after a short delay to let the server start."""
    time.sleep(1.5)
    webbrowser.open('http://localhost:5000')


def main():
    print("=" * 50)
    print("  Swim Sync Web UI")
    print("=" * 50)
    print()
    print("Starting local web server...")
    print("Opening http://localhost:5000 in your browser...")
    print()
    print("Press Ctrl+C to stop the server")
    print()
    
    # Open browser in background thread
    browser_thread = threading.Thread(target=open_browser, daemon=True)
    browser_thread.start()
    
    # Start the server
    try:
        run_server(host='127.0.0.1', port=5000, debug=False)
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == '__main__':
    main()
