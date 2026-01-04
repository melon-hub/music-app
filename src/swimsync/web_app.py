"""
Swim Sync - Web UI Server
A Flask-based local web server for the Swim Sync application.
Supports multi-playlist architecture with deduplicated storage.
"""

import os
import sys
import re
import json
import logging
import secrets
import threading
import subprocess
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory


# Security validation patterns
PLAYLIST_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')
HEX_COLOR_PATTERN = re.compile(r'^#[0-9a-fA-F]{6}$')


def _validate_playlist_id(playlist_id: str) -> bool:
    """Validate playlist_id to prevent path traversal attacks."""
    if not playlist_id:
        return False
    if '..' in playlist_id or '/' in playlist_id or '\\' in playlist_id:
        return False
    if not PLAYLIST_ID_PATTERN.match(playlist_id):
        return False
    return True


def _validate_color(color: str) -> bool:
    """Validate hex color format."""
    if not color:
        return True  # Empty is OK, will use default
    return bool(HEX_COLOR_PATTERN.match(color))


from swimsync.sync_engine import SyncEngine
from swimsync.state_manager import StateManager
from swimsync.config_manager import ConfigManager
from swimsync.track_storage import TrackStorage
from swimsync.library_manager import LibraryManager
from swimsync.migration import run_migration_if_needed, repair_incomplete_migration

app = Flask(__name__,
            template_folder='web/templates',
            static_folder='web/static')
app.secret_key = secrets.token_hex(32)
app.config['TEMPLATES_AUTO_RELOAD'] = True

# Suppress verbose werkzeug request logging (keeps errors visible)
logging.getLogger('werkzeug').setLevel(logging.WARNING)

# Global state
config = None
state = None
sync_engine = None
track_storage = None
library = None
current_playlist_id = None
sync_status = {
    "is_syncing": False,
    "current": 0,
    "total": 0,
    "current_track": "",
    "status": "idle",
    "speed_mbps": 0,
    "file_size_mb": 0,
    "error": None,
    "downloaded_mb": 0,
    "total_download_mb": 0,
    "completed_count": 0,
    "failed_count": 0,
    "pending_count": 0,
    "failed_tracks": []  # List of track names that failed
}
sync_thread = None
sync_lock = threading.Lock()

# Average track size estimate for new tracks (MB)
DEFAULT_AVG_TRACK_SIZE_MB = 8.0


def init_managers():
    """Initialize the config, state, and sync engine managers."""
    global config, state, sync_engine, track_storage, library, current_playlist_id

    config = ConfigManager()
    library_path = Path(config.get("output_folder"))

    # Run migration if needed (v1 -> v2)
    migration_result = run_migration_if_needed(library_path)
    if migration_result and migration_result.success:
        logging.info(f"Migration complete: {migration_result.tracks_migrated} tracks migrated")

    # Initialize v2 components
    track_storage = TrackStorage(library_path)
    library = LibraryManager(library_path, track_storage)

    # Repair any orphaned files from incomplete migration
    repair_result = repair_incomplete_migration(library_path)
    if repair_result.tracks_migrated > 0:
        logging.info(f"Repair complete: {repair_result.tracks_migrated} orphaned tracks recovered")

    # Repair any broken symlinks (from unicode issues or deleted storage files)
    broken_links_removed = library.repair_broken_symlinks()
    if broken_links_removed > 0:
        logging.info(f"Removed {broken_links_removed} broken symlinks")

    # Get or create primary playlist
    primary = library.get_primary_playlist()
    if primary:
        current_playlist_id = primary.id
        # Use v2 state manager for the primary playlist
        state = StateManager(str(library_path), playlist_id=current_playlist_id)
    else:
        # No playlists yet, use legacy v1 mode for backward compatibility
        state = StateManager(str(library_path))
        current_playlist_id = None

    sync_engine = SyncEngine(
        config, state,
        track_storage=track_storage,
        library_manager=library,
        playlist_id=current_playlist_id
    )


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
        "download_timeout": config.get("download_timeout"),
        "device_name": config.get("device_name")
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

        elif key == "device_name":
            if not isinstance(value, str) or len(value) > 100:
                logging.error(f"Invalid device_name value: {value}")
                return jsonify({"error": "Device name must be a string with max 100 characters"}), 400

    # Apply validated settings
    for key, value in data.items():
        if key in ConfigManager.DEFAULTS:
            config.set(key, value)

    # Reinitialize managers if output folder changed
    global state, sync_engine, track_storage, library, current_playlist_id
    if "output_folder" in data:
        library_path = Path(data["output_folder"])
        track_storage = TrackStorage(library_path)
        library = LibraryManager(library_path, track_storage)
        primary = library.get_primary_playlist()
        if primary:
            current_playlist_id = primary.id
            state = StateManager(str(library_path), playlist_id=current_playlist_id)
        else:
            current_playlist_id = None
            state = StateManager(str(library_path))
        sync_engine = SyncEngine(
            config, state,
            track_storage=track_storage,
            library_manager=library,
            playlist_id=current_playlist_id
        )

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

        # Update state manager with current folder and playlist
        output_folder = config.get("output_folder")
        global state, sync_engine
        state = StateManager(output_folder, playlist_id=current_playlist_id)
        sync_engine = SyncEngine(
            config, state,
            track_storage=track_storage,
            library_manager=library,
            playlist_id=current_playlist_id
        )

        # Fetch playlist
        playlist_name, tracks = sync_engine.fetch_playlist(url)

        # Compute diff
        preview = sync_engine.compute_diff(tracks)

        # Calculate storage info
        total_size_mb = state.get_total_size_mb()
        storage_limit_gb = config.get("storage_limit_gb")

        # Calculate size estimates for sync preview
        avg_track_size = state.get_avg_track_size_mb()
        # Use actual average if available, otherwise use default estimate
        est_track_size = avg_track_size if avg_track_size > 0 else DEFAULT_AVG_TRACK_SIZE_MB

        # Calculate existing tracks size (tracks already downloaded)
        existing_size_mb = 0.0
        for existing_track in preview["existing"]:
            track_data = state.get_track(
                existing_track.get("title", ""),
                existing_track.get("artist", "")
            )
            if track_data:
                existing_size_mb += track_data.get("file_size_mb", 0)

        # Estimate size for new tracks
        new_count = len(preview["new"]) + len(preview.get("suspect", []))
        new_size_mb = new_count * est_track_size

        # Total estimated playlist size
        total_est_size_mb = len(tracks) * est_track_size

        # Projected size after sync (existing + new downloads)
        after_sync_size_mb = existing_size_mb + new_size_mb

        # Get playlist folder path for display
        playlist_folder = ""
        if current_playlist_id:
            folder_path = Path(output_folder) / "playlists" / current_playlist_id
            # Convert to Windows path format for display
            playlist_folder = str(folder_path).replace('/', '\\')
            if playlist_folder.startswith('\\mnt\\'):
                # WSL path - convert to Windows format
                playlist_folder = playlist_folder.replace('\\mnt\\c\\', 'C:\\').replace('\\mnt\\d\\', 'D:\\')

        return jsonify({
            "success": True,
            "playlist_name": playlist_name,
            "tracks": tracks,
            "playlist_folder": playlist_folder,
            "preview": {
                "new": preview["new"],
                "existing": preview["existing"],
                "removed": preview["removed"],
                "suspect": preview.get("suspect", [])
            },
            "storage": {
                "used_mb": total_size_mb,
                "limit_gb": storage_limit_gb
            },
            "size_estimates": {
                "total_est_size_mb": total_est_size_mb,
                "existing_size_mb": existing_size_mb,
                "new_size_mb": new_size_mb,
                "after_sync_size_mb": after_sync_size_mb
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

    # Estimate total download size based on average track size
    avg_track_size = state.get_avg_track_size_mb()
    est_track_size = avg_track_size if avg_track_size > 0 else DEFAULT_AVG_TRACK_SIZE_MB
    total_download_mb = len(tracks_to_download) * est_track_size

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
            "error": None,
            "downloaded_mb": 0,
            "total_download_mb": total_download_mb,
            "completed_count": 0,
            "failed_count": 0,
            "pending_count": len(tracks_to_download),
            "failed_tracks": []
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

            # Update download statistics (status values: "Downloading", "Downloaded", "Failed", "Deleting", "Deleted")
            if status == "Downloaded":
                sync_status["downloaded_mb"] += extra.get("file_size_mb", 0)
                sync_status["completed_count"] += 1
                sync_status["pending_count"] = total - current
            elif status == "Failed":
                sync_status["failed_count"] += 1
                sync_status["pending_count"] = total - current
                sync_status["failed_tracks"].append(track_name)

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
                sync_status["pending_count"] = 0
            # Update last sync time on successful completion
            state.set_last_sync_time()
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
    """Get storage information including deduplication stats."""
    total_size_mb = state.get_total_size_mb()
    track_count = state.get_track_count()
    storage_limit_gb = config.get("storage_limit_gb")
    avg_track_size_mb = state.get_avg_track_size_mb()
    last_sync_time = state.get_last_sync_time()
    device_name = config.get("device_name")

    # Get deduplication stats from track storage
    dedup_stats = track_storage.get_storage_stats() if track_storage else {}

    return jsonify({
        "used_mb": total_size_mb,
        "used_gb": total_size_mb / 1024,
        "limit_gb": storage_limit_gb,
        "track_count": track_count,
        "percentage": (total_size_mb / 1024 / storage_limit_gb * 100) if storage_limit_gb > 0 else 0,
        "avg_track_size_mb": avg_track_size_mb,
        "last_sync_time": last_sync_time,
        "device_name": device_name,
        "dedup": dedup_stats
    })


# ============================================================================
# Playlist Management API (v2)
# ============================================================================

@app.route('/api/playlists', methods=['GET'])
def get_playlists():
    """Get all playlists in the library."""
    if not library:
        return jsonify({"error": "Library not initialized"}), 500

    playlists = library.get_all_playlists()
    primary = library.get_primary_playlist()

    return jsonify({
        "playlists": [
            {
                "id": p.id,
                "name": p.name,
                "spotify_url": p.spotify_url,
                "track_count": p.track_count,
                "total_size_mb": p.total_size_mb,
                "last_sync": p.last_sync,
                "color": p.color,
                "is_primary": p.id == (primary.id if primary else None)
            }
            for p in playlists
        ],
        "primary_playlist_id": primary.id if primary else None
    })


@app.route('/api/playlists', methods=['POST'])
def create_playlist():
    """Create a new playlist."""
    if not library:
        return jsonify({"error": "Library not initialized"}), 500

    data = request.json
    if not data:
        return jsonify({"error": "Invalid request data"}), 400

    name = data.get('name', '').strip()
    spotify_url = data.get('spotify_url', '').strip()
    color = data.get('color', '#3b82f6')

    if not _validate_color(color):
        return jsonify({"error": "Invalid color format (use #RRGGBB)"}), 400

    if not name:
        return jsonify({"error": "Playlist name is required"}), 400

    if len(name) > 100:
        return jsonify({"error": "Playlist name too long (max 100 characters)"}), 400

    # Validate Spotify URL if provided
    if spotify_url and "open.spotify.com/playlist" not in spotify_url:
        return jsonify({"error": "Invalid Spotify playlist URL"}), 400

    try:
        playlist = library.create_playlist(name=name, spotify_url=spotify_url, color=color)
        return jsonify({
            "success": True,
            "playlist": {
                "id": playlist.id,
                "name": playlist.name,
                "spotify_url": playlist.spotify_url,
                "track_count": playlist.track_count,
                "color": playlist.color
            }
        })
    except Exception as e:
        logging.error(f"Failed to create playlist: {e}")
        return jsonify({"error": "Failed to create playlist"}), 500


@app.route('/api/playlists/<playlist_id>', methods=['GET'])
def get_playlist(playlist_id):
    """Get a specific playlist by ID."""
    if not _validate_playlist_id(playlist_id):
        return jsonify({"error": "Invalid playlist ID"}), 400

    if not library:
        return jsonify({"error": "Library not initialized"}), 500

    playlist = library.get_playlist(playlist_id)
    if not playlist:
        return jsonify({"error": "Playlist not found"}), 404

    tracks = library.get_playlist_tracks(playlist_id)

    return jsonify({
        "id": playlist.id,
        "name": playlist.name,
        "spotify_url": playlist.spotify_url,
        "track_count": playlist.track_count,
        "total_size_mb": playlist.total_size_mb,
        "last_sync": playlist.last_sync,
        "color": playlist.color,
        "tracks": [
            {
                "title": t.title,
                "artist": t.artist,
                "album": t.album,
                "filename": t.filename,
                "file_size_mb": t.file_size_mb,
                "status": t.status
            }
            for t in tracks
        ]
    })


@app.route('/api/playlists/<playlist_id>', methods=['DELETE'])
def delete_playlist(playlist_id):
    """Delete a playlist."""
    if not _validate_playlist_id(playlist_id):
        return jsonify({"error": "Invalid playlist ID"}), 400

    if not library:
        return jsonify({"error": "Library not initialized"}), 500

    playlist = library.get_playlist(playlist_id)
    if not playlist:
        return jsonify({"error": "Playlist not found"}), 404

    try:
        success = library.delete_playlist(playlist_id)
        if success:
            return jsonify({"success": True, "message": "Playlist deleted"})
        else:
            return jsonify({"error": "Failed to delete playlist"}), 500
    except Exception as e:
        logging.error(f"Failed to delete playlist: {e}")
        return jsonify({"error": "Failed to delete playlist"}), 500


@app.route('/api/playlists/<playlist_id>/select', methods=['POST'])
def select_playlist(playlist_id):
    """Select a playlist as the current/primary playlist."""
    global current_playlist_id, state, sync_engine

    if not _validate_playlist_id(playlist_id):
        return jsonify({"error": "Invalid playlist ID"}), 400

    if not library:
        return jsonify({"error": "Library not initialized"}), 500

    playlist = library.get_playlist(playlist_id)
    if not playlist:
        return jsonify({"error": "Playlist not found"}), 404

    try:
        library.set_primary_playlist(playlist_id)
        current_playlist_id = playlist_id

        # Update state manager to use this playlist
        library_path = Path(config.get("output_folder"))
        state = StateManager(str(library_path), playlist_id=playlist_id)
        sync_engine = SyncEngine(
            config, state,
            track_storage=track_storage,
            library_manager=library,
            playlist_id=playlist_id
        )

        return jsonify({
            "success": True,
            "playlist_id": playlist_id,
            "playlist_name": playlist.name
        })
    except Exception as e:
        logging.error(f"Failed to select playlist: {e}")
        return jsonify({"error": "Failed to select playlist"}), 500


@app.route('/api/playlists/<playlist_id>/open-folder', methods=['POST'])
def open_playlist_folder(playlist_id):
    """Open the playlist's music folder in the system file explorer."""
    if not _validate_playlist_id(playlist_id):
        return jsonify({"error": "Invalid playlist ID"}), 400

    if not library:
        return jsonify({"error": "Library not initialized"}), 500

    playlist = library.get_playlist(playlist_id)
    if not playlist:
        return jsonify({"error": "Playlist not found"}), 404

    try:
        library_path = Path(config.get("output_folder"))
        playlist_folder = library_path / "playlists" / playlist_id

        # Create folder if it doesn't exist
        playlist_folder.mkdir(parents=True, exist_ok=True)

        # Convert to Windows path if running in WSL
        folder_path = str(playlist_folder)
        if '/mnt/c/' in folder_path or '/mnt/d/' in folder_path:
            # Convert WSL path to Windows path
            folder_path = folder_path.replace('/mnt/c/', 'C:\\').replace('/mnt/d/', 'D:\\').replace('/', '\\')

        # Open folder based on platform
        if sys.platform == 'win32' or 'microsoft' in os.uname().release.lower():
            # Windows or WSL
            subprocess.run(['explorer.exe', folder_path], check=False)
        elif sys.platform == 'darwin':
            # macOS
            subprocess.run(['open', folder_path], check=False)
        else:
            # Linux
            subprocess.run(['xdg-open', folder_path], check=False)

        return jsonify({
            "success": True,
            "folder": folder_path
        })
    except Exception as e:
        logging.error(f"Failed to open folder: {e}")
        return jsonify({"error": f"Failed to open folder: {e}"}), 500


@app.route('/api/playlists/<playlist_id>/tracks', methods=['GET'])
def get_playlist_tracks(playlist_id):
    """Get tracks for a specific playlist."""
    if not _validate_playlist_id(playlist_id):
        return jsonify({"error": "Invalid playlist ID"}), 400

    if not library:
        return jsonify({"error": "Library not initialized"}), 500

    playlist = library.get_playlist(playlist_id)
    if not playlist:
        return jsonify({"error": "Playlist not found"}), 404

    tracks = library.get_playlist_tracks(playlist_id)

    return jsonify({
        "playlist_id": playlist_id,
        "playlist_name": playlist.name,
        "tracks": [
            {
                "title": t.title,
                "artist": t.artist,
                "album": t.album,
                "filename": t.filename,
                "file_size_mb": t.file_size_mb,
                "status": t.status,
                "storage_hash": t.storage_hash
            }
            for t in tracks
        ]
    })


@app.route('/api/library/stats', methods=['GET'])
def get_library_stats():
    """Get overall library statistics."""
    if not library:
        return jsonify({"error": "Library not initialized"}), 500

    stats = library.get_library_stats()

    return jsonify({
        "playlist_count": stats["playlist_count"],
        "total_playlist_tracks": stats["total_playlist_tracks"],
        "unique_tracks": stats["unique_tracks"],
        "actual_storage_mb": stats["actual_storage_mb"],
        "logical_size_mb": stats["logical_size_mb"],
        "savings_mb": stats["savings_mb"],
        "savings_percent": stats["savings_percent"]
    })


@app.route('/api/library/repair', methods=['POST'])
def repair_library():
    """Repair library by recovering orphaned MP3 files."""
    library_path = Path(config.get("output_folder"))

    result = repair_incomplete_migration(library_path)

    if result.success:
        # Reinitialize library after repair
        global track_storage, library
        track_storage = TrackStorage(library_path)
        library = LibraryManager(library_path, track_storage)

        return jsonify({
            "success": True,
            "tracks_recovered": result.tracks_migrated,
            "warnings": result.warnings
        })
    else:
        return jsonify({
            "success": False,
            "error": result.error
        }), 500


def run_server(host='127.0.0.1', port=5000, debug=False):
    """Run the Flask local server."""
    init_managers()
    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == '__main__':
    # Debug mode via environment variable only (security: don't enable by default)
    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    run_server(debug=debug_mode)
