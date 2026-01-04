"""
State Manager - Tracks downloaded files and sync state
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional


class StateManager:
    """Manages the local manifest of downloaded tracks"""
    
    MANIFEST_FILENAME = ".swimsync_manifest.json"
    
    def __init__(self, output_folder: str):
        self.output_folder = Path(output_folder)
        self.manifest_path = self.output_folder / self.MANIFEST_FILENAME
        self._data = self._load()
    
    def _load(self) -> Dict:
        """Load manifest from disk or create default"""
        if self.manifest_path.exists():
            try:
                with open(self.manifest_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                # Corrupted manifest, rebuild from folder scan
                return self._rebuild_from_folder()
        
        return self._default_manifest()
    
    def _default_manifest(self) -> Dict:
        """Create empty manifest structure"""
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
        
        if not self.output_folder.exists():
            return manifest
        
        for mp3_file in self.output_folder.glob("*.mp3"):
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
    
    def save(self):
        """Save manifest to disk"""
        self.output_folder.mkdir(parents=True, exist_ok=True)
        
        with open(self.manifest_path, 'w', encoding='utf-8') as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)
    
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
    
    def add_track(self, track_info: Dict, filename: str):
        """Add a track to the manifest"""
        # Check if already exists
        existing = self.get_track(track_info.get("title", ""), track_info.get("artist", ""))
        if existing:
            # Update existing entry
            existing["filename"] = filename
            existing["downloaded_at"] = datetime.now().isoformat()
            existing["status"] = "downloaded"
        else:
            # Add new entry
            track = {
                "spotify_id": track_info.get("spotify_id", ""),
                "title": track_info.get("title", "Unknown"),
                "artist": track_info.get("artist", "Unknown"),
                "album": track_info.get("album", ""),
                "filename": filename,
                "file_size_mb": self._get_file_size(filename),
                "downloaded_at": datetime.now().isoformat(),
                "status": "downloaded"
            }
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
    
    def _get_file_size(self, filename: str) -> float:
        """Get file size in MB"""
        filepath = self.output_folder / filename
        if filepath.exists():
            return filepath.stat().st_size / (1024 * 1024)
        return 0.0
    
    def sync_with_folder(self):
        """
        Sync manifest with actual folder contents.
        Removes entries for files that no longer exist.
        Adds entries for files not in manifest.
        """
        if not self.output_folder.exists():
            return
        
        # Get actual files
        actual_files = {f.name.lower(): f for f in self.output_folder.glob("*.mp3")}
        
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
