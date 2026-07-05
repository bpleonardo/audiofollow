# audiofollow

Moves an app's PipeWire audio stream to the sink mapped to whatever monitor
its window is currently on. Drag Spotify from your desktop screen to the TV,
its audio follows.

Two pieces:
- a small **KWin script** (`kwin_script/`) that watches window
  geometry and figures out which output has the most overlap with a window
- a **Python daemon** that receives that over D-Bus, debounces it, matches
  the window's PID to a PipeWire stream, and moves it with `pactl`

> The daemon is designed to be independent of KWin, so it could be used with other window managers that can send D-Bus messages.

## Installing and running

<!-- TODO: add pacman instructions -->

### Manual installation

1. Clone this repo

```bash
$ git clone https://github.com/bpleonardo/audiofollow
$ cd audiofollow
```

2. Install the Python dependencies and the daemon itself:

```bash
$ pip install .
```

3. Install the KWin script and enable it:

```bash
$ kpackagetool6 --type KWin/Script -i kwin_script/
$ kwriteconfig6 --file kwinrc --group Plugins --key com.bpleonardo.audiofollowEnabled true
```

4. Generate the configuration file and edit it to your liking:

```bash
$ audiofollow --gen-config
$ vi ~/.config/audiofollow/config.yaml # or your favorite editor
```

5. Install the systemd user service and enable it:

```bash
$ cp resources/systemd/unit.service ~/.config/systemd/user/audiofollow.service
$ systemctl --user enable audiofollow.service
```

6. Restart KWin (or log out and back in).

7. **Now drag a window around and its audio should follow it to the output that has the most overlap with it!**


## Notes

- I've observed that sometimes the daemon will fail to move a stream if the window is moved too quickly. This is likely a race condition but I haven't been able to reproduce it reliably, if this happens, re-move the window to the desired output and it should work. Please report any issues you encounter on the issue tracker. See below if it happens consistently with all windows, or with a specific app.
- If you move a window and the audio doesn't follow, check both the daemon and KWin script logs for errors. The KWin script can be viewed with `journalctl --user -u plasma-kwin_wayland.service --follow` (check logs beginning with `audiofollow: `) and the daemon with `journalctl --user -u audiofollow.service --follow`. If you can't figure out the problem, please open an issue on the issue tracker with the logs attached.
- The daemon parses the output of `pactl list *` commands, which may change in future versions of libpulse. If the program stops working after a system update, please check the issue tracker for any reports of this and/or open a new issue. I use a rolling release distro, so by the time you notice it there may already be a fix in the repo.

## License

BSD-3-Clause License. See [LICENSE](https://github.com/bpleonardo/audiofollow/blob/main/LICENSE) for details.