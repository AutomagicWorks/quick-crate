# Working on Quick Crate

Instructions for AI coding assistants (and humans) changing this repository. The README describes what Quick Crate does for users; this file describes how to change it without breaking what makes it useful.

## What it is

A small, audio-only front end for [yt-dlp](https://github.com/yt-dlp/yt-dlp), built by a DJ for DJs. Paste a link, get one clean, tagged audio file that loads in Rekordbox, Serato and Traktor. It deliberately does less than other yt-dlp front ends: no video, no playlists, no queues.

There are two versions with **the same features**:

| Path | What | Runs on |
|---|---|---|
| `macos/QuickCrate.swift` | Native SwiftUI app, one file | macOS 14+ |
| `macos/build.sh` | Builds `~/Applications/Quick Crate.app` (ad-hoc signed) | macOS |
| `macos/make_icon.swift` | Draws the app icon; also used by the web launcher | macOS |
| `web/server.py` | Local web UI: one Python file, HTML/CSS/JS embedded | macOS, Windows, Linux |
| `web/make-launcher.sh` | Creates `Quick Crate (Web).app` on macOS | macOS |
| `web/Quick Crate.pyw` | Double-click launcher with no console window | Windows |
| `tests/smoke_test.py` | End-to-end test of the web version | all three |
| `VERSION` | The version number, shown in both apps | |

## Rules

1. **Keep both versions matched.** A feature, fix or wording change in one belongs in the other, unless it's platform-specific. Say so in the pull request if a change is intentionally one-sided.
2. **Never compete with DJ software.** Every yt-dlp and ffmpeg process runs at background priority: `taskpolicy -b` (macOS), `nice` (Linux), `IDLE_PRIORITY_CLASS` via `win_flags(low=True)` (Windows), `qualityOfService = .background` (Mac app). New subprocesses must do the same. On Windows, pass `**win_flags()` to every `subprocess` call so no console window appears.
3. **Web version: Python standard library only**, Python 3.8+, in a single `server.py`. No pip dependencies, no build step.
4. **Don't bundle yt-dlp or ffmpeg.** Quick Crate runs the user's own installed copies (looked up in `~/.local/bin`, `/opt/homebrew/bin`, `/usr/local/bin`, winget's folder on Windows, then `PATH`).
5. **Stay focused.** Audio only, one link at a time, DJ-friendly output (MP3 default, clean `Artist - Title` names and tags, square cover art, honest quality reporting). Decline features that turn it into a general downloader.
6. **No DRM circumvention, account logins or cookies.** See "Responsible use" in the README.
7. **Plain, friendly user-facing text.** Errors say what happened and what to do next. Match the existing tone in both apps.

## Gotchas

- **yt-dlp splits `--postprocessor-args` like a Unix shell**, on every platform. Any path passed through it must be quoted with forward slashes: `shlex.quote(Path(p).as_posix())` in Python, `shellQuote(...)` in Swift. Unquoted Windows paths lose their backslashes, and paths with spaces split apart.
- **Unfinished files live in a per-download temp folder** so Cancel leaves nothing behind. Keep it that way: write only the final file to the download folder.
- **The web server only answers its own page:** it checks the `Host` header and requires JSON bodies on POST, so other websites can't drive it. Keep both checks on new endpoints.
- **The Mac app is one file and is compiled only by `build.sh` / CI.** If you can't build Swift locally, rely on the macOS CI job and say so.

## Testing

Before pushing a change to the web version, run the end-to-end test (needs `yt-dlp`, `ffmpeg` and `ffprobe` on `PATH`; no internet needed):

```sh
python3 tests/smoke_test.py
```

It serves generated audio from a local web server and checks real MP3 and M4A downloads (names and tags), Cancel, bad links, the version shown, that nothing is written to the working folder, and on Windows the Idle priority. Add a check there when you fix a bug it could have caught.

CI (`.github/workflows/build.yml`) builds the Mac app, checks its bundle and version, and runs the test on macOS, Windows and Linux for every push and pull request.

Things CI can't check, so a person must test them before merging:
- **Web version changes:** a real download in the browser window on a Windows PC (launcher, folder picker, Open file / Show in folder, priority in Task Manager).
- **Mac app interface changes:** build with `zsh macos/build.sh` and look at the window.
- **Anything about real sites:** a real YouTube download, using Creative Commons or public-domain content.

## Releases

1. Bump `VERSION` (semantic versioning) in the same pull request as the changes. `build.sh` and `make-launcher.sh` copy it into Info.plist; CI fails if they disagree.
2. After merging, tag the merge commit `vX.Y.Z` with the same number and publish a GitHub release whose notes say what changed for users and how to update (`git pull`, then rebuild).

## Screenshots and docs

Screenshots in `docs/` must show Creative Commons or public-domain content, credited in the README (the current ones use "Monkeys Spinning Monkeys" by Kevin MacLeod, CC BY 3.0). Don't include personal names, paths or accounts in screenshots, code, or commit messages.
