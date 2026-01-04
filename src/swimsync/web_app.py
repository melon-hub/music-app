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
import shutil
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

    # Build track queue with initial statuses
    track_queue = []
    for i, track in enumerate(tracks_to_download):
        track_queue.append({
            "index": i,
            "title": track.get("title", "Unknown"),
            "artist": track.get("artist", "Unknown"),
            "status": "pending",  # pending, downloading, downloaded, failed
            "file_size_mb": 0
        })

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
            "failed_tracks": [],
            "track_queue": track_queue  # Individual track statuses
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

            # Update individual track status in queue
            track_idx = current - 1  # current is 1-indexed
            if 0 <= track_idx < len(sync_status["track_queue"]):
                track_entry = sync_status["track_queue"][track_idx]
                if status == "Downloading":
                    track_entry["status"] = "downloading"
                elif status == "Downloaded":
                    track_entry["status"] = "downloaded"
                    track_entry["file_size_mb"] = extra.get("file_size_mb", 0)
                elif status == "Failed":
                    track_entry["status"] = "failed"

            # Update download statistics
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
        "current_playlist_id": current_playlist_id,
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
        if sys.platform == 'win32' or _is_wsl():
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


# ============================================================================
# Device Copy API (Copy to Device Wizard)
# ============================================================================

# Device copy state
device_copy_status = {
    "is_copying": False,
    "current": 0,
    "total": 0,
    "current_track": "",
    "status": "idle",
    "error": None,
    "copied_count": 0,
    "skipped_count": 0,
    "failed_count": 0,
    "bytes_copied": 0,
    "total_bytes": 0
}
device_copy_thread = None
device_copy_lock = threading.Lock()


def _is_wsl():
    """Check if running in Windows Subsystem for Linux."""
    if sys.platform != 'linux':
        return False
    try:
        return 'microsoft' in os.uname().release.lower()
    except Exception:
        return False


def _get_volume_label_windows(drive_path: str) -> str:
    """Get volume label for a Windows drive."""
    try:
        import ctypes
        volume_name = ctypes.create_unicode_buffer(261)
        ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(drive_path),
            volume_name, 261,
            None, None, None, None, 0
        )
        return volume_name.value if volume_name.value else ""
    except Exception:
        return ""


def _get_volume_label_wsl(letter: str) -> str:
    """Get volume label for a drive in WSL using PowerShell."""
    try:
        result = subprocess.run(
            ['powershell.exe', '-Command',
             f"(Get-Volume -DriveLetter {letter}).FileSystemLabel"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def _get_free_space_gb(path: str) -> float:
    """Get free space in GB for a path, cross-platform."""
    try:
        if sys.platform == 'win32':
            import ctypes
            free_bytes = ctypes.c_ulonglong(0)
            ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                ctypes.c_wchar_p(path), None, None, ctypes.pointer(free_bytes)
            )
            return free_bytes.value / (1024**3)
        elif _is_wsl():
            result = subprocess.run(
                ['df', '-B1', path], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split('\n')[1].split()
                if len(parts) >= 4:
                    return int(parts[3]) / (1024**3)
            return 0
        else:
            stat = os.statvfs(path)
            return (stat.f_bavail * stat.f_frsize) / (1024**3)
    except Exception:
        return 0


def _build_drive_info(path: str, letter: str, volume_label: str,
                      free_bytes: int, total_bytes: int) -> dict:
    """Build a drive info dictionary with consistent structure."""
    display_name = f"{volume_label} ({letter}:)" if volume_label else f"Drive ({letter}:)"
    return {
        "path": path,
        "letter": letter,
        "name": display_name,
        "volume_label": volume_label,
        "free_gb": round(free_bytes / (1024**3), 2),
        "total_gb": round(total_bytes / (1024**3), 2),
        "is_removable": letter not in ['C', 'D']
    }


def _get_available_drives():
    """Get list of available drives/volumes."""
    import string
    drives = []
    is_wsl = _is_wsl()

    if sys.platform == 'win32':
        # Native Windows - check drive letters
        import ctypes
        for letter in string.ascii_uppercase:
            drive_path = f"{letter}:\\"
            if os.path.exists(drive_path):
                try:
                    free_bytes = ctypes.c_ulonglong(0)
                    total_bytes = ctypes.c_ulonglong(0)
                    ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                        ctypes.c_wchar_p(drive_path),
                        None, ctypes.pointer(total_bytes), ctypes.pointer(free_bytes)
                    )
                    if total_bytes.value > 0:
                        volume_label = _get_volume_label_windows(drive_path)
                        drives.append(_build_drive_info(
                            drive_path, letter, volume_label,
                            free_bytes.value, total_bytes.value
                        ))
                except Exception as e:
                    logging.debug(f"Could not get info for drive {letter}: {e}")

    elif is_wsl:
        # WSL - check /mnt/c, /mnt/d, etc.
        for letter in string.ascii_uppercase:
            drive_path = f"/mnt/{letter.lower()}"
            if os.path.exists(drive_path):
                try:
                    result = subprocess.run(
                        ['df', '-B1', drive_path],
                        capture_output=True, text=True, timeout=5
                    )
                    if result.returncode == 0:
                        lines = result.stdout.strip().split('\n')
                        if len(lines) > 1:
                            parts = lines[1].split()
                            if len(parts) >= 4:
                                total_bytes = int(parts[1])
                                free_bytes = int(parts[3])
                                volume_label = _get_volume_label_wsl(letter)
                                drives.append(_build_drive_info(
                                    drive_path, letter, volume_label,
                                    free_bytes, total_bytes
                                ))
                except Exception as e:
                    logging.debug(f"Could not get info for drive {letter}: {e}")
    else:
        # Linux/macOS - check /media and /Volumes
        mount_points = ['/media', '/Volumes', '/run/media']
        for mount_base in mount_points:
            if os.path.exists(mount_base):
                for name in os.listdir(mount_base):
                    mount_path = os.path.join(mount_base, name)
                    if os.path.isdir(mount_path):
                        try:
                            stat = os.statvfs(mount_path)
                            total_bytes = stat.f_blocks * stat.f_frsize
                            free_bytes = stat.f_bavail * stat.f_frsize
                            if total_bytes > 0:
                                drives.append({
                                    "path": mount_path,
                                    "letter": "",
                                    "name": name,
                                    "volume_label": name,
                                    "free_gb": round(free_bytes / (1024**3), 2),
                                    "total_gb": round(total_bytes / (1024**3), 2),
                                    "is_removable": True
                                })
                        except Exception:
                            pass

    # Sort drives: SWIM* devices first, then by letter/name
    def sort_key(drive):
        label = (drive.get("volume_label") or "").upper()
        is_swim = label.startswith("SWIM")
        # SWIM devices first (0), others second (1), then by letter or name
        return (0 if is_swim else 1, drive.get("letter") or drive.get("name", ""))

    drives.sort(key=sort_key)
    return drives


def _scan_folder_for_tracks(folder_path: str) -> dict:
    """Scan a folder for MP3 files and return track info."""
    folder = Path(folder_path)
    if not folder.exists():
        return {"tracks": [], "error": "Folder does not exist"}

    tracks = []
    for mp3_file in folder.glob("*.mp3"):
        stem = mp3_file.stem
        # Parse "Artist - Title" format
        if " - " in stem:
            parts = stem.split(" - ", 1)
            artist = parts[0].strip()
            title = parts[1].strip()
        else:
            artist = "Unknown"
            title = stem

        try:
            size_bytes = mp3_file.stat().st_size
        except OSError:
            size_bytes = 0

        tracks.append({
            "filename": mp3_file.name,
            "artist": artist,
            "title": title,
            "size_bytes": size_bytes,
            "size_mb": round(size_bytes / (1024 * 1024), 2)
        })

    return {"tracks": tracks}


@app.route('/api/devices', methods=['GET'])
def get_devices():
    """Get list of available drives/devices."""
    drives = _get_available_drives()
    return jsonify({
        "drives": drives,
        "last_used": config.get("last_device_path") if config else None
    })


@app.route('/api/devices/browse', methods=['POST'])
def browse_folder():
    """Get contents of a folder for browsing."""
    data = request.json
    path = data.get('path', '').strip()

    if not path:
        return jsonify({"error": "Path is required"}), 400

    # Security validation
    is_valid, error_msg = _validate_path(path)
    if not is_valid:
        return jsonify({"error": error_msg}), 400

    folder = Path(path)
    if not folder.exists():
        return jsonify({"error": "Path does not exist"}), 404

    if not folder.is_dir():
        return jsonify({"error": "Path is not a directory"}), 400

    # List subdirectories only
    folders = []
    try:
        for item in sorted(folder.iterdir()):
            if item.is_dir() and not item.name.startswith('.'):
                folders.append({
                    "name": item.name,
                    "path": str(item)
                })
    except PermissionError:
        return jsonify({"error": "Permission denied"}), 403

    return jsonify({
        "path": str(folder),
        "parent": str(folder.parent) if folder.parent != folder else None,
        "folders": folders
    })


@app.route('/api/devices/scan', methods=['POST'])
def scan_device():
    """Scan a device/folder and compare with current playlist."""
    data = request.json
    path = data.get('path', '').strip()

    if not path:
        return jsonify({"error": "Path is required"}), 400

    is_valid, error_msg = _validate_path(path)
    if not is_valid:
        return jsonify({"error": error_msg}), 400

    if not current_playlist_id:
        return jsonify({"error": "No playlist selected"}), 400

    # Scan destination folder
    scan_result = _scan_folder_for_tracks(path)
    if "error" in scan_result:
        return jsonify({"error": scan_result["error"]}), 400

    device_tracks = scan_result["tracks"]
    device_filenames = {t["filename"].lower() for t in device_tracks}

    # Get current playlist tracks
    playlist_tracks = library.get_playlist_tracks(current_playlist_id) if library else []

    # Compare
    matched = []  # On device and in playlist
    missing = []  # In playlist but not on device
    extra = []    # On device but not in playlist

    playlist_filenames = set()
    for track in playlist_tracks:
        filename = track.filename
        playlist_filenames.add(filename.lower())

        if filename.lower() in device_filenames:
            matched.append({
                "filename": filename,
                "artist": track.artist,
                "title": track.title
            })
        else:
            missing.append({
                "filename": filename,
                "artist": track.artist,
                "title": track.title,
                "size_mb": track.file_size_mb
            })

    for device_track in device_tracks:
        if device_track["filename"].lower() not in playlist_filenames:
            extra.append(device_track)

    # Calculate sizes
    missing_size_mb = sum(t.get("size_mb", 8) for t in missing)
    free_gb = _get_free_space_gb(path)

    return jsonify({
        "path": path,
        "matched": matched,
        "missing": missing,
        "extra": extra,
        "matched_count": len(matched),
        "missing_count": len(missing),
        "extra_count": len(extra),
        "missing_size_mb": round(missing_size_mb, 1),
        "free_gb": round(free_gb, 2),
        "has_space": free_gb > (missing_size_mb / 1024) * 1.1  # 10% buffer
    })


@app.route('/api/devices/copy', methods=['POST'])
def start_device_copy():
    """Start copying tracks to device."""
    global device_copy_status, device_copy_thread

    with device_copy_lock:
        if device_copy_status["is_copying"]:
            return jsonify({"error": "Copy already in progress"}), 400

    data = request.json
    destination = data.get('destination', '').strip()
    mode = data.get('mode', 'add')  # add, sync, replace

    if not destination:
        return jsonify({"error": "Destination is required"}), 400

    is_valid, error_msg = _validate_path(destination)
    if not is_valid:
        return jsonify({"error": error_msg}), 400

    if not current_playlist_id:
        return jsonify({"error": "No playlist selected"}), 400

    if mode not in ['add', 'sync', 'replace']:
        return jsonify({"error": "Invalid mode"}), 400

    # Save last used path
    config.set("last_device_path", destination)

    # Get playlist tracks
    playlist_tracks = library.get_playlist_tracks(current_playlist_id) if library else []
    if not playlist_tracks:
        return jsonify({"error": "No tracks in playlist"}), 400

    # Scan destination
    scan_result = _scan_folder_for_tracks(destination)
    device_filenames = {t["filename"].lower() for t in scan_result.get("tracks", [])}

    # Determine what to copy/delete
    tracks_to_copy = []
    tracks_to_delete = []

    playlist_filenames = set()
    library_path = Path(config.get("output_folder"))

    for track in playlist_tracks:
        playlist_filenames.add(track.filename.lower())

        if mode == 'replace' or track.filename.lower() not in device_filenames:
            # Get source path (resolve symlink)
            source_path = library_path / "playlists" / current_playlist_id / track.filename
            if source_path.exists() or source_path.is_symlink():
                # Resolve symlink to get actual file
                try:
                    real_path = source_path.resolve()
                    if real_path.exists():
                        tracks_to_copy.append({
                            "source": str(real_path),
                            "filename": track.filename,
                            "artist": track.artist,
                            "title": track.title,
                            "size_bytes": real_path.stat().st_size
                        })
                except Exception as e:
                    logging.warning(f"Could not resolve {source_path}: {e}")

    if mode in ['sync', 'replace']:
        # Find files to delete (on device but not in playlist)
        for device_track in scan_result.get("tracks", []):
            if device_track["filename"].lower() not in playlist_filenames:
                tracks_to_delete.append({
                    "path": str(Path(destination) / device_track["filename"]),
                    "filename": device_track["filename"]
                })

    if not tracks_to_copy and not tracks_to_delete:
        return jsonify({"error": "Nothing to copy or delete"}), 400

    total_bytes = sum(t["size_bytes"] for t in tracks_to_copy)

    # Reset status
    with device_copy_lock:
        device_copy_status = {
            "is_copying": True,
            "current": 0,
            "total": len(tracks_to_copy),
            "current_track": "",
            "status": "starting",
            "error": None,
            "copied_count": 0,
            "skipped_count": 0,
            "failed_count": 0,
            "deleted_count": 0,
            "bytes_copied": 0,
            "total_bytes": total_bytes,
            "mode": mode
        }

    def copy_worker():
        global device_copy_status
        dest_path = Path(destination)
        dest_path.mkdir(parents=True, exist_ok=True)

        try:
            # Delete files first if syncing
            if tracks_to_delete:
                with device_copy_lock:
                    device_copy_status["status"] = "deleting"

                for track in tracks_to_delete:
                    try:
                        Path(track["path"]).unlink()
                        with device_copy_lock:
                            device_copy_status["deleted_count"] += 1
                    except Exception as e:
                        logging.warning(f"Failed to delete {track['filename']}: {e}")

            # Copy files
            for i, track in enumerate(tracks_to_copy):
                with device_copy_lock:
                    device_copy_status["current"] = i + 1
                    device_copy_status["current_track"] = f"{track['artist']} - {track['title']}"
                    device_copy_status["status"] = "copying"

                source = Path(track["source"])
                dest = dest_path / track["filename"]

                try:
                    shutil.copy2(source, dest)
                    with device_copy_lock:
                        device_copy_status["copied_count"] += 1
                        device_copy_status["bytes_copied"] += track["size_bytes"]
                except Exception as e:
                    logging.error(f"Failed to copy {track['filename']}: {e}")
                    with device_copy_lock:
                        device_copy_status["failed_count"] += 1

            with device_copy_lock:
                device_copy_status["status"] = "completed"

        except Exception as e:
            logging.error(f"Copy failed: {e}")
            with device_copy_lock:
                device_copy_status["error"] = str(e)
                device_copy_status["status"] = "error"
        finally:
            with device_copy_lock:
                device_copy_status["is_copying"] = False

    device_copy_thread = threading.Thread(target=copy_worker, daemon=True)
    device_copy_thread.start()

    return jsonify({
        "success": True,
        "tracks_to_copy": len(tracks_to_copy),
        "tracks_to_delete": len(tracks_to_delete),
        "total_size_mb": round(total_bytes / (1024 * 1024), 1)
    })


@app.route('/api/devices/copy/status', methods=['GET'])
def get_device_copy_status():
    """Get current device copy status."""
    with device_copy_lock:
        return jsonify(device_copy_status.copy())


@app.route('/api/devices/copy/cancel', methods=['POST'])
def cancel_device_copy():
    """Cancel current device copy operation."""
    global device_copy_status

    with device_copy_lock:
        if not device_copy_status["is_copying"]:
            return jsonify({"error": "No copy in progress"}), 400
        device_copy_status["status"] = "cancelled"
        device_copy_status["is_copying"] = False

    return jsonify({"success": True})


def run_server(host='127.0.0.1', port=5000, debug=False):
    """Run the Flask local server."""
    init_managers()
    app.run(host=host, port=port, debug=debug, threaded=True)


if __name__ == '__main__':
    # Debug mode via environment variable only (security: don't enable by default)
    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    run_server(debug=debug_mode)
