import argparse
import json
import sys

from societytwin.build.config import BuildError, load_config
from societytwin.build.workflow import build, inspect_build


def main():
    parser = argparse.ArgumentParser(description='Reproducible Ankara population bundles; optional modules remain opt-in.')
    commands = parser.add_subparsers(dest='command',required=True)
    run = commands.add_parser('run')
    run.add_argument('--config',required=True)
    inspect = commands.add_parser('inspect')
    inspect.add_argument('directory')
    args = parser.parse_args()
    try:
        if args.command == 'run':print(build(load_config(args.config)))
        else:print(json.dumps(inspect_build(args.directory),ensure_ascii=False,indent=2))
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print(f'Unified build failed: {exc}',file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
