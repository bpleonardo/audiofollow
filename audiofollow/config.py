from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from dataclasses import field, dataclass

import yaml

if TYPE_CHECKING:
    from pathlib import Path

log = logging.getLogger(__name__)


@dataclass(slots=True)
class Config:
    outputs: dict[str, str | None] = field(default_factory=dict)
    ignore: list[str] = field(default_factory=list)
    fixed_sinks: list[str] = field(default_factory=list)
    debounce_ms: int = 300
    _mtime: float | None = field(default=None, init=False, repr=False, compare=False)
    _path: Path | None = field(default=None, init=False, repr=False, compare=False)

    @classmethod
    def load_from_file(cls, path: Path) -> Config:
        """Load configuration from a YAML file."""
        data = yaml.safe_load(path.read_text()) or {}

        log.debug("Loading config from '%s' (content: `%s`)", path, data)

        instance = cls(
            outputs={
                str(k): str(v) if v is not None else None
                for k, v in (data.get('outputs') or {}).items()
            },
            ignore=list(data.get('ignore') or []),
            fixed_sinks=list(data.get('fixed_sinks') or []),
            debounce_ms=int(data.get('debounce_ms', 300)),
        )
        instance._mtime = path.stat().st_mtime
        instance._path = path
        return instance

    def update_if_needed(self) -> None:
        """Reload the config if the file has changed."""
        if self._path is None:
            return

        mtime = self._path.stat().st_mtime
        if self._mtime is None or mtime > self._mtime:
            log.info("Config file '%s' changed, reloading", self._path)
            new_config = Config.load_from_file(self._path)
            self.outputs = new_config.outputs
            self.ignore = new_config.ignore
            self.fixed_sinks = new_config.fixed_sinks
            self.debounce_ms = new_config.debounce_ms
            self._mtime = mtime


def load_config(path: Path) -> Config:
    """Load configuration from a YAML file."""

    data = yaml.safe_load(path.read_text()) or {}

    log.debug("Loading config from '%s' (content: `%s`)", path, data)

    return Config(
        outputs={
            str(k): str(v) if v is not None else None
            for k, v in (data.get('outputs') or {}).items()
        },
        ignore=list(data.get('ignore') or []),
        fixed_sinks=list(data.get('fixed_sinks') or []),
        debounce_ms=int(data.get('debounce_ms', 300)),
    )
