"""
Loading Overlay Widget for Swim Sync

A semi-transparent overlay that displays a loading indicator over any parent widget.
Includes animated dots and an optional indeterminate progress bar.
"""

import tkinter as tk
from tkinter import ttk
from typing import Optional


class LoadingOverlay:
    """
    A modal loading overlay that can be shown over any parent widget.

    Features:
    - Semi-transparent dark overlay
    - "Loading..." text with animated dots
    - Optional indeterminate progress bar
    - Blocks interaction with underlying widgets

    Usage:
        overlay = LoadingOverlay(parent_frame)
        overlay.show("Loading playlist...")
        # ... do work ...
        overlay.hide()
    """

    # Animation settings
    DOT_ANIMATION_INTERVAL_MS = 400
    MAX_DOTS = 3

    # Styling constants (consistent with app theme)
    OVERLAY_BG = "#1a1a1a"
    OVERLAY_ALPHA = 0.7  # Note: True alpha not supported in Tk, we simulate with color
    TEXT_COLOR = "#ffffff"
    FONT_FAMILY = "Segoe UI"
    FONT_SIZE = 12

    def __init__(
        self,
        parent: tk.Widget,
        show_progress_bar: bool = True,
        message: str = "Loading"
    ):
        """
        Initialize the loading overlay.

        Args:
            parent: The parent widget to overlay
            show_progress_bar: Whether to show an indeterminate progress bar
            message: Default loading message (without trailing dots)
        """
        self.parent = parent
        self.show_progress_bar = show_progress_bar
        self.base_message = message

        self._overlay_frame: Optional[tk.Frame] = None
        self._message_label: Optional[ttk.Label] = None
        self._progress_bar: Optional[ttk.Progressbar] = None
        self._animation_id: Optional[str] = None
        self._dot_count = 0
        self._is_visible = False

        self._setup_styles()

    def _setup_styles(self):
        """Configure ttk styles for the overlay components."""
        style = ttk.Style()

        # Ensure clam theme is active
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass  # Theme may already be set

        # Loading overlay label style
        style.configure(
            "Loading.TLabel",
            background=self.OVERLAY_BG,
            foreground=self.TEXT_COLOR,
            font=(self.FONT_FAMILY, self.FONT_SIZE)
        )

        # Progress bar style with app's green color
        style.configure(
            "Loading.Horizontal.TProgressbar",
            troughcolor="#404040",
            background="#28a745",
            darkcolor="#28a745",
            lightcolor="#28a745",
            bordercolor=self.OVERLAY_BG
        )

    def _create_overlay(self):
        """Create the overlay widgets."""
        # Create overlay frame that covers the parent
        self._overlay_frame = tk.Frame(
            self.parent,
            bg=self.OVERLAY_BG,
            cursor="wait"
        )

        # Container for centered content
        content_frame = tk.Frame(self._overlay_frame, bg=self.OVERLAY_BG)
        content_frame.place(relx=0.5, rely=0.5, anchor="center")

        # Loading message label
        self._message_label = ttk.Label(
            content_frame,
            text=self.base_message,
            style="Loading.TLabel"
        )
        self._message_label.pack(pady=(0, 10))

        # Optional progress bar
        if self.show_progress_bar:
            self._progress_bar = ttk.Progressbar(
                content_frame,
                style="Loading.Horizontal.TProgressbar",
                mode="indeterminate",
                length=200
            )
            self._progress_bar.pack(pady=(0, 5))

    def _destroy_overlay(self):
        """Destroy the overlay widgets."""
        if self._overlay_frame is not None:
            self._overlay_frame.destroy()
            self._overlay_frame = None
            self._message_label = None
            self._progress_bar = None

    def _animate_dots(self):
        """Animate the loading dots."""
        if not self._is_visible or self._message_label is None:
            return

        # Cycle through 0, 1, 2, 3 dots
        self._dot_count = (self._dot_count + 1) % (self.MAX_DOTS + 1)
        dots = "." * self._dot_count

        self._message_label.config(text=f"{self.base_message}{dots}")

        # Schedule next animation frame
        self._animation_id = self.parent.after(
            self.DOT_ANIMATION_INTERVAL_MS,
            self._animate_dots
        )

    def _stop_animation(self):
        """Stop the dot animation."""
        if self._animation_id is not None:
            self.parent.after_cancel(self._animation_id)
            self._animation_id = None

    def show(self, message: Optional[str] = None):
        """
        Show the loading overlay.

        Args:
            message: Optional message to display (without trailing dots).
                     If not provided, uses the default message.
        """
        if self._is_visible:
            # Already visible, just update message if provided
            if message is not None:
                self.base_message = message
                if self._message_label is not None:
                    self._message_label.config(text=self.base_message)
            return

        if message is not None:
            self.base_message = message

        self._is_visible = True
        self._dot_count = 0

        # Create and display overlay
        self._create_overlay()

        # Position overlay to cover entire parent
        self._overlay_frame.place(relx=0, rely=0, relwidth=1, relheight=1)

        # Raise to top of stacking order
        self._overlay_frame.lift()

        # Start progress bar animation
        if self._progress_bar is not None:
            self._progress_bar.start(15)  # Speed in ms

        # Start dot animation
        self._animate_dots()

        # Force update to ensure overlay is visible immediately
        self._overlay_frame.update()

    def hide(self):
        """Hide the loading overlay."""
        if not self._is_visible:
            return

        self._is_visible = False

        # Stop animations
        self._stop_animation()
        if self._progress_bar is not None:
            self._progress_bar.stop()

        # Destroy overlay widgets
        self._destroy_overlay()

    def update_message(self, message: str):
        """
        Update the loading message while overlay is visible.

        Args:
            message: New message to display (without trailing dots)
        """
        self.base_message = message
        if self._message_label is not None and self._is_visible:
            # Keep current dot count when updating message
            dots = "." * self._dot_count
            self._message_label.config(text=f"{self.base_message}{dots}")

    @property
    def is_visible(self) -> bool:
        """Return whether the overlay is currently visible."""
        return self._is_visible


# Demonstration/testing code
if __name__ == "__main__":
    def demo():
        """Demonstrate the LoadingOverlay widget."""
        root = tk.Tk()
        root.title("Loading Overlay Demo")
        root.geometry("600x400")

        # Setup ttk styling
        style = ttk.Style()
        style.theme_use('clam')

        # Create main content
        main_frame = ttk.Frame(root, padding="20")
        main_frame.pack(fill="both", expand=True)

        ttk.Label(
            main_frame,
            text="Main Application Content",
            font=("Segoe UI", 16, "bold")
        ).pack(pady=20)

        ttk.Label(
            main_frame,
            text="This content will be covered by the loading overlay.",
            font=("Segoe UI", 10)
        ).pack(pady=10)

        # Create some interactive elements
        entry = ttk.Entry(main_frame, width=40)
        entry.pack(pady=10)
        entry.insert(0, "Try clicking here when overlay is visible")

        # Create loading overlay
        overlay = LoadingOverlay(main_frame, show_progress_bar=True)

        def show_loading():
            """Show loading overlay for 3 seconds."""
            overlay.show("Fetching playlist")

            # Simulate progress updates
            def update1():
                if overlay.is_visible:
                    overlay.update_message("Downloading tracks")

            def update2():
                if overlay.is_visible:
                    overlay.update_message("Almost done")

            def hide():
                overlay.hide()

            root.after(1000, update1)
            root.after(2000, update2)
            root.after(3000, hide)

        show_btn = ttk.Button(
            main_frame,
            text="Show Loading Overlay (3 sec)",
            command=show_loading
        )
        show_btn.pack(pady=20)

        # Quick show/hide for testing
        toggle_btn = ttk.Button(
            main_frame,
            text="Toggle Overlay",
            command=lambda: overlay.hide() if overlay.is_visible else overlay.show()
        )
        toggle_btn.pack(pady=10)

        root.mainloop()

    demo()
