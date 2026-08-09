"""Where things live on the receiver Pi.

Paths come from the environment so the systemd unit is the single place they
are stated, and so tests can point the whole application at a temp directory
without monkeypatching. The defaults are the deployed layout:

  /var/lib/boxradar-config/selection.json   state the UI writes (StateDirectory)
  /var/cache/boxradar-config/              YAIXM checkout and coastline
  /var/www/html/site.bin                   lighttpd's document root

The selection deliberately lives under /var/lib rather than /etc. It stopped
being a file a human edits the moment this UI existed, and systemd's
StateDirectory= gives a DynamicUser service a writable directory of its own
without a chown in the installer.
"""

import os
import pathlib

DEFAULT_SELECTION = "/var/lib/boxradar-config/selection.json"
DEFAULT_CACHE = "/var/cache/boxradar-config"
DEFAULT_BLOB = "/var/www/html/site.bin"
DEFAULT_PORT = 8082


class Settings:
    def __init__(self, selection_path, cache_dir, blob_path, port):
        self.selection_path = pathlib.Path(selection_path)
        self.cache_dir = pathlib.Path(cache_dir)
        self.blob_path = pathlib.Path(blob_path)
        self.port = int(port)

    @property
    def source_cache(self):
        """Passed to generate.yaml_path(), which appends airspace/."""
        return self.cache_dir

    @property
    def coastline_cache(self):
        return self.cache_dir / "coastline"

    @classmethod
    def from_env(cls, environ=None):
        env = os.environ if environ is None else environ
        return cls(env.get("BOXRADAR_CONFIG_SELECTION", DEFAULT_SELECTION),
                   env.get("BOXRADAR_CONFIG_CACHE", DEFAULT_CACHE),
                   env.get("BOXRADAR_CONFIG_BLOB", DEFAULT_BLOB),
                   env.get("BOXRADAR_CONFIG_PORT", DEFAULT_PORT))

    def __repr__(self):
        return (f"<Settings selection={self.selection_path} "
                f"cache={self.cache_dir} blob={self.blob_path} "
                f"port={self.port}>")
