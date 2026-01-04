"""
State Manager - Tracks downloaded files and sync state
Supports both v1 (single manifest) and v2 (per-playlist manifests) formats.
"""

import json
import logging
import os
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional


class StateManager:
    """
    Manages the local manifest of downloaded tracks.

    Supports two modes:
    - V1 mode: Single manifest in output folder (backward compatible)
    - V2 mode: Per-playlist manifest in playlists/{playlist_id}/ folder
    """

    MANIFEST_FILENAME = ".swimsync_manifest.json"

    def __init__(self, output_folder: str, playlist_id: str = None):
        """
        Initialize the state manager.

        Args:
            output_folder: Root folder for the library
            playlist_id: If provided, uses v2 mode with per-playlist manifest
        """
        self.output_folder = Path(output_folder)
        self.playlist_id = playlist_id
        self._is_v2 = playlist_id is not None

        if self._is_v2:
            # V2 mode: manifest in playlists/{playlist_id}/
            self.manifest_path = (
                self.output_folder / "playlists" / playlist_id / self.MANIFEST_FILENAME
            )
            self.tracks_folder = self.output_folder / "playlists" / playlist_id
        else:
            # V1 mode: manifest in output folder
            self.manifest_path = self.output_folder / self.MANIFEST_FILENAME
            self.tracks_folder = self.output_folder

        self._lock = threading.Lock()
        self._data = self._load()
    
    def _load(self) -> Dict:
        """Load manifest from disk or create default"""
        if self.manifest_path.exists():
            try:
                with open(self.manifest_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except json.JSONDecodeError as e:
                # Corrupted JSON, rebuild from folder scan
                logging.warning(f"Corrupted manifest at {self.manifest_path}: {e}. Rebuilding from folder scan.")
                return self._rebuild_from_folder()
            except IOError as e:
                # IO error reading manifest, rebuild from folder scan
                logging.warning(f"Cannot read manifest at {self.manifest_path}: {e}. Rebuilding from folder scan.")
                return self._rebuild_from_folder()
        
        return self._default_manifest()
    
    def _default_manifest(self) -> Dict:
        """Create empty manifest structure"""
        if self._is_v2:
            return {
                "version": "2.0",
                "playlist_id": self.playlist_id,
                "playlist_url": "",
                "playlist_name": "",
                "last_sync": None,
                "tracks": []
            }
        else:
            return {
                "version": "1.0",
                "playlist_url": "",
                "playlist_name": "",
                "last_sync": None,
                "output_folder": str(self.output_folder),
                "tracks": []
            }
    
    def _rebuild_from_folder(self) -> Dict:
        """Rebuild manifest by scanning existing MP3 files"""
        manifest = self._default_manifest()

        if not self.tracks_folder.exists():
            return manifest

        for mp3_file in self.tracks_folder.glob("*.mp3"):
            # Parse filename: "Artist - Title.mp3"
            stem = mp3_file.stem
            if " - " in stem:
                parts = stem.split(" - ", 1)
                artist = parts[0].strip()
                title = parts[1].strip()
            else:
                artist = "Unknown"
                title = stem
            
            track = {
                "spotify_id": "",
                "title": title,
                "artist": artist,
                "album": "",
                "filename": mp3_file.name,
                "file_size_mb": mp3_file.stat().st_size / (1024 * 1024),
                "downloaded_at": datetime.fromtimestamp(
                    mp3_file.stat().st_mtime
                ).isoformat(),
                "status": "downloaded"
            }
            manifest["tracks"].append(track)
        
        return manifest
    
    def save(self) -> bool:
        """Save manifest to disk. Returns True on success, False on failure."""
        with self._lock:
            try:
                self.output_folder.mkdir(parents=True, exist_ok=True)

                with open(self.manifest_path, 'w', encoding='utf-8') as f:
                    json.dump(self._data, f, indent=2, ensure_ascii=False)
                return True
            except (IOError, OSError, PermissionError) as e:
                logging.warning(f"Failed to save manifest: {e}")
                return False
    
    def get_all_tracks(self) -> List[Dict]:
        """Get list of all tracked tracks"""
        return self._data.get("tracks", [])
    
    def get_track(self, title: str, artist: str) -> Optional[Dict]:
        """Find a specific track by title and artist"""
        key = f"{artist.lower().strip()}::{title.lower().strip()}"
        
        for track in self._data.get("tracks", []):
            track_key = f"{track.get('artist', '').lower().strip()}::{track.get('title', '').lower().strip()}"
            if track_key == key:
                return track
        
        return None
    
    def add_track(
        self,
        track_info: Dict,
        filename: str,
        file_size_bytes: int = 0,
        storage_hash: str = None
    ):
        """
        Add a track to the manifest.

        Args:
            track_info: Track metadata dict
            filename: Display filename for the track
            file_size_bytes: File size in bytes (optional, will be calculated if 0)
            storage_hash: Content hash for deduplicated storage (v2 only)
        """
        # Check if already exists
        existing = self.get_track(track_info.get("title", ""), track_info.get("artist", ""))
        file_size_mb = file_size_bytes / 1024 / 1024 if file_size_bytes else self._get_file_size(filename)
        if existing:
            # Update existing entry
            existing["filename"] = filename
            existing["file_size_mb"] = file_size_mb
            existing["downloaded_at"] = datetime.now().isoformat()
            existing["status"] = "downloaded"
            if storage_hash:
                existing["storage_hash"] = storage_hash
        else:
            # Add new entry
            track = {
                "spotify_id": track_info.get("spotify_id", ""),
                "title": track_info.get("title", "Unknown"),
                "artist": track_info.get("artist", "Unknown"),
                "album": track_info.get("album", ""),
                "filename": filename,
                "file_size_mb": file_size_mb,
                "downloaded_at": datetime.now().isoformat(),
                "status": "downloaded"
            }
            if storage_hash:
                track["storage_hash"] = storage_hash
            self._data["tracks"].append(track)
    
    def remove_track(self, track_info: Dict):
        """Remove a track from the manifest"""
        key = f"{track_info.get('artist', '').lower().strip()}::{track_info.get('title', '').lower().strip()}"
        
        self._data["tracks"] = [
            t for t in self._data["tracks"]
            if f"{t.get('artist', '').lower().strip()}::{t.get('title', '').lower().strip()}" != key
        ]
    
    def update_playlist_info(self, url: str, name: str):
        """Update the playlist metadata"""
        self._data["playlist_url"] = url
        self._data["playlist_name"] = name
        self._data["last_sync"] = datetime.now().isoformat()
    
    def get_playlist_info(self) -> Dict:
        """Get current playlist metadata"""
        return {
            "url": self._data.get("playlist_url", ""),
            "name": self._data.get("playlist_name", ""),
            "last_sync": self._data.get("last_sync")
        }
    
    def get_total_size_mb(self) -> float:
        """Calculate total size of all tracked files"""
        total = 0.0
        for track in self._data.get("tracks", []):
            total += track.get("file_size_mb", 0)
        return total
    
    def get_track_count(self) -> int:
        """Get number of tracked tracks"""
        return len(self._data.get("tracks", []))

    def get_avg_track_size_mb(self) -> float:
        """Calculate average file size per track in MB"""
        tracks = self._data.get("tracks", [])
        if not tracks:
            return 0.0
        total_size = sum(track.get("file_size_mb", 0) for track in tracks)
        return total_size / len(tracks)

    def get_last_sync_time(self) -> Optional[str]:
        """Get the timestamp of the last successful sync"""
        return self._data.get("last_sync")

    def set_last_sync_time(self):
        """Update the last sync timestamp to now"""
        self._data["last_sync"] = datetime.now().isoformat()
        self.save()
    
    def _get_file_size(self, filename: str) -> float:
        """Get file size in MB"""
        filepath = self.tracks_folder / filename
        if filepath.exists():
            return filepath.stat().st_size / (1024 * 1024)
        return 0.0

    def sync_with_folder(self):
        """
        Sync manifest with actual folder contents.
        Removes entries for files that no longer exist.
        Adds entries for files not in manifest.
        """
        if not self.tracks_folder.exists():
            return

        # Get actual files
        actual_files = {f.name.lower(): f for f in self.tracks_folder.glob("*.mp3")}
        
        # Remove manifest entries for missing files
        self._data["tracks"] = [
            t for t in self._data["tracks"]
            if t.get("filename", "").lower() in actual_files
        ]
        
        # Get tracked filenames
        tracked_files = {t.get("filename", "").lower() for t in self._data["tracks"]}
        
        # Add entries for untracked files
        for filename, filepath in actual_files.items():
            if filename not in tracked_files:
                # Parse filename to get track info
                stem = filepath.stem
                if " - " in stem:
                    parts = stem.split(" - ", 1)
                    artist = parts[0].strip()
                    title = parts[1].strip()
                else:
                    artist = "Unknown"
                    title = stem
                
                track = {
                    "spotify_id": "",
                    "title": title,
                    "artist": artist,
                    "album": "",
                    "filename": filepath.name,
                    "file_size_mb": filepath.stat().st_size / (1024 * 1024),
                    "downloaded_at": datetime.fromtimestamp(
                        filepath.stat().st_mtime
                    ).isoformat(),
                    "status": "downloaded"
                }
                self._data["tracks"].append(track)
    
    def clear(self):
        """Clear all tracked data"""
        self._data = self._default_manifest()
        self.save()

    def is_v2(self) -> bool:
        """Check if this is a v2 manifest."""
        return self._is_v2

    def get_track_by_hash(self, storage_hash: str) -> Optional[Dict]:
        """Find a track by its storage hash (v2 only)."""
        for track in self._data.get("tracks", []):
            if track.get("storage_hash") == storage_hash:
                return track
        return None

    def get_version(self) -> str:
        """Get the manifest version."""
        return self._data.get("version", "1.0")
