# Multi-Playlist Folder System Design

## Overview

This document outlines the architecture for supporting multiple playlists with a "primary playlist" concept, **automatic device detection**, and **bi-directional sync** between the library and Shokz OpenSwim Pro.

---

## Core Concept

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SwimSync Library                              │
├─────────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                  │
│  │  Workout    │  │   Chill     │  │  Running    │                  │
│  │  Playlist   │  │  Playlist   │  │  Playlist   │                  │
│  │  ★ PRIMARY  │  │             │  │             │                  │
│  │  45 tracks  │  │  32 tracks  │  │  28 tracks  │                  │
│  │  360 MB     │  │  256 MB     │  │  224 MB     │                  │
│  └─────────────┘  └─────────────┘  └─────────────┘                  │
│                         │                                            │
│                         ▼                                            │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │  🔌 DEVICE CONNECTED: Shokz OpenSwim Pro                      │  │
│  │  ════════════════════════════════════════════════════════════ │  │
│  │  Current: Workout Mix (45 tracks, 360 MB)                     │  │
│  │  [████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░] 360 MB / 32 GB   │  │
│  │                                                                │  │
│  │  [Load "Chill Vibes" to Device]  [Sync Changes]  [Eject]     │  │
│  └───────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Part 1: Folder Structure

### Library Structure
```
~/Music/SwimSync/
├── .swimsync_library.json          # Library-level config
├── playlists/
│   ├── workout-mix/
│   │   ├── Artist - Song 1.mp3
│   │   ├── Artist - Song 2.mp3
│   │   └── .swimsync_manifest.json
│   ├── chill-vibes/
│   │   ├── Artist - Song A.mp3
│   │   └── .swimsync_manifest.json
│   └── running-beats/
│       ├── Artist - Song X.mp3
│       └── .swimsync_manifest.json
└── .device_cache/                   # Cache of last known device state
    └── device_snapshot.json
```

### Device Structure (Shokz OpenSwim Pro)
```
E:\ (or /Volumes/OPENSWIM on Mac)
├── .swimsync_device.json           # SwimSync marker file
├── Artist - Song 1.mp3
├── Artist - Song 2.mp3
└── ... (flat structure, no subfolders)
```

The `.swimsync_device.json` marker file identifies which playlist is loaded:
```json
{
  "swimsync_version": "2.0",
  "playlist_id": "workout-mix",
  "playlist_name": "Workout Mix",
  "loaded_at": "2026-01-04T14:30:00",
  "track_count": 45,
  "total_size_mb": 360,
  "source_library": "C:\\Users\\John\\Music\\SwimSync"
}
```

---

## Part 2: Device Detection

### Detection Strategy

**Cross-platform approach using `psutil` + volume label/marker file:**

```python
import psutil
from pathlib import Path

class DeviceDetector:
    """Detects Shokz OpenSwim Pro connection"""
    
    # Known identifiers for Shokz devices
    KNOWN_LABELS = ["OPENSWIM", "SWIM PRO", "SHOKZ"]
    MARKER_FILE = ".swimsync_device.json"
    
    def __init__(self):
        self._last_state = None
        self._callbacks = []
    
    def get_connected_device(self) -> Optional[DeviceInfo]:
        """Check if a Shokz device is currently connected"""
        for partition in psutil.disk_partitions(all=True):
            # Check if removable
            if 'removable' not in partition.opts.lower() and \
               'cdrom' not in partition.opts.lower():
                # On Windows, check drive type
                if not self._is_removable(partition.mountpoint):
                    continue
            
            mount_path = Path(partition.mountpoint)
            
            # Method 1: Check for SwimSync marker file
            marker = mount_path / self.MARKER_FILE
            if marker.exists():
                return self._read_device_info(mount_path, marker)
            
            # Method 2: Check volume label
            label = self._get_volume_label(partition)
            if any(known in label.upper() for known in self.KNOWN_LABELS):
                return DeviceInfo(
                    mount_path=mount_path,
                    label=label,
                    capacity_bytes=self._get_capacity(mount_path),
                    used_bytes=self._get_used(mount_path),
                    playlist_id=None,  # Unknown - no marker
                    playlist_name=None
                )
        
        return None
    
    def start_monitoring(self, callback: Callable[[DeviceEvent], None]):
        """Start background thread to monitor device connections"""
        self._callbacks.append(callback)
        # Start polling thread (every 2 seconds)
        ...
    
    def _is_removable(self, path: str) -> bool:
        """Check if drive is removable (platform-specific)"""
        if os.name == 'nt':  # Windows
            import ctypes
            drive_type = ctypes.windll.kernel32.GetDriveTypeW(path)
            return drive_type == 2  # DRIVE_REMOVABLE
        else:  # Unix
            # Check /sys/block for removable flag
            ...
```

### Device Events

```python
@dataclass
class DeviceEvent:
    type: Literal["connected", "disconnected", "changed"]
    device: Optional[DeviceInfo]
    timestamp: datetime

@dataclass  
class DeviceInfo:
    mount_path: Path
    label: str
    capacity_bytes: int
    used_bytes: int
    free_bytes: int
    playlist_id: Optional[str]      # From marker file
    playlist_name: Optional[str]    # From marker file
    track_count: Optional[int]      # From marker file
    is_swimsync_device: bool        # Has marker file
```

### Polling vs Event-Based Detection

| Platform | Method | Library |
|----------|--------|---------|
| Windows | WMI events or polling | `wmi` or `psutil` |
| macOS | FSEvents or polling | `watchdog` or `psutil` |
| Linux | udev events or polling | `pyudev` or `psutil` |

**Recommendation**: Use polling (every 2 seconds) for simplicity and cross-platform consistency. Event-based can be added later as an optimization.

---

## Part 3: Device Sync Operations

### Sync Modes

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Device Sync Operations                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  1. LOAD PLAYLIST TO DEVICE                                         │
│     Library ──────────────────────────────────────▶ Device          │
│     "Put Chill Vibes on my Shokz"                                   │
│                                                                      │
│  2. SYNC CHANGES                                                    │
│     Library ◀─────────────────────────────────────▶ Device          │
│     "Update device with latest playlist changes"                    │
│                                                                      │
│  3. OFFLOAD FROM DEVICE                                             │
│     Library ◀────────────────────────────────────── Device          │
│     "Import tracks from device to library"                          │
│     (For tracks added directly to device)                           │
│                                                                      │
│  4. CLEAR DEVICE                                                    │
│     Device ──▶ 🗑️                                                   │
│     "Remove all tracks from device"                                 │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### DeviceSyncManager Class

```python
class DeviceSyncManager:
    """Handles all device sync operations"""
    
    def __init__(self, library: LibraryManager, detector: DeviceDetector):
        self.library = library
        self.detector = detector
    
    # === LOAD PLAYLIST TO DEVICE ===
    def load_playlist_to_device(
        self, 
        playlist_id: str,
        progress_callback: Callable = None
    ) -> SyncResult:
        """
        Load a playlist from library to connected device.
        Replaces all content on device with the selected playlist.
        """
        device = self.detector.get_connected_device()
        if not device:
            raise DeviceNotConnectedError()
        
        playlist = self.library.get_playlist(playlist_id)
        if not playlist:
            raise PlaylistNotFoundError(playlist_id)
        
        # Check capacity
        if playlist.total_size_mb * 1024 * 1024 > device.free_bytes + device.used_bytes:
            raise InsufficientSpaceError(
                required=playlist.total_size_mb,
                available=device.capacity_bytes / 1024 / 1024
            )
        
        # Clear device (except marker file)
        self._clear_device_tracks(device.mount_path)
        
        # Copy tracks
        tracks = self.library.get_playlist_tracks(playlist_id)
        for i, track in enumerate(tracks):
            src = playlist.folder_path / track.filename
            dst = device.mount_path / track.filename
            shutil.copy2(src, dst)
            
            if progress_callback:
                progress_callback(
                    current=i + 1,
                    total=len(tracks),
                    track_name=track.title,
                    status="copying"
                )
        
        # Write marker file
        self._write_device_marker(device.mount_path, playlist)
        
        # Update library's primary playlist
        self.library.set_primary_playlist(playlist_id)
        
        return SyncResult(
            success=True,
            tracks_copied=len(tracks),
            total_size_mb=playlist.total_size_mb
        )
    
    # === SYNC CHANGES ===
    def sync_device_changes(
        self,
        progress_callback: Callable = None
    ) -> SyncResult:
        """
        Sync changes between library and device for the current playlist.
        - Adds new tracks from library to device
        - Removes tracks from device that were removed from playlist
        - Does NOT modify library (one-way: library → device)
        """
        device = self.detector.get_connected_device()
        if not device or not device.playlist_id:
            raise DeviceNotConnectedError()
        
        playlist = self.library.get_playlist(device.playlist_id)
        
        # Get current state
        library_tracks = {t.filename.lower(): t for t in self.library.get_playlist_tracks(device.playlist_id)}
        device_tracks = {f.name.lower(): f for f in device.mount_path.glob("*.mp3")}
        
        # Calculate diff
        to_add = [t for fn, t in library_tracks.items() if fn not in device_tracks]
        to_remove = [f for fn, f in device_tracks.items() if fn not in library_tracks]
        
        # Apply changes
        for track in to_add:
            src = playlist.folder_path / track.filename
            dst = device.mount_path / track.filename
            shutil.copy2(src, dst)
        
        for file in to_remove:
            file.unlink()
        
        # Update marker
        self._write_device_marker(device.mount_path, playlist)
        
        return SyncResult(
            success=True,
            tracks_added=len(to_add),
            tracks_removed=len(to_remove)
        )
    
    # === OFFLOAD FROM DEVICE ===
    def offload_from_device(
        self,
        target_playlist_id: str = None,
        progress_callback: Callable = None
    ) -> SyncResult:
        """
        Import tracks from device that aren't in the library.
        Useful if user added tracks directly to device.
        """
        device = self.detector.get_connected_device()
        if not device:
            raise DeviceNotConnectedError()
        
        # Determine target playlist
        if target_playlist_id:
            playlist = self.library.get_playlist(target_playlist_id)
        elif device.playlist_id:
            playlist = self.library.get_playlist(device.playlist_id)
        else:
            # Create new playlist for orphan tracks
            playlist = self.library.add_playlist(
                name="Imported from Device",
                spotify_url=""
            )
        
        # Find tracks on device not in library playlist
        library_tracks = {t.filename.lower() for t in self.library.get_playlist_tracks(playlist.id)}
        device_files = list(device.mount_path.glob("*.mp3"))
        
        to_import = [f for f in device_files if f.name.lower() not in library_tracks]
        
        # Copy to library
        for file in to_import:
            dst = playlist.folder_path / file.name
            shutil.copy2(file, dst)
            
            # Add to manifest (parse filename for metadata)
            self.library.add_track_to_playlist(playlist.id, file.name)
        
        return SyncResult(
            success=True,
            tracks_imported=len(to_import)
        )
    
    # === CLEAR DEVICE ===
    def clear_device(self) -> SyncResult:
        """Remove all tracks from device"""
        device = self.detector.get_connected_device()
        if not device:
            raise DeviceNotConnectedError()
        
        count = 0
        for mp3 in device.mount_path.glob("*.mp3"):
            mp3.unlink()
            count += 1
        
        # Remove marker file
        marker = device.mount_path / ".swimsync_device.json"
        if marker.exists():
            marker.unlink()
        
        return SyncResult(success=True, tracks_removed=count)
    
    # === COMPARE DEVICE VS LIBRARY ===
    def get_device_diff(self) -> DeviceDiff:
        """
        Compare device contents with library playlist.
        Returns what would happen if sync is performed.
        """
        device = self.detector.get_connected_device()
        if not device or not device.playlist_id:
            return None
        
        playlist = self.library.get_playlist(device.playlist_id)
        
        library_tracks = {t.filename.lower(): t for t in self.library.get_playlist_tracks(device.playlist_id)}
        device_tracks = {f.name.lower(): f for f in device.mount_path.glob("*.mp3")}
        
        return DeviceDiff(
            playlist_id=device.playlist_id,
            playlist_name=playlist.name,
            tracks_to_add=[t for fn, t in library_tracks.items() if fn not in device_tracks],
            tracks_to_remove=[f.name for fn, f in device_tracks.items() if fn not in library_tracks],
            tracks_in_sync=[fn for fn in library_tracks if fn in device_tracks],
            device_only=[f.name for fn, f in device_tracks.items() if fn not in library_tracks],
            library_only=[t for fn, t in library_tracks.items() if fn not in device_tracks]
        )
```

---

## Part 4: API Endpoints

### Device Detection Endpoints

```
GET  /api/device                     # Get current device status
     Response: {
       "connected": true,
       "device": {
         "label": "OPENSWIM",
         "mount_path": "E:\\",
         "capacity_gb": 32,
         "used_gb": 0.35,
         "free_gb": 31.65,
         "playlist_id": "workout-mix",
         "playlist_name": "Workout Mix",
         "track_count": 45,
         "is_swimsync_device": true
       }
     }

GET  /api/device/diff                # Compare device vs library
     Response: {
       "playlist_id": "workout-mix",
       "tracks_to_add": [...],
       "tracks_to_remove": [...],
       "tracks_in_sync": 42,
       "device_only": ["Unknown Track.mp3"],
       "library_only": [...]
     }

POST /api/device/load                # Load playlist to device
     Body: { "playlist_id": "chill-vibes" }
     Response: { "success": true, "tracks_copied": 32 }

POST /api/device/sync                # Sync changes to device
     Response: { "success": true, "added": 3, "removed": 1 }

POST /api/device/offload             # Import from device to library
     Body: { "target_playlist_id": "workout-mix" }  // optional
     Response: { "success": true, "tracks_imported": 2 }

POST /api/device/clear               # Clear all tracks from device
     Response: { "success": true, "tracks_removed": 45 }

POST /api/device/eject               # Safely eject device
     Response: { "success": true }
```

### WebSocket for Real-time Updates

```javascript
// Client-side
const ws = new WebSocket('ws://localhost:5000/ws/device');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  
  switch (data.type) {
    case 'device_connected':
      showDevicePanel(data.device);
      break;
    case 'device_disconnected':
      hideDevicePanel();
      break;
    case 'sync_progress':
      updateProgressBar(data.current, data.total, data.track);
      break;
  }
};
```

---

## Part 5: UI Design

### Device Status Bar (Always Visible)

```
┌─────────────────────────────────────────────────────────────────────┐
│  🔌 Device: Shokz OpenSwim Pro                    [Eject Safely]   │
│  ────────────────────────────────────────────────────────────────── │
│  Current: Workout Mix (45 tracks)                                   │
│  Storage: [████████░░░░░░░░░░░░░░░░░░░░░░░░░░░░] 360 MB / 32 GB    │
└─────────────────────────────────────────────────────────────────────┘
```

When no device connected:
```
┌─────────────────────────────────────────────────────────────────────┐
│  ○ No device connected                                              │
│  Connect your Shokz OpenSwim Pro to manage music                    │
└─────────────────────────────────────────────────────────────────────┘
```

### Device Panel (Expanded View)

```
┌─────────────────────────────────────────────────────────────────────┐
│  🔌 DEVICE CONNECTED                                                │
│  ═══════════════════════════════════════════════════════════════════│
│                                                                      │
│  ┌─ Device Info ────────────────────────────────────────────────┐   │
│  │  Name:         Shokz OpenSwim Pro                            │   │
│  │  Mount:        E:\ (Windows) / /Volumes/OPENSWIM (Mac)       │   │
│  │  Capacity:     32 GB                                         │   │
│  │  Used:         360 MB (1.1%)                                 │   │
│  │  Free:         31.6 GB                                       │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌─ Current Playlist on Device ─────────────────────────────────┐   │
│  │  🎵 Workout Mix                                              │   │
│  │  45 tracks • 360 MB • Last synced: Today 2:30 PM            │   │
│  │                                                               │   │
│  │  Status: ✓ In sync with library                              │   │
│  │  (or)                                                         │   │
│  │  Status: ⚠ 3 tracks to add, 1 to remove                      │   │
│  │          [Sync Changes]                                       │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌─ Quick Actions ──────────────────────────────────────────────┐   │
│  │                                                               │   │
│  │  Load Different Playlist:                                     │   │
│  │  ┌──────────────────────────────────────────────────────┐    │   │
│  │  │  ▼ Select playlist...                                │    │   │
│  │  │    ○ Workout Mix (current)     45 tracks  360 MB     │    │   │
│  │  │    ○ Chill Vibes               32 tracks  256 MB     │    │   │
│  │  │    ○ Running Beats             28 tracks  224 MB     │    │   │
│  │  └──────────────────────────────────────────────────────┘    │   │
│  │                                                               │   │
│  │  [Load to Device]  [Sync Changes]  [Clear Device]            │   │
│  │                                                               │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌─ Advanced ───────────────────────────────────────────────────┐   │
│  │  [Import Tracks from Device]  (for manually added tracks)    │   │
│  │  [View Device Contents]       (file browser)                 │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Load Playlist Confirmation Modal

```
┌─────────────────────────────────────────────────────────────────────┐
│  📥 Load Playlist to Device                                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  You're about to load "Chill Vibes" to your Shokz OpenSwim Pro.    │
│                                                                      │
│  ┌─ What will happen ───────────────────────────────────────────┐   │
│  │  • Current content (Workout Mix) will be REPLACED            │   │
│  │  • 32 tracks (256 MB) will be copied to device               │   │
│  │  • Estimated time: ~2 minutes                                │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌─ Storage Impact ─────────────────────────────────────────────┐   │
│  │  Before:  [████████░░░░░░░░░░░░░░░░░░░░░░░░░░] 360 MB        │   │
│  │  After:   [██████░░░░░░░░░░░░░░░░░░░░░░░░░░░░] 256 MB        │   │
│  │  Change:  -104 MB (freeing space)                            │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ⚠️  Your Workout Mix playlist will remain in the library.          │
│     You can switch back anytime.                                    │
│                                                                      │
│                              [Cancel]  [Load to Device]             │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Sync Progress Modal

```
┌─────────────────────────────────────────────────────────────────────┐
│  📤 Loading to Device...                                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│                    ╭──────────────╮                                 │
│                   │     67%      │                                  │
│                    ╰──────────────╯                                 │
│                                                                      │
│  Track 22 of 32: "Artist - Song Name"                               │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Copied:      176 MB of 256 MB                               │   │
│  │  Speed:       12.4 MB/s                                      │   │
│  │  ETA:         ~6 seconds                                     │   │
│  │                                                               │   │
│  │  ✓ 21 copied  ⟳ 1 copying  ○ 10 pending                     │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│                              [Cancel]                               │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Device Diff View (Before Sync)

```
┌─────────────────────────────────────────────────────────────────────┐
│  🔄 Sync Preview: Workout Mix                                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Your library has changes that aren't on your device yet.           │
│                                                                      │
│  ┌─ Changes to Apply ───────────────────────────────────────────┐   │
│  │                                                               │   │
│  │  ● 3 tracks to ADD to device:                    +24 MB      │   │
│  │    + Artist - New Song 1.mp3                                 │   │
│  │    + Artist - New Song 2.mp3                                 │   │
│  │    + Artist - New Song 3.mp3                                 │   │
│  │                                                               │   │
│  │  ● 1 track to REMOVE from device:                -8 MB       │   │
│  │    - Artist - Old Song.mp3                                   │   │
│  │                                                               │   │
│  │  ● 41 tracks already in sync                     ✓           │   │
│  │                                                               │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌─ Storage Impact ─────────────────────────────────────────────┐   │
│  │  Current:  360 MB                                            │   │
│  │  After:    376 MB (+16 MB)                                   │   │
│  │  Free:     31.6 GB → 31.5 GB                                 │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                      │
│                              [Cancel]  [Apply Changes]              │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Part 6: Data Models (Complete)

### Library Config (`.swimsync_library.json`)

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
  "stats": {
    "total_tracks": 105,
    "total_size_mb": 840,
    "avg_track_size_mb": 8.0
  }
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
    {"filename": "Artist - Song 1.mp3", "size_mb": 8.2},
    {"filename": "Artist - Song 2.mp3", "size_mb": 7.8}
  ],
  "source_library": "C:\\Users\\John\\Music\\SwimSync"
}
```

---

## Part 7: Implementation Phases

### Phase 1: Core Library Manager
- [ ] Create `LibraryManager` class
- [ ] Implement migration from v1 to v2
- [ ] Update `StateManager` to work with playlist folders
- [ ] Add library-level config

### Phase 2: Device Detection
- [ ] Create `DeviceDetector` class
- [ ] Implement cross-platform removable drive detection
- [ ] Add marker file reading/writing
- [ ] Add polling-based monitoring

### Phase 3: Device Sync Operations
- [ ] Create `DeviceSyncManager` class
- [ ] Implement load playlist to device
- [ ] Implement sync changes
- [ ] Implement offload from device
- [ ] Implement clear device

### Phase 4: API Layer
- [ ] Add device detection endpoints
- [ ] Add device sync endpoints
- [ ] Add WebSocket for real-time device events
- [ ] Modify existing endpoints for multi-playlist

### Phase 5: UI Updates
- [ ] Add device status bar component
- [ ] Create device panel (expanded view)
- [ ] Add load/sync confirmation modals
- [ ] Add progress indicators
- [ ] Integrate with planned UI enhancements

### Phase 6: Polish
- [ ] Add safe eject functionality
- [ ] Add error handling and recovery
- [ ] Add device disconnect handling during sync
- [ ] Performance optimization for large playlists

---

## Part 8: Error Handling

### Device Errors

```python
class DeviceError(Exception):
    """Base class for device errors"""
    pass

class DeviceNotConnectedError(DeviceError):
    """No compatible device found"""
    message = "No Shokz device connected. Please connect your OpenSwim Pro."

class DeviceDisconnectedError(DeviceError):
    """Device was disconnected during operation"""
    message = "Device was disconnected. Please reconnect and try again."

class InsufficientSpaceError(DeviceError):
    """Not enough space on device"""
    def __init__(self, required_mb: float, available_mb: float):
        self.message = f"Not enough space. Need {required_mb:.0f} MB but only {available_mb:.0f} MB available."

class DeviceWriteError(DeviceError):
    """Failed to write to device"""
    message = "Failed to write to device. Check if device is write-protected."

class DeviceBusyError(DeviceError):
    """Device is being used by another process"""
    message = "Device is busy. Close any other applications using the device."
```

### Recovery Strategies

1. **Disconnect during copy**: 
   - Track progress in temp file
   - On reconnect, offer to resume or restart

2. **Partial sync failure**:
   - Keep track of successfully copied files
   - Offer to retry failed files only

3. **Corrupted marker file**:
   - Scan device for MP3s
   - Rebuild marker from actual contents
   - Mark as "Unknown Playlist" if can't match to library

---

## Part 9: Questions for Discussion

1. **Marker file visibility**: Should `.swimsync_device.json` be hidden?
   - Pro: Cleaner device view
   - Con: Some systems don't hide dotfiles

2. **Playlist switching speed**: When loading a new playlist:
   - **Option A**: Delete all, then copy all (slower, simpler)
   - **Option B**: Diff and only change what's needed (faster, complex)
   - **Option C**: User choice in settings

3. **Offline device info**: Cache device state when disconnected?
   - Show "Last seen: Workout Mix, 2 hours ago"

4. **Multiple devices**: Support more than one Shokz device?
   - Different family members, backup device, etc.

5. **Auto-sync on connect**: Should we auto-sync when device connects?
   - Or always require user confirmation?
