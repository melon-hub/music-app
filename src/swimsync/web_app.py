"""
Swim Sync - Web UI Server
A Flask-based local web server for the Swim Sync application.
"""

import os
import json
import logging
import secrets
import threading
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory
from swimsync.sync_engine import SyncEngine
from swimsync.state_manager import StateManager
from swimsync.config_manager import ConfigManager

app = Flask(__name__,
            template_folder='web/templates',
            static_folder='web/static')
app.secret_key = secrets.token_hex(32)

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
sync_lock = threading.Lock()


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


def _validate_path(path_str):
    """Validate that a path is safe (no traversal or system directories)."""
    if not path_str or not isinstance(path_str, str):
        return False, "Invalid path"

    # Block path traversal
    if ".." in path_str:
        return False, "Path traversal not allowed"

    # Normalize and check for dangerous paths
    normalized = os.path.normpath(path_str).lower()

    # Block Unix system directories
    dangerous_unix = ['/etc', '/usr', '/bin', '/sbin', '/var', '/root', '/boot', '/sys', '/proc']
    for dangerous in dangerous_unix:
        if normalized.startswith(dangerous):
            return False, "System directories not allowed"

    # Block Windows system directories
    dangerous_windows = ['c:\\windows', 'c:\\program files', 'c:\\programdata', 'c:\\system']
    for dangerous in dangerous_windows:
        if normalized.startswith(dangerous):
            return False, "System directories not allowed"

    return True, None


@app.route('/api/config', methods=['POST'])
def update_config():
    """Update configuration settings."""
    data = request.json

    if not data or not isinstance(data, dict):
        logging.error("Invalid config update: no data provided")
        return jsonify({"error": "Invalid request data"}), 400

    # Validate each field
    for key, value in data.items():
        if key not in ConfigManager.DEFAULTS:
            logging.error(f"Invalid config key: {key}")
            return jsonify({"error": f"Invalid configuration key: {key}"}), 400

        # Type and range validation
        if key == "output_folder":
            if not isinstance(value, str):
                logging.error(f"Invalid type for output_folder: {type(value)}")
                return jsonify({"error": "Output folder must be a string"}), 400
            is_valid, error_msg = _validate_path(value)
            if not is_valid:
                logging.error(f"Invalid output_folder path: {error_msg}")
                return jsonify({"error": error_msg}), 400

        elif key == "bitrate":
            valid_bitrates = ["128k", "192k", "256k", "320k"]
            if value not in valid_bitrates:
                logging.error(f"Invalid bitrate value: {value}")
                return jsonify({"error": f"Bitrate must be one of: {', '.join(valid_bitrates)}"}), 400

        elif key == "storage_limit_gb":
            if not isinstance(value, (int, float)) or value <= 0 or value > 1000:
                logging.error(f"Invalid storage_limit_gb value: {value}")
                return jsonify({"error": "Storage limit must be between 0 and 1000 GB"}), 400

        elif key == "auto_delete_removed":
            if not isinstance(value, bool):
                logging.error(f"Invalid type for auto_delete_removed: {type(value)}")
                return jsonify({"error": "Auto delete must be a boolean"}), 400

        elif key == "download_timeout":
            if not isinstance(value, int) or value < 30 or value > 600:
                logging.error(f"Invalid download_timeout value: {value}")
                return jsonify({"error": "Download timeout must be between 30 and 600 seconds"}), 400

        elif key == "last_playlist_url":
            if not isinstance(value, str):
                logging.error(f"Invalid type for last_playlist_url: {type(value)}")
                return jsonify({"error": "Playlist URL must be a string"}), 400

    # Apply validated settings
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
        logging.error(f"Failed to load playlist: {e}")
        return jsonify({"error": "Failed to load playlist. Please check the URL and try again."}), 500


@app.route('/api/sync/start', methods=['POST'])
def start_sync():
    """Start the sync process."""
    global sync_status, sync_thread

    with sync_lock:
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
    with sync_lock:
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
        with sync_lock:
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
            with sync_lock:
                sync_status["status"] = "completed"
        except Exception as e:
            logging.error(f"Sync failed: {e}")
            with sync_lock:
                sync_status["error"] = "Sync failed. Please try again."
                sync_status["status"] = "error"
        finally:
            with sync_lock:
                sync_status["is_syncing"] = False

    sync_thread = threading.Thread(target=sync_worker, daemon=True)
    sync_thread.start()

    return jsonify({"success": True, "message": "Sync started"})


@app.route('/api/sync/cancel', methods=['POST'])
def cancel_sync():
    """Cancel the current sync operation."""
    global sync_status

    with sync_lock:
        if not sync_status["is_syncing"]:
            return jsonify({"error": "No sync in progress"}), 400

    try:
        sync_engine.cancel()
        with sync_lock:
            sync_status["status"] = "cancelled"
            sync_status["is_syncing"] = False
        return jsonify({"success": True, "message": "Sync cancelled"})
    except Exception as e:
        logging.error(f"Failed to cancel sync: {e}")
        return jsonify({"error": "Failed to cancel sync"}), 500


@app.route('/api/sync/status', methods=['GET'])
def get_sync_status():
    """Get current sync status."""
    with sync_lock:
        return jsonify(sync_status.copy())


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
    """Run the Flask local server."""
    init_managers()
    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == '__main__':
    run_server(debug=False)
