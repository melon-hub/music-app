"""Quick functional test for TrackStorage."""
import tempfile
from pathlib import Path
from swimsync.track_storage import TrackStorage

def test_basic_flow():
    with tempfile.TemporaryDirectory() as tmpdir:
        library_path = Path(tmpdir)
        storage = TrackStorage(library_path)

        # Create a fake MP3
        mp3_path = library_path / "test.mp3"
        mp3_path.write_bytes(b"ID3" + b"\x00" * 100 + b"fake content " * 50)

        # Store it
        track_info = {"artist": "Test", "title": "Song", "album": "", "spotify_id": "sp1"}
        content_hash, is_new = storage.store_track(mp3_path, track_info, "playlist-1")

        assert is_new, "First store should be new"
        assert len(content_hash) == 16, "Hash should be 16 chars"

        # Store again in another playlist
        hash2, is_new2 = storage.store_track(mp3_path, track_info, "playlist-2")
        assert hash2 == content_hash, "Same content should have same hash"
        assert not is_new2, "Second store should not be new"

        # Check ref count
        info = storage.get_track_info(content_hash)
        assert info["reference_count"] == 2, "Should have 2 refs"

        # Create playlist link
        playlist_folder = library_path / "playlists" / "test"
        success = storage.create_playlist_link(content_hash, playlist_folder, "Test - Song.mp3")
        assert success, "Link creation should succeed"
        assert (playlist_folder / "Test - Song.mp3").exists(), "Link file should exist"

        # Stats
        stats = storage.get_storage_stats()
        assert stats["unique_tracks"] == 1
        assert stats["total_references"] == 2
        assert stats["savings_percent"] == 50.0

        # Remove one ref
        deleted = storage.remove_reference(content_hash, "playlist-1")
        assert not deleted, "Should not delete with remaining ref"

        info = storage.get_track_info(content_hash)
        assert info["reference_count"] == 1

        # Remove last ref
        deleted = storage.remove_reference(content_hash, "playlist-2")
        assert deleted, "Should delete when no refs remain"

        print("All tests passed!")

if __name__ == "__main__":
    test_basic_flow()
