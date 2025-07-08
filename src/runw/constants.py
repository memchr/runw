from pathlib import Path
import os


HOME = Path.home()
XDG_RUNTIME_DIR = Path(os.getenv("XDG_RUNTIME_DIR", "/tmp"))
XDG_CONFIG_HOME = Path(os.getenv("XDG_CONFIG_HOME", HOME / ".config"))
XDG_CACHE_HOME = Path(os.getenv("XDG_CACHE_HOME", HOME / ".cache"))
XDG_DATA_HOME = Path(os.getenv("XDG_DATA_HOME", HOME / ".local/share"))
PROTON_PATH = HOME / "steam/primus/steamapps/common/Proton - Experimental/proton"
DBUS_PROXY_PATH = XDG_RUNTIME_DIR / "bus-proxy"
