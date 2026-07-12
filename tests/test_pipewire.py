"""Self-check for pipewire.py's pactl text parser, as unittest.

Fixtures are real pactl/ps/cgroup output (trimmed), covering three distinct
real-world failures this hit, each requiring a genuinely different fix:

1. Flatpak Spotify (native PipeWire protocol): self-reported
   application.process.id ("4") is sandbox-internal, wrong. Fix: use the
   Client's kernel-verified pipewire.sec.pid (4420) instead.

2. Brave (routed through pipewire-pulse, like most non-native apps):
   pipewire.sec.pid is USELESS here - it's always the pipewire-pulse
   daemon's own pid (1514), the same for every app on that path. Fix: use
   application.process.id (6676) instead, walking /proc ancestry since
   it's a child of the window's pid (6284), not the window's pid itself.

3. Flatpak Firefox (ALSO routed through pipewire-pulse): neither of the
   above works - sec.pid is the daemon again, AND application.process.id
   ("2") is sandbox-internal again. Fix: match on the flatpak portal
   instance id instead of any pid - it's stamped on the PipeWire client
   (pipewire.access.portal.instance_id) and independently on the window
   process's own cgroup (.../app-flatpak-<id>-<instance>.scope), so the
   two can be compared with no pid involved at all.

Run with:
    python -m unittest test_pipewire -v
"""

import re
import unittest

from audiofollow import pipewire as pw

SINKS_TEXT = """\
Sink #42
	State: RUNNING
	Name: alsa_output.pci-0000_01_00.1.hdmi-stereo
	Description: LG TV (HDMI)
	Driver: PipeWire

Sink #55
	State: RUNNING
	Name: alsa_output.pci-0000_00_1b.0.analog-stereo
	Description: Caixa de som
	Driver: PipeWire
"""

CLIENTS_TEXT = """\
Client #90
	Driver: PipeWire
	Owner Module: 2
	Properties:
		pipewire.protocol = "protocol-native"
		pipewire.sec.pid = "4420"
		application.name = "Spotify"
		application.process.binary = "spotify"
		application.process.id = "4"

Client #1168
	Driver: PipeWire
	Owner Module: 2
	Properties:
		pipewire.protocol = "protocol-native"
		pipewire.sec.pid = "1514"
		client.api = "pipewire-pulse"
		application.name = "Brave"
		application.process.id = "6676"
		application.process.binary = "brave"

Client #1588
	Driver: PipeWire
	Owner Module: 2
	Properties:
		pipewire.protocol = "protocol-native"
		pipewire.sec.pid = "1514"
		client.api = "pipewire-pulse"
		pipewire.access.portal.app_id = "org.mozilla.firefox"
		pipewire.access.portal.instance_id = "2971616599"
		pipewire.client.access = "flatpak"
		application.name = "Firefox"
		application.process.id = "2"
		application.process.binary = "firefox-bin"
"""

SINK_INPUTS_TEXT = """\
Sink Input #91
	Driver: PipeWire
	Owner Module: n/a
	Client: 90
	Sink: 55
	Sample Specification: float32le 2ch 44100Hz
	Properties:
		media.name = "Spotify"
		application.name = "Spotify"
		application.process.id = "4"
		media.class = "Stream/Output/Audio"

Sink Input #100
	Driver: PipeWire
	Client: 1168
	Sink: 42
	Properties:
		client.api = "pipewire-pulse"
		application.name = "Brave"
		application.process.id = "6676"

Sink Input #123
	Driver: PipeWire
	Client: 1588
	Sink: 55
	Properties:
		client.api = "pipewire-pulse"
		pipewire.access.portal.app_id = "org.mozilla.firefox"
		pipewire.access.portal.instance_id = "2971616599"
		application.name = "Firefox"
		application.process.id = "2"
"""

FAKE_PACTL = {
    'sinks': SINKS_TEXT,
    'clients': CLIENTS_TEXT,
    'sink-inputs': SINK_INPUTS_TEXT,
}

# Brave: window pid 6284, real audio pid 6676 is its direct child.
FAKE_PPIDS = {6676: 6284, 6284: 1103, 1103: 1}

# Window pids -> fake /proc/<pid>/cgroup content. Only the Firefox window
# is a flatpak app - Spotify/Brave's window pids have no such scope.
FAKE_CGROUPS = {
    24980: '0::/user.slice/user-1000.slice/user@1000.service/app.slice/'
    'app-flatpak-org.mozilla.firefox-2971616599.scope',
    6284: '0::/user.slice/user-1000.slice/user@1000.service/app.slice/'
    'app-org.chromium.Chromium-6284.scope',
}


async def fake_pactl_list(kind: str) -> str:  # noqa: RUF029
    return FAKE_PACTL[kind]


def _fake_portal_instance(pid: int) -> str | None:
    m = re.search(r'app-flatpak-.+-(\d+)\.scope', FAKE_CGROUPS.get(pid, ''))
    return m.group(1) if m else None


class PipewireParserTests(unittest.IsolatedAsyncioTestCase):
    """The one subprocess boundary (_pactl_list) and the two /proc reads
    (_ppid, portal_instance_from_cgroup) are monkeypatched here so every
    test runs against fixed, real-world-derived text with no live
    PipeWire/pactl/kernel needed.
    """

    def setUp(self) -> None:
        pw._pactl_list = fake_pactl_list  # type: ignore
        pw._ppid = lambda pid: FAKE_PPIDS.get(pid)  # type: ignore
        pw.portal_instance_from_cgroup = _fake_portal_instance  # type: ignore

    async def test_list_sinks(self) -> None:
        sinks = await pw.list_sinks()
        self.assertEqual(sinks['lg tv (hdmi)'], 42)
        self.assertEqual(sinks['caixa de som'], 55)

    async def test_find_sink_id_exact_and_substring(self) -> None:
        sinks = await pw.list_sinks()
        self.assertEqual(pw.find_sink_id(sinks, 'LG TV'), 42)
        self.assertIsNone(pw.find_sink_id(sinks, 'nonexistent'))

    async def test_native_client_matches_via_sec_pid(self) -> None:
        """Spotify: self-reported pid ("4") is sandbox-internal and wrong;
        matching must go through the kernel-verified pipewire.sec.pid."""
        streams = await pw.streams_for_window(4420)
        self.assertEqual(len(streams), 1)
        self.assertEqual(streams[0].index, 91)
        self.assertEqual(streams[0].app_name, 'Spotify')

    async def test_native_client_wrong_self_reported_pid_does_not_match(self) -> None:
        self.assertEqual(await pw.streams_for_window(4), [])

    async def test_pulse_proxied_client_matches_via_ancestry(self) -> None:
        """Brave: sec.pid is the pipewire-pulse daemon's own pid (useless);
        real pid (6676) is a child of the window's pid (6284), not equal."""
        streams = await pw.streams_for_window(6284)
        self.assertEqual(len(streams), 1)
        self.assertEqual(streams[0].index, 100)
        self.assertEqual(streams[0].app_name, 'Brave')

    async def test_pulse_daemon_pid_does_not_false_match_everything(self) -> None:
        self.assertEqual(await pw.streams_for_window(1514), [])

    async def test_flatpak_client_matches_via_portal_instance(self) -> None:
        """Firefox flatpak: both sec.pid (daemon) and self-reported pid
        ("2", sandbox-internal) are useless; only the portal instance id
        shared between the client and the window's cgroup works."""
        streams = await pw.streams_for_window(24980)
        self.assertEqual(len(streams), 1)
        self.assertEqual(streams[0].index, 123)
        self.assertEqual(streams[0].app_name, 'Firefox')

    async def test_unrelated_pid_matches_nothing(self) -> None:
        self.assertEqual(await pw.streams_for_window(99999), [])


if __name__ == '__main__':
    unittest.main()
