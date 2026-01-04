"""
Unit tests for TrackStorage class.
"""

import pytest
import tempfile
import threading
from pathlib import Path

from swimsync.track_storage import TrackStorage


@pytest.fixture
def temp_library():
    """Create a temporary library directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def storage(temp_library):
    """Create a TrackStorage instance for testing."""
    return TrackStorage(temp_library)


@pytest.fixture
def sample_mp3(temp_library):
    """Create a sample MP3 file for testing."""
    mp3_path = temp_library / "test_track.mp3"
    # Create a fake MP3 file with some content
    mp3_path.write_bytes(b"ID3" + b"\x00" * 100 + b"fake mp3 content " * 100)
    return mp3_path


@pytest.fixture
def sample_track_info():
    """Sample track metadata."""
    return {
        "artist": "Test Artist",
        "title": "Test Song",
        "album": "Test Album",
        "spotify_id": "spotify123"
    }


class TestComputeHash:
    """Tests for hash computation."""

    def test_compute_hash_consistent(self, storage, sample_mp3):
        """Same file should always produce the same hash."""
        hash1 = storage.compute_hash(sample_mp3)
        hash2 = storage.compute_hash(sample_mp3)
        assert hash1 == hash2

    def test_compute_hash_length(self, storage, sample_mp3):
        """Hash should be truncated to 16 characters."""
        content_hash = storage.compute_hash(sample_mp3)
        assert len(content_hash) == 16

    def test_compute_hash_different_content(self, storage, temp_library):
        """Different content should produce different hashes."""
        file1 = temp_library / "file1.mp3"
        file2 = temp_library / "file2.mp3"
        file1.write_bytes(b"content 1")
        file2.write_bytes(b"content 2")

        hash1 = storage.compute_hash(file1)
        hash2 = storage.compute_hash(file2)
        assert hash1 != hash2


class TestStoreTrack:
    """Tests for storing tracks."""

    def test_store_new_track(self, storage, sample_mp3, sample_track_info):
        """Storing a new track should copy it to storage."""
        content_hash, is_new = storage.store_track(
            sample_mp3, sample_track_info, "playlist-1"
        )

        assert is_new is True
        assert len(content_hash) == 16

        # Verify file exists in storage
        storage_path = storage.get_storage_path(content_hash)
        assert storage_path is not None
        assert storage_path.exists()

    def test_store_duplicate_track(self, storage, sample_mp3, sample_track_info):
        """Storing the same track again should not create a new file."""
        hash1, is_new1 = storage.store_track(
            sample_mp3, sample_track_info, "playlist-1"
        )
        hash2, is_new2 = storage.store_track(
            sample_mp3, sample_track_info, "playlist-2"
        )

        assert hash1 == hash2
        assert is_new1 is True
        assert is_new2 is False

    def test_store_track_updates_reference_count(
        self, storage, sample_mp3, sample_track_info
    ):
        """Storing same track in multiple playlists should update ref count."""
        content_hash, _ = storage.store_track(
            sample_mp3, sample_track_info, "playlist-1"
        )
        storage.store_track(sample_mp3, sample_track_info, "playlist-2")

        track_info = storage.get_track_info(content_hash)
        assert track_info["reference_count"] == 2
        assert "playlist-1" in track_info["referenced_by"]
        assert "playlist-2" in track_info["referenced_by"]

    def test_store_same_playlist_twice_no_duplicate_ref(
        self, storage, sample_mp3, sample_track_info
    ):
        """Storing same track in same playlist twice shouldn't duplicate ref."""
        content_hash, _ = storage.store_track(
            sample_mp3, sample_track_info, "playlist-1"
        )
        storage.store_track(sample_mp3, sample_track_info, "playlist-1")

        track_info = storage.get_track_info(content_hash)
        assert track_info["reference_count"] == 1
        assert track_info["referenced_by"].count("playlist-1") == 1


class TestRemoveReference:
    """Tests for removing references."""

    def test_remove_reference_decrements_count(
        self, storage, sample_mp3, sample_track_info
    ):
        """Removing a reference should decrement the count."""
        content_hash, _ = storage.store_track(
            sample_mp3, sample_track_info, "playlist-1"
        )
        storage.store_track(sample_mp3, sample_track_info, "playlist-2")

        deleted = storage.remove_reference(content_hash, "playlist-1")
        assert deleted is False  # Still has one reference

        track_info = storage.get_track_info(content_hash)
        assert track_info["reference_count"] == 1
        assert "playlist-1" not in track_info["referenced_by"]
        assert "playlist-2" in track_info["referenced_by"]

    def test_remove_last_reference_deletes_file(
        self, storage, sample_mp3, sample_track_info
    ):
        """Removing the last reference should delete the file."""
        content_hash, _ = storage.store_track(
            sample_mp3, sample_track_info, "playlist-1"
        )
        storage_path = storage.get_storage_path(content_hash)
        assert storage_path.exists()

        deleted = storage.remove_reference(content_hash, "playlist-1")
        assert deleted is True
        assert not storage_path.exists()

        # Track should be removed from index
        assert storage.get_track_info(content_hash) is None

    def test_remove_nonexistent_reference(self, storage, sample_mp3, sample_track_info):
        """Removing a non-existent reference should not error."""
        content_hash, _ = storage.store_track(
            sample_mp3, sample_track_info, "playlist-1"
        )
        deleted = storage.remove_reference(content_hash, "playlist-nonexistent")
        assert deleted is False

    def test_remove_reference_invalid_hash(self, storage):
        """Removing reference with invalid hash should return False."""
        deleted = storage.remove_reference("invalid-hash", "playlist-1")
        assert deleted is False


class TestPlaylistLinks:
    """Tests for creating playlist links."""

    def test_create_playlist_link(self, storage, sample_mp3, sample_track_info, temp_library):
        """Should create a link in the playlist folder."""
        content_hash, _ = storage.store_track(
            sample_mp3, sample_track_info, "playlist-1"
        )

        playlist_folder = temp_library / "playlists" / "my-playlist"
        success = storage.create_playlist_link(
            content_hash, playlist_folder, "Artist - Song.mp3"
        )

        assert success is True
        link_path = playlist_folder / "Artist - Song.mp3"
        assert link_path.exists()

        # Content should be same as original
        storage_content = storage.get_storage_path(content_hash).read_bytes()
        link_content = link_path.read_bytes()
        assert storage_content == link_content

    def test_create_link_replaces_existing(
        self, storage, sample_mp3, sample_track_info, temp_library
    ):
        """Should replace existing file at link location."""
        content_hash, _ = storage.store_track(
            sample_mp3, sample_track_info, "playlist-1"
        )

        playlist_folder = temp_library / "playlists" / "my-playlist"
        playlist_folder.mkdir(parents=True)

        # Create existing file
        existing = playlist_folder / "Artist - Song.mp3"
        existing.write_bytes(b"old content")

        success = storage.create_playlist_link(
            content_hash, playlist_folder, "Artist - Song.mp3"
        )

        assert success is True
        # Should have new content, not old
        assert existing.read_bytes() != b"old content"

    def test_create_link_invalid_hash(self, storage, temp_library):
        """Should return False for invalid hash."""
        playlist_folder = temp_library / "playlists" / "my-playlist"
        success = storage.create_playlist_link(
            "invalid-hash", playlist_folder, "test.mp3"
        )
        assert success is False


class TestLookup:
    """Tests for track lookup methods."""

    def test_find_by_spotify_id(self, storage, sample_mp3, sample_track_info):
        """Should find track by Spotify ID."""
        content_hash, _ = storage.store_track(
            sample_mp3, sample_track_info, "playlist-1"
        )

        found_hash = storage.find_by_spotify_id("spotify123")
        assert found_hash == content_hash

    def test_find_by_spotify_id_not_found(self, storage):
        """Should return None for unknown Spotify ID."""
        found_hash = storage.find_by_spotify_id("unknown")
        assert found_hash is None

    def test_find_by_track_key(self, storage, sample_mp3, sample_track_info):
        """Should find track by artist/title key."""
        content_hash, _ = storage.store_track(
            sample_mp3, sample_track_info, "playlist-1"
        )

        found_hash = storage.find_by_track_key("Test Artist", "Test Song")
        assert found_hash == content_hash

    def test_find_by_track_key_case_insensitive(
        self, storage, sample_mp3, sample_track_info
    ):
        """Track key lookup should be case-insensitive."""
        content_hash, _ = storage.store_track(
            sample_mp3, sample_track_info, "playlist-1"
        )

        found_hash = storage.find_by_track_key("TEST ARTIST", "TEST SONG")
        assert found_hash == content_hash


class TestStorageStats:
    """Tests for storage statistics."""

    def test_storage_stats_empty(self, storage):
        """Empty storage should have zero stats."""
        stats = storage.get_storage_stats()
        assert stats["unique_tracks"] == 0
        assert stats["total_references"] == 0
        assert stats["savings_percent"] == 0

    def test_storage_stats_single_track(
        self, storage, sample_mp3, sample_track_info
    ):
        """Single track should show no savings."""
        storage.store_track(sample_mp3, sample_track_info, "playlist-1")

        stats = storage.get_storage_stats()
        assert stats["unique_tracks"] == 1
        assert stats["total_references"] == 1
        assert stats["savings_percent"] == 0

    def test_storage_stats_dedup_savings(
        self, storage, sample_mp3, sample_track_info
    ):
        """Shared track should show space savings."""
        storage.store_track(sample_mp3, sample_track_info, "playlist-1")
        storage.store_track(sample_mp3, sample_track_info, "playlist-2")
        storage.store_track(sample_mp3, sample_track_info, "playlist-3")

        stats = storage.get_storage_stats()
        assert stats["unique_tracks"] == 1
        assert stats["total_references"] == 3
        # Savings: 2/3 = ~66.7%
        assert stats["savings_percent"] > 60


class TestIntegrity:
    """Tests for integrity verification."""

    def test_verify_integrity_valid(self, storage, sample_mp3, sample_track_info):
        """All tracked files should be valid."""
        storage.store_track(sample_mp3, sample_track_info, "playlist-1")

        result = storage.verify_integrity()
        assert result["valid_count"] == 1
        assert result["missing_count"] == 0

    def test_verify_integrity_missing(self, storage, sample_mp3, sample_track_info):
        """Should detect missing files."""
        content_hash, _ = storage.store_track(
            sample_mp3, sample_track_info, "playlist-1"
        )

        # Manually delete the file
        storage.get_storage_path(content_hash).unlink()

        result = storage.verify_integrity()
        assert result["valid_count"] == 0
        assert result["missing_count"] == 1
        assert content_hash in result["missing_hashes"]

    def test_cleanup_orphans(self, storage, temp_library):
        """Should remove files not in index."""
        # Create orphan file directly in storage
        storage.storage_path.mkdir(parents=True, exist_ok=True)
        orphan = storage.storage_path / "orphan.mp3"
        orphan.write_bytes(b"orphan content")

        removed = storage.cleanup_orphans()
        assert removed == 1
        assert not orphan.exists()


class TestThreadSafety:
    """Tests for concurrent access."""

    def test_concurrent_store(self, storage, temp_library):
        """Multiple threads storing tracks should not corrupt index."""
        results = []
        errors = []

        def store_track(track_num):
            try:
                mp3_path = temp_library / f"track_{track_num}.mp3"
                mp3_path.write_bytes(f"content {track_num}".encode())
                track_info = {
                    "artist": f"Artist {track_num}",
                    "title": f"Song {track_num}",
                    "album": "",
                    "spotify_id": f"sp{track_num}"
                }
                content_hash, is_new = storage.store_track(
                    mp3_path, track_info, f"playlist-{track_num}"
                )
                results.append((content_hash, is_new))
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=store_track, args=(i,))
            for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 10
        # All should be new tracks with unique content
        assert all(is_new for _, is_new in results)

    def test_concurrent_add_same_track(self, storage, sample_mp3, sample_track_info):
        """Multiple threads adding same track should handle references correctly."""
        results = []
        errors = []

        def add_to_playlist(playlist_num):
            try:
                content_hash, is_new = storage.store_track(
                    sample_mp3, sample_track_info, f"playlist-{playlist_num}"
                )
                results.append((content_hash, is_new))
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=add_to_playlist, args=(i,))
            for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 5

        # All should have same hash
        hashes = [h for h, _ in results]
        assert len(set(hashes)) == 1

        # Only one should be "new"
        new_count = sum(1 for _, is_new in results if is_new)
        assert new_count == 1

        # Reference count should be 5
        track_info = storage.get_track_info(hashes[0])
        assert track_info["reference_count"] == 5


class TestPersistence:
    """Tests for index persistence."""

    def test_index_persists_across_instances(
        self, temp_library, sample_mp3, sample_track_info
    ):
        """Storage index should persist when creating new instance."""
        storage1 = TrackStorage(temp_library)
        content_hash, _ = storage1.store_track(
            sample_mp3, sample_track_info, "playlist-1"
        )

        # Create new instance
        storage2 = TrackStorage(temp_library)

        # Should find the track
        found_hash = storage2.find_by_spotify_id("spotify123")
        assert found_hash == content_hash

        track_info = storage2.get_track_info(content_hash)
        assert track_info is not None
        assert track_info["artist"] == "Test Artist"
