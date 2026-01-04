# Multi-Playlist Architecture Design (Merged)

## Overview

This document merges two design approaches:
1. **Device-Centric Design**: Device detection, bi-directional sync, and device management
2. **Storage Optimization Design**: Deduplicated track storage with reference counting

The merged architecture provides:
- Automatic Shokz OpenSwim Pro device detection
- Multiple playlists with a "primary playlist" concept
- Deduplicated storage saving 20-40% space for overlapping playlists
- Bi-directional sync between library and device
- Real-time device status updates via WebSocket

---

## Part 1: Folder Structure

### Library Structure (with Deduplication)

```
~/Music/SwimSync/
├── .swimsync/
│   ├── library.json                  # Library-level config + playlist metadata
│   ├── storage/                      # Deduplicated track storage
│   │   ├── {hash1}.mp3               # Actual MP3 files stored by content hash
│   │   ├── {hash2}.mp3
│   │   ├── {hash3}.mp3
│   │   └── storage_index.json        # Hash -> track metadata mapping
│   └── device_cache/                 # Cache of last known device state
│       └── device_snapshot.json
├── playlists/
│   ├── workout-mix/
│   │   ├── Artist - Song 1.mp3       # Symlink/hardlink to .swimsync/storage/{hash}.mp3
│   │   ├── Artist - Song 2.mp3       # Symlink/hardlink
│   │   └── .swimsync_manifest.json   # Playlist-specific manifest
│   ├── chill-vibes/
│   │   ├── Artist - Song A.mp3       # May point to same hash as workout-mix
│   │   ├── Artist - Song 2.mp3       # Shared track, same hash
│   │   └── .swimsync_manifest.json
│   └── running-beats/
│       ├── Artist - Song X.mp3
│       └── .swimsync_manifest.json
└── .swimsync_library.json            # Legacy compatibility pointer
```

### Device Structure (Flat - Real MP3s)

```
E:\ (or /Volumes/OPENSWIM)
├── .swimsync_device.json             # SwimSync marker file
├── Artist - Song 1.mp3               # Real files, not links
├── Artist - Song 2.mp3
└── ...
```

The device always contains real MP3 files (not symlinks) because:
1. Most MP3 players don't support symlinks
2. The device is removable storage
3. Tracks are copied during load/sync operations

---

## Part 2: Data Models

### Library Config (`.swimsync/library.json`)

```json
{
  "version": "2.0",
  "primary_playlist_id": "workout-mix",
  "playlists": [
    {
      "id": "workout-mix",
      "name": "Workout Mix",
      "spotify_url": "https://open.spotify.com/playlist/...",
      "folder_name": "workout-mix",
      "track_count": 45,
      "total_size_mb": 360,
      "unique_size_mb": 280,
      "last_sync": "2026-01-04T14:30:00",
      "created_at": "2026-01-01T10:00:00",
      "color": "#22c55e"
    }
  ],
  "device": {
    "name": "Shokz OpenSwim Pro",
    "capacity_gb": 32,
    "last_connected": "2026-01-04T15:00:00",
    "last_playlist_loaded": "workout-mix"
  },
  "storage_stats": {
    "total_tracks": 105,
    "unique_tracks": 85,
    "total_logical_size_mb": 840,
    "actual_storage_mb": 680,
    "dedup_savings_mb": 160,
    "dedup_savings_percent": 19.0
  }
}
```

### Storage Index (`.swimsync/storage/storage_index.json`)

```json
{
  "version": "1.0",
  "tracks": {
    "a1b2c3d4e5f6...": {
      "hash": "a1b2c3d4e5f6...",
      "filename": "a1b2c3d4e5f6.mp3",
      "original_name": "Artist - Song Title.mp3",
      "size_bytes": 8500000,
      "duration_ms": 210000,
      "artist": "Artist",
      "title": "Song Title",
      "album": "Album Name",
      "spotify_id": "4iV5W9uYEdYUVa79Axb7Rh",
      "downloaded_at": "2026-01-04T10:30:00",
      "reference_count": 2,
      "referenced_by": ["workout-mix", "chill-vibes"]
    }
  },
  "hash_by_spotify_id": {
    "4iV5W9uYEdYUVa79Axb7Rh": "a1b2c3d4e5f6..."
  },
  "hash_by_key": {
    "artist::song title": "a1b2c3d4e5f6..."
  }
}
```

### Playlist Manifest (`.swimsync_manifest.json`)

```json
{
  "version": "2.0",
  "playlist_id": "workout-mix",
  "playlist_url": "https://open.spotify.com/playlist/...",
  "playlist_name": "Workout Mix",
  "last_sync": "2026-01-04T14:30:00",
  "tracks": [
    {
      "spotify_id": "4iV5W9uYEdYUVa79Axb7Rh",
      "title": "Song Title",
      "artist": "Artist",
      "album": "Album Name",
      "filename": "Artist - Song Title.mp3",
      "storage_hash": "a1b2c3d4e5f6...",
      "file_size_mb": 8.5,
      "status": "downloaded"
    }
  ]
}
```

### Device Marker (`.swimsync_device.json`)

```json
{
  "swimsync_version": "2.0",
  "playlist_id": "workout-mix",
  "playlist_name": "Workout Mix",
  "loaded_at": "2026-01-04T14:30:00",
  "track_count": 45,
  "total_size_mb": 360,
  "tracks": [
    {"filename": "Artist - Song 1.mp3", "hash": "a1b2c3d4...", "size_mb": 8.2}
  ],
  "source_library": "C:\\Users\\John\\Music\\SwimSync"
}
```

---

## Part 3: Class Designs

### TrackStorage Class (Deduplication Engine)

```python
import hashlib
import os
import shutil
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Dict, List, Tuple
import json
import threading


@dataclass
class StoredTrack:
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
    referenced_by: List[str]


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
        self.library_path = Path(library_path)
        self.storage_path = self.library_path / self.STORAGE_DIR
        self.index_path = self.storage_path / self.INDEX_FILE
        self._lock = threading.Lock()
        self._index = self._load_index()

        # Ensure storage directory exists
        self.storage_path.mkdir(parents=True, exist_ok=True)

    def _load_index(self) -> Dict:
        """Load storage index from disk"""
        if self.index_path.exists():
            try:
                with open(self.index_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return self._default_index()
        return self._default_index()

    def _default_index(self) -> Dict:
        return {
            "version": "1.0",
            "tracks": {},
            "hash_by_spotify_id": {},
            "hash_by_key": {}
        }

    def _save_index(self):
        """Save storage index to disk"""
        with self._lock:
            self.storage_path.mkdir(parents=True, exist_ok=True)
            with open(self.index_path, 'w', encoding='utf-8') as f:
                json.dump(self._index, f, indent=2)

    def compute_hash(self, file_path: Path) -> str:
        """Compute content hash of a file"""
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
        Returns (hash, is_new) where is_new indicates if this was a new file.
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
                shutil.copy2(source_path, storage_file)
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
                    "downloaded_at": track_info.get("downloaded_at", ""),
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
        Returns True if the track file was deleted (no more references).
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
                    storage_file.unlink()

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
        """Get the path to a stored track file"""
        if content_hash in self._index["tracks"]:
            return self.storage_path / f"{content_hash}.mp3"
        return None

    def create_playlist_link(
        self,
        content_hash: str,
        playlist_folder: Path,
        display_name: str
    ) -> bool:
        """
        Create a symlink/hardlink in a playlist folder pointing to storage.
        Falls back to copy if links not supported.
        """
        source = self.get_storage_path(content_hash)
        if not source or not source.exists():
            return False

        target = playlist_folder / display_name
        playlist_folder.mkdir(parents=True, exist_ok=True)

        # Remove existing file/link if present
        if target.exists() or target.is_symlink():
            target.unlink()

        # Try symlink first (most space-efficient)
        try:
            target.symlink_to(source)
            return True
        except (OSError, NotImplementedError):
            pass

        # Try hardlink (works on same filesystem)
        try:
            os.link(source, target)
            return True
        except (OSError, NotImplementedError):
            pass

        # Fallback: copy the file (least efficient but always works)
        shutil.copy2(source, target)
        return True

    def find_by_spotify_id(self, spotify_id: str) -> Optional[str]:
        """Find a track hash by Spotify ID"""
        return self._index["hash_by_spotify_id"].get(spotify_id)

    def find_by_track_key(self, artist: str, title: str) -> Optional[str]:
        """Find a track hash by artist/title key"""
        key = f"{artist.lower().strip()}::{title.lower().strip()}"
        return self._index["hash_by_key"].get(key)

    def get_storage_stats(self) -> Dict:
        """Get deduplication statistics"""
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
            "actual_storage_mb": total_bytes / 1024 / 1024,
            "logical_size_mb": logical_bytes / 1024 / 1024,
            "savings_mb": savings_bytes / 1024 / 1024,
            "savings_percent": round(savings_percent, 1)
        }

    def _make_track_key(self, track_info: Dict) -> str:
        """Generate normalized track key for lookup"""
        artist = track_info.get("artist", "").lower().strip()
        title = track_info.get("title", "").lower().strip()
        return f"{artist}::{title}"
```

### DeviceDetector Class

```python
import os
import json
import psutil
import threading
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Callable, Literal
from datetime import datetime


@dataclass
class DeviceInfo:
    mount_path: Path
    label: str
    capacity_bytes: int
    used_bytes: int
    free_bytes: int
    playlist_id: Optional[str]
    playlist_name: Optional[str]
    track_count: Optional[int]
    is_swimsync_device: bool


@dataclass
class DeviceEvent:
    type: Literal["connected", "disconnected", "changed"]
    device: Optional[DeviceInfo]
    timestamp: datetime


class DeviceDetector:
    """Detects Shokz OpenSwim Pro connection via USB"""

    KNOWN_LABELS = ["OPENSWIM", "SWIM PRO", "SHOKZ", "OPENSWIM PRO"]
    MARKER_FILE = ".swimsync_device.json"
    POLL_INTERVAL = 2.0  # seconds

    def __init__(self):
        self._last_state: Optional[DeviceInfo] = None
        self._callbacks: List[Callable[[DeviceEvent], None]] = []
        self._monitoring = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def get_connected_device(self) -> Optional[DeviceInfo]:
        """Check if a Shokz device is currently connected"""
        for partition in psutil.disk_partitions(all=True):
            mount_path = Path(partition.mountpoint)

            # Skip non-removable drives
            if not self._is_removable(partition):
                continue

            # Method 1: Check for SwimSync marker file
            marker = mount_path / self.MARKER_FILE
            if marker.exists():
                return self._read_device_from_marker(mount_path, marker)

            # Method 2: Check volume label
            label = self._get_volume_label(partition)
            if any(known in label.upper() for known in self.KNOWN_LABELS):
                return self._create_device_info(mount_path, label)

        return None

    def _is_removable(self, partition) -> bool:
        """Check if drive is removable"""
        opts = partition.opts.lower() if partition.opts else ""
        if 'removable' in opts:
            return True

        # Windows-specific check
        if os.name == 'nt':
            try:
                import ctypes
                drive_type = ctypes.windll.kernel32.GetDriveTypeW(partition.mountpoint)
                return drive_type == 2  # DRIVE_REMOVABLE
            except Exception:
                pass

        return False

    def _get_volume_label(self, partition) -> str:
        """Get volume label for a partition"""
        if os.name == 'nt':
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                volume_name = ctypes.create_unicode_buffer(1024)
                kernel32.GetVolumeInformationW(
                    partition.mountpoint,
                    volume_name, 1024,
                    None, None, None, None, 0
                )
                return volume_name.value
            except Exception:
                pass

        return partition.device.split('/')[-1] if partition.device else ""

    def _read_device_from_marker(self, mount_path: Path, marker_path: Path) -> DeviceInfo:
        """Read device info from SwimSync marker file"""
        try:
            with open(marker_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            usage = psutil.disk_usage(str(mount_path))

            return DeviceInfo(
                mount_path=mount_path,
                label=data.get("playlist_name", "SwimSync Device"),
                capacity_bytes=usage.total,
                used_bytes=usage.used,
                free_bytes=usage.free,
                playlist_id=data.get("playlist_id"),
                playlist_name=data.get("playlist_name"),
                track_count=data.get("track_count"),
                is_swimsync_device=True
            )
        except (json.JSONDecodeError, IOError):
            return self._create_device_info(mount_path, "SwimSync Device")

    def _create_device_info(self, mount_path: Path, label: str) -> DeviceInfo:
        """Create DeviceInfo for a newly discovered device"""
        usage = psutil.disk_usage(str(mount_path))
        mp3_count = len(list(mount_path.glob("*.mp3")))

        return DeviceInfo(
            mount_path=mount_path,
            label=label,
            capacity_bytes=usage.total,
            used_bytes=usage.used,
            free_bytes=usage.free,
            playlist_id=None,
            playlist_name=None,
            track_count=mp3_count if mp3_count > 0 else None,
            is_swimsync_device=False
        )

    def start_monitoring(self, callback: Callable[[DeviceEvent], None]):
        """Start background thread to monitor device connections"""
        self._callbacks.append(callback)

        if not self._monitoring:
            self._monitoring = True
            self._stop_event.clear()
            self._monitor_thread = threading.Thread(
                target=self._monitor_loop,
                daemon=True
            )
            self._monitor_thread.start()

    def stop_monitoring(self):
        """Stop device monitoring"""
        self._monitoring = False
        self._stop_event.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)

    def _monitor_loop(self):
        """Background monitoring loop"""
        while not self._stop_event.is_set():
            current = self.get_connected_device()

            if current != self._last_state:
                event = self._create_event(current)
                for callback in self._callbacks:
                    try:
                        callback(event)
                    except Exception as e:
                        print(f"Device callback error: {e}")

                self._last_state = current

            self._stop_event.wait(self.POLL_INTERVAL)

    def _create_event(self, current: Optional[DeviceInfo]) -> DeviceEvent:
        """Create appropriate device event"""
        if self._last_state is None and current is not None:
            return DeviceEvent("connected", current, datetime.now())
        elif self._last_state is not None and current is None:
            return DeviceEvent("disconnected", None, datetime.now())
        else:
            return DeviceEvent("changed", current, datetime.now())
```

### DeviceSyncManager Class

```python
import shutil
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Callable, Dict
from datetime import datetime


@dataclass
class SyncResult:
    success: bool
    tracks_copied: int = 0
    tracks_removed: int = 0
    tracks_imported: int = 0
    total_size_mb: float = 0
    error: Optional[str] = None


@dataclass
class DeviceDiff:
    playlist_id: str
    playlist_name: str
    tracks_to_add: List[Dict]
    tracks_to_remove: List[str]
    tracks_in_sync: int
    device_only: List[str]
    library_only: List[Dict]


class DeviceSyncManager:
    """Handles all device sync operations with deduplication awareness"""

    def __init__(
        self,
        library_manager: 'LibraryManager',
        detector: DeviceDetector,
        track_storage: TrackStorage
    ):
        self.library = library_manager
        self.detector = detector
        self.storage = track_storage

    def load_playlist_to_device(
        self,
        playlist_id: str,
        progress_callback: Callable = None
    ) -> SyncResult:
        """
        Load a playlist from library to connected device.
        Copies actual MP3 files (not symlinks) to device.
        """
        device = self.detector.get_connected_device()
        if not device:
            return SyncResult(success=False, error="No device connected")

        playlist = self.library.get_playlist(playlist_id)
        if not playlist:
            return SyncResult(success=False, error=f"Playlist not found: {playlist_id}")

        # Check capacity
        required_bytes = playlist.total_size_mb * 1024 * 1024
        if required_bytes > device.free_bytes + device.used_bytes:
            return SyncResult(
                success=False,
                error=f"Insufficient space. Need {playlist.total_size_mb:.0f} MB"
            )

        # Clear existing tracks on device
        self._clear_device_tracks(device.mount_path)

        # Get tracks from storage and copy to device
        tracks = self.library.get_playlist_tracks(playlist_id)
        total_size = 0

        for i, track in enumerate(tracks):
            # Get actual file from deduplicated storage
            storage_path = self.storage.get_storage_path(track.storage_hash)
            if not storage_path or not storage_path.exists():
                continue

            # Copy real file to device (not symlink)
            dest_path = device.mount_path / track.filename
            shutil.copy2(storage_path, dest_path)
            total_size += storage_path.stat().st_size

            if progress_callback:
                progress_callback(
                    current=i + 1,
                    total=len(tracks),
                    track_name=track.title,
                    status="copying"
                )

        # Write device marker
        self._write_device_marker(device.mount_path, playlist, tracks)

        # Update library's primary playlist
        self.library.set_primary_playlist(playlist_id)

        return SyncResult(
            success=True,
            tracks_copied=len(tracks),
            total_size_mb=total_size / 1024 / 1024
        )

    def sync_device_changes(
        self,
        progress_callback: Callable = None
    ) -> SyncResult:
        """
        Sync changes between library and device for current playlist.
        Adds new tracks, removes deleted tracks.
        """
        device = self.detector.get_connected_device()
        if not device or not device.playlist_id:
            return SyncResult(success=False, error="No SwimSync device connected")

        playlist = self.library.get_playlist(device.playlist_id)
        if not playlist:
            return SyncResult(success=False, error="Playlist not found in library")

        # Get diff
        diff = self.get_device_diff()
        if not diff:
            return SyncResult(success=True)  # Already in sync

        # Add new tracks
        for track in diff.tracks_to_add:
            storage_path = self.storage.get_storage_path(track.storage_hash)
            if storage_path and storage_path.exists():
                dest = device.mount_path / track.filename
                shutil.copy2(storage_path, dest)

        # Remove deleted tracks
        for filename in diff.tracks_to_remove:
            file_path = device.mount_path / filename
            if file_path.exists():
                file_path.unlink()

        # Update marker
        tracks = self.library.get_playlist_tracks(device.playlist_id)
        self._write_device_marker(device.mount_path, playlist, tracks)

        return SyncResult(
            success=True,
            tracks_copied=len(diff.tracks_to_add),
            tracks_removed=len(diff.tracks_to_remove)
        )

    def offload_from_device(
        self,
        target_playlist_id: str = None,
        progress_callback: Callable = None
    ) -> SyncResult:
        """
        Import tracks from device that aren't in the library.
        Stores them in deduplicated storage.
        """
        device = self.detector.get_connected_device()
        if not device:
            return SyncResult(success=False, error="No device connected")

        # Determine target playlist
        if target_playlist_id:
            playlist = self.library.get_playlist(target_playlist_id)
        elif device.playlist_id:
            playlist = self.library.get_playlist(device.playlist_id)
        else:
            playlist = self.library.create_playlist(
                name="Imported from Device",
                spotify_url=""
            )

        # Find unknown tracks on device
        known_hashes = set()
        for track in self.library.get_playlist_tracks(playlist.id):
            known_hashes.add(track.storage_hash)

        imported = 0
        for mp3_file in device.mount_path.glob("*.mp3"):
            if mp3_file.name.startswith('.'):
                continue

            # Compute hash to check if we already have it
            file_hash = self.storage.compute_hash(mp3_file)
            if file_hash in known_hashes:
                continue

            # Parse track info from filename
            track_info = self._parse_filename(mp3_file.name)

            # Store in deduplicated storage
            content_hash, is_new = self.storage.store_track(
                mp3_file,
                track_info,
                playlist.id
            )

            # Add to playlist manifest
            self.library.add_track_to_playlist(playlist.id, track_info, content_hash)
            imported += 1

        return SyncResult(success=True, tracks_imported=imported)

    def clear_device(self) -> SyncResult:
        """Remove all tracks from device"""
        device = self.detector.get_connected_device()
        if not device:
            return SyncResult(success=False, error="No device connected")

        count = 0
        for mp3 in device.mount_path.glob("*.mp3"):
            mp3.unlink()
            count += 1

        # Remove marker
        marker = device.mount_path / DeviceDetector.MARKER_FILE
        if marker.exists():
            marker.unlink()

        return SyncResult(success=True, tracks_removed=count)

    def get_device_diff(self) -> Optional[DeviceDiff]:
        """Compare device contents with library playlist"""
        device = self.detector.get_connected_device()
        if not device or not device.playlist_id:
            return None

        playlist = self.library.get_playlist(device.playlist_id)
        if not playlist:
            return None

        # Build lookup maps
        library_tracks = {
            t.filename.lower(): t
            for t in self.library.get_playlist_tracks(device.playlist_id)
        }
        device_files = {
            f.name.lower(): f
            for f in device.mount_path.glob("*.mp3")
            if not f.name.startswith('.')
        }

        # Calculate diff
        to_add = [t for fn, t in library_tracks.items() if fn not in device_files]
        to_remove = [f.name for fn, f in device_files.items() if fn not in library_tracks]
        in_sync = sum(1 for fn in library_tracks if fn in device_files)

        return DeviceDiff(
            playlist_id=device.playlist_id,
            playlist_name=playlist.name,
            tracks_to_add=to_add,
            tracks_to_remove=to_remove,
            tracks_in_sync=in_sync,
            device_only=to_remove,
            library_only=to_add
        )

    def _clear_device_tracks(self, mount_path: Path):
        """Remove all MP3 files from device"""
        for mp3 in mount_path.glob("*.mp3"):
            mp3.unlink()

    def _write_device_marker(self, mount_path: Path, playlist, tracks):
        """Write SwimSync marker file to device"""
        marker_data = {
            "swimsync_version": "2.0",
            "playlist_id": playlist.id,
            "playlist_name": playlist.name,
            "loaded_at": datetime.now().isoformat(),
            "track_count": len(tracks),
            "total_size_mb": sum(t.file_size_mb for t in tracks),
            "tracks": [
                {"filename": t.filename, "hash": t.storage_hash, "size_mb": t.file_size_mb}
                for t in tracks
            ],
            "source_library": str(self.library.library_path)
        }

        marker_path = mount_path / DeviceDetector.MARKER_FILE
        with open(marker_path, 'w', encoding='utf-8') as f:
            json.dump(marker_data, f, indent=2)

    def _parse_filename(self, filename: str) -> Dict:
        """Parse track info from filename (Artist - Title.mp3)"""
        stem = Path(filename).stem
        if " - " in stem:
            parts = stem.split(" - ", 1)
            return {
                "artist": parts[0].strip(),
                "title": parts[1].strip(),
                "album": "",
                "spotify_id": ""
            }
        return {
            "artist": "Unknown",
            "title": stem,
            "album": "",
            "spotify_id": ""
        }
```

### LibraryManager Class

```python
from dataclasses import dataclass
from typing import List, Optional, Dict
from pathlib import Path
import json
import shutil
from datetime import datetime


@dataclass
class Playlist:
    id: str
    name: str
    spotify_url: str
    folder_name: str
    track_count: int
    total_size_mb: float
    unique_size_mb: float
    last_sync: str
    created_at: str
    color: str


@dataclass
class Track:
    spotify_id: str
    title: str
    artist: str
    album: str
    filename: str
    storage_hash: str
    file_size_mb: float
    status: str


class LibraryManager:
    """
    Manages multiple playlists with deduplicated storage.
    Handles playlist creation, track management, and library configuration.
    """

    LIBRARY_CONFIG = ".swimsync/library.json"
    PLAYLISTS_DIR = "playlists"

    def __init__(self, library_path: Path, track_storage: TrackStorage):
        self.library_path = Path(library_path)
        self.storage = track_storage
        self.config_path = self.library_path / self.LIBRARY_CONFIG
        self._config = self._load_config()

    def _load_config(self) -> Dict:
        """Load library configuration"""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return self._default_config()

    def _default_config(self) -> Dict:
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
        """Save library configuration"""
        self._config["storage_stats"] = self.storage.get_storage_stats()

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self._config, f, indent=2)

    def get_playlist(self, playlist_id: str) -> Optional[Playlist]:
        """Get a playlist by ID"""
        for p in self._config["playlists"]:
            if p["id"] == playlist_id:
                return Playlist(**p)
        return None

    def get_all_playlists(self) -> List[Playlist]:
        """Get all playlists"""
        return [Playlist(**p) for p in self._config["playlists"]]

    def create_playlist(
        self,
        name: str,
        spotify_url: str,
        color: str = "#3b82f6"
    ) -> Playlist:
        """Create a new playlist"""
        import re

        # Generate ID from name
        playlist_id = name.lower().replace(" ", "-").replace("'", "")
        playlist_id = ''.join(c for c in playlist_id if c.isalnum() or c == '-')

        # Ensure unique
        base_id = playlist_id
        counter = 1
        while any(p["id"] == playlist_id for p in self._config["playlists"]):
            playlist_id = f"{base_id}-{counter}"
            counter += 1

        playlist_data = {
            "id": playlist_id,
            "name": name,
            "spotify_url": spotify_url,
            "folder_name": playlist_id,
            "track_count": 0,
            "total_size_mb": 0,
            "unique_size_mb": 0,
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

        self._save_config()
        return Playlist(**playlist_data)

    def delete_playlist(self, playlist_id: str) -> bool:
        """Delete a playlist and remove its track references"""
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
            shutil.rmtree(folder)

        # Remove from config
        self._config["playlists"] = [
            p for p in self._config["playlists"] if p["id"] != playlist_id
        ]

        # Update primary if needed
        if self._config["primary_playlist_id"] == playlist_id:
            self._config["primary_playlist_id"] = None

        self._save_config()
        return True

    def get_playlist_tracks(self, playlist_id: str) -> List[Track]:
        """Get all tracks in a playlist"""
        playlist = self.get_playlist(playlist_id)
        if not playlist:
            return []

        manifest_path = (
            self.library_path / self.PLAYLISTS_DIR /
            playlist.folder_name / ".swimsync_manifest.json"
        )

        if not manifest_path.exists():
            return []

        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)

        return [Track(**t) for t in manifest.get("tracks", [])]

    def add_track_to_playlist(
        self,
        playlist_id: str,
        track_info: Dict,
        storage_hash: str
    ):
        """Add a track to a playlist (assumes already in storage)"""
        import re

        playlist = self.get_playlist(playlist_id)
        if not playlist:
            return

        manifest_path = (
            self.library_path / self.PLAYLISTS_DIR /
            playlist.folder_name / ".swimsync_manifest.json"
        )

        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)

        # Create display filename
        filename = f"{track_info['artist']} - {track_info['title']}.mp3"
        filename = self._sanitize_filename(filename)

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

    def set_primary_playlist(self, playlist_id: str):
        """Set the primary/active playlist"""
        self._config["primary_playlist_id"] = playlist_id
        self._save_config()

    def get_primary_playlist(self) -> Optional[Playlist]:
        """Get the primary playlist"""
        primary_id = self._config.get("primary_playlist_id")
        return self.get_playlist(primary_id) if primary_id else None

    def _update_playlist_stats(self, playlist_id: str):
        """Update playlist statistics in library config"""
        tracks = self.get_playlist_tracks(playlist_id)

        total_size = sum(t.file_size_mb for t in tracks)
        unique_hashes = set(t.storage_hash for t in tracks)
        unique_size = sum(
            self.storage._index["tracks"].get(h, {}).get("size_bytes", 0)
            for h in unique_hashes
        ) / 1024 / 1024

        for p in self._config["playlists"]:
            if p["id"] == playlist_id:
                p["track_count"] = len(tracks)
                p["total_size_mb"] = total_size
                p["unique_size_mb"] = unique_size
                break

        self._save_config()

    def _sanitize_filename(self, filename: str) -> str:
        """Remove invalid characters from filename"""
        import re
        filename = re.sub(r'[<>:"/\\|?*]', '', filename)
        filename = filename.replace('..', '')
        return filename.strip('. ')
```

---

## Part 4: API Endpoints

### Playlist Management

```
GET  /api/playlists                  # List all playlists
POST /api/playlists                  # Create new playlist
     Body: { "name": "...", "spotify_url": "..." }

GET  /api/playlists/{id}             # Get playlist details
DELETE /api/playlists/{id}           # Delete playlist

POST /api/playlists/{id}/sync        # Sync playlist with Spotify
GET  /api/playlists/{id}/tracks      # Get playlist tracks
```

### Device Management

```
GET  /api/device                     # Get device status
GET  /api/device/diff                # Compare device vs library
POST /api/device/load                # Load playlist to device
     Body: { "playlist_id": "..." }
POST /api/device/sync                # Sync changes to device
POST /api/device/offload             # Import from device
POST /api/device/clear               # Clear device
POST /api/device/eject               # Safely eject
```

### Storage Stats

```
GET  /api/storage                    # Get storage/dedup statistics
     Response: {
       "library": {
         "total_tracks": 105,
         "unique_tracks": 85,
         "total_size_mb": 840,
         "actual_size_mb": 680,
         "savings_mb": 160,
         "savings_percent": 19.0
       },
       "device": {
         "connected": true,
         "capacity_gb": 32,
         "used_gb": 0.35,
         "playlist_id": "workout-mix"
       }
     }
```

### WebSocket

```javascript
// Real-time device and sync events
const ws = new WebSocket('ws://localhost:5000/ws');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  switch (data.type) {
    case 'device_connected':
    case 'device_disconnected':
    case 'sync_progress':
    case 'storage_updated':
      // Handle events
  }
};
```

---

## Part 5: Implementation Phases

### Phase 1: Core Storage Engine
- [ ] Implement `TrackStorage` class with hash-based deduplication
- [ ] Add reference counting for shared tracks
- [ ] Implement symlink/hardlink/copy fallback chain
- [ ] Create storage index management

### Phase 2: Library Manager
- [ ] Implement `LibraryManager` class
- [ ] Add multi-playlist support
- [ ] Migrate from v1 single-playlist to v2 multi-playlist
- [ ] Update `StateManager` to work with new structure

### Phase 3: Device Detection
- [ ] Implement `DeviceDetector` class
- [ ] Add cross-platform removable drive detection
- [ ] Implement marker file reading/writing
- [ ] Add polling-based monitoring

### Phase 4: Device Sync
- [ ] Implement `DeviceSyncManager` class
- [ ] Load playlist to device (with real file copies)
- [ ] Sync changes
- [ ] Offload from device
- [ ] Clear device

### Phase 5: API Layer
- [ ] Add playlist management endpoints
- [ ] Add device endpoints
- [ ] Add storage stats endpoint
- [ ] Implement WebSocket for real-time updates

### Phase 6: UI Updates
- [ ] Add playlist sidebar/selector
- [ ] Add device status bar
- [ ] Add deduplication stats display
- [ ] Add load/sync confirmation modals

---

## Part 6: Key Integration Points

### Deduplication + Device Sync Flow

```
1. User downloads new track via spotDL
   |
   v
2. SyncEngine saves to temp location
   |
   v
3. TrackStorage.store_track():
   - Compute content hash
   - If hash exists: just add reference
   - If new: copy to .swimsync/storage/{hash}.mp3
   - Update reference count
   |
   v
4. LibraryManager.add_track_to_playlist():
   - Add to playlist manifest
   - Create symlink in playlist folder
   |
   v
5. When loading to device (DeviceSyncManager.load_playlist_to_device):
   - Get storage path from hash
   - Copy ACTUAL file (not symlink) to device
   - Device gets real MP3 files it can play
```

### Reference Counting Example

```
Playlist A: [Song1, Song2, Song3]
Playlist B: [Song2, Song3, Song4]

Storage:
- song1-hash.mp3  ref_count=1 (only Playlist A)
- song2-hash.mp3  ref_count=2 (Playlist A + B)
- song3-hash.mp3  ref_count=2 (Playlist A + B)
- song4-hash.mp3  ref_count=1 (only Playlist B)

Actual storage: 4 files
Logical files: 7 files
Savings: 43% (3 duplicate files avoided)

If Playlist A is deleted:
- song1-hash.mp3 deleted (ref_count=0)
- song2-hash.mp3 remains (ref_count=1, still used by B)
- song3-hash.mp3 remains (ref_count=1, still used by B)
```
