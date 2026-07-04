import logging

try:
    import rich
    from rich.console import Console
    from rich.logging import RichHandler
except ImportError:
    rich = None
    Console = None
    RichHandler = None

SIMPLE_LOG_FORMAT = '[%(asctime)s] [%(levelname)-7s] %(name)s: %(message)s'


def setup_logging(*, verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    if rich and Console().color_system is not None:
        logging.basicConfig(
            level=level,
            format='%(message)s',
            datefmt='[%X]',
            handlers=[RichHandler(rich_tracebacks=True)],
        )
    else:
        logging.basicConfig(level=level, format=SIMPLE_LOG_FORMAT)
