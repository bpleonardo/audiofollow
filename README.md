# audiofollow

Moves an app's PipeWire audio stream to the sink mapped to whatever monitor
its window is currently on. Drag Spotify from your desktop screen to the TV,
its audio follows.

Two pieces:
- a small **KWin script** (`kwin_script/`) that watches window
  geometry and figures out which output has the most overlap with a window
- a **Python daemon** that receives that over D-Bus, debounces it, matches
  the window's PID to a PipeWire stream, and moves it with `pactl`
