# 🏊 Sync or Swim

A lightweight Windows app to sync Spotify playlists to your Shokz OpenSwim Pro (or any MP3 player with limited storage).

**Zero Spotify account risk** - Uses YouTube matching via spotDL, no direct Spotify downloads.

## Features

- 📋 Load any public Spotify playlist
- 🔍 Preview changes before syncing (new/existing/removed tracks)
- 📊 Storage gauge to monitor 32GB device limit
- 🗑️ Optional auto-cleanup of removed tracks
- 💾 State tracking to avoid re-downloading
- ⚡ Simple one-click sync
- 🌐 **NEW: Web UI** - Modern browser-based interface

## Requirements

Before running Sync or Swim, you need:

### 1. Python 3.11+

Download from [python.org](https://www.python.org/downloads/) or install via Windows Store.

Verify installation:
```cmd
python --version
```

### 2. FFmpeg

Required by spotDL for audio conversion.

**Option A: Chocolatey (recommended)**
```cmd
choco install ffmpeg
```

**Option B: Manual Install**
1. Download from [ffmpeg.org](https://ffmpeg.org/download.html)
2. Extract to `C:\ffmpeg`
3. Add `C:\ffmpeg\bin` to your system PATH

Verify installation:
```cmd
ffmpeg -version
```

### 3. spotDL

Install via pip:
```cmd
pip install spotdl
```

Verify installation:
```cmd
spotdl --version
```

## Installation

1. Clone or download this repository

2. Install Python dependencies:
```cmd
pip install -r requirements.txt
```

3. Run the app (choose one):

**Desktop GUI (Tkinter):**
```cmd
python run.py
```

**Web UI (Browser-based):**
```cmd
python run_web.py
```

Or use the batch launchers:
```cmd
scripts\SwimSync.bat      # Desktop GUI
scripts\SwimSyncWeb.bat   # Web UI
```

## User Interfaces

### Desktop GUI (Tkinter)
The original desktop application with a native Windows look and feel.

### Web UI (NEW)
A modern browser-based interface that runs on a local server.

**Features:**
- Clean, modern design with teal/navy color scheme
- Responsive layout that works on any screen size
- Real-time sync progress with circular progress indicator
- Settings page for configuration
- Keyboard shortcuts (Ctrl+S to sync, Escape to cancel)

**How to use:**
1. Run `python run_web.py` or `scripts\SwimSyncWeb.bat`
2. Your browser will automatically open to `http://localhost:5000`
3. Paste a Spotify playlist URL and click "Load Playlist"
4. Review the track list and click "Sync Now"

## Project Structure

```
swimsync/
├── src/swimsync/           # Main application package
│   ├── app.py              # Tkinter GUI
│   ├── web_app.py          # Flask Web UI server
│   ├── web/                # Web UI assets
│   │   ├── templates/      # HTML templates
│   │   └── static/         # CSS & JavaScript
│   ├── sync_engine.py      # spotDL integration
│   ├── state_manager.py    # Track manifest
│   └── config_manager.py   # Settings
├── scripts/                # Launcher scripts
├── docs/                   # Documentation (PRD)
├── tests/                  # Test suite
├── run.py                  # Desktop GUI launcher
├── run_web.py              # Web UI launcher
├── pyproject.toml          # Python package config
└── requirements.txt        # Dependencies
```

## Usage
### First Time Setup

1. **Paste your Spotify playlist URL**  
   Example: `https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M`
   
   ⚠️ The playlist must be **public** (not private/collaborative)

2. **Select an output folder**  
   Default: `C:\Users\[You]\Music\SwimSync`

3. **Click "Load Playlist"**  
   The app will fetch all track metadata

### Syncing

1. Review the track list:
   - 🟢 **New** - Will be downloaded
   - ⚪ **Exists** - Already on disk
   - 🔴 **Removed** - No longer in playlist
   - 🟠 **Suspect** - Possibly corrupt, will re-download

2. Check the **storage gauge** to ensure you won't exceed device capacity

3. Optionally check **"Delete removed tracks"** to clean up old files

4. Click **"Sync Now"**

5. Wait for downloads to complete (progress shown per-track)

### Transferring to Device

1. Connect your Shokz OpenSwim Pro via the magnetic USB cable
2. Open the device in File Explorer (appears as "SWIM PRO" or similar)
3. Drag all MP3 files from your sync folder to the device
4. Safely eject the device

## Settings

Access via the **Settings** button (Desktop) or Settings page (Web UI):

| Setting | Default | Description |
|---------|---------|-------------|
| Audio Bitrate | 320k | Download quality (128k/192k/256k/320k) |
| Storage Limit | 32 GB | Warning threshold for gauge |
| Download Timeout | 120s | Max time per track before retry |

## Troubleshooting

### "spotDL not found"
- Ensure spotDL is installed: `pip install spotdl`
- Check it's in PATH: `spotdl --version`
- Try reinstalling: `pip uninstall spotdl && pip install spotdl`

### "FFmpeg not found"
- Install FFmpeg and ensure it's in your system PATH
- Restart your terminal after installation

### "No tracks found in playlist"
- Ensure the playlist is **public** (check Spotify settings)
- The playlist URL should look like: `https://open.spotify.com/playlist/...`

### Download fails for specific tracks
- spotDL uses YouTube matching - some tracks may not have good matches
- Check the spotDL output for specific errors
- Try manually downloading problem tracks with: `spotdl "artist - title"`

### Mismatched tracks (wrong version downloaded)
- This happens occasionally with covers, remixes, or live versions
- Delete the wrong file and manually download the correct one
- Report consistent issues to the [spotDL GitHub](https://github.com/spotDL/spotify-downloader)

### Web UI not loading
- Ensure port 5000 is not in use by another application
- Try accessing `http://127.0.0.1:5000` directly
- Check the terminal for error messages

## How It Works

```
┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
│     Spotify     │──────▶│    Sync or Swim    │──────▶│  OpenSwim Pro   │
│  Public API     │ meta  │   (this app)    │ MP3s  │    (32GB)       │
│                 │ data  │                 │       │                 │
└─────────────────┘       └────────┬────────┘       └─────────────────┘
                                   │
                                   ▼
                          ┌─────────────────┐
                          │     spotDL      │
                          │  (YouTube DL)   │
                          └─────────────────┘
```

1. **Metadata Fetch**: Sync or Swim uses spotDL to read track info from Spotify's public API (no login needed)
2. **State Compare**: Local manifest tracks what's already downloaded
3. **Delta Preview**: Shows you exactly what will change
4. **Download**: spotDL finds matching audio on YouTube and converts to MP3
5. **Cleanup**: Optionally removes tracks no longer in playlist

Your Spotify account is never at risk because:
- No Spotify login/authentication is used
- Audio comes from YouTube, not Spotify servers
- Only public playlist metadata is accessed

## File Structure


```
~/Music/SwimSync/
├── Artist - Song 1.mp3
├── Artist - Song 2.mp3
├── ...
└── .swimsync_manifest.json   (hidden, tracks sync state)
```

## Building Standalone Executable

To create a single `.exe` file:

```cmd
pip install pyinstaller
pyinstaller --onefile --windowed --name "SwimSync" run.py
```

The executable will be in `dist/SwimSync.exe`

## License

MIT License - Free for personal use.

## Credits

- [spotDL](https://github.com/spotDL/spotify-downloader) - The engine behind the downloads
- [Tkinter](https://docs.python.org/3/library/tkinter.html) - Python's built-in GUI framework
- [Flask](https://flask.palletsprojects.com/) - Web UI framework
