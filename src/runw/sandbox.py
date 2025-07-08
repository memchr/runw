# pyright: reportUninitializedInstanceVariable=false, reportIgnoreCommentWithoutRule=false, reportImplicitStringConcatenation=false

import logging
import os
import subprocess
from glob import glob
from os.path import expandvars
from pathlib import Path
from reprlib import Repr
from typing import Literal, NotRequired, Self, TypedDict
from .constants import (
    DBUS_PROXY_PATH,
    HOME,
    PROTON_PATH,
    XDG_CACHE_HOME,
    XDG_CONFIG_HOME,
    XDG_DATA_HOME,
    XDG_RUNTIME_DIR,
)


MountMode = Literal["dev", "ro", "rw"]


class BindMount(TypedDict):
    src: str | Path
    dest: NotRequired[str | Path]
    mode: NotRequired[str]


class AppConfig(TypedDict):
    cmd: list[str]  # app command
    launcher: NotRequired[list[str]]  # launchers
    home: NotRequired[str]  # where to store home dir data
    binds: list[BindMount | str | Path]  # bind mounts
    nvidia: bool  # enable nvidia GPU, default true
    kill: bool  # kill sandbox processes when bwrap exits, default true
    bus: NotRequired[list[str]]  # dbus proxy args
    system_bus: NotRequired[list[str]]  # dbus proxy args
    share: NotRequired[list[str]]  # host namespaces to share
    sandbox_args: NotRequired[list[str]]
    env: NotRequired[dict[str, str]]


ar = Repr(indent=2, maxdict=200, maxstring=200, maxlist=200)


def run(config: AppConfig, shell=False):
    sandbox, cmd = create(config)
    sandbox.exec(cmd)


def create(config: AppConfig) -> tuple["Sandbox", list[str]]:
    logging.debug("config:\n %s", ar.repr(config))
    sandbox = (
        Sandbox()
        .share(*config.get("share", []))
        .bind(
            "/usr",
            "/etc",
            "/opt",
            "/var/lib/alsa/",
            "/run/systemd/resolve/",
            "/tmp/.X11-unix",
            "/tmp/.ICE-unix",
        )
        .dir(
            "/var/empty",
            "/tmp",
        )
        .link(
            ("/usr/bin", "/bin"),
            ("/usr/bin", "/sbin"),
            ("/usr/lib", "/lib"),
            ("/usr/lib64", "/lib64"),
            ("/run", "/var/run"),
        )
        .options("--proc", "/proc", "--dev", "/dev")
        .bind(
            "/dev/dri",
            "/dev/input",
            "/dev/hugepages",
            *glob("/dev/nvidia*"),
            "/dev/snd",
            "/dev/fuse",
            "/sys/block/",
            "/sys/bus/",
            "/sys/class/",
            "/sys/dev/",
            "/sys/devices/",
            "/sys/module/",
            default_mode="dev",
        )
        .home(config.get("home"))
        .bind(
            # graphics
            *glob(str(XDG_RUNTIME_DIR / "wayland*")),
            # sound
            *glob(str(XDG_RUNTIME_DIR / "pulse*")),
            *glob(str(XDG_RUNTIME_DIR / "pipewire*")),
            # cache
            XDG_CACHE_HOME / "mesa_shader_cache",
            XDG_CACHE_HOME / "radv_builtin_shaders64",
            XDG_CACHE_HOME / "nv",
            XDG_CACHE_HOME / "nvidia",
            XDG_CACHE_HOME / "radv_builtin_shaders",
            XDG_CACHE_HOME / "mesa_shader_cache_db",
            # other
            XDG_CONFIG_HOME / "MangoHud",
            {"src": XDG_CONFIG_HOME / "user-dirs.dirs", "mode": "ro"},
            {"src": XDG_CONFIG_HOME / "user-dirs.locale", "mode": "ro"},
        )
    )

    if config["kill"]:
        logging.debug("Ensures child process dies when bwrap exits")
        sandbox.options("--die-with-parent")

    if config["nvidia"]:
        logging.debug("force nvidia gpu")
        sandbox.setenv(
            __NV_PRIME_RENDER_OFFLOAD="1",
            __GLX_VENDOR_LIBRARY_NAME="nvidia",
            __VK_LAYER_NV_optimus="NVIDIA_only",
            VK_DRIVER_FILES="/usr/share/vulkan/icd.d/nvidia_icd.json",
        )

    if "bus" in config or "system_bus" in config:
        sandbox.dbus_proxy(config.get("bus", []), config.get("system_bus", []))

    # setup launchers and command
    cmd: list[str] = []
    for launcher in config.get("launcher", []):
        match launcher:
            case "mangohud":
                cmd.append("mangohud")
            case "proton":
                compat_data = XDG_DATA_HOME / "proton"
                compat_data.mkdir(exist_ok=True, parents=True)

                logging.debug(
                    "use proton\n"
                    + f"  path: {PROTON_PATH.parent}\n"
                    + f"  prefix: {compat_data}"
                )
                sandbox.setenv(
                    STEAM_COMPAT_CLIENT_INSTALL_PATH=str(XDG_DATA_HOME / "Steam"),
                    STEAM_COMPAT_DATA_PATH=str(compat_data),
                ).bind(compat_data, PROTON_PATH.parent)
                cmd.extend([str(PROTON_PATH), "run"])
            case "wine":
                logging.debug("use wine")
                sandbox.bind(HOME / ".wine")
                cmd.append("wine")
            case _:
                pass
    cmd.extend(expandvars(c) for c in config["cmd"])
    logging.debug("command: %s", cmd)

    sandbox.bind(*config["binds"]).setenv(**config.get("env", {}))

    if shell:
        logging.debug("runing shell")
        sandbox.exec([os.getenv("SHELL", "bash")])
    else:
        sandbox.exec(cmd)


def openfd(content: bytes) -> int:
    r, w = os.pipe()
    os.set_inheritable(r, True)
    os.write(w, content)
    return r


class Sandbox:
    def __init__(self) -> None:
        self._options: list[str] = []

    def exec(self, cmd: list[str]):
        logging.debug("bwrap args %s", ar.repr(self._options))
        os.execvp(
            "bwrap",
            ["bwrap", "--args", str(openfd("\0".join(self._options).encode())), *cmd],
        )

    _BIND_VERBS = {"ro": "--ro-bind-try", "rw": "--bind-try", "dev": "--dev-bind-try"}

    def bind(
        self, *mounts: str | Path | BindMount, default_mode: MountMode = "rw"
    ) -> Self:
        for mount in mounts:
            if isinstance(mount, dict):
                src = expandvars(str(mount["src"]))
                dest = expandvars(str(mount.get("dest", src)))
                mode = self._BIND_VERBS[mount.get("mode", default_mode)]
            else:
                src = dest = expandvars(str(mount))
                mode = self._BIND_VERBS[default_mode]
            self._options.extend([mode, src, dest])
        return self

    def dir(self, *paths: str) -> Self:
        self._options.extend([arg for path in paths for arg in ("--dir", path)])
        return self

    def link(self, *links: tuple[str, str]) -> Self:
        self._options.extend([arg for link in links for arg in ("--symlink", *link)])
        return self

    def setenv(self, **environ: str) -> Self:
        self._options.extend(
            [arg for k, v in environ.items() for arg in ("--setenv", k, str(v))]
        )
        return self

    def home(self, src: str | Path | None) -> Self:
        if src is not None:
            self._options.extend(["--bind", str(expandvars(src)), str(HOME)])
        return self

    def options(self, *options: str) -> Self:
        self._options.extend(options)
        return self

    _unshares = {
        "user": "--unshare-user-try",
        "ipc": "--unshare-ipc",
        "pid": "--unshare-pid",
        "uts": "--unshare-uts",
        "cgroup": "--unshare-cgroup-try",
        "net": "--unshare-net",
    }

    def share(self, *namespaces: str) -> Self:
        self._options.extend(
            [self._unshares[ns] for ns in set(self._unshares.keys()) - set(namespaces)]
        )
        return self

    def dbus_proxy(self, session_bus_filter: list[str], system_bus_filter: list[str]):
        DBUS_PROXY_PATH.mkdir(exist_ok=True, parents=True)

        session_bus = XDG_RUNTIME_DIR / "bus"
        session_bus_proxy = DBUS_PROXY_PATH / str(os.getpid())

        system_bus = Path("/run/dbus/system_bus_socket")
        system_bus_proxy = DBUS_PROXY_PATH / f"{os.getpid()}-system"
        logging.debug(
            f"enabled dbus proxy\n  session bus: {session_bus_proxy}\n  system bus:  {system_bus_proxy}"
        )

        fd_bwrap, fd_dbus_proxy = os.pipe()
        subprocess.Popen(
            [
                "/usr/bin/xdg-dbus-proxy",
                f"--fd={fd_dbus_proxy}",
                # session bus
                os.getenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={session_bus}"),
                str(session_bus_proxy),
                "--filter",
                *session_bus_filter,
                # system bus
                f"unix:path={system_bus}",
                str(system_bus_proxy),
                "--filter",
                *system_bus_filter,
            ],
            pass_fds=[fd_dbus_proxy],
        )

        os.read(fd_bwrap, 1)
        logging.debug("xdg-dbus-proxy is ready")

        os.set_inheritable(fd_bwrap, True)
        self.bind(
            {"src": session_bus_proxy, "dest": session_bus},
            {"src": system_bus_proxy, "dest": system_bus},
        ).options("--sync-fd", str(fd_bwrap))
