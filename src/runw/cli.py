import argparse
import logging
import os

from runw.config import load_configs, load_presets
from runw.sandbox import Bwrap
# pyright: reportUninitializedInstanceVariable=false


class Arguments(argparse.Namespace):
    verbose: bool
    shell: bool
    cmd: list[str] | None
    container: str | None
    args: list[str]
    list: bool


def main():
    parser = argparse.ArgumentParser(
        description="Run preconfigured bubblewrap containers",
        allow_abbrev=False,
        usage="runw [options] container [args]\n       runw -l",
    )
    parser.add_argument(
        "-s", "--shell", action="store_true", help="Run a temporary shell"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable debug logging"
    )
    parser.add_argument("-c", "--cmd", type=str, help="override app command", nargs=1)
    parser.add_argument("-l", "--list", action="store_true", help="List all apps")
    parser.add_argument("container", nargs="?")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="additional arguments")

    args = parser.parse_args(namespace=Arguments())

    if args.verbose:
        log_level = logging.DEBUG
    else:
        log_level = logging.WARNING
    logging.basicConfig(level=log_level, format="[runw %(levelname)s] %(message)s")

    presets = load_presets()
    configs = load_configs()

    if args.list:
        for k in configs:
            print(k)
        return 0

    if args.container is None:
        parser.error("the following arguments are required: container")
    try:
        sandbox = Bwrap.from_dict(configs[args.container.lower()])
    except KeyError:
        parser.error(f"{args.container} not found")

    sandbox = sandbox.resolve(presets)
    if args.cmd:
        sandbox.cmd = args.cmd
    if args.args:
        sandbox.cmd.extend(args.args)
    if args.shell:
        sandbox.cmd = [os.getenv("SHELL", "bash")]
    sandbox.exec()
