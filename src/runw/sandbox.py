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
    no_default: bool | None = None

    def __post_init__(self):
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
        if other.no_default is not None:
            self.no_default = other.no_default
        return self

    def resolve(self, presets: dict[str, Self]):
        """Resolve and return a merged configuration by applying presets"""
        resolved = Bwrap()
        if not self.no_default:
            resolved.merge(presets["default"])
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
        argv = []

        # custom rootfs
        if self.rootfs is not None:
            argv.extend(["--dev-bind", expandvars(self.rootfs), "/"])

        # /dev and /proc pseudo filesystem
        argv.extend(["--proc", "/proc", "--dev", "/dev"])

        # mount home directory
        if self.home:
            self.home = expandvars(self.home)
            logging.debug(f"home: {self.home}")
            os.makedirs(self.home, exist_ok=True)
            argv.extend(["--bind", self.home, str(HOME)])

        # unshare namespaces
        argv.extend(
            [self._unshares[ns] for ns in set(self._unshares.keys()) - set(self.share)]
        )

        # kill process group when sandbox quits
        if self.kill:
            logging.debug("die with parent")
            argv.append("--die-with-parent")

        # update environment
        os.environ["RUNW"] = "1"
        for k, e in self.env.items():
            os.environ[k] = expandvars(e)
        for e in self.unsetenv:
            argv.extend(["--unsetenv", e])

        # mounts
        self._bind(self.dev, argv, default_mode="dev")
        self._bind(self.bind, argv, default_mode="rw")

        # symlinks
        for link in self.link:
            logging.debug(f"symlink: {link[0]} -> {link[1]}")
            argv.extend(["--symlink", link[0], link[1]])

        # mkdir
        for dir in self.dir:
            logging.debug(f"mkdir: {dir}")
            argv.extend(["--dir", dir])

        # dbus
        if self.bus or self.system_bus:
            self._start_dbus_proxy(argv)

        # chdir
        if self.chdir:
            argv.extend(["--chdir", expandvars(self.chdir)])

        # command
        cmd = [expandvars(i) for i in self.cmd]
        logging.debug(f"command: {cmd}")
        logging.debug(f"bwrap args: {argv}")

        os.execvp(
            "bwrap",
            [
                "bwrap",
                "--args",
                str(openfd("\0".join(argv).encode())),
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

    def _bind(
        self,
        binds: list[str | Bind],
        argv: list[str],
        default_mode="rw",
    ):
        default_verb = self._bind_verbs[default_mode]
        for bind in binds:
            if isinstance(bind, str):
                path = expandvars(bind)
                logging.debug(f"{default_mode} mount: {path}")
                argv.extend([default_verb, path, path])
                continue

            mode = bind.get("mode", default_mode)
            verb = self._bind_verbs[mode]
            if "glob" in bind:
                for path in glob(expandvars(bind["glob"])):
                    logging.debug(f"{mode} mount: {path}")
                    argv.extend([verb, path, path])
            elif "tmpfs" in bind:
                path = expandvars(bind["tmpfs"])
                argv.extend(["--tmpfs", path])
            elif "src" in bind:
                src = expandvars(bind["src"])
                dest = expandvars(bind["dest"]) if "dest" in bind else src
                logging.debug(f"{mode} mount: {src} -> {dest}")
                if bind.get("create", False):
                    os.makedirs(src, exist_ok=True)
                    logging.debug(f"host mkdir {src}")
                argv.extend([verb, src, dest])

    def _start_dbus_proxy(self, argv: list[str]):
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
        argv.extend([
            "--bind", str(session_bus_proxy), str(session_bus),
            "--bind", str(system_bus_proxy), str(system_bus),
            "--sync-fd", str(fd_bwrap)
        ])  # fmt: skip
        logging.debug("xdg-dbus-proxy is ready")
