from __future__ import annotations

import os
import asyncio
import logging
import argparse
import subprocess
from pathlib import Path
from importlib.resources import files as resource_files

from . import pipewire as pw
from .config import load_config
from .daemon import run

DEFAULT_CONFIG = (
    Path(os.getenv('XDG_CONFIG_HOME', os.path.expanduser('~/.config/')))
    / 'audiofollow'
    / 'config.yaml'
)


def _list_sinks() -> None:
    for name in pw.list_sinks(pw.dump()):
        print(name)


def _list_monitors() -> None:
    # ponytail: kscreen-doctor already prints exactly this, no need to
    # reimplement KDE's output enumeration in Python
    out = subprocess.run(
        ['kscreen-doctor', '-o'], capture_output=True, text=True, check=True
    )
    print(out.stdout)


def _gen_config(config_path: Path) -> None:
    if config_path.exists():
        raise SystemExit(f'Config file already exists at {config_path}')

    config = resource_files('audiofollow').joinpath('data/config.example.yaml')

    config_path.parent.mkdir(parents=True, exist_ok=True)

    with open(config, 'r') as orig, config_path.open('w') as new:
        new.write(orig.read())


def _install_service() -> None:
    install_path = (
        Path(os.getenv('XDG_CONFIG_HOME', os.path.expanduser('~/.config/')))
        / 'systemd'
        / 'user'
        / 'audiofollow.service'
    )

    unit = resource_files('audiofollow').joinpath('data/audiofollow.service')

    with open(unit, 'r') as orig, open(install_path, 'w') as new:
        new.write(orig.read())


def main() -> None:
    p = argparse.ArgumentParser(prog='audiofollow')
    p.add_argument(
        '--config',
        type=Path,
        default=DEFAULT_CONFIG,
        help=f'Path to config file. Default: "{DEFAULT_CONFIG}".',
    )
    p.add_argument('-v', '--verbose', action='store_true', help='DEBUG logging.')
    p.add_argument(
        '--dry-run',
        action='store_true',
        help="Don't actually change the audio sink, just log what would happen.",
    )
    sub = p.add_subparsers(dest='command')
    sub.add_parser('list-sinks', help='List available audio sinks.')
    sub.add_parser('list-monitors', help='List available monitors (outputs).')
    sub.add_parser('gen-config', help='Generate a default config file and exit.')
    sub.add_parser(
        'install-service',
        help='Install the systemd user service and exit. '
        'This is not needed if you install audiofollow as a system package.',
    )

    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s %(levelname)-7s %(message)s',
    )

    if args.command == 'list-sinks':
        _list_sinks()
        return
    if args.command == 'list-monitors':
        _list_monitors()
        return
    if args.command == 'gen-config':
        _gen_config(args.config)
        return
    if args.command == 'install-service':
        _install_service()
        return

    if not args.config.exists():
        raise SystemExit(
            f'No config at {args.config}. Run `audiofollow gen-config` to generate one.'
        )

    cfg = load_config(args.config)

    asyncio.run(run(cfg, dry_run=args.dry_run))


if __name__ == '__main__':
    main()
