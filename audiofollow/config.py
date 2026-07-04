from __future__ import annotations

from typing import TYPE_CHECKING
from dataclasses import field, dataclass

import yaml

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class Config:
    outputs: dict[str, str] = field(default_factory=dict)
    ignore: list[str] = field(default_factory=list)
    debounce_ms: int = 300


def load_config(path: Path) -> Config:
    data = yaml.safe_load(path.read_text()) or {}
    return Config(
        outputs={str(k): str(v) for k, v in (data.get('outputs') or {}).items()},
        ignore=list(data.get('ignore') or []),
        debounce_ms=int(data.get('debounce_ms', 300)),
    )
