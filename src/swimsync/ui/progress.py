"""
Swim Sync - Sync Progress Panel Widget

A prominent progress panel for displaying sync operation status.
Shows overall progress, current track, status, and estimated time remaining.
"""

import tkinter as tk
from tkinter import ttk
from typing import Optional
import time


class SyncProgressPanel(ttk.Frame):
    """
    A progress panel widget for sync operations.

    Displays:
    - Overall progress bar (determinate) showing X of Y tracks
    - Current track name being processed
    - Status text (Downloading/Downloaded/Failed)
    - Estimated time remaining (optional)

    Usage:
        panel = SyncProgressPanel(parent)
        panel.show()
        panel.update_progress(1, 10, "Track Name", "Downloading")
        panel.hide()
    """

    # Status colors matching app theme
    COLOR_SUCCESS = "#28a745"  # Green
    COLOR_NEUTRAL = "#6c757d"  # Gray
    COLOR_ERROR = "#dc3545"    # Red
    COLOR_PROGRESS = "#007bff" # Blue for in-progress

    # Font configuration
    FONT_FAMILY = "Segoe UI"

    def __init__(self, parent: tk.Widget, **kwargs):
        """
        Initialize the sync progress panel.

        Args:
            parent: Parent widget to attach this panel to.
            **kwargs: Additional keyword arguments passed to ttk.Frame.
        """
        super().__init__(parent, **kwargs)

        # State tracking
        self._is_visible = False
        self._start_time: Optional[float] = None
        self._total_tracks = 0
        self._processed_tracks = 0

        # Configure styles
        self._setup_styles()

        # Build the UI
        self._create_widgets()

        # Initially hidden
        self.grid_remove()

    def _setup_styles(self):
        """Configure ttk styles for this widget."""
        style = ttk.Style()

        # Ensure clam theme is active (should already be set by main app)
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass  # Theme already in use

        # Progress bar style with green color
        style.configure(
            "Sync.Horizontal.TProgressbar",
            troughcolor="#e9ecef",
            background=self.COLOR_SUCCESS,
            lightcolor=self.COLOR_SUCCESS,
            darkcolor=self.COLOR_SUCCESS,
            bordercolor="#ced4da",
            thickness=20
        )

        # Panel header style
        style.configure(
            "ProgressHeader.TLabel",
            font=(self.FONT_FAMILY, 11, "bold"),
            foreground="#212529"
        )

        # Track name style
        style.configure(
            "TrackName.TLabel",
            font=(self.FONT_FAMILY, 10),
            foreground="#495057"
        )

        # Status label styles
        style.configure(
            "Status.TLabel",
            font=(self.FONT_FAMILY, 9),
            foreground=self.COLOR_NEUTRAL
        )

        style.configure(
            "StatusDownloading.TLabel",
            font=(self.FONT_FAMILY, 9, "bold"),
            foreground=self.COLOR_PROGRESS
        )

        style.configure(
            "StatusDownloaded.TLabel",
            font=(self.FONT_FAMILY, 9, "bold"),
            foreground=self.COLOR_SUCCESS
        )

        style.configure(
            "StatusFailed.TLabel",
            font=(self.FONT_FAMILY, 9, "bold"),
            foreground=self.COLOR_ERROR
        )

        # Time remaining style
        style.configure(
            "TimeRemaining.TLabel",
            font=(self.FONT_FAMILY, 9),
            foreground=self.COLOR_NEUTRAL
        )

    def _create_widgets(self):
        """Build the progress panel UI."""
        # Configure grid weights
        self.columnconfigure(0, weight=1)

        # Add internal padding
        self.configure(padding=(15, 10))

        row = 0

        # Header label
        self._header_label = ttk.Label(
            self,
            text="Syncing Playlist...",
            style="ProgressHeader.TLabel"
        )
        self._header_label.grid(row=row, column=0, sticky="w", pady=(0, 8))
        row += 1

        # Progress bar frame (contains bar and percentage)
        progress_frame = ttk.Frame(self)
        progress_frame.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        progress_frame.columnconfigure(0, weight=1)

        # Progress bar
        self._progress_bar = ttk.Progressbar(
            progress_frame,
            orient="horizontal",
            mode="determinate",
            style="Sync.Horizontal.TProgressbar",
            length=400
        )
        self._progress_bar.grid(row=0, column=0, sticky="ew", padx=(0, 10))

        # Progress text (X of Y)
        self._progress_text = ttk.Label(
            progress_frame,
            text="0 of 0",
            font=(self.FONT_FAMILY, 10),
            width=12,
            anchor="e"
        )
        self._progress_text.grid(row=0, column=1, sticky="e")
        row += 1

        # Current track frame
        track_frame = ttk.Frame(self)
        track_frame.grid(row=row, column=0, sticky="ew", pady=(0, 5))
        track_frame.columnconfigure(1, weight=1)

        # Status indicator
        self._status_label = ttk.Label(
            track_frame,
            text="Ready",
            style="Status.TLabel",
            width=12,
            anchor="w"
        )
        self._status_label.grid(row=0, column=0, sticky="w", padx=(0, 10))

        # Current track name (truncated if too long)
        self._track_name_var = tk.StringVar(value="")
        self._track_name_label = ttk.Label(
            track_frame,
            textvariable=self._track_name_var,
            style="TrackName.TLabel",
            anchor="w"
        )
        self._track_name_label.grid(row=0, column=1, sticky="ew")
        row += 1

        # Time remaining label
        self._time_remaining_var = tk.StringVar(value="")
        self._time_remaining_label = ttk.Label(
            self,
            textvariable=self._time_remaining_var,
            style="TimeRemaining.TLabel"
        )
        self._time_remaining_label.grid(row=row, column=0, sticky="w", pady=(5, 0))

    def show(self):
        """Display the progress panel."""
        if not self._is_visible:
            self._is_visible = True
            self._start_time = time.time()
            self.grid()

    def hide(self):
        """Hide the progress panel."""
        if self._is_visible:
            self._is_visible = False
            self._start_time = None
            self.grid_remove()

    def update_progress(
        self,
        current: int,
        total: int,
        track_name: str,
        status: str,
        extra: dict = None
    ):
        """
        Update the progress display.

        Args:
            current: Current track number (1-based).
            total: Total number of tracks to process.
            track_name: Name of the current track being processed.
            status: Current status (Downloading, Downloaded, Failed, etc.)
            extra: Additional info dict with speed_mbps, file_size_mb, etc.
        """
        extra = extra or {}
        self._processed_tracks = current
        self._total_tracks = total

        # Update progress bar
        if total > 0:
            progress_percent = (current / total) * 100
            self._progress_bar["value"] = progress_percent
        else:
            self._progress_bar["value"] = 0

        # Update progress text with speed if available
        speed = extra.get("speed_mbps", 0)
        if speed > 0:
            self._progress_text.configure(text=f"{current} of {total} • {speed:.1f} MB/s")
        else:
            self._progress_text.configure(text=f"{current} of {total}")

        # Update header with percentage
        if total > 0:
            percent = int((current / total) * 100)
            self._header_label.configure(text=f"Syncing Playlist... {percent}%")

        # Truncate track name if too long (max ~60 chars)
        display_name = track_name
        if len(track_name) > 60:
            display_name = track_name[:57] + "..."
        self._track_name_var.set(display_name)

        # Update status label with file size if available
        file_size = extra.get("file_size_mb", 0)
        status_text = status
        if status.lower() == "downloaded" and file_size > 0:
            status_text = f"{status} ({file_size:.1f} MB)"

        self._status_label.configure(text=status_text)

        status_lower = status.lower()
        if "downloading" in status_lower:
            self._status_label.configure(style="StatusDownloading.TLabel")
        elif "downloaded" in status_lower or "complete" in status_lower:
            self._status_label.configure(style="StatusDownloaded.TLabel")
        elif "failed" in status_lower or "error" in status_lower:
            self._status_label.configure(style="StatusFailed.TLabel")
        else:
            self._status_label.configure(style="Status.TLabel")

        # Calculate and display estimated time remaining
        self._update_time_remaining(current, total)

    def _update_time_remaining(self, current: int, total: int):
        """
        Calculate and update the estimated time remaining.

        Args:
            current: Current track number (1-based).
            total: Total number of tracks.
        """
        if self._start_time is None or current <= 0 or total <= 0:
            self._time_remaining_var.set("")
            return

        elapsed = time.time() - self._start_time

        # Need at least some progress to estimate
        if current < 1:
            self._time_remaining_var.set("")
            return

        # Calculate average time per track and remaining time
        avg_time_per_track = elapsed / current
        remaining_tracks = total - current
        estimated_remaining = avg_time_per_track * remaining_tracks

        if remaining_tracks <= 0:
            self._time_remaining_var.set("Almost done...")
            return

        # Format the time remaining
        time_str = self._format_time(estimated_remaining)
        self._time_remaining_var.set(f"Estimated time remaining: {time_str}")

    def _format_time(self, seconds: float) -> str:
        """
        Format seconds into a human-readable time string.

        Args:
            seconds: Number of seconds.

        Returns:
            Formatted time string (e.g., "2m 30s", "1h 5m").
        """
        if seconds < 0:
            return "0s"

        seconds = int(seconds)

        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            minutes = seconds // 60
            secs = seconds % 60
            if secs > 0:
                return f"{minutes}m {secs}s"
            return f"{minutes}m"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            if minutes > 0:
                return f"{hours}h {minutes}m"
            return f"{hours}h"

    def reset(self):
        """Reset all progress display to initial state."""
        self._processed_tracks = 0
        self._total_tracks = 0
        self._start_time = None

        # Reset progress bar
        self._progress_bar["value"] = 0

        # Reset labels
        self._header_label.configure(text="Syncing Playlist...")
        self._progress_text.configure(text="0 of 0")
        self._track_name_var.set("")
        self._status_label.configure(text="Ready", style="Status.TLabel")
        self._time_remaining_var.set("")

    @property
    def is_visible(self) -> bool:
        """Check if the panel is currently visible."""
        return self._is_visible

    @property
    def progress(self) -> tuple[int, int]:
        """Get current progress as (current, total) tuple."""
        return (self._processed_tracks, self._total_tracks)
