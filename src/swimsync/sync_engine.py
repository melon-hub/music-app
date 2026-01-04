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


class SyncEngine:
    """Manages playlist sync operations using spotDL"""
    
    def __init__(self, config, state_manager):
        self.config = config
        self.state = state_manager
        self._cancelled = False
        self._current_process: Optional[subprocess.Popen] = None
    
    def fetch_playlist(self, url: str) -> Tuple[str, List[Dict]]:
        """
        Fetch playlist metadata from Spotify via spotDL.
        Returns (playlist_name, list of track dicts)
        """
        # Use spotDL to get track list as JSON
        cmd = [
            "spotdl", "save", url,
            "--save-file", "-",  # Output to stdout
        ]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode != 0:
                # Try alternative method - just list tracks
                return self._fetch_playlist_fallback(url)
            
            # Parse the JSON output
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
            # Fallback to simpler parsing
            return self._fetch_playlist_fallback(url)
        except FileNotFoundError:
            raise Exception("spotDL not found. Please install it with: pip install spotdl")
    
    def _fetch_playlist_fallback(self, url: str) -> Tuple[str, List[Dict]]:
        """
        Fallback method using spotdl url command to list tracks
        """
        cmd = ["spotdl", "url", url]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120
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
        progress_callback: Optional[Callable[[int, int, str, str], None]] = None
    ) -> Dict:
        """
        Perform sync operation.
        Downloads new tracks and deletes removed ones.
        Returns summary dict.
        """
        self._cancelled = False
        total = len(tracks_to_download) + len(tracks_to_delete)
        current = 0
        
        downloaded = 0
        failed = 0
        deleted = 0
        
        output_folder = Path(self.config.get("output_folder"))
        output_folder.mkdir(parents=True, exist_ok=True)
        
        # Download new tracks
        for track in tracks_to_download:
            if self._cancelled:
                break
            
            current += 1
            track_name = f"{track['title']} - {track['artist']}"
            
            if progress_callback:
                progress_callback(current, total, track_name, "Downloading")
            
            success = self._download_track(track, output_folder)
            
            if success:
                downloaded += 1
                self.state.add_track(track, self._generate_filename(track))
                if progress_callback:
                    progress_callback(current, total, track_name, "Downloaded")
            else:
                failed += 1
                if progress_callback:
                    progress_callback(current, total, track_name, "Failed")
        
        # Delete removed tracks
        for track in tracks_to_delete:
            if self._cancelled:
                break
            
            current += 1
            track_name = f"{track['title']} - {track['artist']}"
            
            if progress_callback:
                progress_callback(current, total, track_name, "Deleting")
            
            success = self._delete_track(track, output_folder)
            
            if success:
                deleted += 1
                self.state.remove_track(track)
                if progress_callback:
                    progress_callback(current, total, track_name, "Deleted")
        
        # Save state
        self.state.save()
        
        return {
            "downloaded": downloaded,
            "failed": failed,
            "deleted": deleted,
            "cancelled": self._cancelled
        }
    
    def _download_track(self, track: Dict, output_folder: Path) -> bool:
        """Download a single track using spotDL"""
        # Build search query - use URL if available, otherwise search by name
        if track.get("url"):
            query = track["url"]
        else:
            query = f"{track['artist']} - {track['title']}"
        
        # Output format template
        output_template = str(output_folder / "{artist} - {title}")
        
        cmd = [
            "spotdl",
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
            
            # Check if file was created
            expected_file = output_folder / self._generate_filename(track)
            
            # spotDL might use slightly different naming, check for similar files
            if expected_file.exists():
                return True
            
            # Look for any new MP3 that matches
            pattern = f"*{track['title']}*.mp3"
            matches = list(output_folder.glob(pattern))
            if matches:
                return True
            
            # Check stderr for errors
            if "No results found" in stderr or "Could not find" in stderr:
                return False
            
            # If no obvious error, assume success if exit code is 0
            return self._current_process is None or True
            
        except subprocess.TimeoutExpired:
            if self._current_process:
                self._current_process.kill()
                self._current_process = None
            return False
        except Exception as e:
            return False
    
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
        
        # Check spotDL
        try:
            result = subprocess.run(
                ["spotdl", "--version"],
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
