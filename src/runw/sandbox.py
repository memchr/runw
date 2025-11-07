from glob import glob
import logging
from os.path import expandvars
from pathlib import Path
from dataclasses import dataclass, field
import os
from typing import Any, Self

# pyright: reportCallInDefaultInitializer=false, reportExplicitAny=false
from runw.common import Bind, XDG_RUNTIME_DIR, DBUS_PROXY_DIR, HOME, openfd


@dataclass(kw_only=True)
class Bwrap:
    use: list[str] = field(default_factory=list)

    cmd: list[str] = field(default_factory=list)
    bind: list[str | Bind] = field(default_factory=list)
    # device binds
    dev: list[str | Bind] = field(default_factory=list)
    # symlinks
    link: list[tuple[str, str]] = field(default_factory=list)
    # mkdir
    dir: list[str] = field(default_factory=list)
    bus: list[str] = field(default_factory=list)
    system_bus: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    unsetenv: list[str] = field(default_factory=list)
    share: set[str] = field(default_factory=set)

    # override
    kill: bool | None = None
    home: str | None = None
    chdir: str | None = None
    desc: str | None = None
    rootfs: str | None = None

    _bwrap_argv: list[str] = field(init=False, default_factory=list)

    def __post_init__(self):
        if self.rootfs is not None:
            self.rootfs = expandvars(self.rootfs)
            self._bwrap_argv.extend(["--dev-bind", self.rootfs, "/"])
        self._bwrap_argv.extend(["--proc", "/proc", "--dev", "/dev"])
        # allow use string as cmd
        if isinstance(self.cmd, str):
            self.cmd = [self.cmd]
        if isinstance(self.share, list):
            self.share = set(self.share)

    def merge(self, other: Self):
        # extend
        self.cmd.extend(other.cmd)
        self.bind.extend(other.bind)
        self.dev.extend(other.dev)
        self.link.extend(other.link)
        self.dir.extend(other.dir)
        self.bus.extend(other.bus)
        self.system_bus.extend(other.system_bus)
        self.env.update(other.env)
        self.unsetenv.extend(other.unsetenv)
        self.share = self.share.union(other.share)
        # override
        if other.kill is not None:
            self.kill = other.kill
        self.home = other.home or self.home
        self.chdir = other.chdir or self.chdir
        self.desc = other.desc
        self.rootfs = other.rootfs
        return self

    def resolve(self, presets: dict[str, Self]):
        """Resolve and return a merged configuration by applying presets"""
        resolved = Bwrap(rootfs=self.rootfs).merge(presets["global"])
        if not self.use:
            return resolved.merge(self)

        # Merge each preset only after its dependencies have been merged.
        # Depth-first postorder traversal of DAG
        stack: list[str] = list(reversed(self.use))
        visited: set[str] = set()
        processed: set[str] = set()
        while stack:
            node = stack[-1]
            if node in visited:
                stack.pop()
                continue
            preset = presets[node]
            if node in processed:
                # process it here
                logging.debug(f"using preset: {node}")
                resolved.merge(preset)
                visited.add(stack.pop())
            else:
                stack.extend(reversed(preset.use))
                processed.add(node)
        return resolved.merge(self)

    def exec(self):
        # mount home directory
        if self.home:
            self.home = expandvars(self.home)
            logging.debug(f"home: {self.home}")
            os.makedirs(self.home, exist_ok=True)
            self._bwrap_argv.extend(["--bind", self.home, str(HOME)])

        # unshare namespaces
        self._bwrap_argv.extend(
            [self._unshares[ns] for ns in set(self._unshares.keys()) - set(self.share)]
        )

        # kill process group when sandbox quits
        if self.kill:
            logging.debug("die with parent")
            self._bwrap_argv.append("--die-with-parent")

        # update environment
        os.environ["RUNW"] = "1"
        for k, e in self.env.items():
            os.environ[k] = expandvars(e)
        for e in self.unsetenv:
            self._bwrap_argv.extend(["--unsetenv", e])

        # mounts
        self._bind(self.dev, "dev")
        self._bind(self.bind, "rw")

        # symlinks
        for link in self.link:
            logging.debug(f"symlink: {link[0]} -> {link[1]}")
            self._bwrap_argv.extend(["--symlink", link[0], link[1]])

        # mkdir
        for dir in self.dir:
            logging.debug(f"mkdir: {dir}")
            self._bwrap_argv.extend(["--dir", dir])

        # dbus
        if self.bus or self.system_bus:
            self._start_dbus_proxy()

        # chdir
        if self.chdir:
            self._bwrap_argv.extend(["--chdir", expandvars(self.chdir)])

        # command
        cmd = [expandvars(i) for i in self.cmd]
        logging.debug(f"command: {cmd}")
        logging.debug(f"bwrap args: {self._bwrap_argv}")

        os.execvp(
            "bwrap",
            [
                "bwrap",
                "--args",
                str(openfd("\0".join(self._bwrap_argv).encode())),
                "--",
                *cmd,
            ],
        )

    @classmethod
    def from_dict(cls, config: dict[str, Any]):
        return cls(**{k: v for k, v in config.items() if k in cls.__dataclass_fields__})

    _unshares = {
        "user": "--unshare-user-try",
        "ipc": "--unshare-ipc",
        "pid": "--unshare-pid",
        "uts": "--unshare-uts",
        "cgroup": "--unshare-cgroup-try",
        "net": "--unshare-net",
    }
    _bind_verbs = {"ro": "--ro-bind-try", "rw": "--bind-try", "dev": "--dev-bind-try"}

    def _bind(self, binds: list[str | Bind], default_mode="rw"):
        default_verb = self._bind_verbs[default_mode]
        for bind in binds:
            if isinstance(bind, str):
                path = expandvars(bind)
                logging.debug(f"{default_mode} mount: {path}")
                self._bwrap_argv.extend([default_verb, path, path])
                continue

            mode = bind.get("mode", default_mode)
            verb = self._bind_verbs[mode]
            if "glob" in bind:
                for path in glob(expandvars(bind["glob"])):
                    logging.debug(f"{mode} mount: {path}")
                    self._bwrap_argv.extend([verb, path, path])
            elif "tmpfs" in bind:
                path = expandvars(bind["tmpfs"])
                self._bwrap_argv.extend(["--tmpfs", path])
            elif "src" in bind:
                src = expandvars(bind["src"])
                dest = expandvars(bind["dest"]) if "dest" in bind else src
                logging.debug(f"{mode} mount: {src} -> {dest}")
                if bind.get("create", False):
                    os.makedirs(src, exist_ok=True)
                    logging.debug(f"host mkdir {src}")
                self._bwrap_argv.extend([verb, src, dest])

    def _start_dbus_proxy(self):
        DBUS_PROXY_DIR.mkdir(exist_ok=True, parents=True)

        session_bus = XDG_RUNTIME_DIR / "bus"
        system_bus = Path("/run/dbus/system_bus_socket")
        session_bus_proxy = DBUS_PROXY_DIR / str(os.getpid())
        system_bus_proxy = DBUS_PROXY_DIR / f"{os.getpid()}-system"

        fd_bwrap, fd_dbus_proxy = os.pipe2(0)
        if os.fork() == 0:
            os.close(fd_bwrap)
            os.execlp(
                "xdg-dbus-proxy",
                "xdg-dbus-proxy",
                f"--fd={fd_dbus_proxy}",
                # session bus
                os.getenv("DBUS_SESSION_BUS_ADDRESS", f"unix:path={session_bus}"),
                str(session_bus_proxy),
                "--filter", *self.bus,
                # system bus
                f"unix:path={system_bus}",
                str(system_bus_proxy),
                "--filter", *self.system_bus,
            )  # fmt: skip

        assert os.read(fd_bwrap, 1) == b"x"
        self._bwrap_argv.extend([
            "--bind", str(session_bus_proxy), str(session_bus),
            "--bind", str(system_bus_proxy), str(system_bus),
            "--sync-fd", str(fd_bwrap)
        ])  # fmt: skip
        logging.debug("xdg-dbus-proxy is ready")
