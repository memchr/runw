import argparse
import logging
import sys
import tomllib
from .sandbox import run, AppConfig
from .constants import XDG_CONFIG_HOME


# pyright: reportUninitializedInstanceVariable=false, reportIgnoreCommentWithoutRule=false, reportImplicitStringConcatenation=false

CONFIG_PATH = XDG_CONFIG_HOME / "runw.toml"


class Arguments(argparse.Namespace):
    verbose: bool
    shell: bool
    cmd: list[str] | None
    app: str | None
    args: list[str]
    list: bool


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-s", "--shell", action="store_true", help="Run a temporary shell"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging"
    )
    parser.add_argument("-c", "--cmd", type=str, help="override app command", nargs=1)
    parser.add_argument("-l", "--list", action="store_true", help="List all apps")
    parser.add_argument("app", nargs="?", help="name of the app")
    parser.add_argument("args", nargs=argparse.REMAINDER)

    args = parser.parse_args(namespace=Arguments())

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    with (CONFIG_PATH).open("rb") as f:
        configs: dict[str, AppConfig] = tomllib.load(f)

    if args.list:
        try:
            del configs["default"]
        except KeyError:
            pass
        for key in configs:
            print(key)
        return 0

    if args.app is None:
        parser.error("name of the app is required")

    app: str = args.app.lower()
    if app not in configs:
        parser.error(f"{app} not found")

    default = configs.get("default", {})
    config = configs[app]

    def get(x: str, y):
        return config.get(x, default.get(x, y))  # pyright: ignore

    run(
        {
            **config,
            "cmd": (args.cmd or config["cmd"]) + args.args,
            "nvidia": get("nvidia", False),
            "kill": get("kill", False),
            "binds": default.get("binds", []) + config.get("binds", []),
        },
        shell=args.shell,
    )
