"""
Swim Sync - V1 to V2 Migration
Handles migration from single-playlist (v1) to multi-playlist (v2) architecture.
"""

import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List

from swimsync.track_storage import TrackStorage
from swimsync.library_manager import LibraryManager


@dataclass
class MigrationResult:
    """Result of a migration operation."""
    success: bool
    tracks_migrated: int = 0
    playlists_created: int = 0
    error: Optional[str] = None
    warnings: List[str] = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


class V1toV2Migration:
    """
    Migrates from v1 (single manifest in output folder) to v2 (multi-playlist with dedup).

    V1 Structure:
        output_folder/
        ├── .swimsync_manifest.json  # Single manifest
        ├── Artist - Song 1.mp3
        └── Artist - Song 2.mp3

    V2 Structure:
        output_folder/
        ├── .swimsync/
        │   ├── library.json
        │   └── storage/
        │       ├── {hash1}.mp3
        │       ├── {hash2}.mp3
        │       └── storage_index.json
        ├── playlists/
        │   └── default/
        │       ├── Artist - Song 1.mp3  (symlink)
        │       ├── Artist - Song 2.mp3  (symlink)
        │       └── .swimsync_manifest.json
        └── .swimsync_manifest.v1.backup.json
    """

    V1_MANIFEST = ".swimsync_manifest.json"
    V1_BACKUP = ".swimsync_manifest.v1.backup.json"
    DEFAULT_PLAYLIST_ID = "default"
    DEFAULT_PLAYLIST_NAME = "My Music"

    def __init__(self, library_path: Path):
        """
        Initialize migration.

        Args:
            library_path: Path to the output folder (which will become the library)
        """
        self.library_path = Path(library_path)

    def detect_v1_manifest(self) -> bool:
        """
        Check if a v1 manifest exists and needs migration.

        Returns:
            True if v1 manifest exists and migration is needed
        """
        manifest_path = self.library_path / self.V1_MANIFEST

        if not manifest_path.exists():
            return False

        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # V1 has version "1.0" or no version field
                version = data.get("version", "1.0")
                return version.startswith("1.")
        except (json.JSONDecodeError, IOError):
            return False

    def is_already_migrated(self) -> bool:
        """
        Check if library is already in v2 format.

        Returns:
            True if v2 structure already exists
        """
        library_config = self.library_path / ".swimsync" / "library.json"
        return library_config.exists()

    def migrate(self, playlist_name: str = None) -> MigrationResult:
        """
        Perform the v1 to v2 migration.

        Args:
            playlist_name: Name for the migrated playlist (default: "My Music")

        Returns:
            MigrationResult with details
        """
        if self.is_already_migrated():
            return MigrationResult(
                success=True,
                error="Already migrated to v2"
            )

        if not self.detect_v1_manifest():
            # No v1 manifest - just initialize empty v2 structure
            return self._initialize_empty_v2()

        # Read v1 manifest
        v1_manifest = self._read_v1_manifest()
        if v1_manifest is None:
            return MigrationResult(
                success=False,
                error="Failed to read v1 manifest"
            )

        # Initialize v2 components
        storage = TrackStorage(self.library_path)
        library = LibraryManager(self.library_path, storage)

        # Create default playlist
        name = playlist_name or v1_manifest.get("playlist_name") or self.DEFAULT_PLAYLIST_NAME
        spotify_url = v1_manifest.get("playlist_url", "")

        playlist = library.create_playlist(
            name=name,
            spotify_url=spotify_url,
            color="#22c55e"  # Green for default
        )

        # Migrate tracks
        tracks_migrated = 0
        warnings = []

        for track_data in v1_manifest.get("tracks", []):
            result = self._migrate_track(track_data, storage, library, playlist.id)
            if result["success"]:
                tracks_migrated += 1
            else:
                warnings.append(result["warning"])

        # Backup v1 manifest
        self._backup_v1_manifest()

        # Clean up old MP3 files from root (they're now in storage)
        self._cleanup_migrated_files(v1_manifest.get("tracks", []))

        return MigrationResult(
            success=True,
            tracks_migrated=tracks_migrated,
            playlists_created=1,
            warnings=warnings
        )

    def _read_v1_manifest(self) -> Optional[Dict]:
        """Read v1 manifest file."""
        manifest_path = self.library_path / self.V1_MANIFEST
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logging.error(f"Failed to read v1 manifest: {e}")
            return None

    def _migrate_track(
        self,
        track_data: Dict,
        storage: TrackStorage,
        library: LibraryManager,
        playlist_id: str
    ) -> Dict:
        """
        Migrate a single track.

        Returns:
            Dict with "success" and optional "warning"
        """
        filename = track_data.get("filename", "")
        if not filename:
            return {
                "success": False,
                "warning": f"Track missing filename: {track_data.get('title', 'Unknown')}"
            }

        # Find the MP3 file
        mp3_path = self.library_path / filename

        if not mp3_path.exists():
            return {
                "success": False,
                "warning": f"MP3 file not found: {filename}"
            }

        # Store in deduplicated storage
        try:
            track_info = {
                "artist": track_data.get("artist", "Unknown"),
                "title": track_data.get("title", "Unknown"),
                "album": track_data.get("album", ""),
                "spotify_id": track_data.get("spotify_id", ""),
                "file_size_mb": track_data.get("file_size_mb", 0)
            }

            content_hash, is_new = storage.store_track(
                mp3_path,
                track_info,
                playlist_id
            )

            # Add to playlist
            library.add_track_to_playlist(playlist_id, track_info, content_hash)

            return {"success": True}

        except Exception as e:
            return {
                "success": False,
                "warning": f"Failed to migrate {filename}: {e}"
            }

    def _backup_v1_manifest(self):
        """Backup the v1 manifest file."""
        src = self.library_path / self.V1_MANIFEST
        dst = self.library_path / self.V1_BACKUP

        if src.exists():
            try:
                shutil.copy2(src, dst)
                src.unlink()  # Remove original after backup
                logging.info(f"Backed up v1 manifest to {dst}")
            except Exception as e:
                logging.warning(f"Failed to backup v1 manifest: {e}")

    def _cleanup_migrated_files(self, tracks: List[Dict]):
        """Remove MP3 files from root that are now in storage."""
        for track in tracks:
            filename = track.get("filename", "")
            if filename:
                mp3_path = self.library_path / filename
                if mp3_path.exists():
                    try:
                        mp3_path.unlink()
                        logging.debug(f"Removed migrated file: {filename}")
                    except Exception as e:
                        logging.warning(f"Failed to remove {filename}: {e}")

    def _initialize_empty_v2(self) -> MigrationResult:
        """Initialize an empty v2 library structure."""
        try:
            storage = TrackStorage(self.library_path)
            library = LibraryManager(self.library_path, storage)

            return MigrationResult(
                success=True,
                tracks_migrated=0,
                playlists_created=0
            )
        except Exception as e:
            return MigrationResult(
                success=False,
                error=f"Failed to initialize v2 structure: {e}"
            )


def run_migration_if_needed(library_path: Path) -> Optional[MigrationResult]:
    """
    Convenience function to run migration if needed.

    Args:
        library_path: Path to the library folder

    Returns:
        MigrationResult if migration was performed, None if not needed
    """
    migration = V1toV2Migration(library_path)

    if migration.is_already_migrated():
        logging.debug("Library already in v2 format")
        return None

    if migration.detect_v1_manifest():
        logging.info("V1 manifest detected, starting migration...")
        result = migration.migrate()
        if result.success:
            logging.info(f"Migration complete: {result.tracks_migrated} tracks migrated")
        else:
            logging.error(f"Migration failed: {result.error}")
        return result

    # No v1 manifest, initialize empty v2
    logging.debug("No v1 manifest found, initializing empty v2 library")
    return migration._initialize_empty_v2()


def repair_incomplete_migration(library_path: Path) -> MigrationResult:
    """
    Repair an incomplete migration by finding orphaned MP3 files in the root
    and adding them to storage and the primary playlist.

    Args:
        library_path: Path to the library folder

    Returns:
        MigrationResult with repair details
    """
    import re
    library_path = Path(library_path)

    # Must have v2 structure
    library_config = library_path / ".swimsync" / "library.json"
    if not library_config.exists():
        return MigrationResult(
            success=False,
            error="No v2 library found. Run migration first."
        )

    # Initialize v2 components
    storage = TrackStorage(library_path)
    library = LibraryManager(library_path, storage)

    # Get primary playlist
    primary = library.get_primary_playlist()
    if not primary:
        # Create default if none exists
        primary = library.create_playlist(
            name="My Music",
            spotify_url="",
            color="#22c55e"
        )

    playlist_id = primary.id

    # Find orphaned MP3 files in root (not symlinks, not in .swimsync)
    orphaned = []
    for mp3 in library_path.glob("*.mp3"):
        if mp3.is_symlink():
            continue
        orphaned.append(mp3)

    if not orphaned:
        return MigrationResult(
            success=True,
            tracks_migrated=0,
            warnings=["No orphaned MP3 files found"]
        )

    # Migrate each orphaned file
    tracks_migrated = 0
    warnings = []

    for mp3_path in orphaned:
        try:
            # Parse filename to get track info
            stem = mp3_path.stem
            if " - " in stem:
                parts = stem.split(" - ", 1)
                artist = parts[0].strip()
                title = parts[1].strip()
            else:
                artist = "Unknown"
                title = stem

            track_info = {
                "artist": artist,
                "title": title,
                "album": "",
                "spotify_id": "",
                "file_size_mb": mp3_path.stat().st_size / (1024 * 1024)
            }

            # Store in deduplicated storage
            content_hash, is_new = storage.store_track(
                mp3_path,
                track_info,
                playlist_id
            )

            if content_hash:
                # Add to playlist
                library.add_track_to_playlist(playlist_id, track_info, content_hash)

                # Create playlist link
                playlist_folder = library_path / "playlists" / playlist_id
                storage.create_playlist_link(
                    content_hash,
                    playlist_folder,
                    mp3_path.name
                )

                # Remove original file (now in storage)
                mp3_path.unlink()
                tracks_migrated += 1
                logging.info(f"Repaired: {mp3_path.name}")
            else:
                warnings.append(f"Failed to store: {mp3_path.name}")

        except Exception as e:
            warnings.append(f"Error migrating {mp3_path.name}: {e}")

    return MigrationResult(
        success=True,
        tracks_migrated=tracks_migrated,
        warnings=warnings
    )
