// audiofollow KWin script.
//
// Job: whenever a window's geometry changes, work out which output has the
// most overlap with it, and if that's a different output than last time,
// call a D-Bus method on the Python daemon. That's it - all matching,
// debouncing, and PipeWire work happens in Python. This script never
// touches the filesystem or spawns processes; callDBus is the only
// integration point KWin's script sandbox gives us, so it's what we use.
//
// NOTE: KWin's scripting API has shifted across Plasma 5->6 (Client vs
// Window naming, property renames like `output`/`screen`). This targets
// Plasma 6 / KWin 6 (Window.frameGeometryChanged, Window.output,
// workspace.screens). If your KWin version differs, `qdbus org.kde.KWin
// /Scripting org.kde.kwin.Scripting.loadScript` plus `journalctl --user -f`
// while dragging a window is the fastest way to see what actually fired.

const DBUS_NAME = "com.bpleonardo.audiofollow";
const DBUS_PATH = "/Daemon";

var lastOutput = {}; // pid -> output name, avoids spamming D-Bus on every pixel of drag

function overlapArea(a, b) {
  var x = Math.max(
    0,
    Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x),
  );
  var y = Math.max(
    0,
    Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y),
  );
  return x * y;
}

function bestOutputFor(window) {
  var geo = window.frameGeometry;
  var best = null;
  var bestArea = -1;
  for (var i = 0; i < workspace.screens.length; i++) {
    var screen = workspace.screens[i];
    var area = overlapArea(geo, screen.geometry);
    if (area > bestArea) {
      bestArea = area;
      best = screen;
    }
  }
  return best;
}

function notify(window) {
  if (!window.pid || window.pid <= 0) return;
  var screen = bestOutputFor(window);
  if (!screen) return;
  if (lastOutput[window.pid] === screen.name) {
    return;
  } else {
    console.debug(`${window.pid} changed screens.`);
  }
  lastOutput[window.pid] = screen.name;

  callDBus(
    DBUS_NAME,
    DBUS_PATH,
    DBUS_NAME,
    "WindowMoved",
    window.pid,
    screen.name,
    function () {},
  );
}

function track(window) {
  if (window.normalWindow !== undefined && !window.normalWindow) return; // skip panels/docks/etc
  if (window.pid === -1) return; // special windows.
  window.frameGeometryChanged.connect(function () {
    notify(window);
  });
  notify(window);
}

function init() {
  console.debug("audiofollow: Initialized.");

  // Track all existing windows
  var existing = workspace.windowList
    ? workspace.windowList()
    : workspace.clientList();
  for (var i = 0; i < existing.length; i++) {
    track(existing[i]);
  }

  workspace.windowAdded.connect(track);
  workspace.windowRemoved.connect(function (window) {
    delete lastOutput[window.pid];
  });
}

init();
