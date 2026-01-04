"""
Sync Engine - Handles playlist fetching and downloading via spotDL

Supports two modes:
- V1 mode: Downloads directly to output folder (backward compatible)
- V2 mode: Uses TrackStorage for content-addressed deduplication
"""

import subprocess
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Callable, Optional, Tuple, List, Dict, TYPE_CHECKING
import threading
import urllib.request
import urllib.error
import ssl

if TYPE_CHECKING:
    from swimsync.track_storage import TrackStorage
    from swimsync.library_manager import LibraryManager


def find_spotdl() -> str:
    """Find spotdl executable, checking common Python Scripts locations"""
    import shutil

    # First check if it's in PATH
    spotdl = shutil.which("spotdl")
    if spotdl:
        return spotdl

    # Check common Windows Python Scripts locations
    home = os.path.expanduser("~")
    possible_paths = [
        # User install locations
        os.path.join(home, "AppData", "Roaming", "Python", "Python313", "Scripts", "spotdl.exe"),
        os.path.join(home, "AppData", "Roaming", "Python", "Python312", "Scripts", "spotdl.exe"),
        os.path.join(home, "AppData", "Roaming", "Python", "Python311", "Scripts", "spotdl.exe"),
        os.path.join(home, "AppData", "Local", "Programs", "Python", "Python313", "Scripts", "spotdl.exe"),
        os.path.join(home, "AppData", "Local", "Programs", "Python", "Python312", "Scripts", "spotdl.exe"),
        os.path.join(home, "AppData", "Local", "Programs", "Python", "Python311", "Scripts", "spotdl.exe"),
        # System-wide install
        r"C:\Python313\Scripts\spotdl.exe",
        r"C:\Python312\Scripts\spotdl.exe",
        r"C:\Python311\Scripts\spotdl.exe",
    ]

    for path in possible_paths:
        if os.path.isfile(path):
            return path

    # Fallback to just "spotdl" and let it fail with a clear message
    return "spotdl"


class SyncEngine:
    """Manages playlist sync operations using spotDL"""

    def __init__(
        self,
        config,
        state_manager,
        track_storage: Optional["TrackStorage"] = None,
        library_manager: Optional["LibraryManager"] = None,
        playlist_id: Optional[str] = None
    ):
        """
        Initialize sync engine.

        Args:
            config: Configuration manager
            state_manager: State manager for tracking downloads
            track_storage: Optional TrackStorage for v2 deduplication
            library_manager: Optional LibraryManager for v2 multi-playlist
            playlist_id: Optional playlist ID for v2 mode
        """
        self.config = config
        self.state = state_manager
        self._lock = threading.Lock()  # Thread safety for shared state
        self._cancelled = False
        self._current_process: Optional[subprocess.Popen] = None
        self._spotdl_path = find_spotdl()

        # V2 storage components (optional)
        self._track_storage = track_storage
        self._library_manager = library_manager
        self._playlist_id = playlist_id

    @property
    def is_v2(self) -> bool:
        """Check if running in v2 mode with deduplication"""
        return self._track_storage is not None and self._playlist_id is not None
    
    def fetch_playlist(self, url: str) -> Tuple[str, List[Dict]]:
        """
        Fetch playlist metadata - tries web scraping first (faster, no rate limits),
        falls back to spotDL if scraping fails.
        Returns (playlist_name, list of track dicts)
        """
        # Try web scraping first (no API rate limits)
        # Intentionally catching all exceptions here - scraping can fail in many ways
        # (network, parsing, HTML structure changes) and we always want to fall back to spotDL
        try:
            return self._fetch_playlist_scrape(url)
        except (urllib.error.URLError, json.JSONDecodeError, ValueError, KeyError) as scrape_error:
            print(f"Scraping failed: {scrape_error}, trying spotDL...")
        except Exception as scrape_error:
            # Catch-all for unexpected errors during scraping (HTML parsing, etc.)
            print(f"Scraping failed unexpectedly: {type(scrape_error).__name__}: {scrape_error}, trying spotDL...")

        # Fall back to spotDL
        return self._fetch_playlist_spotdl(url)

    def _fetch_playlist_scrape(self, url: str) -> Tuple[str, List[Dict]]:
        """
        Fetch playlist by scraping Spotify's web page directly.
        Bypasses API rate limits entirely.
        """
        # Extract playlist ID from URL
        match = re.search(r'playlist/([a-zA-Z0-9]+)', url)
        if not match:
            raise Exception("Invalid playlist URL")

        playlist_id = match.group(1)
        embed_url = f"https://open.spotify.com/embed/playlist/{playlist_id}"

        # Fetch the embed page (lighter than full page)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

        req = urllib.request.Request(embed_url, headers=headers)
        # Create SSL context that doesn't verify certs (Windows compatibility)
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        try:
            with urllib.request.urlopen(req, timeout=30, context=ssl_context) as response:
                html = response.read().decode('utf-8')
        except urllib.error.URLError as e:
            raise Exception(f"Failed to fetch playlist page: {e}")

        # Extract JSON data from the page
        # Spotify embeds data in a <script id="__NEXT_DATA__"> tag
        json_match = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>([^<]+)</script>', html)

        if not json_match:
            # Try alternative: look for resource data in script
            json_match = re.search(r'"entity"\s*:\s*(\{[^}]+?"tracks"[^}]+\})', html)
            if not json_match:
                raise Exception("Could not parse playlist data from page")

        try:
            data = json.loads(json_match.group(1))
        except json.JSONDecodeError:
            raise Exception("Failed to parse playlist JSON")

        # Navigate the JSON structure to find tracks
        tracks = []
        playlist_name = "Spotify Playlist"

        # Try different JSON structures Spotify might use
        if "props" in data:
            # __NEXT_DATA__ structure
            page_props = data.get("props", {}).get("pageProps", {})
            state = page_props.get("state", {}).get("data", {}).get("entity", {})
            playlist_name = state.get("name", playlist_name)
            track_list = state.get("trackList", [])

            for item in track_list:
                track = item if isinstance(item, dict) else {}
                tracks.append({
                    "spotify_id": track.get("uri", "").split(":")[-1] if track.get("uri") else "",
                    "title": track.get("title", "Unknown"),
                    "artist": track.get("subtitle", "Unknown"),
                    "album": "",
                    "url": f"https://open.spotify.com/track/{track.get('uri', '').split(':')[-1]}" if track.get('uri') else "",
                    "duration": track.get("duration", 0),
                })

        if not tracks:
            raise Exception("No tracks found in playlist")

        return playlist_name, tracks

    def _fetch_playlist_spotdl(self, url: str) -> Tuple[str, List[Dict]]:
        """
        Fetch playlist metadata via spotDL (fallback method).
        """
        cmd = [
            self._spotdl_path, "save", url,
            "--save-file", "-",
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=180
            )

            if result.returncode != 0:
                return self._fetch_playlist_fallback(url)

            data = json.loads(result.stdout)

            playlist_name = data.get("name", "Unknown Playlist")
            tracks = []

            for track in data.get("songs", []):
                tracks.append({
                    "spotify_id": track.get("song_id", ""),
                    "title": track.get("name", "Unknown"),
                    "artist": ", ".join(track.get("artists", ["Unknown"])),
                    "album": track.get("album_name", ""),
                    "url": track.get("url", ""),
                    "duration": track.get("duration", 0),
                })

            return playlist_name, tracks

        except subprocess.TimeoutExpired:
            raise Exception("Timeout fetching playlist. Check your connection.")
        except json.JSONDecodeError:
            return self._fetch_playlist_fallback(url)
        except FileNotFoundError:
            raise Exception("spotDL not found. Please install it with: pip install spotdl")
    
    def _fetch_playlist_fallback(self, url: str) -> Tuple[str, List[Dict]]:
        """
        Fallback method using spotdl url command to list tracks
        """
        cmd = [self._spotdl_path, "url", url]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=180  # 3 min to allow for Spotify rate limit retries
            )
            
            # Parse output - spotDL prints track info line by line
            tracks = []
            lines = result.stdout.strip().split("\n")
            
            # Try to extract playlist name from first line or URL
            playlist_name = "Spotify Playlist"
            
            for line in lines:
                # spotDL output format: "Artist - Title"
                line = line.strip()
                if not line or line.startswith(("Processing", "Found", "Downloading", "[", "Error")):
                    continue
                
                # Parse "Artist - Title" format
                if " - " in line:
                    parts = line.split(" - ", 1)
                    artist = parts[0].strip()
                    title = parts[1].strip() if len(parts) > 1 else "Unknown"
                else:
                    artist = "Unknown"
                    title = line
                
                tracks.append({
                    "spotify_id": "",  # Not available in fallback
                    "title": title,
                    "artist": artist,
                    "album": "",
                    "url": "",
                    "duration": 0,
                })
            
            if not tracks:
                raise Exception("No tracks found in playlist. Is the playlist public?")
            
            return playlist_name, tracks
            
        except subprocess.TimeoutExpired:
            raise Exception("Timeout fetching playlist.")
    
    # Minimum file size to consider valid (100KB - smaller likely corrupt/incomplete)
    MIN_VALID_FILE_SIZE = 100 * 1024  # 100KB in bytes

    def compute_diff(self, playlist_tracks: List[Dict]) -> Dict[str, List[Dict]]:
        """
        Compare playlist tracks against local state.
        Returns dict with 'new', 'existing', 'removed', 'suspect' lists.
        'suspect' contains tracks with files that appear corrupt (too small).
        """
        # First, sync manifest with actual files to remove stale entries
        # This prevents "ghost" removed tracks from accumulating
        self.state.sync_with_folder()
        self.state.save()

        # Refresh playlist stats in library (updates sidebar count)
        if self._library_manager and self._playlist_id:
            self._library_manager.refresh_playlist_stats(self._playlist_id)

        # Get current local state (now cleaned up)
        local_tracks = self.state.get_all_tracks()
        local_by_key = {self._track_key(t): t for t in local_tracks}

        # Scan actual files in folder with sizes
        # In v2 mode, scan the playlist folder; in v1 mode, scan output folder
        output_folder = Path(self.config.get("output_folder"))
        if self.is_v2 and self._playlist_id:
            scan_folder = output_folder / "playlists" / self._playlist_id
        else:
            scan_folder = output_folder

        existing_files = {}  # filename_stem -> file_size
        if scan_folder.exists():
            for f in scan_folder.glob("*.mp3"):
                # Handle both real files and symlinks
                try:
                    existing_files[f.stem.lower()] = f.stat().st_size
                except OSError:
                    # Broken symlink or inaccessible file
                    pass

        new_tracks = []
        existing_tracks = []
        suspect_tracks = []  # Potentially corrupt files
        playlist_keys = set()

        for track in playlist_tracks:
            key = self._track_key(track)
            playlist_keys.add(key)

            # First check if track exists in manifest (by key which uses spotify_id)
            manifest_entry = local_by_key.get(key)

            if manifest_entry:
                # Track is in manifest - check if the manifest's filename exists on disk
                manifest_filename = manifest_entry.get("filename", "").lower().replace(".mp3", "")
                file_size = existing_files.get(manifest_filename, 0)

                if file_size > 0:
                    # File exists - check if it's potentially corrupt (too small)
                    if file_size < self.MIN_VALID_FILE_SIZE:
                        track["_suspect_reason"] = f"File too small ({file_size // 1024}KB)"
                        suspect_tracks.append(track)
                    else:
                        existing_tracks.append(track)
                else:
                    # In manifest but file missing - needs re-download
                    track["_suspect_reason"] = "File missing from disk"
                    suspect_tracks.append(track)
            else:
                # Not in manifest - check if file exists by expected filename
                expected_filename = self._generate_filename(track).lower().replace(".mp3", "")
                file_size = existing_files.get(expected_filename, 0)

                if file_size > 0:
                    # File exists but not in manifest - treat as existing
                    if file_size < self.MIN_VALID_FILE_SIZE:
                        track["_suspect_reason"] = f"File too small ({file_size // 1024}KB)"
                        suspect_tracks.append(track)
                    else:
                        existing_tracks.append(track)
                else:
                    new_tracks.append(track)

        # Find removed tracks (in local state but not in playlist)
        removed_tracks = []
        for track in local_tracks:
            key = self._track_key(track)
            if key not in playlist_keys:
                removed_tracks.append(track)

        return {
            "new": new_tracks,
            "existing": existing_tracks,
            "removed": removed_tracks,
            "suspect": suspect_tracks
        }
    
    def sync(
        self,
        tracks_to_download: List[Dict],
        tracks_to_delete: List[Dict],
        progress_callback: Optional[Callable[[int, int, str, str, dict], None]] = None
    ) -> Dict:
        """
        Perform sync operation.
        Downloads new tracks and deletes removed ones.
        Progress callback receives: (current, total, track_name, status, extra_info)
        extra_info dict contains: file_size_mb, speed_mbps, elapsed_seconds
        Returns summary dict.
        """
        import time

        self._cancelled = False
        total = len(tracks_to_download) + len(tracks_to_delete)
        current = 0

        downloaded = 0
        failed = 0
        deleted = 0
        total_bytes = 0
        sync_start_time = time.time()

        output_folder = Path(self.config.get("output_folder"))
        output_folder.mkdir(parents=True, exist_ok=True)

        # Download new tracks
        for track in tracks_to_download:
            if self._cancelled:
                break

            current += 1
            track_name = f"{track['title']} - {track['artist']}"

            # If this is a suspect/corrupt file, delete it first so spotDL will re-download
            if track.get("_suspect_reason"):
                self._delete_track(track, output_folder)
                self.state.remove_track(track)

            if progress_callback:
                elapsed = time.time() - sync_start_time
                speed = (total_bytes / 1024 / 1024) / elapsed if elapsed > 0 else 0
                progress_callback(current, total, track_name, "Downloading", {
                    "file_size_mb": 0,
                    "speed_mbps": speed,
                    "elapsed_seconds": elapsed,
                    "total_bytes": total_bytes
                })

            track_start = time.time()

            # V2 mode: download to temp, store in content-addressed storage
            if self.is_v2:
                success, file_size, storage_hash = self._download_track_v2(track)
            else:
                # V1 mode: download directly to output folder
                success, file_size = self._download_track(track, output_folder)
                storage_hash = None

            track_elapsed = time.time() - track_start

            if success:
                downloaded += 1
                total_bytes += file_size
                self.state.add_track(
                    track,
                    self._generate_filename(track),
                    file_size,
                    storage_hash=storage_hash
                )
                self.state.save()  # Save after each track for crash recovery
                if progress_callback:
                    elapsed = time.time() - sync_start_time
                    speed = (total_bytes / 1024 / 1024) / elapsed if elapsed > 0 else 0
                    progress_callback(current, total, track_name, "Downloaded", {
                        "file_size_mb": file_size / 1024 / 1024,
                        "speed_mbps": speed,
                        "elapsed_seconds": elapsed,
                        "track_time": track_elapsed,
                        "total_bytes": total_bytes
                    })
            else:
                failed += 1
                if progress_callback:
                    elapsed = time.time() - sync_start_time
                    progress_callback(current, total, track_name, "Failed", {
                        "file_size_mb": 0,
                        "speed_mbps": 0,
                        "elapsed_seconds": elapsed
                    })
        
        # Delete removed tracks
        for track in tracks_to_delete:
            if self._cancelled:
                break

            current += 1
            track_name = f"{track['title']} - {track['artist']}"

            if progress_callback:
                elapsed = time.time() - sync_start_time
                progress_callback(current, total, track_name, "Deleting", {
                    "elapsed_seconds": elapsed
                })

            # V2 mode: remove reference from storage
            if self.is_v2:
                success = self._delete_track_v2(track)
            else:
                success = self._delete_track(track, output_folder)

            if success:
                deleted += 1
                self.state.remove_track(track)
                if progress_callback:
                    elapsed = time.time() - sync_start_time
                    progress_callback(current, total, track_name, "Deleted", {
                        "elapsed_seconds": elapsed
                    })
        
        # Save state
        self.state.save()
        
        return {
            "downloaded": downloaded,
            "failed": failed,
            "deleted": deleted,
            "cancelled": self._cancelled
        }
    
    def _download_track(self, track: Dict, output_folder: Path) -> Tuple[bool, int]:
        """Download a single track using spotDL. Returns (success, file_size_bytes)"""
        # Build search query - use URL if available, otherwise search by name
        if track.get("url"):
            query = track["url"]
        else:
            query = f"{track['artist']} - {track['title']}"

        # Output format template
        output_template = str(output_folder / "{artist} - {title}")

        cmd = [
            self._spotdl_path,
            "download",
            query,
            "--output", output_template,
            "--format", "mp3",
            "--bitrate", self.config.get("bitrate"),
        ]

        try:
            # Log the command being run
            print(f"[spotDL] Running: {' '.join(cmd)}")

            self._current_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            timeout = self.config.get("download_timeout")
            stdout, stderr = self._current_process.communicate(timeout=timeout)

            self._current_process = None

            # Log spotDL output for debugging
            if stdout.strip():
                print(f"[spotDL stdout] {stdout.strip()}")
            if stderr.strip():
                print(f"[spotDL stderr] {stderr.strip()}")

            # Check if file was created and get size
            expected_file = output_folder / self._generate_filename(track)

            # spotDL might use slightly different naming, check for similar files
            if expected_file.exists():
                return True, expected_file.stat().st_size

            # Look for any new MP3 that matches
            pattern = f"*{track['title']}*.mp3"
            matches = list(output_folder.glob(pattern))
            if matches:
                return True, matches[0].stat().st_size

            # Check stderr for errors
            if "No results found" in stderr or "Could not find" in stderr:
                print(f"Download failed for '{track.get('title')}': No matching audio found")
                return False, 0

            # No file found - download likely failed
            print(f"Download failed for '{track.get('title')}': File not created")
            return False, 0

        except subprocess.TimeoutExpired:
            if self._current_process:
                self._current_process.kill()
                self._current_process = None
            print(f"Download timeout for '{track.get('title')}'")
            return False, 0
        except FileNotFoundError:
            print(f"spotDL not found at {self._spotdl_path}")
            return False, 0
        except PermissionError as e:
            print(f"Permission denied for '{track.get('title')}': {e}")
            return False, 0
        except OSError as e:
            print(f"OS error downloading '{track.get('title')}': {e}")
            return False, 0
        except Exception as e:
            print(f"Unexpected error downloading '{track.get('title')}': {type(e).__name__}: {e}")
            return False, 0

    def _download_track_v2(self, track: Dict) -> Tuple[bool, int, Optional[str]]:
        """
        Download track using v2 storage system.
        Downloads to temp file, stores in content-addressed storage, creates playlist link.
        Returns (success, file_size_bytes, storage_hash)
        """
        if not self._track_storage or not self._playlist_id:
            print("V2 storage not configured")
            return False, 0, None

        # First check if track already exists in storage (deduplication)
        existing_hash = self._track_storage.find_by_track_key(
            track.get("artist", ""),
            track.get("title", "")
        )

        if existing_hash:
            # Track already in storage, just create playlist link
            display_name = self._generate_filename(track)
            playlist_folder = Path(self.config.get("output_folder")) / "playlists" / self._playlist_id

            success = self._track_storage.create_playlist_link(
                existing_hash,
                playlist_folder,
                display_name
            )

            if success:
                storage_path = self._track_storage.get_storage_path(existing_hash)
                file_size = storage_path.stat().st_size if storage_path and storage_path.exists() else 0
                print(f"[V2] Reusing existing track: {track.get('title')} (deduplicated)")
                return True, file_size, existing_hash
            else:
                print(f"[V2] Failed to create link for existing track: {track.get('title')}")

        # Download to temp directory
        temp_dir = tempfile.mkdtemp(prefix="swimsync_")
        temp_output = Path(temp_dir) / "{artist} - {title}"

        cmd = [
            self._spotdl_path,
            "download",
            track.get("url") or f"{track['artist']} - {track['title']}",
            "--output", str(temp_output),
            "--format", "mp3",
            "--bitrate", self.config.get("bitrate"),
        ]

        try:
            print(f"[spotDL V2] Running: {' '.join(cmd)}")

            self._current_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            timeout = self.config.get("download_timeout")
            stdout, stderr = self._current_process.communicate(timeout=timeout)
            self._current_process = None

            if stdout.strip():
                print(f"[spotDL stdout] {stdout.strip()}")
            if stderr.strip():
                print(f"[spotDL stderr] {stderr.strip()}")

            # Find downloaded file
            downloaded_file = None
            for mp3 in Path(temp_dir).glob("*.mp3"):
                downloaded_file = mp3
                break

            if not downloaded_file or not downloaded_file.exists():
                if "No results found" in stderr or "Could not find" in stderr:
                    print(f"[V2] Download failed: No matching audio found")
                else:
                    print(f"[V2] Download failed: File not created")
                return False, 0, None

            file_size = downloaded_file.stat().st_size
            if file_size < self.MIN_VALID_FILE_SIZE:
                print(f"[V2] Download failed: File too small ({file_size} bytes)")
                return False, 0, None

            # Store in content-addressed storage
            content_hash, is_new = self._track_storage.store_track(
                downloaded_file,
                track,
                self._playlist_id
            )

            if not content_hash:
                print(f"[V2] Failed to store track in storage")
                return False, 0, None

            # Create playlist link
            display_name = self._generate_filename(track)
            playlist_folder = Path(self.config.get("output_folder")) / "playlists" / self._playlist_id

            success = self._track_storage.create_playlist_link(
                content_hash,
                playlist_folder,
                display_name
            )

            if success:
                status = "new" if is_new else "deduplicated"
                print(f"[V2] Track stored ({status}): {track.get('title')}")
                return True, file_size, content_hash
            else:
                print(f"[V2] Failed to create playlist link")
                return False, 0, None

        except subprocess.TimeoutExpired:
            if self._current_process:
                self._current_process.kill()
                self._current_process = None
            print(f"[V2] Download timeout for '{track.get('title')}'")
            return False, 0, None
        except FileNotFoundError:
            print(f"[V2] spotDL not found at {self._spotdl_path}")
            return False, 0, None
        except PermissionError as e:
            print(f"[V2] Permission denied for '{track.get('title')}': {e}")
            return False, 0, None
        except OSError as e:
            print(f"[V2] OS error downloading '{track.get('title')}': {e}")
            return False, 0, None
        except (ValueError, KeyError) as e:
            print(f"[V2] Data error for '{track.get('title')}': {e}")
            return False, 0, None
        finally:
            # Clean up temp directory
            import shutil
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass

    def _delete_track_v2(self, track: Dict) -> bool:
        """
        Delete track using v2 storage system.
        Removes playlist link and decrements reference count.
        Only deletes the actual file if no other playlists reference it.
        """
        if not self._track_storage or not self._playlist_id:
            print("[V2] Storage not configured for delete")
            return False

        # Get storage hash from track info
        storage_hash = track.get("storage_hash")

        if not storage_hash:
            # Try to find by track key
            storage_hash = self._track_storage.find_by_track_key(
                track.get("artist", ""),
                track.get("title", "")
            )

        if not storage_hash:
            print(f"[V2] No storage hash found for '{track.get('title')}'")
            # Still try to remove playlist link by filename
            playlist_folder = Path(self.config.get("output_folder")) / "playlists" / self._playlist_id
            link_path = playlist_folder / self._generate_filename(track)
            if link_path.exists():
                try:
                    link_path.unlink()
                    return True
                except OSError:
                    pass
            return False

        # Remove reference from storage (may delete file if last reference)
        file_deleted = self._track_storage.remove_reference(storage_hash, self._playlist_id)

        # Remove playlist link
        playlist_folder = Path(self.config.get("output_folder")) / "playlists" / self._playlist_id
        link_path = playlist_folder / self._generate_filename(track)

        try:
            if link_path.exists() or link_path.is_symlink():
                link_path.unlink()
                if file_deleted:
                    print(f"[V2] Deleted track and storage: {track.get('title')}")
                else:
                    print(f"[V2] Removed playlist link (file still referenced): {track.get('title')}")
                return True
        except OSError as e:
            print(f"[V2] Failed to remove playlist link: {e}")

        return file_deleted

    def _delete_track(self, track: Dict, output_folder: Path) -> bool:
        """Delete a track file from the output folder (v1 mode)"""
        filename = self._generate_filename(track)
        filepath = output_folder / filename
        
        try:
            if filepath.exists():
                filepath.unlink()
                return True

            # Try to find by partial match
            pattern = f"*{track['title']}*"
            for match in output_folder.glob(pattern):
                if match.is_file() and match.suffix.lower() == ".mp3":
                    match.unlink()
                    return True

            return False  # File not found

        except PermissionError as e:
            print(f"Cannot delete '{filename}': file may be in use or read-only: {e}")
            return False
        except OSError as e:
            print(f"File system error deleting '{filename}': {e}")
            return False
    
    def cancel(self):
        """Cancel ongoing sync operation. Thread-safe."""
        with self._lock:
            self._cancelled = True
            if self._current_process:
                try:
                    self._current_process.terminate()
                except ProcessLookupError:
                    pass  # Process already terminated
                except OSError as e:
                    print(f"Warning: Could not terminate download process: {e}")
    
    def _normalize_text(self, text: str) -> str:
        """Normalize text by replacing unicode whitespace with regular spaces."""
        import unicodedata
        # Replace non-breaking spaces and other unicode whitespace with regular space
        text = text.replace('\xa0', ' ')  # Non-breaking space
        text = text.replace('\u200b', '')  # Zero-width space
        text = text.replace('\u2009', ' ')  # Thin space
        text = text.replace('\u202f', ' ')  # Narrow no-break space
        # Normalize unicode to NFC form for consistent comparison
        text = unicodedata.normalize('NFC', text)
        return text

    def _track_key(self, track: Dict) -> str:
        """Generate a unique key for track comparison.

        Uses spotify_id as primary key when available (most reliable).
        Falls back to normalized first_artist::title for matching.
        """
        # Prefer spotify_id when available - most reliable identifier
        spotify_id = track.get("spotify_id", "").strip()
        if spotify_id:
            return f"spotify::{spotify_id}"

        # Fall back to artist::title with normalization
        title = self._normalize_text(track.get("title", "")).lower().strip()
        artist = self._normalize_text(track.get("artist", "")).lower().strip()

        # Use only first artist for matching (handles "Artist1, Artist2" variations)
        first_artist = artist.split(',')[0].strip()

        return f"{first_artist}::{title}"

    def _generate_filename(self, track: Dict) -> str:
        """Generate safe filename for track"""
        artist = self._normalize_text(track.get("artist", "Unknown"))
        title = self._normalize_text(track.get("title", "Unknown"))

        # Remove invalid filename characters
        filename = f"{artist} - {title}"
        filename = re.sub(r'[<>:"/\\|?*]', '', filename)
        filename = filename.replace('..', '')  # Prevent path traversal
        filename = filename.strip('. ')

        # Ensure we have a valid filename
        if not filename or filename in (".", ".."):
            filename = "Unknown Track"

        return f"{filename}.mp3"
    
    @staticmethod
    def check_dependencies() -> Dict[str, bool]:
        """Check if required dependencies are installed"""
        deps = {
            "spotdl": False,
            "ffmpeg": False
        }

        # Check spotDL (using smart path finder)
        spotdl_path = find_spotdl()
        try:
            result = subprocess.run(
                [spotdl_path, "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            deps["spotdl"] = result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass

        # Check FFmpeg
        try:
            result = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            deps["ffmpeg"] = result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass
        
        return deps
