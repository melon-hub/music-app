"""
Keyboard shortcuts handler for Swim Sync application.

Provides centralized keyboard shortcut management for the Tkinter GUI,
binding common actions like load, sync, cancel, and settings navigation.
"""

import re
import tkinter as tk
from typing import Callable, Dict, Optional


class KeyboardShortcuts:
    """
    Manages keyboard shortcuts for the Swim Sync application.

    Binds keyboard shortcuts to a Tkinter root window and provides methods
    to bind and unbind all shortcuts as a group.

    Supported shortcuts:
        - Ctrl+V in URL field: auto-trigger load if valid Spotify URL pasted
        - Enter in URL field: trigger Load Playlist
        - Ctrl+S: Start Sync (when enabled)
        - Escape: Cancel sync (when syncing)
        - Ctrl+O: Open folder browser
        - Ctrl+,: Open settings

    Example usage:
        shortcuts = KeyboardShortcuts()
        shortcuts.bind_all(root, {
            'load_playlist': self._load_playlist,
            'start_sync': self._start_sync,
            'cancel_sync': self._cancel_sync,
            'browse_folder': self._browse_folder,
            'open_settings': self._open_settings
        })
    """

    # Spotify URL pattern for validation
    SPOTIFY_URL_PATTERN = re.compile(
        r'https?://open\.spotify\.com/playlist/[a-zA-Z0-9]+',
        re.IGNORECASE
    )

    def __init__(self):
        """Initialize the keyboard shortcuts handler."""
        self._root: Optional[tk.Tk] = None
        self._url_entry: Optional[tk.Entry] = None
        self._callbacks: Dict[str, Callable] = {}
        self._bound_ids: Dict[str, str] = {}
        self._entry_bound_ids: Dict[str, str] = {}

    def bind_all(
        self,
        root: tk.Tk,
        callbacks: Dict[str, Callable],
        url_entry: Optional[tk.Entry] = None
    ) -> None:
        """
        Bind all keyboard shortcuts to the root window.

        Args:
            root: The Tkinter root window to bind shortcuts to.
            callbacks: Dictionary mapping action names to callback functions.
                Required keys:
                    - 'load_playlist': Called when Enter pressed in URL field
                                       or valid Spotify URL pasted
                    - 'start_sync': Called on Ctrl+S
                    - 'cancel_sync': Called on Escape
                    - 'browse_folder': Called on Ctrl+O
                    - 'open_settings': Called on Ctrl+,
            url_entry: Optional Entry widget for URL field. If provided,
                       enables paste detection and Enter key handling.

        Raises:
            ValueError: If required callback keys are missing.
        """
        required_keys = {
            'load_playlist',
            'start_sync',
            'cancel_sync',
            'browse_folder',
            'open_settings'
        }

        missing_keys = required_keys - set(callbacks.keys())
        if missing_keys:
            raise ValueError(
                f"Missing required callbacks: {', '.join(sorted(missing_keys))}"
            )

        self._root = root
        self._callbacks = callbacks
        self._url_entry = url_entry

        # Bind global shortcuts to root window
        self._bind_global_shortcuts()

        # Bind URL entry specific shortcuts if entry provided
        if url_entry is not None:
            self._bind_url_entry_shortcuts()

    def _bind_global_shortcuts(self) -> None:
        """Bind shortcuts that work globally across the application."""
        if self._root is None:
            return

        # Ctrl+S: Start Sync
        bind_id = self._root.bind('<Control-s>', self._on_start_sync)
        self._bound_ids['<Control-s>'] = bind_id

        # Escape: Cancel Sync
        bind_id = self._root.bind('<Escape>', self._on_cancel_sync)
        self._bound_ids['<Escape>'] = bind_id

        # Ctrl+O: Open folder browser
        bind_id = self._root.bind('<Control-o>', self._on_browse_folder)
        self._bound_ids['<Control-o>'] = bind_id

        # Ctrl+,: Open settings (comma key)
        bind_id = self._root.bind('<Control-comma>', self._on_open_settings)
        self._bound_ids['<Control-comma>'] = bind_id

    def _bind_url_entry_shortcuts(self) -> None:
        """Bind shortcuts specific to the URL entry field."""
        if self._url_entry is None:
            return

        # Enter: Load playlist
        bind_id = self._url_entry.bind('<Return>', self._on_load_playlist)
        self._entry_bound_ids['<Return>'] = bind_id

        # Ctrl+V: Paste and auto-load if valid URL
        # We need to handle this after the default paste behavior
        bind_id = self._url_entry.bind(
            '<Control-v>',
            self._on_url_paste,
            add='+'  # Add to existing bindings, don't replace
        )
        self._entry_bound_ids['<Control-v>'] = bind_id

        # Also bind KeyRelease for Ctrl+V to check after paste completes
        bind_id = self._url_entry.bind(
            '<KeyRelease-v>',
            self._on_key_release_after_paste
        )
        self._entry_bound_ids['<KeyRelease-v>'] = bind_id

    def unbind_all(self, root: tk.Tk) -> None:
        """
        Remove all keyboard shortcut bindings from the root window.

        Args:
            root: The Tkinter root window to unbind shortcuts from.
        """
        # Unbind global shortcuts
        for event_sequence in self._bound_ids:
            try:
                root.unbind(event_sequence)
            except tk.TclError:
                # Binding may already be removed
                pass
        self._bound_ids.clear()

        # Unbind URL entry shortcuts
        if self._url_entry is not None:
            for event_sequence in self._entry_bound_ids:
                try:
                    self._url_entry.unbind(event_sequence)
                except tk.TclError:
                    pass
            self._entry_bound_ids.clear()

        self._root = None
        self._url_entry = None
        self._callbacks.clear()

    def _on_load_playlist(self, event: tk.Event) -> Optional[str]:
        """Handle Enter key in URL field."""
        callback = self._callbacks.get('load_playlist')
        if callback:
            callback()
        return 'break'  # Prevent default behavior

    def _on_start_sync(self, event: tk.Event) -> Optional[str]:
        """Handle Ctrl+S for starting sync."""
        callback = self._callbacks.get('start_sync')
        if callback:
            callback()
        return 'break'

    def _on_cancel_sync(self, event: tk.Event) -> Optional[str]:
        """Handle Escape for cancelling sync."""
        callback = self._callbacks.get('cancel_sync')
        if callback:
            callback()
        # Don't return 'break' for Escape - allow it to propagate
        # for closing dialogs etc.
        return None

    def _on_browse_folder(self, event: tk.Event) -> Optional[str]:
        """Handle Ctrl+O for opening folder browser."""
        callback = self._callbacks.get('browse_folder')
        if callback:
            callback()
        return 'break'

    def _on_open_settings(self, event: tk.Event) -> Optional[str]:
        """Handle Ctrl+, for opening settings."""
        callback = self._callbacks.get('open_settings')
        if callback:
            callback()
        return 'break'

    def _on_url_paste(self, event: tk.Event) -> None:
        """
        Handle Ctrl+V paste in URL field.

        Sets a flag to check the URL after the paste operation completes.
        """
        # Set flag to check URL after paste
        self._pending_paste_check = True

    def _on_key_release_after_paste(self, event: tk.Event) -> None:
        """
        Check URL validity after paste operation completes.

        If a valid Spotify playlist URL was pasted, automatically
        triggers the load playlist action.
        """
        # Only proceed if we have a pending paste check and Ctrl is held
        if not getattr(self, '_pending_paste_check', False):
            return

        self._pending_paste_check = False

        # Get the current URL from the entry
        if self._url_entry is None:
            return

        try:
            url = self._url_entry.get().strip()
        except tk.TclError:
            return

        # Check if it's a valid Spotify playlist URL
        if self._is_valid_spotify_url(url):
            # Schedule the load callback to run after event processing
            if self._root is not None:
                self._root.after(50, self._trigger_load_after_paste)

    def _trigger_load_after_paste(self) -> None:
        """Trigger load playlist after a small delay."""
        callback = self._callbacks.get('load_playlist')
        if callback:
            callback()

    def _is_valid_spotify_url(self, url: str) -> bool:
        """
        Check if a string is a valid Spotify playlist URL.

        Args:
            url: The URL string to validate.

        Returns:
            True if the URL is a valid Spotify playlist URL, False otherwise.
        """
        if not url:
            return False
        return bool(self.SPOTIFY_URL_PATTERN.search(url))

    @staticmethod
    def get_shortcut_help() -> str:
        """
        Get a formatted string describing all available shortcuts.

        Returns:
            A multi-line string listing all keyboard shortcuts and their actions.
        """
        return """Keyboard Shortcuts:
  Ctrl+V (in URL field)  - Paste and auto-load if valid Spotify URL
  Enter (in URL field)   - Load playlist
  Ctrl+S                 - Start sync
  Escape                 - Cancel sync
  Ctrl+O                 - Open folder browser
  Ctrl+,                 - Open settings"""
