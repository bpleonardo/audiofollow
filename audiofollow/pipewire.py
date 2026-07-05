"""
PipeWire access entirely through pactl (its pipewire-pulse compat layer).

Matching a window to its audio stream turned out to need two entirely
different strategies, not one, learned from three real failures in a row:

1. pactl sink-input indices / sink indices are pactl's own index space,
   unrelated to PipeWire node ids from pw-dump. Everything below stays
   inside pactl's id space so a move never crosses spaces.

2. PID MATCHING (non-flatpak apps): a stream's own application.process.id
   is self-reported and can't be trusted blindly (Spotify native-protocol
   case). pipewire.sec.pid (kernel-verified socket peer) is trustworthy
   for native clients, but for anything routed through pipewire-pulse
   (Brave, Firefox, most non-native apps) the socket peer is the
   pipewire-pulse *daemon itself* - same value for every app on that path,
   useless. For those, application.process.id is the real per-app pid
   forwarded from the PulseAudio protocol - and since it can differ from
   the window's own pid (browser audio lives in a child process), matching
   walks the /proc parent chain rather than requiring equality.

3. FLATPAK MATCHING: none of the above works for a flatpak app. Its
   self-reported pid is relative to its own pid namespace (meaningless
   outside it), AND if it's also routed through pipewire-pulse, sec.pid is
   the daemon again. But flatpak stamps a portal instance id on both ends
   independently of any of that: PipeWire clients get
   `pipewire.access.portal.instance_id`, and systemd puts the identical
   number in the window process's own cgroup path
   (.../app-flatpak-<app-id>-<instance-id>.scope). Matching on that number
   sidesteps pids entirely, so it's used whenever it's available.
"""

from __future__ import annotations

import re
import logging
from pathlib import Path
from dataclasses import dataclass

from .utils import sp_run

log = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class Stream:
    index: int  # pactl sink-input index - same id space move_stream expects
    app_name: str
    sink: int | None  # pactl sink index this stream is currently on


@dataclass(slots=True, frozen=True)
class _ClientInfo:
    pid: int | None
    portal_instance: str | None


async def _pactl_list(kind: str) -> str:
    return await sp_run(
        ['pactl', 'list', kind], capture_output=True, text=True, timeout=5, check=True
    )


async def list_sinks() -> dict[str, int]:
    """name/description (lowercased) -> pactl sink index, for every sink."""
    text = await _pactl_list('sinks')
    sinks: dict[str, int] = {}
    for m in re.finditer(
        r'^Sink #(\d+)\n(.*?)(?=^Sink #\d+|\Z)', text, re.MULTILINE | re.DOTALL
    ):
        idx, body = int(m.group(1)), m.group(2)
        for field in ('Description', 'Name'):
            fm = re.search(rf'^\s*{field}: (.+)$', body, re.MULTILINE)
            if fm:
                sinks[fm.group(1).strip().lower()] = idx
    return sinks


def find_sink_id(sinks: dict[str, int], configured_name: str) -> int | None:
    """Find a sink index by name or description, case-insensitive."""
    target = configured_name.lower()
    if target in sinks:
        return sinks[target]
    for name, idx in sinks.items():
        if target in name:
            return idx
    return None


def portal_instance_from_cgroup(pid: int) -> str | None:
    """
    Flatpak's portal instance id, read from a process's own cgroup path.

    Path looks like .../app-flatpak-org.mozilla.firefox-2971616599.scope -
    the trailing digits before .scope are the instance id. None for a
    non-flatpak process (no such scope in its cgroup).
    """
    try:
        cgroup = Path(f'/proc/{pid}/cgroup').read_text()
    except OSError:
        return None
    m = re.search(r'app-flatpak-.+-(\d+)\.scope', cgroup)
    return m.group(1) if m else None


async def _client_infos() -> dict[int, _ClientInfo]:
    """
    pactl client index -> (real pid or None, portal instance id or None).

    See module docstring for why both fields exist and why neither one
    alone is enough.
    """
    text = await _pactl_list('clients')
    clients: dict[int, _ClientInfo] = {}
    for m in re.finditer(
        r'^Client #(\d+)\n(.*?)(?=^Client #\d+|\Z)', text, re.MULTILINE | re.DOTALL
    ):
        idx, body = int(m.group(1)), m.group(2)

        instance_m = re.search(r'pipewire\.access\.portal\.instance_id = "(\d+)"', body)
        portal_instance = instance_m.group(1) if instance_m else None

        is_pulse_proxied = 'client.api = "pipewire-pulse"' in body
        if is_pulse_proxied:
            pid_m = re.search(r'application\.process\.id = "(\d+)"', body)
        else:
            pid_m = re.search(r'pipewire\.sec\.pid = "(\d+)"', body) or re.search(
                r'application\.process\.id = "(\d+)"', body
            )
        pid = int(pid_m.group(1)) if pid_m else None

        clients[idx] = _ClientInfo(pid=pid, portal_instance=portal_instance)
    return clients


def _ppid(pid: int) -> int | None:
    """Parent pid of `pid`, or None if it's gone/unreadable. stdlib /proc read."""
    try:
        stat = Path(f'/proc/{pid}/stat').read_text()
    except OSError:
        return None
    # Format: "pid (comm) state ppid ..." - comm can contain ')' itself,
    # so split on the *last* ')' rather than the first.
    fields = stat.rsplit(')', 1)[-1].split()
    return int(fields[1])  # fields[0] is state, fields[1] is ppid


def _is_pid_or_descendant(pid: int, window_pid: int, max_depth: int = 32) -> bool:
    """
    True if `pid` is `window_pid` or a child/grandchild/... of it.

    Needed because multi-process apps (every Chromium/Firefox-based
    browser) put the window in one process and the audio stream in a
    different, separately-pid'd child process.
    """
    current = pid
    for _ in range(max_depth):
        if current == window_pid:
            return True
        if current is None or current <= 1:
            return False
        current = _ppid(current)
    return False


async def streams_for_window(window_pid: int) -> list[Stream]:
    """
    All sink-inputs belonging to the app that owns `window_pid`.

    If the window belongs to a flatpak app, matching goes through the
    portal instance id (see module docstring) instead of any pid at all -
    that's the only signal that's reliable for a sandboxed app regardless
    of which PipeWire protocol path it uses. Otherwise, falls back to
    pid/ancestry matching.
    """
    portal_instance = portal_instance_from_cgroup(window_pid)
    clients = await _client_infos()

    if portal_instance:
        log.debug(
            'Window pid %d is flatpak, matching on portal instance %s',
            window_pid,
            portal_instance,
        )
        matching_clients = {
            idx for idx, c in clients.items() if c.portal_instance == portal_instance
        }
    else:
        log.debug('Window pid %d is not flatpak, matching on pid/ancestry', window_pid)
        matching_clients = {
            idx
            for idx, c in clients.items()
            if c.pid is not None and _is_pid_or_descendant(c.pid, window_pid)
        }

    if not matching_clients:
        return []

    text = await _pactl_list('sink-inputs')
    result = []
    for m in re.finditer(
        r'^Sink Input #(\d+)\n(.*?)(?=^Sink Input #\d+|\Z)',
        text,
        re.MULTILINE | re.DOTALL,
    ):
        idx, body = int(m.group(1)), m.group(2)
        client_m = re.search(r'^\s*Client: (\d+)$', body, re.MULTILINE)
        if not client_m or int(client_m.group(1)) not in matching_clients:
            continue
        sink_m = re.search(r'^\s*Sink: (\d+)$', body, re.MULTILINE)
        name_m = re.search(r'application\.name = "([^"]*)"', body)
        result.append(
            Stream(
                index=idx,
                app_name=name_m.group(1) if name_m else '?',
                sink=int(sink_m.group(1)) if sink_m else None,
            )
        )
    return result


async def move_stream(stream_index: int, sink_index: int) -> None:
    """
    Move a running sink-input to a different sink.

    Both ids are pactl indices (see module docstring) - both must come from list_sinks()/streams_for_window() above,
    never from pw-dump.
    """
    log.debug(
        'pactl move-sink-input %d %d (%s)',
        stream_index,
        sink_index,
        await sp_run(
            ['pactl', 'move-sink-input', str(stream_index), str(sink_index)],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ),
    )
