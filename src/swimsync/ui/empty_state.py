"""
Empty State Panel Widget

Displays helpful guidance when no playlist is loaded in Swim Sync.
Shows a centered panel with an icon, heading, subtext, and example URL hint.
"""

import tkinter as tk
from tkinter import ttk


class EmptyStatePanel(ttk.Frame):
    """
    A panel that displays when no playlist is loaded.

    Shows centered content with:
    - A music/playlist icon
    - "No playlist loaded" heading
    - Instructional subtext
    - Example URL hint

    Usage:
        empty_panel = EmptyStatePanel(parent_frame)
        empty_panel.grid(row=0, column=0, sticky="nsew")

        # Toggle visibility
        empty_panel.show()
        empty_panel.hide()
    """

    # App color scheme (consistent with main app)
    COLOR_GREEN = "#28a745"
    COLOR_GRAY = "#6c757d"
    COLOR_RED = "#dc3545"
    COLOR_LIGHT_GRAY = "#adb5bd"

    # Font settings
    FONT_FAMILY = "Segoe UI"

    def __init__(self, parent: tk.Widget, **kwargs):
        """
        Initialize the empty state panel.

        Args:
            parent: The parent widget to attach this panel to.
            **kwargs: Additional arguments passed to ttk.Frame.
        """
        super().__init__(parent, **kwargs)

        self._setup_styles()
        self._create_widgets()

    def _setup_styles(self):
        """Configure custom ttk styles for the empty state panel."""
        style = ttk.Style()

        # Ensure clam theme is active (matches main app)
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass  # Theme already set or unavailable

        # Icon style - large music symbol
        style.configure(
            "EmptyState.Icon.TLabel",
            font=(self.FONT_FAMILY, 48),
            foreground=self.COLOR_LIGHT_GRAY
        )

        # Heading style - bold, medium size
        style.configure(
            "EmptyState.Heading.TLabel",
            font=(self.FONT_FAMILY, 14, "bold"),
            foreground="#333333"
        )

        # Subtext style - normal, slightly muted
        style.configure(
            "EmptyState.Subtext.TLabel",
            font=(self.FONT_FAMILY, 10),
            foreground=self.COLOR_GRAY
        )

        # Hint style - smaller, more muted, monospace for URL
        style.configure(
            "EmptyState.Hint.TLabel",
            font=("Consolas", 9),
            foreground=self.COLOR_LIGHT_GRAY
        )

    def _create_widgets(self):
        """Build the empty state panel UI."""
        # Configure grid to center content
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        # Inner container for centered content
        container = ttk.Frame(self)
        container.grid(row=0, column=0)

        # Music icon (using Unicode musical note)
        icon_label = ttk.Label(
            container,
            text="\u266B",  # Musical note: ♫
            style="EmptyState.Icon.TLabel"
        )
        icon_label.pack(pady=(0, 15))

        # Main heading
        heading_label = ttk.Label(
            container,
            text="No playlist loaded",
            style="EmptyState.Heading.TLabel"
        )
        heading_label.pack(pady=(0, 8))

        # Instructional subtext
        subtext_label = ttk.Label(
            container,
            text="Paste a Spotify playlist URL above to get started",
            style="EmptyState.Subtext.TLabel"
        )
        subtext_label.pack(pady=(0, 15))

        # Example URL hint
        hint_label = ttk.Label(
            container,
            text="Example: https://open.spotify.com/playlist/...",
            style="EmptyState.Hint.TLabel"
        )
        hint_label.pack()

    def show(self):
        """Make the empty state panel visible."""
        self.grid()

    def hide(self):
        """Hide the empty state panel."""
        self.grid_remove()


# For testing the widget standalone
if __name__ == "__main__":
    root = tk.Tk()
    root.title("Empty State Panel Test")
    root.geometry("600x400")

    # Apply clam theme
    style = ttk.Style()
    style.theme_use('clam')

    # Configure root grid
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)

    # Create and display the empty state panel
    panel = EmptyStatePanel(root)
    panel.grid(row=0, column=0, sticky="nsew")

    # Test show/hide with buttons
    btn_frame = ttk.Frame(root)
    btn_frame.grid(row=1, column=0, pady=10)

    ttk.Button(btn_frame, text="Hide", command=panel.hide).pack(side="left", padx=5)
    ttk.Button(btn_frame, text="Show", command=panel.show).pack(side="left", padx=5)

    root.mainloop()
