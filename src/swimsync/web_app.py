"""
Swim Sync - Web UI Server
A Flask-based local web server for the Swim Sync application.
"""

import os
import json
import threading
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory
from swimsync.sync_engine import SyncEngine
from swimsync.state_manager import StateManager
from swimsync.config_manager import ConfigManager

app = Flask(__name__, 
            template_folder='web/templates',
            static_folder='web/static')

# Global state
config = None
state = None
sync_engine = None
sync_status = {
    "is_syncing": False,
    "current": 0,
    "total": 0,
    "current_track": "",
    "status": "idle",
    "speed_mbps": 0,
    "file_size_mb": 0,
    "error": None
}
sync_thread = None


def init_managers():
    """Initialize the config, state, and sync engine managers."""
    global config, state, sync_engine
    config = ConfigManager()
    state = StateManager(config.get("output_folder"))
    sync_engine = SyncEngine(config, state)


@app.route('/')
def index():
    """Serve the main application page."""
    return render_template('index.html')


@app.route('/api/config', methods=['GET'])
def get_config():
    """Get current configuration."""
    return jsonify({
        "output_folder": config.get("output_folder"),
        "bitrate": config.get("bitrate"),
        "storage_limit_gb": config.get("storage_limit_gb"),
        "auto_delete_removed": config.get("auto_delete_removed"),
        "last_playlist_url": config.get("last_playlist_url"),
        "download_timeout": config.get("download_timeout")
    })


@app.route('/api/config', methods=['POST'])
def update_config():
    """Update configuration settings."""
    data = request.json
    for key, value in data.items():
        if key in ConfigManager.DEFAULTS:
            config.set(key, value)
    
    # Reinitialize state manager if output folder changed
    global state, sync_engine
    if "output_folder" in data:
        state = StateManager(data["output_folder"])
        sync_engine = SyncEngine(config, state)
    
    return jsonify({"success": True})


@app.route('/api/playlist/load', methods=['POST'])
def load_playlist():
    """Load a Spotify playlist and compute sync preview."""
    data = request.json
    url = data.get('url', '').strip()
    
    if not url:
        return jsonify({"error": "Please enter a Spotify playlist URL"}), 400
    
    if "open.spotify.com/playlist" not in url:
        return jsonify({"error": "Please enter a valid Spotify playlist URL"}), 400
    
    try:
        # Save URL for next session
        config.set("last_playlist_url", url)
        
        # Update state manager with current folder
        output_folder = config.get("output_folder")
        global state, sync_engine
        state = StateManager(output_folder)
        sync_engine = SyncEngine(config, state)
        
        # Fetch playlist
        playlist_name, tracks = sync_engine.fetch_playlist(url)
        
        # Compute diff
        preview = sync_engine.compute_diff(tracks)
        
        # Calculate storage info
        total_size_mb = state.get_total_size_mb()
        storage_limit_gb = config.get("storage_limit_gb")
        
        return jsonify({
            "success": True,
            "playlist_name": playlist_name,
            "tracks": tracks,
            "preview": {
                "new": preview["new"],
                "existing": preview["existing"],
                "removed": preview["removed"],
                "suspect": preview.get("suspect", [])
            },
            "storage": {
                "used_mb": total_size_mb,
                "limit_gb": storage_limit_gb
            }
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/sync/start', methods=['POST'])
def start_sync():
    """Start the sync process."""
    global sync_status, sync_thread
    
    if sync_status["is_syncing"]:
        return jsonify({"error": "Sync already in progress"}), 400
    
    data = request.json
    new_tracks = data.get('new_tracks', [])
    suspect_tracks = data.get('suspect_tracks', [])
    removed_tracks = data.get('removed_tracks', [])
    delete_removed = data.get('delete_removed', False)
    
    tracks_to_download = new_tracks + suspect_tracks
    tracks_to_delete = removed_tracks if delete_removed else []
    
    if not tracks_to_download and not tracks_to_delete:
        return jsonify({"error": "Nothing to sync"}), 400
    
    # Reset sync status
    sync_status = {
        "is_syncing": True,
        "current": 0,
        "total": len(tracks_to_download),
        "current_track": "",
        "status": "starting",
        "speed_mbps": 0,
        "file_size_mb": 0,
        "error": None
    }
    
    def progress_callback(current, total, track_name, status, extra=None):
        extra = extra or {}
        sync_status["current"] = current
        sync_status["total"] = total
        sync_status["current_track"] = track_name
        sync_status["status"] = status
        sync_status["speed_mbps"] = extra.get("speed_mbps", 0)
        sync_status["file_size_mb"] = extra.get("file_size_mb", 0)
    
    def sync_worker():
        global sync_status
        try:
            sync_engine.sync(
                tracks_to_download,
                tracks_to_delete,
                progress_callback=progress_callback
            )
            sync_status["status"] = "completed"
        except Exception as e:
            sync_status["error"] = str(e)
            sync_status["status"] = "error"
        finally:
            sync_status["is_syncing"] = False
    
    sync_thread = threading.Thread(target=sync_worker, daemon=True)
    sync_thread.start()
    
    return jsonify({"success": True, "message": "Sync started"})


@app.route('/api/sync/cancel', methods=['POST'])
def cancel_sync():
    """Cancel the current sync operation."""
    global sync_status
    
    if not sync_status["is_syncing"]:
        return jsonify({"error": "No sync in progress"}), 400
    
    try:
        sync_engine.cancel()
        sync_status["status"] = "cancelled"
        sync_status["is_syncing"] = False
        return jsonify({"success": True, "message": "Sync cancelled"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/sync/status', methods=['GET'])
def get_sync_status():
    """Get current sync status."""
    return jsonify(sync_status)


@app.route('/api/storage', methods=['GET'])
def get_storage():
    """Get storage information."""
    total_size_mb = state.get_total_size_mb()
    track_count = state.get_track_count()
    storage_limit_gb = config.get("storage_limit_gb")
    
    return jsonify({
        "used_mb": total_size_mb,
        "used_gb": total_size_mb / 1024,
        "limit_gb": storage_limit_gb,
        "track_count": track_count,
        "percentage": (total_size_mb / 1024 / storage_limit_gb * 100) if storage_limit_gb > 0 else 0
    })


def run_server(host='127.0.0.1', port=5000, debug=False):
    """Run the Flask development server."""
    init_managers()
    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == '__main__':
    run_server(debug=True)
