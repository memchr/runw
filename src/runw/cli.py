import argparse
import logging
import os
import sys

from runw.config import load_configs, load_presets
from runw.sandbox import Bwrap
# pyright: reportUninitializedInstanceVariable=false


class RunArgumentParser(argparse.ArgumentParser):
    class Arguments(argparse.Namespace):
        verbose: bool
        shell: bool
        cmd: list[str] | None
        container: str | None
        args: list[str]
        list: bool

    def __init__(self):
        super().__init__(
            description="Run preconfigured bubblewrap containers",
            allow_abbrev=False,
            usage="runw [options] container [args]\n       runw -l",
        )
        self.add_argument(
            "-s", "--shell", action="store_true", help="Run a temporary shell"
        )
        self.add_argument(
            "-v", "--verbose", action="store_true", help="Enable debug logging"
        )
        self.add_argument("-c", "--cmd", type=str, help="override app command", nargs=1)
        self.add_argument("-l", "--list", action="store_true", help="List all apps")
        self.add_argument("container", nargs="?")
        self.add_argument("args", nargs=argparse.REMAINDER, help="additional arguments")


def main():
    progname = os.path.basename(sys.argv[0])
    if progname == "runw":
        runw()
    else:
        run_config(progname)


def run_config(profile_name: str):
    presets = load_presets()
    configs = load_configs()
    try:
        sandbox = Bwrap.from_dict(configs[profile_name])
    except KeyError:
        print(f"{profile_name} not found")
        raise SystemExit
    sandbox = sandbox.resolve(presets)
    sandbox.cmd.extend(sys.argv[1:])
    sandbox.exec()


def runw():
    parser = RunArgumentParser()

    args = parser.parse_args(namespace=RunArgumentParser.Arguments())

    if args.verbose:
        log_level = logging.DEBUG
    else:
        log_level = logging.WARNING
    logging.basicConfig(level=log_level, format="[runw %(levelname)s] %(message)s")

    presets = load_presets()
    configs = load_configs()

    if args.list:
        for name, config in configs.items():
            print(f"\033[1m{name:<30}\033[0m{config.get('desc', '')}")
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
