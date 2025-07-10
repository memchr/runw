import tomllib
from typing import Any

from runw.common import XDG_CONFIG_HOME
from runw.sandbox import Bwrap
# pyright: reportAny=false,reportExplicitAny=false

CONFIG_DIR = XDG_CONFIG_HOME / "runw"
PRESETS_PATH = CONFIG_DIR / "presets.toml"
CONFIG_PATH = CONFIG_DIR / "runw.toml"


def load_presets() -> dict[str, Bwrap]:
    with PRESETS_PATH.open("rb") as f:
        return {n: Bwrap.from_dict(c) for n, c in tomllib.load(f).items()}


def load_configs() -> dict[str, dict[str, Any]]:
    with CONFIG_PATH.open("rb") as f:
        return tomllib.load(f)
