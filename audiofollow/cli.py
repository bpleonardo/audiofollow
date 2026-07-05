from __future__ import annotations

import os
import asyncio
import argparse
import subprocess
from shutil import which
from pathlib import Path
from importlib.resources import files as resource_files

from rich.console import Console

from . import pipewire as pw
from .utils import setup_logging
from .config import load_config
from .daemon import run

DEFAULT_CONFIG = (
    Path(os.getenv('XDG_CONFIG_HOME', os.path.expanduser('~/.config/')))
    / 'audiofollow'
    / 'config.yaml'
)


async def _list_sinks() -> None:
    console = Console()

    sinks = tuple((await pw.list_sinks()).keys())
    # Due to the way we query the sinks, they are returned in pairs of (description, name).
    mapping = {sinks[i + 1]: sinks[i] for i in range(0, len(sinks), 2)}

    console.print(
        "[bold blue]Here's a list of connected sinks. "
        'You can use either the ID or the description in your config file.[/]\n'
    )

    for name, desc in mapping.items():
        console.print(
            f'[bold yellow]ID:[/] {name}\n[bold yellow]Description:[/] {desc.capitalize()}\n'
        )


def _list_monitors() -> None:
    console = Console()
    console.print("[bold blue]Here's a list of connected monitors (outputs):[/]\n")

    if which('kscreen-doctor') is not None:
        out = subprocess.run(
            ['kscreen-doctor', '-o'], capture_output=True, text=True, check=True
        )
        print(out.stdout)
        return

    # We don't have kscreen-doctor, fallback to filesystem inspection.
    monitors = Path('/sys/class/drm').glob('card*-*/status')
    for m in monitors:
        if m.read_text().strip() == 'connected':
            console.print(f'[bold yellow]Monitor:[/] {m.parent.name.split("-", 1)[1]}')


def _gen_config(config_path: Path) -> None:
    if config_path.exists():
        raise SystemExit(f'Config file already exists at {config_path}')

    config = resource_files('audiofollow').joinpath('data/config.example.yaml')

    config_path.parent.mkdir(parents=True, exist_ok=True)

    with open(config, 'r') as orig, config_path.open('w') as new:
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

    args = p.parse_args()

    setup_logging(verbose=args.verbose)

    if args.command == 'list-sinks':
        asyncio.run(_list_sinks())
        return
    if args.command == 'list-monitors':
        _list_monitors()
        return
    if args.command == 'gen-config':
        _gen_config(args.config)
        return

    if not args.config.exists():
        raise SystemExit(
            f'No config at {args.config}. Run `audiofollow gen-config` to generate one.'
        )

    cfg = load_config(args.config)

    asyncio.run(run(cfg, dry_run=args.dry_run))


if __name__ == '__main__':
    main()
