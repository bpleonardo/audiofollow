from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING
from pathlib import Path

from dbus_fast.aio import MessageBus
from dbus_fast.service import ServiceInterface, dbus_method
from dbus_fast.annotations import DBusStr, DBusInt32

from . import pipewire as pw

if TYPE_CHECKING:
    from .config import Config

log = logging.getLogger(__name__)

BUS_NAME = 'com.bpleonardo.audiofollow'
BUS_PATH = '/Daemon'


def _app_name(pid: int) -> str:
    try:
        return Path(f'/proc/{pid}/comm').read_text().strip()
    except OSError:
        return f'pid:{pid}'


class AudioFollowService(ServiceInterface):
    def __init__(self, cfg: 'Config', *, dry_run: bool = False):
        super().__init__(BUS_NAME)
        self.cfg = cfg
        self.dry_run = dry_run
        self._timers: dict[int, asyncio.TimerHandle] = {}
        self._last_screen: dict[int, str] = {}

    @dbus_method()
    def WindowMoved(self, pid: DBusInt32, screen: DBusStr):
        pid = int(pid)
        if self._last_screen.get(pid) == screen:
            return
        self._last_screen[pid] = screen

        log.debug('Window moved: pid %d -> %s', pid, screen)

        old = self._timers.pop(pid, None)
        if old:
            log.debug('Cancelling pending timer for pid %d', pid)
            old.cancel()

        loop = asyncio.get_event_loop()

        log.debug('Scheduling debounce timer for pid %d', pid)
        self._timers[pid] = loop.call_later(
            self.cfg.debounce_ms / 1000,
            lambda: asyncio.create_task(self._resolve(pid, screen)),
        )

    async def _resolve(self, pid: int, screen: str) -> None:  # noqa: C901
        log.debug('Resolving window move for pid %d', pid)

        self._timers.pop(pid, None)
        name = _app_name(pid)

        if name in self.cfg.ignore:
            log.debug('Ignoring %s (pid %d)', name, pid)
            return

        sink_name = self.cfg.outputs.get(screen)
        if not sink_name:
            log.warning('No sink configured for output %s', screen)
            return

        try:
            sinks = await pw.list_sinks()
        except Exception:
            log.exception('pactl list sinks failed')
            return

        target_id = pw.find_sink_id(sinks, sink_name)
        if target_id is None:
            log.warning("Sink '%s' not found (unplugged?)", sink_name)
            return

        try:
            streams = await pw.streams_for_window(pid)
        except Exception:
            log.exception('pactl list sink-inputs failed')
            return

        if not streams:
            log.debug('No active audio stream for %s (pid %d)', name, pid)
            return

        sink_name_by_id = {v: k for k, v in sinks.items()}
        for stream in streams:
            if stream.sink == target_id:
                continue  # already there.

            log.info(
                'Window %s moved to %s. (pid: %d, stream: %d)',
                name,
                screen,
                pid,
                stream.index,
            )

            old_sink = sink_name_by_id.get(stream.sink, '?')
            if self.dry_run:
                log.info(
                    '[dry-run] Moving stream %d: %s -> %s',
                    stream.index,
                    old_sink,
                    sink_name,
                )
                continue

            log.info('Moving stream %d (%s -> %s)', stream.index, old_sink, sink_name)
            try:
                await pw.move_stream(stream.index, target_id)
            except Exception:
                log.exception('Failed to move stream %d', stream.index)


async def run(cfg: 'Config', *, dry_run: bool = False) -> None:
    service = AudioFollowService(cfg, dry_run=dry_run)

    bus = await MessageBus().connect()
    bus.export(BUS_PATH, service)

    await bus.request_name(BUS_NAME)

    log.info('audiofollow ready, listening on dbus %s', BUS_NAME)

    await asyncio.Event().wait()  # block forever.
