"""
Swim Sync - Library Manager
Manages multiple playlists with deduplicated storage.
"""

import json
import logging
import re
import shutil
import unicodedata
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict

from swimsync.track_storage import TrackStorage


def _normalize_text(text: str) -> str:
    """Normalize text by replacing unicode whitespace with regular spaces."""
    # Replace non-breaking spaces and other unicode whitespace with regular space
    text = text.replace('\xa0', ' ')  # Non-breaking space
    text = text.replace('\u200b', '')  # Zero-width space
    text = text.replace('\u2009', ' ')  # Thin space
    text = text.replace('\u202f', ' ')  # Narrow no-break space
    # Normalize unicode to NFC form for consistent comparison
    text = unicodedata.normalize('NFC', text)
    return text


@dataclass
class Playlist:
    """Represents a playlist in the library."""
    id: str
    name: str
    spotify_url: str
    folder_name: str
    track_count: int = 0
    total_size_mb: float = 0.0
    unique_size_mb: float = 0.0
    last_sync: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    color: str = "#3b82f6"


@dataclass
class Track:
    """Represents a track in a playlist."""
    spotify_id: str
    title: str
    artist: str
    album: str
    filename: str
    file_size_mb: float = 0.0
    storage_hash: str = ""
    status: str = "downloaded"
    downloaded_at: str = ""


class LibraryManager:
    """
    Manages multiple playlists with deduplicated storage.
    Handles playlist creation, track management, and library configuration.
    """

    LIBRARY_DIR = ".swimsync"
    LIBRARY_CONFIG = "library.json"
    PLAYLISTS_DIR = "playlists"

    def __init__(self, library_path: Path, track_storage: TrackStorage):
        """
        Initialize the library manager.

        Args:
            library_path: Root path of the SwimSync library
            track_storage: TrackStorage instance for deduplicated storage
        """
        self.library_path = Path(library_path)
        self.storage = track_storage
        self.config_path = self.library_path / self.LIBRARY_DIR / self.LIBRARY_CONFIG
        self._config = self._load_config()

        # Ensure directories exist
        (self.library_path / self.LIBRARY_DIR).mkdir(parents=True, exist_ok=True)
        (self.library_path / self.PLAYLISTS_DIR).mkdir(parents=True, exist_ok=True)

    def _load_config(self) -> Dict:
        """Load library configuration from disk."""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Validate structure
                    if "version" in data and "playlists" in data:
                        return data
            except (json.JSONDecodeError, IOError) as e:
                logging.warning(f"Failed to load library config: {e}")
        return self._default_config()

    def _default_config(self) -> Dict:
        """Create a new empty library config."""
        return {
            "version": "2.0",
            "primary_playlist_id": None,
            "playlists": [],
            "device": {
                "name": "Shokz OpenSwim Pro",
                "capacity_gb": 32,
                "last_connected": None,
                "last_playlist_loaded": None
            },
            "storage_stats": {}
        }

    def _save_config(self):
        """Save library configuration to disk."""
        # Update storage stats before saving
        self._config["storage_stats"] = self.storage.get_storage_stats()

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.config_path.with_suffix('.tmp')
        try:
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(self._config, f, indent=2)
            temp_path.replace(self.config_path)
        except Exception as e:
            logging.error(f"Failed to save library config: {e}")
            if temp_path.exists():
                temp_path.unlink()
            raise

    def get_playlist(self, playlist_id: str) -> Optional[Playlist]:
        """
        Get a playlist by ID.

        Args:
            playlist_id: The playlist ID

        Returns:
            Playlist object or None if not found
        """
        for p in self._config["playlists"]:
            if p["id"] == playlist_id:
                return Playlist(**p)
        return None

    def get_all_playlists(self) -> List[Playlist]:
        """Get all playlists in the library."""
        return [Playlist(**p) for p in self._config["playlists"]]

    def create_playlist(
        self,
        name: str,
        spotify_url: str = "",
        color: str = "#3b82f6"
    ) -> Playlist:
        """
        Create a new playlist.

        Args:
            name: Display name for the playlist
            spotify_url: Spotify playlist URL (optional)
            color: Display color for the playlist

        Returns:
            The created Playlist object
        """
        # Generate ID from name
        playlist_id = self._generate_playlist_id(name)

        playlist_data = {
            "id": playlist_id,
            "name": name,
            "spotify_url": spotify_url,
            "folder_name": playlist_id,
            "track_count": 0,
            "total_size_mb": 0.0,
            "unique_size_mb": 0.0,
            "last_sync": None,
            "created_at": datetime.now().isoformat(),
            "color": color
        }

        self._config["playlists"].append(playlist_data)

        # Create playlist folder
        folder = self.library_path / self.PLAYLISTS_DIR / playlist_id
        folder.mkdir(parents=True, exist_ok=True)

        # Initialize empty manifest
        manifest = {
            "version": "2.0",
            "playlist_id": playlist_id,
            "playlist_url": spotify_url,
            "playlist_name": name,
            "last_sync": None,
            "tracks": []
        }
        manifest_path = folder / ".swimsync_manifest.json"
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2)

        # Set as primary if first playlist
        if len(self._config["playlists"]) == 1:
            self._config["primary_playlist_id"] = playlist_id

        self._save_config()
        return Playlist(**playlist_data)

    def delete_playlist(self, playlist_id: str) -> bool:
        """
        Delete a playlist and remove its track references.

        Args:
            playlist_id: The playlist ID to delete

        Returns:
            True if deleted successfully
        """
        playlist = self.get_playlist(playlist_id)
        if not playlist:
            return False

        # Remove track references from storage
        tracks = self.get_playlist_tracks(playlist_id)
        for track in tracks:
            self.storage.remove_reference(track.storage_hash, playlist_id)

        # Remove playlist folder
        folder = self.library_path / self.PLAYLISTS_DIR / playlist.folder_name
        if folder.exists():
            try:
                shutil.rmtree(folder)
            except Exception as e:
                logging.error(f"Failed to remove playlist folder: {e}")

        # Remove from config
        self._config["playlists"] = [
            p for p in self._config["playlists"] if p["id"] != playlist_id
        ]

        # Update primary if needed
        if self._config["primary_playlist_id"] == playlist_id:
            if self._config["playlists"]:
                self._config["primary_playlist_id"] = self._config["playlists"][0]["id"]
            else:
                self._config["primary_playlist_id"] = None

        self._save_config()
        return True

    def update_playlist(
        self,
        playlist_id: str,
        name: str = None,
        spotify_url: str = None,
        color: str = None
    ) -> Optional[Playlist]:
        """
        Update playlist metadata.

        Args:
            playlist_id: The playlist ID to update
            name: New name (optional)
            spotify_url: New Spotify URL (optional)
            color: New color (optional)

        Returns:
            Updated Playlist object or None if not found
        """
        for p in self._config["playlists"]:
            if p["id"] == playlist_id:
                if name is not None:
                    p["name"] = name
                    # Also update manifest
                    self._update_manifest_metadata(playlist_id, name=name)
                if spotify_url is not None:
                    p["spotify_url"] = spotify_url
                    self._update_manifest_metadata(playlist_id, spotify_url=spotify_url)
                if color is not None:
                    p["color"] = color

                self._save_config()
                return Playlist(**p)
        return None

    def get_playlist_tracks(self, playlist_id: str) -> List[Track]:
        """
        Get all tracks in a playlist.

        Args:
            playlist_id: The playlist ID

        Returns:
            List of Track objects
        """
        playlist = self.get_playlist(playlist_id)
        if not playlist:
            return []

        manifest_path = (
            self.library_path / self.PLAYLISTS_DIR /
            playlist.folder_name / ".swimsync_manifest.json"
        )

        if not manifest_path.exists():
            return []

        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
            return [Track(**t) for t in manifest.get("tracks", [])]
        except (json.JSONDecodeError, IOError) as e:
            logging.error(f"Failed to load playlist tracks: {e}")
            return []

    def add_track_to_playlist(
        self,
        playlist_id: str,
        track_info: Dict,
        storage_hash: str
    ) -> bool:
        """
        Add a track to a playlist (assumes already stored in TrackStorage).

        Args:
            playlist_id: The playlist ID
            track_info: Track metadata dict
            storage_hash: Content hash from TrackStorage

        Returns:
            True if successful
        """
        playlist = self.get_playlist(playlist_id)
        if not playlist:
            return False

        manifest_path = (
            self.library_path / self.PLAYLISTS_DIR /
            playlist.folder_name / ".swimsync_manifest.json"
        )

        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
        except (json.JSONDecodeError, IOError):
            manifest = {
                "version": "2.0",
                "playlist_id": playlist_id,
                "playlist_url": playlist.spotify_url,
                "playlist_name": playlist.name,
                "last_sync": None,
                "tracks": []
            }

        # Create display filename
        filename = f"{track_info.get('artist', 'Unknown')} - {track_info.get('title', 'Unknown')}.mp3"
        filename = self._sanitize_filename(filename)

        # Check if track already exists (using spotify_id or first_artist::title)
        def make_track_key(t):
            spotify_id = t.get("spotify_id", "").strip()
            if spotify_id:
                return f"spotify::{spotify_id}"
            title = _normalize_text(t.get("title", "")).lower()
            artist = _normalize_text(t.get("artist", "")).lower()
            first_artist = artist.split(',')[0].strip()
            return f"{first_artist}::{title}"

        existing_keys = {make_track_key(t) for t in manifest["tracks"]}
        new_key = make_track_key(track_info)
        if new_key in existing_keys:
            logging.debug(f"Track already in playlist: {new_key}")
            return True

        track_data = {
            "spotify_id": track_info.get("spotify_id", ""),
            "title": track_info.get("title", "Unknown"),
            "artist": track_info.get("artist", "Unknown"),
            "album": track_info.get("album", ""),
            "filename": filename,
            "storage_hash": storage_hash,
            "file_size_mb": track_info.get("file_size_mb", 0),
            "status": "downloaded"
        }

        manifest["tracks"].append(track_data)
        manifest["last_sync"] = datetime.now().isoformat()

        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2)

        # Create symlink in playlist folder
        playlist_folder = self.library_path / self.PLAYLISTS_DIR / playlist.folder_name
        self.storage.create_playlist_link(storage_hash, playlist_folder, filename)

        # Update playlist stats
        self._update_playlist_stats(playlist_id)

        return True

    def remove_track_from_playlist(
        self,
        playlist_id: str,
        artist: str,
        title: str,
        spotify_id: str = ""
    ) -> bool:
        """
        Remove a track from a playlist.

        Args:
            playlist_id: The playlist ID
            artist: Track artist
            title: Track title

        Returns:
            True if removed successfully
        """
        playlist = self.get_playlist(playlist_id)
        if not playlist:
            return False

        manifest_path = (
            self.library_path / self.PLAYLISTS_DIR /
            playlist.folder_name / ".swimsync_manifest.json"
        )

        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
        except (json.JSONDecodeError, IOError):
            return False

        # Helper to generate track key (spotify_id preferred, then first_artist::title)
        def make_track_key(t):
            sid = t.get("spotify_id", "").strip() if isinstance(t, dict) else ""
            if sid:
                return f"spotify::{sid}"
            t_title = _normalize_text(t.get("title", "") if isinstance(t, dict) else title).lower()
            t_artist = _normalize_text(t.get("artist", "") if isinstance(t, dict) else artist).lower()
            first_artist = t_artist.split(',')[0].strip()
            return f"{first_artist}::{t_title}"

        # Build search key from parameters
        if spotify_id:
            search_key = f"spotify::{spotify_id}"
        else:
            norm_artist = _normalize_text(artist).lower()
            first_artist = norm_artist.split(',')[0].strip()
            search_key = f"{first_artist}::{_normalize_text(title).lower()}"

        # Find and remove track
        removed_track = None
        new_tracks = []
        for t in manifest["tracks"]:
            key = make_track_key(t)
            if key == search_key:
                removed_track = t
            else:
                new_tracks.append(t)

        if not removed_track:
            return False

        manifest["tracks"] = new_tracks

        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2)

        # Remove reference from storage
        if removed_track.get("storage_hash"):
            self.storage.remove_reference(removed_track["storage_hash"], playlist_id)

        # Remove symlink from playlist folder
        playlist_folder = self.library_path / self.PLAYLISTS_DIR / playlist.folder_name
        link_path = playlist_folder / removed_track["filename"]
        if link_path.exists() or link_path.is_symlink():
            try:
                link_path.unlink()
            except Exception as e:
                logging.warning(f"Failed to remove track link: {e}")

        # Update playlist stats
        self._update_playlist_stats(playlist_id)

        return True

    def set_primary_playlist(self, playlist_id: str) -> bool:
        """
        Set the primary/active playlist.

        Args:
            playlist_id: The playlist ID to set as primary

        Returns:
            True if successful
        """
        if not self.get_playlist(playlist_id):
            return False

        self._config["primary_playlist_id"] = playlist_id
        self._save_config()
        return True

    def get_primary_playlist(self) -> Optional[Playlist]:
        """Get the primary playlist."""
        primary_id = self._config.get("primary_playlist_id")
        return self.get_playlist(primary_id) if primary_id else None

    def get_library_stats(self) -> Dict:
        """Get overall library statistics."""
        storage_stats = self.storage.get_storage_stats()
        playlists = self.get_all_playlists()

        total_playlist_tracks = sum(p.track_count for p in playlists)

        return {
            "playlist_count": len(playlists),
            "total_playlist_tracks": total_playlist_tracks,
            "unique_tracks": storage_stats["unique_tracks"],
            "actual_storage_mb": storage_stats["actual_storage_mb"],
            "logical_size_mb": storage_stats["logical_size_mb"],
            "savings_mb": storage_stats["savings_mb"],
            "savings_percent": storage_stats["savings_percent"]
        }

    def _generate_playlist_id(self, name: str) -> str:
        """Generate a unique playlist ID from name."""
        # Convert to lowercase, replace spaces with hyphens
        playlist_id = name.lower().replace(" ", "-").replace("'", "")
        # Remove invalid characters
        playlist_id = re.sub(r'[^a-z0-9\-]', '', playlist_id)
        # Ensure not empty
        if not playlist_id:
            playlist_id = "playlist"

        # Ensure unique
        base_id = playlist_id
        counter = 1
        existing_ids = {p["id"] for p in self._config["playlists"]}
        while playlist_id in existing_ids:
            playlist_id = f"{base_id}-{counter}"
            counter += 1

        return playlist_id

    def refresh_playlist_stats(self, playlist_id: str):
        """
        Public method to refresh playlist stats.
        Call this after syncing manifest with folder to update sidebar counts.
        """
        self._update_playlist_stats(playlist_id)

    def _update_playlist_stats(self, playlist_id: str):
        """Update playlist statistics in library config."""
        tracks = self.get_playlist_tracks(playlist_id)

        total_size = sum(t.file_size_mb for t in tracks)
        unique_hashes = set(t.storage_hash for t in tracks)
        unique_size = 0
        for h in unique_hashes:
            track_info = self.storage.get_track_info(h)
            if track_info:
                unique_size += track_info.get("size_bytes", 0) / 1024 / 1024

        for p in self._config["playlists"]:
            if p["id"] == playlist_id:
                p["track_count"] = len(tracks)
                p["total_size_mb"] = round(total_size, 2)
                p["unique_size_mb"] = round(unique_size, 2)
                p["last_sync"] = datetime.now().isoformat()
                break

        self._save_config()

    def _update_manifest_metadata(
        self,
        playlist_id: str,
        name: str = None,
        spotify_url: str = None
    ):
        """Update playlist manifest metadata."""
        playlist = self.get_playlist(playlist_id)
        if not playlist:
            return

        manifest_path = (
            self.library_path / self.PLAYLISTS_DIR /
            playlist.folder_name / ".swimsync_manifest.json"
        )

        if not manifest_path.exists():
            return

        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                manifest = json.load(f)

            if name is not None:
                manifest["playlist_name"] = name
            if spotify_url is not None:
                manifest["playlist_url"] = spotify_url

            with open(manifest_path, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, indent=2)
        except (json.JSONDecodeError, IOError) as e:
            logging.error(f"Failed to update manifest metadata: {e}")

    def _sanitize_filename(self, filename: str) -> str:
        """Remove invalid characters from filename."""
        # Normalize unicode whitespace
        filename = _normalize_text(filename)
        # Remove characters invalid on Windows
        filename = re.sub(r'[<>:"/\\|?*]', '', filename)
        # Remove path traversal
        filename = filename.replace('..', '')
        # Strip leading/trailing spaces and dots
        filename = filename.strip('. ')
        # Limit length
        if len(filename) > 200:
            name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
            filename = name[:195] + ('.' + ext if ext else '')
        return filename

    def repair_broken_symlinks(self) -> int:
        """
        Find and remove broken symlinks in all playlist folders.
        This handles cases where storage files were deleted or symlinks
        were created with unicode issues.

        Returns:
            Number of broken symlinks removed
        """
        removed = 0
        playlists_dir = self.library_path / self.PLAYLISTS_DIR

        if not playlists_dir.exists():
            return 0

        for playlist_folder in playlists_dir.iterdir():
            if not playlist_folder.is_dir():
                continue

            for file_path in playlist_folder.glob("*.mp3"):
                # Check if it's a symlink pointing to a non-existent target
                if file_path.is_symlink():
                    try:
                        # Try to access the target - this will fail if broken
                        file_path.stat()
                    except OSError:
                        # Broken symlink - remove it
                        try:
                            file_path.unlink()
                            removed += 1
                            logging.info(f"Removed broken symlink: {file_path.name}")
                        except OSError as e:
                            logging.warning(f"Failed to remove broken symlink {file_path}: {e}")

        if removed > 0:
            logging.info(f"Repaired {removed} broken symlinks")

        return removed
