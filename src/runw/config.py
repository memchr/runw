from pathlib import Path
import tomllib

from runw.common import XDG_CONFIG_HOME
from runw.sandbox import Bwrap
# pyright: reportAny=false

CONFIG_DIR = XDG_CONFIG_HOME / "runw"
PRESETS_PATH = CONFIG_DIR / "presets.toml"
CONFIG_PATH = CONFIG_DIR / "runw.toml"


def _load(path: Path) -> dict[str, Bwrap]:
    try:
        with path.open("rb") as f:
            return {
                name: Bwrap(
                    **{
                        k: v
                        for k, v in config.items()
                        if k in Bwrap.__dataclass_fields__
                    }
                )
                for name, config in tomllib.load(f).items()
            }
    except FileNotFoundError:
        return {}


def load_presets() -> dict[str, Bwrap]:
    return _load(PRESETS_PATH)


def load_configs() -> dict[str, Bwrap]:
    return _load(CONFIG_PATH)
