"""
Swim Sync - Spotify Playlist to MP3 Sync Manager
Main application entry point with Tkinter GUI
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import json
import os
from pathlib import Path
from datetime import datetime

from swimsync.sync_engine import SyncEngine
from swimsync.state_manager import StateManager
from swimsync.config_manager import ConfigManager
from swimsync.ui.loading import LoadingOverlay
from swimsync.ui.empty_state import EmptyStatePanel
from swimsync.ui.progress import SyncProgressPanel
from swimsync.ui.shortcuts import KeyboardShortcuts


class SwimSyncApp:
    """Main application window"""
    
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Swim Sync")
        self.root.geometry("800x650")
        self.root.minsize(700, 550)
        
        # Initialize managers
        self.config = ConfigManager()
        self.state = StateManager(self.config.get("output_folder"))
        self.sync_engine = SyncEngine(self.config, self.state)
        
        # Track state
        self.playlist_tracks = []
        self.sync_preview = {"new": [], "existing": [], "removed": []}
        self.is_syncing = False
        self.sync_thread = None
        
        # Setup UI
        self._setup_styles()
        self._create_widgets()
        self._setup_keyboard_shortcuts()
        self._load_last_session()
    
    def _setup_styles(self):
        """Configure ttk styles"""
        style = ttk.Style()
        style.theme_use('clam')  # More modern look on Windows
        
        # Custom styles
        style.configure("New.TLabel", foreground="#28a745")
        style.configure("Exists.TLabel", foreground="#6c757d")
        style.configure("Removed.TLabel", foreground="#dc3545")
        style.configure("Header.TLabel", font=("Segoe UI", 11, "bold"))
        style.configure("Big.TButton", padding=(20, 10))
        
    def _create_widgets(self):
        """Build the main UI"""
        # Main container with padding
        main_frame = ttk.Frame(self.root, padding="15")
        main_frame.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        
        row = 0
        
        # === Playlist URL Section ===
        ttk.Label(main_frame, text="Spotify Playlist URL:", style="Header.TLabel").grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 5)
        )
        row += 1
        
        self.url_var = tk.StringVar()
        self.url_entry = ttk.Entry(main_frame, textvariable=self.url_var, width=60)
        self.url_entry.grid(row=row, column=0, columnspan=2, sticky="ew", padx=(0, 10))
        
        self.load_btn = ttk.Button(main_frame, text="Load Playlist", command=self._load_playlist)
        self.load_btn.grid(row=row, column=2, sticky="e")
        row += 1
        
        # === Output Folder Section ===
        ttk.Label(main_frame, text="Output Folder:", style="Header.TLabel").grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(15, 5)
        )
        row += 1
        
        self.folder_var = tk.StringVar(value=self.config.get("output_folder"))
        self.folder_entry = ttk.Entry(main_frame, textvariable=self.folder_var, width=60)
        self.folder_entry.grid(row=row, column=0, columnspan=2, sticky="ew", padx=(0, 10))
        
        self.browse_btn = ttk.Button(main_frame, text="Browse", command=self._browse_folder)
        self.browse_btn.grid(row=row, column=2, sticky="e")
        row += 1
        
        # === Playlist Info Label ===
        self.playlist_info_var = tk.StringVar(value="No playlist loaded")
        ttk.Label(main_frame, textvariable=self.playlist_info_var, font=("Segoe UI", 10)).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(15, 5)
        )
        row += 1
        
        # === Track List (Treeview) ===
        list_frame = ttk.Frame(main_frame)
        list_frame.grid(row=row, column=0, columnspan=3, sticky="nsew", pady=(5, 10))
        main_frame.rowconfigure(row, weight=1)
        
        # Treeview with scrollbar
        self.tree = ttk.Treeview(list_frame, columns=("artist", "status"), show="headings", height=15)
        self.tree.heading("artist", text="Track / Artist")
        self.tree.heading("status", text="Status")
        self.tree.column("artist", width=500)
        self.tree.column("status", width=120, anchor="center")
        
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Empty state panel (shown when no playlist loaded)
        self.empty_state = EmptyStatePanel(list_frame)
        self.empty_state.place(relx=0.5, rely=0.5, anchor="center")

        # Loading overlay for async operations
        self.loading_overlay = LoadingOverlay(list_frame)

        # Sync progress panel (shown during sync)
        self.sync_progress_panel = SyncProgressPanel(main_frame)
        self.sync_progress_panel.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(5, 10))
        self.sync_progress_panel.grid_remove()  # Hidden by default

        row += 1
        
        # === Storage Gauge ===
        storage_frame = ttk.Frame(main_frame)
        storage_frame.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(5, 10))
        storage_frame.columnconfigure(0, weight=1)
        
        ttk.Label(storage_frame, text="Storage:", font=("Segoe UI", 9)).pack(side="left")
        
        self.storage_progress = ttk.Progressbar(storage_frame, length=400, mode="determinate")
        self.storage_progress.pack(side="left", padx=(10, 10), fill="x", expand=True)
        
        self.storage_label = ttk.Label(storage_frame, text="0 GB / 32 GB", font=("Segoe UI", 9))
        self.storage_label.pack(side="left")
        row += 1
        
        # === Summary Label ===
        self.summary_var = tk.StringVar(value="Load a playlist to see sync preview")
        ttk.Label(main_frame, textvariable=self.summary_var, font=("Segoe UI", 10)).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 10)
        )
        row += 1
        
        # === Bottom Controls ===
        controls_frame = ttk.Frame(main_frame)
        controls_frame.grid(row=row, column=0, columnspan=3, sticky="ew")
        
        self.sync_btn = ttk.Button(
            controls_frame, text="Sync Now", style="Big.TButton",
            command=self._start_sync, state="disabled"
        )
        self.sync_btn.pack(side="left")
        
        self.cancel_btn = ttk.Button(
            controls_frame, text="Cancel", command=self._cancel_sync, state="disabled"
        )
        self.cancel_btn.pack(side="left", padx=(10, 0))
        
        # Delete removed checkbox
        self.delete_removed_var = tk.BooleanVar(value=self.config.get("auto_delete_removed"))
        self.delete_cb = ttk.Checkbutton(
            controls_frame, text="Delete removed tracks",
            variable=self.delete_removed_var
        )
        self.delete_cb.pack(side="right")
        
        # Settings button
        settings_btn = ttk.Button(controls_frame, text="Settings", command=self._open_settings)
        settings_btn.pack(side="right", padx=(0, 20))
        
        # === Status Bar ===
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(
            self.root, textvariable=self.status_var,
            relief="sunken", anchor="w", padding=(5, 2)
        )
        status_bar.grid(row=1, column=0, sticky="ew")
        
        # Update storage display
        self._update_storage_display()
    
    def _setup_keyboard_shortcuts(self):
        """Bind keyboard shortcuts"""
        self.shortcuts = KeyboardShortcuts()
        self.shortcuts.bind_all(
            self.root,
            {
                'load_playlist': self._load_playlist,
                'start_sync': self._start_sync,
                'cancel_sync': self._cancel_sync,
                'browse_folder': self._browse_folder,
                'open_settings': self._open_settings
            },
            url_entry=self.url_entry
        )

    def _load_last_session(self):
        """Load the last used playlist URL"""
        last_url = self.config.get("last_playlist_url")
        if last_url:
            self.url_var.set(last_url)
    
    def _browse_folder(self):
        """Open folder picker dialog"""
        folder = filedialog.askdirectory(
            initialdir=self.folder_var.get(),
            title="Select Output Folder"
        )
        if folder:
            self.folder_var.set(folder)
            self.config.set("output_folder", folder)
            self.state = StateManager(folder)
            self.sync_engine = SyncEngine(self.config, self.state)
            self._update_storage_display()
    
    def _load_playlist(self):
        """Fetch playlist metadata and compute sync preview"""
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("Input Required", "Please enter a Spotify playlist URL")
            return
        
        if "open.spotify.com/playlist" not in url:
            messagebox.showerror("Invalid URL", "Please enter a valid Spotify playlist URL")
            return
        
        # Save URL for next session
        self.config.set("last_playlist_url", url)
        
        # Update state manager with current folder
        output_folder = self.folder_var.get()
        self.config.set("output_folder", output_folder)
        self.state = StateManager(output_folder)
        self.sync_engine = SyncEngine(self.config, self.state)
        
        # Disable controls during load
        self.load_btn.config(state="disabled")
        self.status_var.set("Loading playlist...")
        self.empty_state.place_forget()  # Hide empty state
        self.loading_overlay.show("Loading playlist")
        self.root.update()
        
        # Run in thread to keep UI responsive
        def load_thread():
            try:
                # Fetch playlist info
                playlist_name, tracks = self.sync_engine.fetch_playlist(url)
                
                # Compute diff
                preview = self.sync_engine.compute_diff(tracks)
                
                # Update UI in main thread
                self.root.after(0, lambda: self._on_playlist_loaded(playlist_name, tracks, preview))
                
            except Exception as e:
                error_msg = str(e)
                self.root.after(0, lambda msg=error_msg: self._on_load_error(msg))
        
        threading.Thread(target=load_thread, daemon=True).start()
    
    def _on_playlist_loaded(self, name: str, tracks: list, preview: dict):
        """Handle successful playlist load"""
        self.loading_overlay.hide()
        self.playlist_tracks = tracks
        self.sync_preview = preview

        # Update playlist info
        self.playlist_info_var.set(f"Playlist: {name} ({len(tracks)} tracks)")

        # Clear and populate tree
        for item in self.tree.get_children():
            self.tree.delete(item)

        # Add tracks with status tags
        for track in preview["new"]:
            self.tree.insert("", "end", values=(
                f"{track['title']} — {track['artist']}",
                "● New"
            ), tags=("new",))

        # Show suspect/corrupt files first with warning
        for track in preview.get("suspect", []):
            reason = track.get("_suspect_reason", "Possibly corrupt")
            self.tree.insert("", "end", values=(
                f"{track['title']} — {track['artist']}",
                f"⚠ {reason}"
            ), tags=("suspect",))

        for track in preview["existing"]:
            self.tree.insert("", "end", values=(
                f"{track['title']} — {track['artist']}",
                "✓ Exists"
            ), tags=("existing",))

        for track in preview["removed"]:
            self.tree.insert("", "end", values=(
                f"{track['title']} — {track['artist']}",
                "✗ Removed"
            ), tags=("removed",))

        # Apply tag colors
        self.tree.tag_configure("new", foreground="#28a745")
        self.tree.tag_configure("suspect", foreground="#fd7e14")  # Orange warning
        self.tree.tag_configure("existing", foreground="#6c757d")
        self.tree.tag_configure("removed", foreground="#dc3545")

        # Update summary
        new_count = len(preview["new"])
        suspect_count = len(preview.get("suspect", []))
        removed_count = len(preview["removed"])
        download_count = new_count + suspect_count
        est_size = download_count * 8  # Rough estimate: 8MB per track

        summary = f"{len(tracks)} tracks │ {new_count} new │ {removed_count} removed"
        if suspect_count > 0:
            summary += f" │ {suspect_count} suspect"
        if download_count > 0:
            summary += f" │ ~{est_size} MB to download"
        self.summary_var.set(summary)

        # Enable sync if there's work to do (new tracks OR suspect tracks to re-download)
        if download_count > 0 or (removed_count > 0 and self.delete_removed_var.get()):
            self.sync_btn.config(state="normal")
        else:
            self.sync_btn.config(state="disabled")

        self.load_btn.config(state="normal")
        status_msg = "Playlist loaded - review changes and click Sync"
        if suspect_count > 0:
            status_msg = f"⚠ {suspect_count} suspect file(s) will be re-downloaded"
        self.status_var.set(status_msg)
        self._update_storage_display()
    
    def _on_load_error(self, error: str):
        """Handle playlist load failure"""
        self.loading_overlay.hide()
        self.empty_state.place(relx=0.5, rely=0.5, anchor="center")  # Show empty state again
        self.load_btn.config(state="normal")
        self.status_var.set("Error loading playlist")
        messagebox.showerror("Load Failed", f"Could not load playlist:\n\n{error}")
    
    def _start_sync(self):
        """Begin the sync process"""
        if self.is_syncing:
            return

        new_tracks = self.sync_preview["new"]
        suspect_tracks = self.sync_preview.get("suspect", [])
        removed_count = len(self.sync_preview["removed"])
        delete_removed = self.delete_removed_var.get()

        # Combine new + suspect tracks for download (suspect files will be re-downloaded)
        tracks_to_download = new_tracks + suspect_tracks

        # Confirm if deleting
        if delete_removed and removed_count > 0:
            if not messagebox.askyesno(
                "Confirm Deletion",
                f"This will delete {removed_count} track(s) that were removed from the playlist.\n\nContinue?"
            ):
                return

        self.is_syncing = True
        self.sync_btn.config(state="disabled")
        self.load_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")

        # Show sync progress panel
        self.sync_progress_panel.reset()
        self.sync_progress_panel.show()

        # Progress callback
        def on_progress(current: int, total: int, track_name: str, status: str, extra: dict = None):
            self.root.after(0, lambda c=current, t=total, n=track_name, s=status, e=extra:
                            self._update_sync_progress(c, t, n, s, e or {}))

        # Run sync in thread
        def sync_thread():
            try:
                results = self.sync_engine.sync(
                    tracks_to_download,
                    self.sync_preview["removed"] if delete_removed else [],
                    progress_callback=on_progress
                )
                self.root.after(0, lambda: self._on_sync_complete(results))
            except Exception as e:
                error_msg = str(e)
                self.root.after(0, lambda msg=error_msg: self._on_sync_error(msg))
        
        self.sync_thread = threading.Thread(target=sync_thread, daemon=True)
        self.sync_thread.start()
    
    def _update_sync_progress(self, current: int, total: int, track_name: str, status: str, extra: dict):
        """Update UI with sync progress including speed and size"""
        # Build status message with speed info
        speed_str = ""
        if extra.get("speed_mbps", 0) > 0:
            speed_str = f" ({extra['speed_mbps']:.2f} MB/s)"

        self.status_var.set(f"[{current}/{total}] {status}: {track_name}{speed_str}")
        self.sync_progress_panel.update_progress(current, total, track_name, status, extra)

        # Update tree item status if possible
        for item in self.tree.get_children():
            values = self.tree.item(item, "values")
            if track_name in values[0]:
                if status == "Downloading":
                    self.tree.item(item, values=(values[0], "◐ Downloading..."))
                    # Scroll to make this item visible
                    self.tree.see(item)
                elif status == "Downloaded":
                    size_mb = extra.get("file_size_mb", 0)
                    size_str = f"✓ {size_mb:.1f} MB" if size_mb else "✓ Done"
                    self.tree.item(item, values=(values[0], size_str), tags=("existing",))
                elif status == "Failed":
                    self.tree.item(item, values=(values[0], "✗ Failed"), tags=("removed",))
                elif status == "Deleted":
                    self.tree.delete(item)
                break
    
    def _on_sync_complete(self, results: dict):
        """Handle sync completion"""
        self.is_syncing = False
        self.sync_btn.config(state="disabled")
        self.load_btn.config(state="normal")
        self.cancel_btn.config(state="disabled")
        self.sync_progress_panel.hide()
        
        downloaded = results.get("downloaded", 0)
        failed = results.get("failed", 0)
        deleted = results.get("deleted", 0)
        
        summary = f"Sync complete: {downloaded} downloaded"
        if failed > 0:
            summary += f", {failed} failed"
        if deleted > 0:
            summary += f", {deleted} deleted"
        
        self.status_var.set(summary)
        self.summary_var.set(summary)
        self._update_storage_display()
        
        messagebox.showinfo("Sync Complete", summary)
    
    def _on_sync_error(self, error: str):
        """Handle sync failure"""
        self.is_syncing = False
        self.sync_btn.config(state="normal")
        self.load_btn.config(state="normal")
        self.cancel_btn.config(state="disabled")
        self.sync_progress_panel.hide()
        self.status_var.set("Sync failed")
        messagebox.showerror("Sync Error", f"Sync failed:\n\n{error}")
    
    def _cancel_sync(self):
        """Cancel ongoing sync"""
        if self.is_syncing:
            self.sync_engine.cancel()
            self.status_var.set("Cancelling...")
    
    def _update_storage_display(self):
        """Update the storage gauge"""
        folder = self.folder_var.get()
        if os.path.exists(folder):
            total_size = sum(
                f.stat().st_size for f in Path(folder).glob("*.mp3") if f.is_file()
            )
            size_gb = total_size / (1024 ** 3)
        else:
            size_gb = 0
        
        max_gb = self.config.get("storage_limit_gb")
        percent = min(100, (size_gb / max_gb) * 100)
        
        self.storage_progress["value"] = percent
        self.storage_label.config(text=f"{size_gb:.1f} GB / {max_gb} GB")
        
        # Change color if near limit
        if percent > 90:
            self.storage_progress.config(style="red.Horizontal.TProgressbar")
        elif percent > 75:
            self.storage_progress.config(style="yellow.Horizontal.TProgressbar")
    
    def _open_settings(self):
        """Open settings dialog"""
        SettingsDialog(self.root, self.config, self._on_settings_changed)
    
    def _on_settings_changed(self):
        """Handle settings update"""
        self._update_storage_display()


class SettingsDialog:
    """Settings configuration dialog"""
    
    def __init__(self, parent, config: ConfigManager, on_save_callback):
        self.config = config
        self.on_save = on_save_callback
        
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Settings")
        self.dialog.geometry("400x300")
        self.dialog.transient(parent)
        self.dialog.grab_set()
        
        self._create_widgets()
    
    def _create_widgets(self):
        frame = ttk.Frame(self.dialog, padding="20")
        frame.pack(fill="both", expand=True)
        
        row = 0
        
        # Bitrate
        ttk.Label(frame, text="Audio Bitrate:").grid(row=row, column=0, sticky="w", pady=5)
        self.bitrate_var = tk.StringVar(value=self.config.get("bitrate"))
        bitrate_combo = ttk.Combobox(
            frame, textvariable=self.bitrate_var,
            values=["128k", "192k", "256k", "320k"], state="readonly", width=10
        )
        bitrate_combo.grid(row=row, column=1, sticky="w", pady=5)
        row += 1
        
        # Storage limit
        ttk.Label(frame, text="Storage Limit (GB):").grid(row=row, column=0, sticky="w", pady=5)
        self.storage_var = tk.StringVar(value=str(self.config.get("storage_limit_gb")))
        storage_spin = ttk.Spinbox(
            frame, from_=1, to=128, textvariable=self.storage_var, width=10
        )
        storage_spin.grid(row=row, column=1, sticky="w", pady=5)
        row += 1
        
        # Download timeout
        ttk.Label(frame, text="Download Timeout (sec):").grid(row=row, column=0, sticky="w", pady=5)
        self.timeout_var = tk.StringVar(value=str(self.config.get("download_timeout")))
        timeout_spin = ttk.Spinbox(
            frame, from_=30, to=600, textvariable=self.timeout_var, width=10
        )
        timeout_spin.grid(row=row, column=1, sticky="w", pady=5)
        row += 1
        
        # Buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=row, column=0, columnspan=2, pady=20)
        
        ttk.Button(btn_frame, text="Save", command=self._save).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Cancel", command=self.dialog.destroy).pack(side="left", padx=5)
    
    def _save(self):
        self.config.set("bitrate", self.bitrate_var.get())
        self.config.set("storage_limit_gb", int(self.storage_var.get()))
        self.config.set("download_timeout", int(self.timeout_var.get()))
        self.on_save()
        self.dialog.destroy()


def main():
    """Application entry point"""
    root = tk.Tk()
    
    # Set icon if available
    try:
        root.iconbitmap("icon.ico")
    except:
        pass
    
    app = SwimSyncApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
