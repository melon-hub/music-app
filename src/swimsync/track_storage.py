"""
Swim Sync - Track Storage Engine
Content-addressed storage with deduplication and reference counting.
"""

import hashlib
import os
import shutil
import json
import logging
import threading
import unicodedata
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List, Tuple
from datetime import datetime


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
class StoredTrack:
    """Metadata for a track in deduplicated storage."""
    hash: str
    filename: str
    original_name: str
    size_bytes: int
    artist: str
    title: str
    album: str
    spotify_id: str
    downloaded_at: str
    reference_count: int
    referenced_by: List[str] = field(default_factory=list)


class TrackStorage:
    """
    Manages deduplicated track storage using content-addressed storage.
    Tracks are stored by their content hash, with reference counting
    to track which playlists use each track.
    """

    STORAGE_DIR = ".swimsync/storage"
    INDEX_FILE = "storage_index.json"
    HASH_ALGORITHM = "sha256"
    HASH_PREFIX_LENGTH = 16  # Use first 16 chars of hash for filename

    def __init__(self, library_path: Path):
        """
        Initialize track storage.

        Args:
            library_path: Root path of the SwimSync library
        """
        self.library_path = Path(library_path)
        self.storage_path = self.library_path / self.STORAGE_DIR
        self.index_path = self.storage_path / self.INDEX_FILE
        self._lock = threading.Lock()
        self._index = self._load_index()

        # Ensure storage directory exists
        self.storage_path.mkdir(parents=True, exist_ok=True)

    def _load_index(self) -> Dict:
        """Load storage index from disk."""
        if self.index_path.exists():
            try:
                with open(self.index_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Validate structure
                    if "tracks" in data and "version" in data:
                        return data
            except (json.JSONDecodeError, IOError) as e:
                logging.warning(f"Failed to load storage index: {e}")
        return self._default_index()

    def _default_index(self) -> Dict:
        """Create a new empty storage index."""
        return {
            "version": "1.0",
            "tracks": {},
            "hash_by_spotify_id": {},
            "hash_by_key": {}
        }

    def _save_index(self):
        """Save storage index to disk."""
        with self._lock:
            self.storage_path.mkdir(parents=True, exist_ok=True)
            # Write to temp file first, then rename for atomicity
            temp_path = self.index_path.with_suffix('.tmp')
            try:
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(self._index, f, indent=2)
                # Atomic rename (on POSIX) or replace (on Windows)
                temp_path.replace(self.index_path)
            except Exception as e:
                logging.error(f"Failed to save storage index: {e}")
                if temp_path.exists():
                    temp_path.unlink()
                raise

    def compute_hash(self, file_path: Path) -> str:
        """
        Compute content hash of a file.

        Args:
            file_path: Path to the file to hash

        Returns:
            First 16 characters of the SHA256 hash
        """
        hasher = hashlib.new(self.HASH_ALGORITHM)
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                hasher.update(chunk)
        return hasher.hexdigest()[:self.HASH_PREFIX_LENGTH]

    def store_track(
        self,
        source_path: Path,
        track_info: Dict,
        playlist_id: str
    ) -> Tuple[str, bool]:
        """
        Store a track in deduplicated storage.

        Args:
            source_path: Path to the downloaded MP3 file
            track_info: Track metadata dict with keys: artist, title, album, spotify_id
            playlist_id: ID of the playlist this track belongs to

        Returns:
            Tuple of (content_hash, is_new) where is_new indicates if this was a new file
        """
        content_hash = self.compute_hash(source_path)
        storage_file = self.storage_path / f"{content_hash}.mp3"
        is_new = False

        with self._lock:
            if content_hash in self._index["tracks"]:
                # Track already exists - just add reference
                track_data = self._index["tracks"][content_hash]
                if playlist_id not in track_data["referenced_by"]:
                    track_data["referenced_by"].append(playlist_id)
                    track_data["reference_count"] = len(track_data["referenced_by"])
            else:
                # New track - copy to storage
                try:
                    shutil.copy2(source_path, storage_file)
                except Exception as e:
                    logging.error(f"Failed to store track: {e}")
                    raise
                is_new = True

                track_data = {
                    "hash": content_hash,
                    "filename": f"{content_hash}.mp3",
                    "original_name": source_path.name,
                    "size_bytes": source_path.stat().st_size,
                    "artist": track_info.get("artist", "Unknown"),
                    "title": track_info.get("title", "Unknown"),
                    "album": track_info.get("album", ""),
                    "spotify_id": track_info.get("spotify_id", ""),
                    "downloaded_at": datetime.now().isoformat(),
                    "reference_count": 1,
                    "referenced_by": [playlist_id]
                }
                self._index["tracks"][content_hash] = track_data

                # Update lookup indices
                if track_info.get("spotify_id"):
                    self._index["hash_by_spotify_id"][track_info["spotify_id"]] = content_hash

                track_key = self._make_track_key(track_info)
                self._index["hash_by_key"][track_key] = content_hash

        self._save_index()
        return content_hash, is_new

    def remove_reference(self, content_hash: str, playlist_id: str) -> bool:
        """
        Remove a playlist's reference to a track.

        Args:
            content_hash: The track's content hash
            playlist_id: ID of the playlist to remove reference from

        Returns:
            True if the track file was deleted (no more references)
        """
        with self._lock:
            if content_hash not in self._index["tracks"]:
                return False

            track_data = self._index["tracks"][content_hash]

            if playlist_id in track_data["referenced_by"]:
                track_data["referenced_by"].remove(playlist_id)
                track_data["reference_count"] = len(track_data["referenced_by"])

            if track_data["reference_count"] == 0:
                # No more references - delete the file
                storage_file = self.storage_path / track_data["filename"]
                if storage_file.exists():
                    try:
                        storage_file.unlink()
                    except Exception as e:
                        logging.error(f"Failed to delete unreferenced track: {e}")

                # Clean up indices
                if track_data.get("spotify_id"):
                    self._index["hash_by_spotify_id"].pop(track_data["spotify_id"], None)

                track_key = self._make_track_key(track_data)
                self._index["hash_by_key"].pop(track_key, None)

                del self._index["tracks"][content_hash]
                self._save_index()
                return True

        self._save_index()
        return False

    def get_storage_path(self, content_hash: str) -> Optional[Path]:
        """
        Get the path to a stored track file.

        Args:
            content_hash: The track's content hash

        Returns:
            Path to the stored file, or None if not found
        """
        if content_hash in self._index["tracks"]:
            return self.storage_path / f"{content_hash}.mp3"
        return None

    def get_track_info(self, content_hash: str) -> Optional[Dict]:
        """
        Get metadata for a stored track.

        Args:
            content_hash: The track's content hash

        Returns:
            Track metadata dict, or None if not found
        """
        return self._index["tracks"].get(content_hash)

    def create_playlist_link(
        self,
        content_hash: str,
        playlist_folder: Path,
        display_name: str
    ) -> bool:
        """
        Create a symlink/hardlink in a playlist folder pointing to storage.
        Falls back to copy if links not supported.

        Args:
            content_hash: The track's content hash
            playlist_folder: Path to the playlist folder
            display_name: Display filename (e.g., "Artist - Title.mp3")

        Returns:
            True if successful
        """
        source = self.get_storage_path(content_hash)
        if not source or not source.exists():
            logging.warning(f"Source file not found for hash: {content_hash}")
            return False

        target = playlist_folder / display_name
        playlist_folder.mkdir(parents=True, exist_ok=True)

        # Remove existing file/link if present
        if target.exists() or target.is_symlink():
            try:
                target.unlink()
            except Exception as e:
                logging.warning(f"Failed to remove existing file: {e}")

        # Try symlink first (most space-efficient)
        try:
            target.symlink_to(source)
            return True
        except (OSError, NotImplementedError) as e:
            logging.debug(f"Symlink failed, trying hardlink: {e}")

        # Try hardlink (works on same filesystem)
        try:
            os.link(source, target)
            return True
        except (OSError, NotImplementedError) as e:
            logging.debug(f"Hardlink failed, falling back to copy: {e}")

        # Fallback: copy the file (least efficient but always works)
        try:
            shutil.copy2(source, target)
            return True
        except Exception as e:
            logging.error(f"Failed to copy file: {e}")
            return False

    def find_by_spotify_id(self, spotify_id: str) -> Optional[str]:
        """
        Find a track hash by Spotify ID.

        Args:
            spotify_id: The Spotify track ID

        Returns:
            Content hash if found, None otherwise
        """
        return self._index["hash_by_spotify_id"].get(spotify_id)

    def find_by_track_key(self, artist: str, title: str) -> Optional[str]:
        """
        Find a track hash by artist/title key.

        Args:
            artist: Artist name
            title: Track title

        Returns:
            Content hash if found, None otherwise
        """
        key = f"{_normalize_text(artist).lower().strip()}::{_normalize_text(title).lower().strip()}"
        return self._index["hash_by_key"].get(key)

    def get_storage_stats(self) -> Dict:
        """
        Get deduplication statistics.

        Returns:
            Dict with storage statistics
        """
        total_tracks = len(self._index["tracks"])
        total_references = sum(
            t["reference_count"] for t in self._index["tracks"].values()
        )
        total_bytes = sum(
            t["size_bytes"] for t in self._index["tracks"].values()
        )
        logical_bytes = sum(
            t["size_bytes"] * t["reference_count"]
            for t in self._index["tracks"].values()
        )

        savings_bytes = logical_bytes - total_bytes
        savings_percent = (savings_bytes / logical_bytes * 100) if logical_bytes > 0 else 0

        return {
            "unique_tracks": total_tracks,
            "total_references": total_references,
            "actual_storage_bytes": total_bytes,
            "actual_storage_mb": round(total_bytes / 1024 / 1024, 2),
            "logical_size_bytes": logical_bytes,
            "logical_size_mb": round(logical_bytes / 1024 / 1024, 2),
            "savings_bytes": savings_bytes,
            "savings_mb": round(savings_bytes / 1024 / 1024, 2),
            "savings_percent": round(savings_percent, 1)
        }

    def verify_integrity(self) -> Dict:
        """
        Verify storage integrity by checking all tracked files exist.

        Returns:
            Dict with verification results
        """
        missing = []
        valid = []

        for content_hash, track_data in self._index["tracks"].items():
            storage_file = self.storage_path / track_data["filename"]
            if storage_file.exists():
                valid.append(content_hash)
            else:
                missing.append(content_hash)

        return {
            "valid_count": len(valid),
            "missing_count": len(missing),
            "missing_hashes": missing
        }

    def cleanup_orphans(self) -> int:
        """
        Remove files in storage that aren't tracked in the index.

        Returns:
            Number of orphan files removed
        """
        removed = 0
        tracked_files = {
            t["filename"] for t in self._index["tracks"].values()
        }

        for file_path in self.storage_path.glob("*.mp3"):
            if file_path.name not in tracked_files:
                try:
                    file_path.unlink()
                    removed += 1
                    logging.info(f"Removed orphan file: {file_path.name}")
                except Exception as e:
                    logging.error(f"Failed to remove orphan: {e}")

        return removed

    def _make_track_key(self, track_info: Dict) -> str:
        """Generate normalized track key for lookup."""
        artist = _normalize_text(track_info.get("artist", "")).lower().strip()
        title = _normalize_text(track_info.get("title", "")).lower().strip()
        return f"{artist}::{title}"
