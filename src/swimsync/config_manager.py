"""
Config Manager - Handles application settings persistence
"""

import json
import os
from pathlib import Path
from typing import Any, Dict


class ConfigManager:
    """Manages application configuration and settings"""
    
    CONFIG_FILENAME = "swimsync_config.json"
    
    # Default settings
    DEFAULTS = {
        "output_folder": str(Path.home() / "Music" / "SwimSync"),
        "bitrate": "320k",
        "format": "mp3",
        "auto_delete_removed": False,
        "storage_limit_gb": 32,
        "download_timeout": 120,
        "concurrent_downloads": 1,
        "last_playlist_url": "",
        "window_geometry": "800x650",
    }
    
    def __init__(self, config_dir: str = None):
        """
        Initialize config manager.
        Config is stored in user's app data directory.
        """
        if config_dir:
            self.config_dir = Path(config_dir)
        else:
            # Use appropriate app data location
            if os.name == 'nt':  # Windows
                app_data = os.environ.get('APPDATA', Path.home())
                self.config_dir = Path(app_data) / "SwimSync"
            else:  # macOS/Linux
                self.config_dir = Path.home() / ".swimsync"
        
        self.config_path = self.config_dir / self.CONFIG_FILENAME
        self._data = self._load()
    
    def _load(self) -> Dict:
        """Load configuration from disk"""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                    # Merge with defaults to handle new settings
                    merged = self.DEFAULTS.copy()
                    merged.update(saved)
                    return merged
            except (json.JSONDecodeError, IOError):
                return self.DEFAULTS.copy()
        
        return self.DEFAULTS.copy()
    
    def save(self):
        """Save configuration to disk"""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(self._data, f, indent=2)
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value"""
        return self._data.get(key, default if default is not None else self.DEFAULTS.get(key))
    
    def set(self, key: str, value: Any):
        """Set a configuration value and save"""
        self._data[key] = value
        self.save()
    
    def get_all(self) -> Dict:
        """Get all configuration values"""
        return self._data.copy()
    
    def reset(self):
        """Reset all settings to defaults"""
        self._data = self.DEFAULTS.copy()
        self.save()
    
    def reset_key(self, key: str):
        """Reset a specific setting to default"""
        if key in self.DEFAULTS:
            self._data[key] = self.DEFAULTS[key]
            self.save()
