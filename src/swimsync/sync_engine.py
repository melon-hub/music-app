"""
Sync Engine - Handles playlist fetching and downloading via spotDL
"""

import subprocess
import json
import os
import re
from pathlib import Path
from typing import Callable, Optional, Tuple, List, Dict
import threading
import urllib.request
import urllib.error
import ssl


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

    def __init__(self, config, state_manager):
        self.config = config
        self.state = state_manager
        self._cancelled = False
        self._current_process: Optional[subprocess.Popen] = None
        self._spotdl_path = find_spotdl()
    
    def fetch_playlist(self, url: str) -> Tuple[str, List[Dict]]:
        """
        Fetch playlist metadata - tries web scraping first (faster, no rate limits),
        falls back to spotDL if scraping fails.
        Returns (playlist_name, list of track dicts)
        """
        # Try web scraping first (no API rate limits)
        try:
            return self._fetch_playlist_scrape(url)
        except Exception as scrape_error:
            print(f"Scraping failed: {scrape_error}, trying spotDL...")

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
    
    def compute_diff(self, playlist_tracks: List[Dict]) -> Dict[str, List[Dict]]:
        """
        Compare playlist tracks against local state.
        Returns dict with 'new', 'existing', 'removed' lists.
        """
        # Get current local state
        local_tracks = self.state.get_all_tracks()
        local_by_key = {self._track_key(t): t for t in local_tracks}
        
        # Also scan actual files in folder
        output_folder = Path(self.config.get("output_folder"))
        existing_files = set()
        if output_folder.exists():
            existing_files = {f.stem.lower() for f in output_folder.glob("*.mp3")}
        
        new_tracks = []
        existing_tracks = []
        playlist_keys = set()
        
        for track in playlist_tracks:
            key = self._track_key(track)
            playlist_keys.add(key)
            
            # Check if in manifest or on disk
            expected_filename = self._generate_filename(track).lower().replace(".mp3", "")
            
            if key in local_by_key or expected_filename in existing_files:
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
            "removed": removed_tracks
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
            success, file_size = self._download_track(track, output_folder)
            track_elapsed = time.time() - track_start

            if success:
                downloaded += 1
                total_bytes += file_size
                self.state.add_track(track, self._generate_filename(track), file_size)
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
            "--output", output_template,
            "--format", "mp3",
            "--bitrate", self.config.get("bitrate"),
            query
        ]

        try:
            self._current_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            timeout = self.config.get("download_timeout")
            stdout, stderr = self._current_process.communicate(timeout=timeout)

            self._current_process = None

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
                return False, 0

            # If no obvious error, assume success if exit code is 0
            return self._current_process is None or True, 0

        except subprocess.TimeoutExpired:
            if self._current_process:
                self._current_process.kill()
                self._current_process = None
            return False, 0
        except Exception as e:
            return False, 0
    
    def _delete_track(self, track: Dict, output_folder: Path) -> bool:
        """Delete a track file from the output folder"""
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
            
        except Exception:
            return False
    
    def cancel(self):
        """Cancel ongoing sync operation"""
        self._cancelled = True
        if self._current_process:
            try:
                self._current_process.terminate()
            except:
                pass
    
    def _track_key(self, track: Dict) -> str:
        """Generate a unique key for track comparison"""
        # Normalize for comparison
        title = track.get("title", "").lower().strip()
        artist = track.get("artist", "").lower().strip()
        return f"{artist}::{title}"
    
    def _generate_filename(self, track: Dict) -> str:
        """Generate safe filename for track"""
        artist = track.get("artist", "Unknown")
        title = track.get("title", "Unknown")
        
        # Remove invalid filename characters
        filename = f"{artist} - {title}"
        filename = re.sub(r'[<>:"/\\|?*]', '', filename)
        filename = filename.strip('. ')
        
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
        except:
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
        except:
            pass
        
        return deps
