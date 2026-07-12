import asyncio
import logging
import contextlib
import subprocess
from typing import Sequence

from rich.console import Console
from rich.logging import RichHandler

SIMPLE_LOG_FORMAT = '[%(asctime)s] [%(levelname)-7s] %(name)s: %(message)s'


def setup_logging(*, verbose: bool = False) -> None:
    """Set up logging with rich if color available, otherwise fallback to simple logging."""
    level = logging.DEBUG if verbose else logging.INFO
    if Console().color_system is not None:
        logging.basicConfig(
            level=level,
            format='%(message)s',
            datefmt='[%X]',
            handlers=[RichHandler(rich_tracebacks=True)],
        )
    else:
        logging.basicConfig(level=level, format=SIMPLE_LOG_FORMAT)


async def sp_run(
    cmd: Sequence[str],
    *,
    capture_output: bool = True,
    check: bool = True,
    text: bool = False,
    timeout: float | None = None,
):
    """Run a subprocess command asynchronously, with optional output capture and timeout."""
    cm = asyncio.timeout(timeout) if timeout is not None else contextlib.nullcontext()

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.PIPE if capture_output else None
    )

    stdout = None

    async with cm:
        if capture_output:
            stdout, _ = await proc.communicate()
        else:
            await proc.wait()

    if check and proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd, output=stdout)

    return stdout.decode('utf-8') if text and stdout is not None else stdout
