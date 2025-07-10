from pathlib import Path
import os
from typing import NotRequired, TypedDict, Literal
# pyright: reportCallInDefaultInitializer=false, reportExplicitAny=false

HOME = Path.home()
XDG_RUNTIME_DIR = Path(os.getenv("XDG_RUNTIME_DIR", "/tmp"))
XDG_CONFIG_HOME = Path(os.getenv("XDG_CONFIG_HOME", HOME / ".config"))

DBUS_PROXY_DIR = XDG_RUNTIME_DIR / "bus-proxy"


AccessMode = Literal["ro", "rw", "dev"]


class Bind(TypedDict):
    src: NotRequired[str]
    dest: NotRequired[str]
    mode: NotRequired[AccessMode]
    create: NotRequired[bool]
    glob: NotRequired[str]
    tmpfs: NotRequired[str]


def openfd(content: bytes) -> int:
    r, w = os.pipe2(0)
    os.write(w, content)
    os.close(w)
    return r
