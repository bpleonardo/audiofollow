from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Coroutine
from pathlib import Path
from collections import defaultdict

from dbus_fast.aio import MessageBus
from dbus_fast.service import ServiceInterface, dbus_method
from dbus_fast.annotations import DBusStr, DBusInt32

from . import pipewire as pw

if TYPE_CHECKING:
    from .config import Config

log = logging.getLogger(__name__)

BUS_NAME = 'com.bpleonardo.audiofollow'
BUS_PATH = '/Daemon'

_MISSING: Any = object()


def _app_name(pid: int) -> str:
    try:
        return Path(f'/proc/{pid}/comm').read_text().strip()
    except OSError:
        return f'pid:{pid}'


class AudioFollowService(ServiceInterface):
    def __init__(self, cfg: Config, *, dry_run: bool = False) -> None:
        super().__init__(BUS_NAME)
        self.cfg = cfg
        self.dry_run = dry_run
        self._timers: dict[int, asyncio.TimerHandle] = {}
        self._last_screen: dict[int, str] = {}
        self._locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._tasks = set()

    def _schedule_task(self, coro: Coroutine) -> None:
        # We need to keep track of tasks so that the garbage collector
        # doesn't cancel them before they finish.
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    @dbus_method()
    def WindowMoved(self, pid: DBusInt32, screen: DBusStr):  # noqa: ANN201
        pid = int(pid)
        if self._last_screen.get(pid) == screen:
            log.warning(
                'Got duplicate window move event for pid %d -> %s, ignoring',
                pid,
                screen,
            )
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
            lambda: self._schedule_task(self._resolve(pid, screen)),
        )

    async def clear_locks(self) -> None:
        # We can't clear locks immediately after they are released
        # because there might be some pending tasks awaiting the lock.
        while True:
            await asyncio.sleep(60)
            for pid, lock in tuple(self._locks.items()):
                if not lock.locked():
                    log.debug('Removing unused lock for pid %d', pid)
                    del self._locks[pid]
                await asyncio.sleep(0)  # yield to event loop

    async def _resolve(self, pid: int, screen: str) -> None:  # noqa: C901
        if self._locks[pid].locked():
            log.debug('Waiting lock for pid %d', pid)

        async with self._locks[pid]:
            name = _app_name(pid)

            log.debug("Resolving window move for '%s' (pid %d)", name, pid)

            self._timers.pop(pid, None)

            if name in self.cfg.ignore:
                log.info("Ignoring '%s' (pid %d)", name, pid)
                return

            sink_name = self.cfg.outputs.get(
                screen,
                _MISSING,
            )

            if sink_name is _MISSING:
                log.warning("No sink configured for output '%s'", screen)
                return

            if sink_name is None:
                log.debug("No sink set for output '%s', ignoring", screen)
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
                log.debug("No active audio stream for '%s' (pid %d)", name, pid)
                return

            ignored_sinks = {pw.find_sink_id(sinks, s) for s in self.cfg.fixed_sinks}
            ignored_sinks.discard(None)

            sink_name_by_id = {s.index: s.description or s.name for s in sinks}
            for stream in streams:
                if stream.sink == target_id:
                    continue  # already there.

                if stream.sink in ignored_sinks:
                    log.debug(
                        'Stream %d (%s) is on a fixed sink (%s), ignoring',
                        stream.index,
                        stream.app_name,
                        sink_name_by_id.get(stream.sink or -1, '<unknown>'),
                    )
                    continue

                log.info(
                    "Window '%s' moved to '%s' (pid: %d, stream: %d)",
                    name,
                    screen,
                    pid,
                    stream.index,
                )

                old_sink = sink_name_by_id.get(stream.sink or -1, '<unknown>')

                if self.dry_run:
                    log.info(
                        "[dry-run] Moving stream %d: '%s' -> '%s'",
                        stream.index,
                        old_sink,
                        sink_name,
                    )
                    continue

                log.info(
                    "Moving stream %d: '%s' -> '%s'", stream.index, old_sink, sink_name
                )
                try:
                    await pw.move_stream(stream.index, target_id)
                except Exception:
                    log.exception('Failed to move stream %d', stream.index)


async def run(cfg: Config, *, dry_run: bool = False) -> None:
    service = AudioFollowService(cfg, dry_run=dry_run)

    bus = await MessageBus().connect()
    bus.export(BUS_PATH, service)

    await bus.request_name(BUS_NAME)

    log.info('audiofollow ready, listening on dbus %s', BUS_NAME)
    service._schedule_task(service.clear_locks())

    try:
        await asyncio.Event().wait()  # block forever.
    except KeyboardInterrupt:
        log.info('Shutting down.')
