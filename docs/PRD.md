# Swim Sync - Product Requirements Document

## Overview

**Product Name:** Swim Sync  
**Version:** 1.0  
**Author:** Hoff  
**Date:** January 2026  
**Platform:** Windows 11 (Desktop)

---

## 1. Problem Statement

The Shokz OpenSwim Pro is a bone-conduction headset designed for underwater use with 32GB of onboard storage. It has no Bluetooth streaming capability underwater and no native integration with streaming services. Users must manually transfer MP3 files via USB.

For users who maintain Spotify playlists, keeping the device in sync with their evolving music preferences requires:
- Manually identifying new/removed tracks
- Downloading new tracks individually
- Remembering to delete removed tracks
- Monitoring storage to avoid exceeding 32GB
- Repeating this tedious process whenever the playlist changes

This friction leads to stale music libraries on the device.

---

## 2. User Story

> *As a swimmer with a Shokz OpenSwim Pro, I want to keep my Spotify playlist synced to my device's storage as MP3 files, without manually re-downloading everything, creating duplicates, or exceeding capacity. I need visibility into what's changed (added/removed tracks) and one-click sync with safe cleanup of deleted items.*

---

## 3. Functional Requirements

### 3.1 Core Features (v1.0)

| ID | Feature | Description | Priority |
|----|---------|-------------|----------|
| F1 | Playlist Input | User enters a public Spotify playlist URL | Must Have |
| F2 | Metadata Fetch | Retrieve current playlist tracks via Spotify public API/spotDL | Must Have |
| F3 | Local State Tracking | Maintain record of downloaded files (JSON manifest) | Must Have |
| F4 | Delta Preview | Show comparison: New / Exists / Removed tracks before sync | Must Have |
| F5 | Download Engine | Invoke spotDL to download new/missing tracks as MP3 (256-320kbps) | Must Have |
| F6 | Cleanup Option | Delete local files no longer present in playlist | Must Have |
| F7 | Storage Monitoring | Display current folder size vs 32GB limit with visual gauge | Must Have |
| F8 | Progress Tracking | Real-time progress during download (per-track status) | Must Have |
| F9 | Output Folder Config | User-configurable destination folder | Must Have |
| F10 | Error Handling | Log failed downloads, allow retry | Must Have |

### 3.2 Future Features (v2.0+)

| ID | Feature | Description |
|----|---------|-------------|
| F11 | Multiple Playlists | Support syncing multiple playlists to subfolders |
| F12 | Podcast Support | Handle Spotify podcast episodes |
| F13 | Scheduled Sync | Optional background task to check for updates |
| F14 | Device Detection | Detect when OpenSwim Pro is connected via USB |
| F15 | Direct Transfer | Copy files directly to device after sync |

---

## 4. Technical Architecture

### 4.1 Technology Stack

| Component | Technology | Rationale |
|-----------|------------|-----------|
| Language | Python 3.11+ | Cross-platform, spotDL native |
| GUI Framework | Tkinter (ttk themed) | No external deps, ships with Python |
| Download Engine | spotDL (subprocess) | Mature, maintained, zero account risk |
| Audio Processing | FFmpeg | Required by spotDL for conversion |
| State Storage | JSON file | Simple, human-readable, portable |
| Packaging | PyInstaller | Single .exe for Windows distribution |

### 4.2 System Components

```
┌─────────────────────────────────────────────────────────────┐
│                      Swim Sync App                          │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   GUI       │  │   Sync      │  │   Storage           │  │
│  │   Layer     │◄─┤   Engine    │◄─┤   Manager           │  │
│  │  (Tkinter)  │  │             │  │                     │  │
│  └─────────────┘  └──────┬──────┘  └─────────────────────┘  │
│                          │                                   │
│                          ▼                                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   State     │  │   spotDL    │  │   Config            │  │
│  │   Manager   │  │   Wrapper   │  │   Manager           │  │
│  │  (JSON)     │  │ (subprocess)│  │                     │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │   Local File System   │
              │   (MP3 Output Folder) │
              └───────────────────────┘
```

### 4.3 Data Flow

1. **Load Playlist**: User pastes Spotify URL → spotDL fetches metadata → display track list
2. **Compare State**: Load local manifest → scan output folder → compute delta (new/existing/removed)
3. **Preview**: Display delta to user with estimated download size
4. **Sync**: 
   - Download new tracks via spotDL (with progress callbacks)
   - Update manifest with new entries
   - Optionally delete removed tracks
   - Update manifest to remove deleted entries
5. **Complete**: Display summary, update storage gauge

### 4.4 State Manifest Schema

```json
{
  "playlist_url": "https://open.spotify.com/playlist/...",
  "playlist_name": "Swimming Vibes",
  "last_sync": "2026-01-04T10:30:00Z",
  "output_folder": "C:/Users/Hoff/Music/SwimSync",
  "tracks": [
    {
      "spotify_id": "4iV5W9uYEdYUVa79Axb7Rh",
      "title": "Song Name",
      "artist": "Artist Name",
      "album": "Album Name",
      "filename": "Artist Name - Song Name.mp3",
      "file_size_mb": 8.2,
      "downloaded_at": "2026-01-04T10:30:00Z",
      "status": "downloaded"
    }
  ]
}
```

---

## 5. User Interface Design

### 5.1 Screen Flow

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│              │     │              │     │              │
│    Setup     │────►│   Preview    │────►│   Syncing    │
│              │     │              │     │              │
└──────────────┘     └──────────────┘     └──────────────┘
       │                    │                    │
       │                    │                    │
       ▼                    ▼                    ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  - URL input │     │  - Track list│     │  - Progress  │
│  - Folder    │     │  - Status    │     │  - Per-track │
│    picker    │     │    badges    │     │    status    │
│  - Load btn  │     │  - Size est  │     │  - Cancel    │
│              │     │  - Sync btn  │     │              │
└──────────────┘     └──────────────┘     └──────────────┘
                                                 │
                                                 ▼
                                          ┌──────────────┐
                                          │   Complete   │
                                          │  - Summary   │
                                          │  - Storage   │
                                          │    gauge     │
                                          └──────────────┘
```

### 5.2 Main Window Layout

```
╔══════════════════════════════════════════════════════════════╗
║  Swim Sync                                          [─][□][×] ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  Spotify Playlist URL:                                       ║
║  ┌────────────────────────────────────────────┐ ┌──────────┐ ║
║  │ https://open.spotify.com/playlist/...      │ │  Load    │ ║
║  └────────────────────────────────────────────┘ └──────────┘ ║
║                                                              ║
║  Output Folder:                                              ║
║  ┌────────────────────────────────────────────┐ ┌──────────┐ ║
║  │ C:\Users\Hoff\Music\SwimSync               │ │ Browse   │ ║
║  └────────────────────────────────────────────┘ └──────────┘ ║
║                                                              ║
║  ┌────────────────────────────────────────────────────────┐  ║
║  │ Track                      │ Artist       │ Status     │  ║
║  ├────────────────────────────┼──────────────┼────────────┤  ║
║  │ Blinding Lights            │ The Weeknd   │ ✓ Exists   │  ║
║  │ Levitating                 │ Dua Lipa     │ ● New      │  ║
║  │ Heat Waves                 │ Glass Animals│ ✓ Exists   │  ║
║  │ Old Song Removed           │ Old Artist   │ ✗ Removed  │  ║
║  │ ...                        │ ...          │ ...        │  ║
║  └────────────────────────────────────────────────────────┘  ║
║                                                              ║
║  Storage: ████████████░░░░░░░░░░░░░░░░░░  12.4 GB / 32 GB    ║
║                                                              ║
║  Summary: 45 tracks │ 3 new │ 1 removed │ ~24 MB to download ║
║                                                              ║
║  ┌────────────────┐  ┌────────────────┐  ☑ Delete removed    ║
║  │   Sync Now     │  │    Settings    │     tracks           ║
║  └────────────────┘  └────────────────┘                      ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

### 5.3 Sync Progress View

```
╔══════════════════════════════════════════════════════════════╗
║  Syncing...                                                  ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  Overall Progress:                                           ║
║  ████████████████░░░░░░░░░░░░░░░░░░░░░░  2 / 3 tracks        ║
║                                                              ║
║  ┌────────────────────────────────────────────────────────┐  ║
║  │ ✓  Blinding Lights - The Weeknd          Downloaded    │  ║
║  │ ✓  Levitating - Dua Lipa                 Downloaded    │  ║
║  │ ◐  Heat Waves - Glass Animals            Downloading...│  ║
║  └────────────────────────────────────────────────────────┘  ║
║                                                              ║
║  Current: Heat Waves - Glass Animals                         ║
║  ████████████████████░░░░░░░░░░░░░░░░░░  67%                 ║
║                                                              ║
║                                          ┌────────────────┐  ║
║                                          │     Cancel     │  ║
║                                          └────────────────┘  ║
╚══════════════════════════════════════════════════════════════╝
```

---

## 6. Edge Cases & Error Handling

| Scenario | Handling |
|----------|----------|
| Invalid playlist URL | Validate format, show error message |
| Private playlist | Detect and prompt user to make public |
| spotDL not installed | Check on startup, show install instructions |
| FFmpeg not installed | Check on startup, show install instructions |
| Download fails (network) | Mark as failed, allow retry, continue with others |
| Track mismatch (wrong version) | Log warning, allow manual skip/override |
| Storage would exceed 32GB | Warn before sync, block or partial sync option |
| Output folder doesn't exist | Create automatically with confirmation |
| Manifest corrupted | Rebuild from folder scan + Spotify metadata |
| spotDL process hangs | Timeout after configurable period, kill and retry |
| Duplicate filenames | Append number suffix (e.g., "Song (2).mp3") |

---

## 7. Configuration Options

| Setting | Default | Description |
|---------|---------|-------------|
| Output Folder | `~/Music/SwimSync` | Where MP3 files are saved |
| Audio Bitrate | 320kbps | Target bitrate for downloads |
| Audio Format | MP3 | Output format (MP3 recommended for device) |
| Auto-delete Removed | false | Automatically delete tracks removed from playlist |
| Storage Limit | 32 GB | Warning threshold for storage gauge |
| Download Timeout | 120 seconds | Max time per track before retry |
| Concurrent Downloads | 1 | Number of parallel downloads (1 = safest) |

---

## 8. Dependencies & Prerequisites

### 8.1 User Must Install

| Dependency | Installation | Verification |
|------------|--------------|--------------|
| Python 3.11+ | python.org or Windows Store | `python --version` |
| spotDL | `pip install spotdl` | `spotdl --version` |
| FFmpeg | Via chocolatey or manual | `ffmpeg -version` |

### 8.2 Python Packages

```
spotdl>=4.4.0
```

*Note: Tkinter ships with Python on Windows - no separate install needed.*

---

## 9. Success Metrics

| Metric | Target |
|--------|--------|
| Sync accuracy | 95%+ tracks download correctly on first attempt |
| False positives (wrong version) | <5% of tracks |
| Sync time (50 track playlist) | <10 minutes on reasonable connection |
| User actions to sync | 2 clicks (Load → Sync) |

---

## 10. Out of Scope (v1.0)

- Private playlist support (requires OAuth flow)
- Podcast episodes (different metadata structure)
- Multiple playlists in single session
- Scheduled/automatic background sync
- Direct USB transfer to device
- macOS/Linux builds (Windows only for v1)
- Album art embedding customisation
- Audio normalisation/loudness matching

---

## 11. Implementation Phases

### Phase 1: Core MVP (This Build)
- Single playlist URL input
- spotDL integration for downloads
- Basic state management (JSON manifest)
- Delta preview (new/existing/removed)
- Simple Tkinter GUI
- Storage gauge
- Delete removed tracks option

### Phase 2: Polish
- Better error handling and retry logic
- Settings persistence
- Improved progress tracking
- Mismatch detection and warnings

### Phase 3: Extended Features
- Multiple playlist support
- Podcast support
- Device detection
- Portable .exe build
- Web UI option (Express/Node.js alternative interface)

---

## 12. Open Questions

1. ~~Should we support private playlists?~~ → No, public only for v1 (simpler, no OAuth)
2. ~~YouTube matching vs direct Spotify?~~ → YouTube matching via spotDL (zero ban risk)
3. Should failed downloads block the sync or continue? → Continue, log failures
4. Folder structure: flat or artist/album subfolders? → Flat for v1 (device navigation is limited anyway)

---

## Appendix A: spotDL Command Reference

```bash
# Download entire playlist as MP3
spotdl --output "{artist} - {title}" --format mp3 --bitrate 320k "PLAYLIST_URL"

# Get playlist metadata only (for preview)
spotdl --print-tracks "PLAYLIST_URL"

# Download specific track
spotdl "TRACK_URL"
```

---

## Appendix B: File Naming Convention

Format: `{artist} - {title}.mp3`

Examples:
- `The Weeknd - Blinding Lights.mp3`
- `Dua Lipa - Levitating.mp3`
- `Glass Animals - Heat Waves.mp3`

This format is:
- Human-readable when browsing on device
- Sortable by artist
- Compatible with most file systems (no special characters)
