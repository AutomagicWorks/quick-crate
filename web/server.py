#!/usr/bin/env python3
"""Quick Crate: built by a DJ, for DJs. A tiny local web UI for yt-dlp audio downloads. Standard library only.

Runs on your own computer only (127.0.0.1). Needs yt-dlp and ffmpeg installed; see README.md.
"""
import datetime, json, os, platform, re, shutil, signal, subprocess, sys, tempfile, threading, time, uuid, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = int(os.environ.get("QUICK_CRATE_PORT", "8765"))
SYSTEM = platform.system()
CONFIG = Path.home() / ".config" / "quick-crate" / "config.json"
OLD_CONFIG = Path.home() / ".config" / "audio-downloader" / "config.json"  # before the rename
JOBS = {}
# Quit on our own once the page is closed (unless started with --keep-running):
# ~10 s after the page says goodbye, or 10 min after the last sign of life if it never could.
QUIT_AFTER_BYE = int(os.environ.get("QUICK_CRATE_QUIT_AFTER_BYE", "10"))
QUIT_AFTER_SILENCE = int(os.environ.get("QUICK_CRATE_QUIT_AFTER_SILENCE", "600"))
ACTIVITY = {"last": time.monotonic(), "bye": None}

# Where to look for yt-dlp / ffmpeg / ffprobe before falling back to PATH.
SEARCH_DIRS = [Path.home() / ".local" / "bin", Path("/opt/homebrew/bin"), Path("/usr/local/bin")]
INSTALL_HINT = ("Install it first: on a Mac run  brew install yt-dlp ffmpeg  "
                "(other systems: see the README).")


def tool(name):
    """Full path to a command-line tool, or None if it isn't installed."""
    exe = name + (".exe" if SYSTEM == "Windows" else "")
    for d in SEARCH_DIRS:
        p = d / exe
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return shutil.which(name)


def default_dir():
    return (Path.home() / "Downloads").resolve()


def load_download_dir():
    for cfg in (CONFIG, OLD_CONFIG):
        try:
            p = Path(json.loads(cfg.read_text())["download_dir"]).expanduser().resolve()
            if p.is_dir():
                return p
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return default_dir()


def save_download_dir(p):
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps({"download_dir": str(p)}))


def pretty(p):
    """Show a path with ~ for the home folder, like the Mac app does."""
    home = str(Path.home())
    s = str(p)
    return "~" + s[len(home):] if s == home or s.startswith(home + os.sep) else s


STATE = {"download_dir": load_download_dir()}

HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Quick Crate</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='100 100 824 824'%3E%3Cdefs%3E%3ClinearGradient id='bg' x1='0' y1='100' x2='0' y2='924' gradientUnits='userSpaceOnUse'%3E%3Cstop offset='0' stop-color='%23ff4d5c'/%3E%3Cstop offset='1' stop-color='%23b80f2e'/%3E%3C/linearGradient%3E%3ClinearGradient id='gl' x1='0' y1='100' x2='0' y2='464' gradientUnits='userSpaceOnUse'%3E%3Cstop offset='0' stop-color='%23fff' stop-opacity='.22'/%3E%3Cstop offset='1' stop-color='%23fff' stop-opacity='0'/%3E%3C/linearGradient%3E%3C/defs%3E%3Cpath d='M924.0 512.0L923.9 608.0L923.8 638.6L923.5 660.9L923.1 679.0L922.6 694.5L922.0 708.2L921.2 720.5L920.4 731.8L919.4 742.2L918.3 751.9L917.1 761.0L915.8 769.6L914.4 777.6L912.8 785.3L911.2 792.6L909.4 799.5L907.5 806.1L905.4 812.4L903.3 818.5L901.0 824.2L898.5 829.8L896.0 835.1L893.3 840.2L890.5 845.1L887.6 849.8L884.5 854.3L881.2 858.7L877.9 862.8L874.3 866.8L870.7 870.7L866.8 874.3L862.8 877.9L858.7 881.2L854.3 884.5L849.8 887.6L845.1 890.5L840.2 893.3L835.1 896.0L829.8 898.5L824.2 901.0L818.5 903.3L812.4 905.4L806.1 907.5L799.5 909.4L792.6 911.2L785.3 912.8L777.6 914.4L769.6 915.8L761.0 917.1L751.9 918.3L742.2 919.4L731.8 920.4L720.5 921.2L708.2 922.0L694.5 922.6L679.0 923.1L660.9 923.5L638.6 923.8L608.0 923.9L512.0 924.0L416.0 923.9L385.4 923.8L363.1 923.5L345.0 923.1L329.5 922.6L315.8 922.0L303.5 921.2L292.2 920.4L281.8 919.4L272.1 918.3L263.0 917.1L254.4 915.8L246.4 914.4L238.7 912.8L231.4 911.2L224.5 909.4L217.9 907.5L211.6 905.4L205.5 903.3L199.8 901.0L194.2 898.5L188.9 896.0L183.8 893.3L178.9 890.5L174.2 887.6L169.7 884.5L165.3 881.2L161.2 877.9L157.2 874.3L153.3 870.7L149.7 866.8L146.1 862.8L142.8 858.7L139.5 854.3L136.4 849.8L133.5 845.1L130.7 840.2L128.0 835.1L125.5 829.8L123.0 824.2L120.7 818.5L118.6 812.4L116.5 806.1L114.6 799.5L112.8 792.6L111.2 785.3L109.6 777.6L108.2 769.6L106.9 761.0L105.7 751.9L104.6 742.2L103.6 731.8L102.8 720.5L102.0 708.2L101.4 694.5L100.9 679.0L100.5 660.9L100.2 638.6L100.1 608.0L100.0 512.0L100.1 416.0L100.2 385.4L100.5 363.1L100.9 345.0L101.4 329.5L102.0 315.8L102.8 303.5L103.6 292.2L104.6 281.8L105.7 272.1L106.9 263.0L108.2 254.4L109.6 246.4L111.2 238.7L112.8 231.4L114.6 224.5L116.5 217.9L118.6 211.6L120.7 205.5L123.0 199.8L125.5 194.2L128.0 188.9L130.7 183.8L133.5 178.9L136.4 174.2L139.5 169.7L142.8 165.3L146.1 161.2L149.7 157.2L153.3 153.3L157.2 149.7L161.2 146.1L165.3 142.8L169.7 139.5L174.2 136.4L178.9 133.5L183.8 130.7L188.9 128.0L194.2 125.5L199.8 123.0L205.5 120.7L211.6 118.6L217.9 116.5L224.5 114.6L231.4 112.8L238.7 111.2L246.4 109.6L254.4 108.2L263.0 106.9L272.1 105.7L281.8 104.6L292.2 103.6L303.5 102.8L315.8 102.0L329.5 101.4L345.0 100.9L363.1 100.5L385.4 100.2L416.0 100.1L512.0 100.0L608.0 100.1L638.6 100.2L660.9 100.5L679.0 100.9L694.5 101.4L708.2 102.0L720.5 102.8L731.8 103.6L742.2 104.6L751.9 105.7L761.0 106.9L769.6 108.2L777.6 109.6L785.3 111.2L792.6 112.8L799.5 114.6L806.1 116.5L812.4 118.6L818.5 120.7L824.2 123.0L829.8 125.5L835.1 128.0L840.2 130.7L845.1 133.5L849.8 136.4L854.3 139.5L858.7 142.8L862.8 146.1L866.8 149.7L870.7 153.3L874.3 157.2L877.9 161.2L881.2 165.3L884.5 169.7L887.6 174.2L890.5 178.9L893.3 183.8L896.0 188.9L898.5 194.2L901.0 199.8L903.3 205.5L905.4 211.6L907.5 217.9L909.4 224.5L911.2 231.4L912.8 238.7L914.4 246.4L915.8 254.4L917.1 263.0L918.3 272.1L919.4 281.8L920.4 292.2L921.2 303.5L922.0 315.8L922.6 329.5L923.1 345.0L923.5 363.1L923.8 385.4L923.9 416.0Z' fill='url(%23bg)'/%3E%3Cpath d='M924.0 512.0L923.9 608.0L923.8 638.6L923.5 660.9L923.1 679.0L922.6 694.5L922.0 708.2L921.2 720.5L920.4 731.8L919.4 742.2L918.3 751.9L917.1 761.0L915.8 769.6L914.4 777.6L912.8 785.3L911.2 792.6L909.4 799.5L907.5 806.1L905.4 812.4L903.3 818.5L901.0 824.2L898.5 829.8L896.0 835.1L893.3 840.2L890.5 845.1L887.6 849.8L884.5 854.3L881.2 858.7L877.9 862.8L874.3 866.8L870.7 870.7L866.8 874.3L862.8 877.9L858.7 881.2L854.3 884.5L849.8 887.6L845.1 890.5L840.2 893.3L835.1 896.0L829.8 898.5L824.2 901.0L818.5 903.3L812.4 905.4L806.1 907.5L799.5 909.4L792.6 911.2L785.3 912.8L777.6 914.4L769.6 915.8L761.0 917.1L751.9 918.3L742.2 919.4L731.8 920.4L720.5 921.2L708.2 922.0L694.5 922.6L679.0 923.1L660.9 923.5L638.6 923.8L608.0 923.9L512.0 924.0L416.0 923.9L385.4 923.8L363.1 923.5L345.0 923.1L329.5 922.6L315.8 922.0L303.5 921.2L292.2 920.4L281.8 919.4L272.1 918.3L263.0 917.1L254.4 915.8L246.4 914.4L238.7 912.8L231.4 911.2L224.5 909.4L217.9 907.5L211.6 905.4L205.5 903.3L199.8 901.0L194.2 898.5L188.9 896.0L183.8 893.3L178.9 890.5L174.2 887.6L169.7 884.5L165.3 881.2L161.2 877.9L157.2 874.3L153.3 870.7L149.7 866.8L146.1 862.8L142.8 858.7L139.5 854.3L136.4 849.8L133.5 845.1L130.7 840.2L128.0 835.1L125.5 829.8L123.0 824.2L120.7 818.5L118.6 812.4L116.5 806.1L114.6 799.5L112.8 792.6L111.2 785.3L109.6 777.6L108.2 769.6L106.9 761.0L105.7 751.9L104.6 742.2L103.6 731.8L102.8 720.5L102.0 708.2L101.4 694.5L100.9 679.0L100.5 660.9L100.2 638.6L100.1 608.0L100.0 512.0L100.1 416.0L100.2 385.4L100.5 363.1L100.9 345.0L101.4 329.5L102.0 315.8L102.8 303.5L103.6 292.2L104.6 281.8L105.7 272.1L106.9 263.0L108.2 254.4L109.6 246.4L111.2 238.7L112.8 231.4L114.6 224.5L116.5 217.9L118.6 211.6L120.7 205.5L123.0 199.8L125.5 194.2L128.0 188.9L130.7 183.8L133.5 178.9L136.4 174.2L139.5 169.7L142.8 165.3L146.1 161.2L149.7 157.2L153.3 153.3L157.2 149.7L161.2 146.1L165.3 142.8L169.7 139.5L174.2 136.4L178.9 133.5L183.8 130.7L188.9 128.0L194.2 125.5L199.8 123.0L205.5 120.7L211.6 118.6L217.9 116.5L224.5 114.6L231.4 112.8L238.7 111.2L246.4 109.6L254.4 108.2L263.0 106.9L272.1 105.7L281.8 104.6L292.2 103.6L303.5 102.8L315.8 102.0L329.5 101.4L345.0 100.9L363.1 100.5L385.4 100.2L416.0 100.1L512.0 100.0L608.0 100.1L638.6 100.2L660.9 100.5L679.0 100.9L694.5 101.4L708.2 102.0L720.5 102.8L731.8 103.6L742.2 104.6L751.9 105.7L761.0 106.9L769.6 108.2L777.6 109.6L785.3 111.2L792.6 112.8L799.5 114.6L806.1 116.5L812.4 118.6L818.5 120.7L824.2 123.0L829.8 125.5L835.1 128.0L840.2 130.7L845.1 133.5L849.8 136.4L854.3 139.5L858.7 142.8L862.8 146.1L866.8 149.7L870.7 153.3L874.3 157.2L877.9 161.2L881.2 165.3L884.5 169.7L887.6 174.2L890.5 178.9L893.3 183.8L896.0 188.9L898.5 194.2L901.0 199.8L903.3 205.5L905.4 211.6L907.5 217.9L909.4 224.5L911.2 231.4L912.8 238.7L914.4 246.4L915.8 254.4L917.1 263.0L918.3 272.1L919.4 281.8L920.4 292.2L921.2 303.5L922.0 315.8L922.6 329.5L923.1 345.0L923.5 363.1L923.8 385.4L923.9 416.0Z' fill='url(%23gl)'/%3E%3Crect x='261' y='289' width='46' height='90' rx='23' fill='%23fff' fill-opacity='0.5'/%3E%3Crect x='337' y='249' width='46' height='170' rx='23' fill='%23fff' fill-opacity='0.65'/%3E%3Crect x='413' y='204' width='46' height='260' rx='23' fill='%23fff' fill-opacity='0.82'/%3E%3Crect x='489' y='149' width='46' height='370' rx='23' fill='%23fff' fill-opacity='1'/%3E%3Crect x='565' y='204' width='46' height='260' rx='23' fill='%23fff' fill-opacity='0.82'/%3E%3Crect x='641' y='249' width='46' height='170' rx='23' fill='%23fff' fill-opacity='0.65'/%3E%3Crect x='717' y='289' width='46' height='90' rx='23' fill='%23fff' fill-opacity='0.5'/%3E%3Cpath d='M352 554H672L512 754Z' fill='%23fff' stroke='%23fff' stroke-width='44' stroke-linejoin='round'/%3E%3Crect x='342' y='802' width='340' height='34' rx='17' fill='%23fff' fill-opacity='.9'/%3E%3C/svg%3E">
<style>
/* Mirrors the macOS app: system font and colours, gray push buttons, blue default button. */
:root{--bg:#ececec;--fg:#1d1d1f;--mut:#6e6e73;--acc:#0a84ff;--ok:#1f9d3a;--err:#d70015;--field:#fff;--line:#c8c8cc;
  --btn:#e3e3e6;--btnfg:#1d1d1f;--track:#d9d9de;--note:rgba(255,149,0,.16)}
@media(prefers-color-scheme:dark){:root{--bg:#262626;--fg:#f2f2f7;--mut:#9a9aa0;--acc:#0a84ff;--ok:#32d74b;--err:#ff453a;
  --field:#1c1c1e;--line:#3a3a3c;--btn:#3a3a3c;--btnfg:#f2f2f7;--track:#3a3a3c;--note:rgba(255,159,10,.18)}}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--fg)}
body{font:15px/1.4 -apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",sans-serif;-webkit-font-smoothing:antialiased}
main{max-width:640px;margin:0 auto;padding:28px 24px 32px}
header{display:flex;align-items:center;gap:14px;margin-bottom:14px}
#quit{margin-left:auto;align-self:flex-start;padding:4px 12px;font-size:13px}
header svg{width:52px;height:52px;flex:none;filter:drop-shadow(0 2px 3px rgba(0,0,0,.3))}
h1{margin:0;font-size:24px;font-weight:700;letter-spacing:-.01em}
p.sub{margin:0 0 12px;color:var(--mut);font-size:14px}
input[type=text]{width:100%;padding:8px 10px;font:inherit;font-size:15px;border:1px solid var(--line);border-radius:7px;background:var(--field);color:var(--fg)}
input[type=text]::placeholder{color:var(--acc);opacity:.85}
input[type=text]:focus{outline:3px solid rgba(10,132,255,.45);outline-offset:0;border-color:var(--acc)}
input[type=text]:disabled{opacity:.6}
button{font:inherit;cursor:pointer}
button:disabled{cursor:default}
.push{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:6px 14px;font-size:15px;border:0;border-radius:7px;
  background:var(--btn);color:var(--btnfg);box-shadow:0 .5px 1.5px rgba(0,0,0,.25)}
.push:active:not(:disabled){filter:brightness(.92)}
.push:disabled{opacity:.5}
.push.large{padding:10px 18px;border-radius:10px;font-size:16px}
.push svg{width:18px;height:18px;flex:none}
#advtoggle{display:inline-flex;align-items:center;gap:8px;margin:12px 0 4px;padding:0;border:0;background:none;color:var(--mut);font-size:15px}
#advtoggle svg{width:14px;height:14px;transition:transform .15s}
#advtoggle.open svg{transform:rotate(90deg)}
#adv{display:none;padding:6px 0 2px 8px}
#fmtrow{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
#fmt{font:inherit;font-size:15px;padding:5px 8px;border-radius:7px;border:0;background:var(--btn);color:var(--btnfg);min-width:220px;box-shadow:0 .5px 1.5px rgba(0,0,0,.25)}
#fmthelp{color:var(--mut);font-size:13px;margin:8px 0 2px}
.optrow{display:flex;align-items:baseline;gap:8px;cursor:pointer;margin-top:10px}
.optrow input{margin:0;flex:none;width:16px;height:16px;accent-color:var(--acc);position:relative;top:2px}
.optrow b{white-space:nowrap;font-weight:600;color:var(--fg);font-size:15px}.optrow span{color:var(--mut);font-size:13px}
#dirrow{display:flex;align-items:center;gap:12px;margin-top:12px;min-width:0}
#dir{color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
#btnrow{display:flex;gap:10px;margin-top:14px}
#go{flex:1;min-width:0;background:var(--acc);color:#fff;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:block}
#go:disabled{background:var(--btn);color:var(--mut);opacity:.7}
#paste,#cancel{display:none;flex:none}
#hint{display:none;margin-top:10px;text-align:center;color:var(--mut)}
#banner{display:none;margin:0 0 12px;padding:10px 12px;border-radius:8px;background:var(--note);font-size:14px}
#banner .push{margin-top:8px}
#updstatus{display:none;margin:-4px 0 10px;color:var(--mut);font-size:13px}
#status{margin-top:16px;display:none}
.bar{height:6px;background:var(--track);border-radius:3px;overflow:hidden}
.fill{height:100%;width:0;background:var(--acc);border-radius:3px;transition:width .3s}
.fill.busy{width:100%;background:linear-gradient(90deg,var(--acc) 25%,transparent 50%,var(--acc) 75%);background-size:200% 100%;animation:s 1.2s linear infinite}
@keyframes s{to{background-position:-200% 0}}
#msg{margin-top:10px;color:var(--mut);word-break:break-word}
#msg.err{color:var(--err)}#msg.ok{color:var(--ok)}
#updfail{display:none;margin-top:8px;align-items:center;gap:10px;flex-wrap:wrap}
#updfail span{color:var(--mut);font-size:13px}
#result{display:none;margin-top:12px;gap:14px;align-items:flex-start}
#art{display:none;flex:none;width:96px;height:96px;object-fit:cover;border-radius:8px;border:1px solid var(--line)}
#quality{font-size:13px;color:var(--mut);line-height:1.45}
#quality br{display:none}#quality b{display:block;color:var(--fg);font-size:15px;font-weight:600;margin-bottom:2px}
#links{margin-top:12px;display:none;gap:10px;flex-wrap:wrap}
main.drop{outline:3px dashed var(--acc);outline-offset:-6px;border-radius:12px}
</style></head><body><main>
<header><svg xmlns="http://www.w3.org/2000/svg" viewBox="100 100 824 824"><defs><linearGradient id="bg" x1="0" y1="100" x2="0" y2="924" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#ff4d5c"/><stop offset="1" stop-color="#b80f2e"/></linearGradient><linearGradient id="gl" x1="0" y1="100" x2="0" y2="464" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#fff" stop-opacity=".22"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient></defs><path d="M924.0 512.0L923.9 608.0L923.8 638.6L923.5 660.9L923.1 679.0L922.6 694.5L922.0 708.2L921.2 720.5L920.4 731.8L919.4 742.2L918.3 751.9L917.1 761.0L915.8 769.6L914.4 777.6L912.8 785.3L911.2 792.6L909.4 799.5L907.5 806.1L905.4 812.4L903.3 818.5L901.0 824.2L898.5 829.8L896.0 835.1L893.3 840.2L890.5 845.1L887.6 849.8L884.5 854.3L881.2 858.7L877.9 862.8L874.3 866.8L870.7 870.7L866.8 874.3L862.8 877.9L858.7 881.2L854.3 884.5L849.8 887.6L845.1 890.5L840.2 893.3L835.1 896.0L829.8 898.5L824.2 901.0L818.5 903.3L812.4 905.4L806.1 907.5L799.5 909.4L792.6 911.2L785.3 912.8L777.6 914.4L769.6 915.8L761.0 917.1L751.9 918.3L742.2 919.4L731.8 920.4L720.5 921.2L708.2 922.0L694.5 922.6L679.0 923.1L660.9 923.5L638.6 923.8L608.0 923.9L512.0 924.0L416.0 923.9L385.4 923.8L363.1 923.5L345.0 923.1L329.5 922.6L315.8 922.0L303.5 921.2L292.2 920.4L281.8 919.4L272.1 918.3L263.0 917.1L254.4 915.8L246.4 914.4L238.7 912.8L231.4 911.2L224.5 909.4L217.9 907.5L211.6 905.4L205.5 903.3L199.8 901.0L194.2 898.5L188.9 896.0L183.8 893.3L178.9 890.5L174.2 887.6L169.7 884.5L165.3 881.2L161.2 877.9L157.2 874.3L153.3 870.7L149.7 866.8L146.1 862.8L142.8 858.7L139.5 854.3L136.4 849.8L133.5 845.1L130.7 840.2L128.0 835.1L125.5 829.8L123.0 824.2L120.7 818.5L118.6 812.4L116.5 806.1L114.6 799.5L112.8 792.6L111.2 785.3L109.6 777.6L108.2 769.6L106.9 761.0L105.7 751.9L104.6 742.2L103.6 731.8L102.8 720.5L102.0 708.2L101.4 694.5L100.9 679.0L100.5 660.9L100.2 638.6L100.1 608.0L100.0 512.0L100.1 416.0L100.2 385.4L100.5 363.1L100.9 345.0L101.4 329.5L102.0 315.8L102.8 303.5L103.6 292.2L104.6 281.8L105.7 272.1L106.9 263.0L108.2 254.4L109.6 246.4L111.2 238.7L112.8 231.4L114.6 224.5L116.5 217.9L118.6 211.6L120.7 205.5L123.0 199.8L125.5 194.2L128.0 188.9L130.7 183.8L133.5 178.9L136.4 174.2L139.5 169.7L142.8 165.3L146.1 161.2L149.7 157.2L153.3 153.3L157.2 149.7L161.2 146.1L165.3 142.8L169.7 139.5L174.2 136.4L178.9 133.5L183.8 130.7L188.9 128.0L194.2 125.5L199.8 123.0L205.5 120.7L211.6 118.6L217.9 116.5L224.5 114.6L231.4 112.8L238.7 111.2L246.4 109.6L254.4 108.2L263.0 106.9L272.1 105.7L281.8 104.6L292.2 103.6L303.5 102.8L315.8 102.0L329.5 101.4L345.0 100.9L363.1 100.5L385.4 100.2L416.0 100.1L512.0 100.0L608.0 100.1L638.6 100.2L660.9 100.5L679.0 100.9L694.5 101.4L708.2 102.0L720.5 102.8L731.8 103.6L742.2 104.6L751.9 105.7L761.0 106.9L769.6 108.2L777.6 109.6L785.3 111.2L792.6 112.8L799.5 114.6L806.1 116.5L812.4 118.6L818.5 120.7L824.2 123.0L829.8 125.5L835.1 128.0L840.2 130.7L845.1 133.5L849.8 136.4L854.3 139.5L858.7 142.8L862.8 146.1L866.8 149.7L870.7 153.3L874.3 157.2L877.9 161.2L881.2 165.3L884.5 169.7L887.6 174.2L890.5 178.9L893.3 183.8L896.0 188.9L898.5 194.2L901.0 199.8L903.3 205.5L905.4 211.6L907.5 217.9L909.4 224.5L911.2 231.4L912.8 238.7L914.4 246.4L915.8 254.4L917.1 263.0L918.3 272.1L919.4 281.8L920.4 292.2L921.2 303.5L922.0 315.8L922.6 329.5L923.1 345.0L923.5 363.1L923.8 385.4L923.9 416.0Z" fill="url(#bg)"/><path d="M924.0 512.0L923.9 608.0L923.8 638.6L923.5 660.9L923.1 679.0L922.6 694.5L922.0 708.2L921.2 720.5L920.4 731.8L919.4 742.2L918.3 751.9L917.1 761.0L915.8 769.6L914.4 777.6L912.8 785.3L911.2 792.6L909.4 799.5L907.5 806.1L905.4 812.4L903.3 818.5L901.0 824.2L898.5 829.8L896.0 835.1L893.3 840.2L890.5 845.1L887.6 849.8L884.5 854.3L881.2 858.7L877.9 862.8L874.3 866.8L870.7 870.7L866.8 874.3L862.8 877.9L858.7 881.2L854.3 884.5L849.8 887.6L845.1 890.5L840.2 893.3L835.1 896.0L829.8 898.5L824.2 901.0L818.5 903.3L812.4 905.4L806.1 907.5L799.5 909.4L792.6 911.2L785.3 912.8L777.6 914.4L769.6 915.8L761.0 917.1L751.9 918.3L742.2 919.4L731.8 920.4L720.5 921.2L708.2 922.0L694.5 922.6L679.0 923.1L660.9 923.5L638.6 923.8L608.0 923.9L512.0 924.0L416.0 923.9L385.4 923.8L363.1 923.5L345.0 923.1L329.5 922.6L315.8 922.0L303.5 921.2L292.2 920.4L281.8 919.4L272.1 918.3L263.0 917.1L254.4 915.8L246.4 914.4L238.7 912.8L231.4 911.2L224.5 909.4L217.9 907.5L211.6 905.4L205.5 903.3L199.8 901.0L194.2 898.5L188.9 896.0L183.8 893.3L178.9 890.5L174.2 887.6L169.7 884.5L165.3 881.2L161.2 877.9L157.2 874.3L153.3 870.7L149.7 866.8L146.1 862.8L142.8 858.7L139.5 854.3L136.4 849.8L133.5 845.1L130.7 840.2L128.0 835.1L125.5 829.8L123.0 824.2L120.7 818.5L118.6 812.4L116.5 806.1L114.6 799.5L112.8 792.6L111.2 785.3L109.6 777.6L108.2 769.6L106.9 761.0L105.7 751.9L104.6 742.2L103.6 731.8L102.8 720.5L102.0 708.2L101.4 694.5L100.9 679.0L100.5 660.9L100.2 638.6L100.1 608.0L100.0 512.0L100.1 416.0L100.2 385.4L100.5 363.1L100.9 345.0L101.4 329.5L102.0 315.8L102.8 303.5L103.6 292.2L104.6 281.8L105.7 272.1L106.9 263.0L108.2 254.4L109.6 246.4L111.2 238.7L112.8 231.4L114.6 224.5L116.5 217.9L118.6 211.6L120.7 205.5L123.0 199.8L125.5 194.2L128.0 188.9L130.7 183.8L133.5 178.9L136.4 174.2L139.5 169.7L142.8 165.3L146.1 161.2L149.7 157.2L153.3 153.3L157.2 149.7L161.2 146.1L165.3 142.8L169.7 139.5L174.2 136.4L178.9 133.5L183.8 130.7L188.9 128.0L194.2 125.5L199.8 123.0L205.5 120.7L211.6 118.6L217.9 116.5L224.5 114.6L231.4 112.8L238.7 111.2L246.4 109.6L254.4 108.2L263.0 106.9L272.1 105.7L281.8 104.6L292.2 103.6L303.5 102.8L315.8 102.0L329.5 101.4L345.0 100.9L363.1 100.5L385.4 100.2L416.0 100.1L512.0 100.0L608.0 100.1L638.6 100.2L660.9 100.5L679.0 100.9L694.5 101.4L708.2 102.0L720.5 102.8L731.8 103.6L742.2 104.6L751.9 105.7L761.0 106.9L769.6 108.2L777.6 109.6L785.3 111.2L792.6 112.8L799.5 114.6L806.1 116.5L812.4 118.6L818.5 120.7L824.2 123.0L829.8 125.5L835.1 128.0L840.2 130.7L845.1 133.5L849.8 136.4L854.3 139.5L858.7 142.8L862.8 146.1L866.8 149.7L870.7 153.3L874.3 157.2L877.9 161.2L881.2 165.3L884.5 169.7L887.6 174.2L890.5 178.9L893.3 183.8L896.0 188.9L898.5 194.2L901.0 199.8L903.3 205.5L905.4 211.6L907.5 217.9L909.4 224.5L911.2 231.4L912.8 238.7L914.4 246.4L915.8 254.4L917.1 263.0L918.3 272.1L919.4 281.8L920.4 292.2L921.2 303.5L922.0 315.8L922.6 329.5L923.1 345.0L923.5 363.1L923.8 385.4L923.9 416.0Z" fill="url(#gl)"/><rect x="261" y="289" width="46" height="90" rx="23" fill="#fff" fill-opacity="0.5"/><rect x="337" y="249" width="46" height="170" rx="23" fill="#fff" fill-opacity="0.65"/><rect x="413" y="204" width="46" height="260" rx="23" fill="#fff" fill-opacity="0.82"/><rect x="489" y="149" width="46" height="370" rx="23" fill="#fff" fill-opacity="1"/><rect x="565" y="204" width="46" height="260" rx="23" fill="#fff" fill-opacity="0.82"/><rect x="641" y="249" width="46" height="170" rx="23" fill="#fff" fill-opacity="0.65"/><rect x="717" y="289" width="46" height="90" rx="23" fill="#fff" fill-opacity="0.5"/><path d="M352 554H672L512 754Z" fill="#fff" stroke="#fff" stroke-width="44" stroke-linejoin="round"/><rect x="342" y="802" width="340" height="34" rx="17" fill="#fff" fill-opacity=".9"/></svg><h1>Quick Crate</h1><button class="push" id="quit" type="button" title="Stop Quick Crate and close this window">Quit</button></header>
<p class="sub">Built by a DJ, for DJs. Paste or drop a link (YouTube or any site yt-dlp supports) to add its audio to your crate in seconds.</p>
<div id="banner"><div id="bannertext"></div><button class="push" id="updbanner" type="button">Update yt-dlp</button></div>
<div id="updstatus"></div>
<form id="f"><input id="url" type="text" placeholder="https://www.youtube.com/watch?v=..." autocomplete="off" autofocus>
<button id="advtoggle" type="button"><svg viewBox="0 0 16 16"><path d="M6 3.5 10.5 8 6 12.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg><span id="advlabel">Show advanced options</span></button>
<div id="adv">
<div id="fmtrow"><label for="fmt">Format:</label><select id="fmt">
<option value="mp3">MP3</option><option value="m4a">M4A (original AAC)</option><option value="original">Original (best stream)</option></select></div>
<div id="fmthelp"></div>
<label class="optrow" id="vbrrow"><input id="vbr" type="checkbox"><span><b>Use VBR?</b> <span>(unchecked = constant bitrate, up to 320 kbps, matched to the source)</span></span></label>
<label class="optrow"><input id="square" type="checkbox" checked><span><b>Square cover art</b> <span>(crops the wide video thumbnail so it fits music players)</span></span></label>
<label class="optrow"><input id="sponsor" type="checkbox"><span><b>Remove non-music parts</b> <span>(YouTube only: cuts talking intros and outros using SponsorBlock community data)</span></span></label>
<div id="dirrow"><button class="push" id="choose" type="button">Download to...</button><span id="dir"></span></div>
</div>
<div id="btnrow"><button class="push large" id="paste" type="button" title="Download the link on your clipboard"><svg viewBox="0 0 20 20"><rect x="6.5" y="3.5" width="10" height="13" rx="2" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M4 6.5v9.5a2 2 0 0 0 2 2h7" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><rect x="9" y="2" width="5" height="3" rx="1" fill="currentColor"/></svg>Paste &amp; download</button>
<button class="push large" id="go" type="submit" disabled>Download audio</button>
<button class="push large" id="cancel" type="button">Cancel</button></div></form>
<div id="hint">Paste a new URL link to start again</div>
<div id="status"><div class="bar"><div class="fill" id="fill"></div></div><div id="msg"></div>
<div id="updfail"><button class="push" id="updbtn" type="button">Update yt-dlp</button><span>An outdated yt-dlp is the most common cause of download errors.</span></div>
<div id="result"><img id="art" alt="Embedded cover art"><div id="quality"></div></div>
<div id="links"><button class="push" id="openfile" type="button">Open file</button><button class="push" id="openfolder" type="button">Show in folder</button></div></div>
</main>
<script>
const $=id=>document.getElementById(id);let job=null,timer=null,busy=false,finished=false,title="",fmtRunning="mp3",stopping=false;
const HELP={mp3:"Converted to MP3. Works in every DJ app and on CDJs; the safest choice.",
  m4a:"Saves the site's AAC audio as-is, with no conversion. Works in Rekordbox, Serato, Traktor and Apple Music.",
  original:"Saves the best audio stream as-is, with no conversion. Usually Opus, which Rekordbox, Serato, Traktor and Apple Music can't play."};
const store={get(k,d){try{const v=localStorage.getItem(k);return v===null?d:JSON.parse(v)}catch(e){return d}},
  set(k,v){try{localStorage.setItem(k,JSON.stringify(v))}catch(e){}}};
const canPaste=!!(navigator.clipboard&&navigator.clipboard.readText);
async function post(path,body){const r=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body||{})});return r.json()}
function bar(w){
  // Switching from the "preparing" animation to real progress: jump, don't slide down from 100%.
  const f=$("fill");if(f.classList.contains("busy")){f.style.transition="none";f.className="fill";f.style.width=w;void f.offsetWidth;f.style.transition=""}
  else{f.className="fill";f.style.width=w}}
function show(msg,cls){$("msg").textContent=msg;$("msg").className=cls||""}
function refresh(){
  const empty=!$("url").value.trim();
  if(!empty)finished=false;
  $("go").textContent=busy?(title?"Downloading "+title:"Downloading…"):(finished&&empty?"Finished!":"Download audio");
  $("go").disabled=busy||empty;
  for(const id of ["url","fmt","vbr","square","sponsor","choose"])$(id).disabled=busy;
  $("paste").style.display=canPaste&&empty&&!busy?"inline-flex":"none";
  $("cancel").style.display=busy?"inline-flex":"none";
  $("vbrrow").style.display=$("fmt").value==="mp3"?"flex":"none";
  $("fmthelp").textContent=HELP[$("fmt").value];
  $("hint").style.display=finished&&empty?"block":"none"}
function setDir(s){$("dir").textContent=s.display;$("dir").title=s.download_dir}
function notify(heading,body){
  // Only when the tab is in the background; clicking brings it back.
  if(!document.hidden||!("Notification" in window)||Notification.permission!=="granted")return;
  const n=new Notification(heading,{body});n.onclick=()=>{window.focus();n.close()}}
$("fmt").value=store.get("fmt","mp3");$("vbr").checked=store.get("vbr",false);$("square").checked=store.get("square",true);
$("sponsor").checked=store.get("sponsor",false);
for(const id of ["fmt","vbr","square","sponsor"])$(id).addEventListener("change",()=>{store.set(id,id==="fmt"?$(id).value:$(id).checked);refresh()});
$("url").addEventListener("input",refresh);
$("advtoggle").onclick=()=>{const open=$("adv").style.display!=="block";$("adv").style.display=open?"block":"none";
  $("advtoggle").classList.toggle("open",open);$("advlabel").textContent=(open?"Hide":"Show")+" advanced options"};
$("choose").onclick=async()=>{$("choose").disabled=true;const r=await post("/api/choose-folder");$("choose").disabled=busy;
  if(r.error){$("status").style.display="block";show(r.error,"err")}else if(r.download_dir)setDir(r)};
async function start(){
  const url=$("url").value.trim();if(busy||!url)return;
  if("Notification" in window&&Notification.permission==="default"){try{Notification.requestPermission()}catch(e){}}
  busy=true;finished=false;title="";fmtRunning=$("fmt").value;refresh();
  $("status").style.display="block";$("links").style.display="none";$("result").style.display="none";$("updfail").style.display="none";
  $("fill").className="fill busy";show("Analyzing video and preparing...");
  const r=await post("/api/download",{url,format:fmtRunning,vbr:$("vbr").checked,square:$("square").checked,sponsorblock:$("sponsor").checked});
  if(r.error){busy=false;refresh();bar("0");show(r.error,"err");return}
  job=r.id;timer=setInterval(poll,500)}
$("f").addEventListener("submit",e=>{e.preventDefault();start()});
$("paste").onclick=async()=>{
  try{$("url").value=(await navigator.clipboard.readText()).trim();refresh();start()}
  catch(e){$("status").style.display="block";show("Couldn't read the clipboard. Paste the link into the box instead.","err")}};
// Drag a link from another browser tab or the address bar onto the page.
const main=document.querySelector("main");
document.addEventListener("dragover",e=>{e.preventDefault();if(!busy)main.classList.add("drop")});
document.addEventListener("dragleave",e=>{if(!e.relatedTarget)main.classList.remove("drop")});
document.addEventListener("drop",e=>{e.preventDefault();main.classList.remove("drop");if(busy)return;
  const raw=e.dataTransfer.getData("text/uri-list")||e.dataTransfer.getData("text/plain")||"";
  const link=raw.split(/\r?\n/).map(s=>s.trim()).find(s=>s&&!s.startsWith("#"));
  if(link){$("url").value=link;refresh();start()}});
async function poll(){
  const j=await (await fetch("/api/job/"+job)).json();
  if(j.title&&j.title!==title){title=j.title;refresh()}
  const t=title?title+" — ":"";
  if(j.state==="running"){
    if(j.stage==="download"){bar((j.percent*0.5)+"%");show(t+"Downloading "+j.percent.toFixed(0)+"%")}
    else if(j.stage==="convert"){bar((50+j.cpercent*0.45)+"%");
      show(t+(fmtRunning==="mp3"?"Converting to MP3 "+j.cpercent.toFixed(0)+"%":"Saving original audio…"))}
    else if(j.stage==="finish"){$("fill").className="fill busy";show(t+"Embedding cover art and tags…")}
    else{$("fill").className="fill busy";show("Analyzing video and preparing...")}
    return}
  clearInterval(timer);busy=false;
  if(j.state==="done"){bar("100%");show("Saved: "+j.filename,"ok");$("links").style.display="flex";
    $("url").value="";finished=true;
    const q=$("quality");q.replaceChildren();
    if(j.quality){const b=document.createElement("b");b.textContent="Quality: "+j.quality.summary;q.append(b,document.createElement("br"),j.quality.note)}
    $("result").style.display="flex";
    const a=$("art");a.style.display="none";a.onload=()=>a.style.display="block";a.src="/api/art/"+job+"?t="+Date.now();
    notify("Download finished",j.filename)}
  else if(j.state==="cancelled"){bar("0");show("Download cancelled.")}
  else{bar("0");show(j.error||"Download failed","err");$("updfail").style.display="flex";notify("Download failed",j.error||"")}
  refresh()}
$("cancel").onclick=()=>{if(job){$("cancel").disabled=true;show("Cancelling…");post("/api/cancel",{id:job}).finally(()=>$("cancel").disabled=false)}};
async function updateYtdlp(btn){
  const label=btn.textContent;btn.disabled=true;btn.textContent="Updating yt-dlp…";
  const st=$("updstatus");st.style.display="block";st.textContent="Updating yt-dlp…";
  try{const r=await post("/api/update-ytdlp");st.textContent=r.message;if(r.ok)$("banner").style.display="none"}
  catch(e){st.textContent="Couldn't update yt-dlp."}
  btn.disabled=false;btn.textContent=label}
$("updbanner").onclick=()=>updateYtdlp($("updbanner"));$("updbtn").onclick=()=>updateYtdlp($("updbtn"));
fetch("/api/ytdlp").then(r=>r.json()).then(i=>{if(i.old){
  $("bannertext").textContent="Your yt-dlp ("+i.version+") is "+i.age_days+" days old. Sites change often, and updating fixes most download errors.";
  $("banner").style.display="block"}});
$("quit").onclick=async()=>{
  if(busy&&!confirm("A download is still running. Cancel it and quit?"))return;
  stopping=true;try{await post("/api/quit")}catch(e){}
  document.body.innerHTML='<main><p style="color:var(--mut);margin-top:40px;text-align:center">Quick Crate has stopped. You can close this window.</p></main>';
  window.close()};
$("openfile").onclick=()=>post("/api/open",{id:job,what:"file"});
$("openfolder").onclick=()=>post("/api/open",{id:job,what:"folder"});
fetch("/api/settings").then(r=>r.json()).then(setDir);refresh();
// In an app window (Chrome/Edge/Brave --app, which reports display-mode "standalone"), keep the window exactly as tall as the content, like the Mac app:
// it grows when advanced options or results appear and shrinks when they go away. Width stays user-controlled.
// In a normal browser tab this does nothing.
let titleBar=null,lastTarget=0,fitQueued=false,winW=null,ourResizeAt=0;
// Full screen (the green button): leave the size alone and allow scrolling until the user leaves full screen.
const isFullScreen=()=>outerWidth>=screen.width-2&&outerHeight>=screen.height-2;
function fitWindow(){
  if(!matchMedia("(display-mode: standalone)").matches)return;
  if(isFullScreen()){document.documentElement.style.overflowY="auto";return}
  if(titleBar===null){
    // First fit after opening: measure the title bar once, and set the width ourselves, because Chrome
    // reopens app windows at whatever size they last had. Default 600 px, or the width you last dragged it to.
    titleBar=Math.max(0,outerHeight-innerHeight);
    winW=Math.min(Math.max(480,store.get("winW",600)),screen.availWidth);
  }
  let h=Math.ceil(main.getBoundingClientRect().height)+titleBar;
  const cap=screen.availHeight;
  // No scrollbar unless the content is taller than the screen (a scrollbar re-wraps text and changes the height).
  document.documentElement.style.overflowY=h>cap?"auto":"hidden";
  h=Math.min(h,cap);
  if(Math.abs(outerHeight-h)>2||Math.abs(outerWidth-winW)>2){lastTarget=h;ourResizeAt=Date.now();resizeTo(winW,h)}}
function rememberWidth(){
  // A width change we didn't make ourselves is the user dragging the window: keep it for next time.
  if(winW===null||isFullScreen()||Date.now()-ourResizeAt<600||Math.abs(outerWidth-winW)<=2)return;
  winW=Math.max(480,outerWidth);store.set("winW",winW)}
addEventListener("resize",rememberWidth);
function queueFit(){if(!fitQueued){fitQueued=true;requestAnimationFrame(()=>{fitQueued=false;fitWindow()})}}
new ResizeObserver(queueFit).observe(main);addEventListener("resize",queueFit);
// Keep the local server alive while this page is open; tell it when the page closes so it can quit.
setInterval(()=>fetch("/api/ping").catch(()=>{}),20000);
addEventListener("pagehide",()=>{try{fetch("/api/bye",{method:"POST",keepalive:true,headers:{"Content-Type":"application/json"},body:"{}"})}catch(e){}});
addEventListener("pageshow",e=>{if(e.persisted)fetch("/api/ping").catch(()=>{})});
document.addEventListener("visibilitychange",()=>{if(!document.hidden&&!stopping)fetch("/api/ping").catch(()=>{
  $("status").style.display="block";show("Quick Crate has stopped. Open it again to keep downloading.","err")})});
</script></body></html>"""


NAMES = {"opus": "Opus", "mp4a": "AAC", "aac": "AAC", "vorbis": "Vorbis", "mp3": "MP3"}
FORMATS = ("mp3", "m4a", "original")
# Crops the (usually 16:9) video thumbnail to a centred square before it is embedded.
SQUARE_CROP = "ThumbnailsConvertor:-vf crop=\"'min(iw,ih)':'min(iw,ih)'\""
# "Artist - Title (Official Video)" -> artist and title tags, and a clean "Artist - Title.ext" filename.
# Mix names such as "(Extended Mix)" are kept; only video-ish suffixes are removed.
TAG_ARGS = ["--parse-metadata", "%(title)s:%(meta_title)s",
            "--parse-metadata", "title:(?P<meta_artist>.+?) - (?P<meta_title>.+)",
            "--replace-in-metadata", "meta_title",
            r"(?i)\s*[(\[][^)\]]*\b(official|lyrics?|audio|video|visuali[sz]er|hd|4k|mv)\b[^)\]]*[)\]]", ""]
# Cuts sections SponsorBlock users marked as non-music (talking intros/outros) out of music videos. YouTube only.
SPONSORBLOCK_ARGS = ["--sponsorblock-remove", "music_offtopic"]
YTDLP_OLD_DAYS = 60
OUTPUT_NAME = "%(meta_artist,artist&{} - |)s%(meta_title,title)s.%(ext)s"


def low_priority(cmd):
    """Run downloads and conversions at background priority, so they never take CPU or disk time
    from DJ software playing on the same computer."""
    if SYSTEM == "Darwin" and os.path.exists("/usr/sbin/taskpolicy"):
        return ["/usr/sbin/taskpolicy", "-b"] + cmd
    if SYSTEM != "Windows" and shutil.which("nice"):
        return ["nice", "-n", "15"] + cmd
    return cmd


def nice(codec):
    return next((v for k, v in NAMES.items() if codec.startswith(k)), codec or "original")


def describe_quality(path, src, fmt="mp3", vbr=True):
    """Probe the saved file and describe it honestly relative to the source."""
    codec, _, abr = src.partition("|")
    codec = "" if codec in ("NA", "None") else codec
    abr = "" if abr in ("NA", "None") else abr
    src_name = nice(codec)
    try:
        origin = f"{src_name} source (~{round(float(abr))} kbps)"
    except ValueError:
        origin = f"{src_name} source"

    out_codec = "mp3" if fmt == "mp3" else ""
    summary = ("MP3, highest VBR setting" if vbr else "MP3, constant bitrate") if fmt == "mp3" else "Original audio"
    try:
        out = subprocess.run([tool("ffprobe") or "ffprobe", "-v", "error", "-select_streams", "a:0",
                              "-show_entries", "stream=codec_name,sample_rate,channels,bit_rate:format=bit_rate",
                              "-of", "json", path], capture_output=True, text=True, timeout=20)
        info = json.loads(out.stdout)
        st = info["streams"][0]
        out_codec = st.get("codec_name", out_codec)
        ext = os.path.splitext(path)[1].lstrip(".").upper()
        if fmt == "mp3":
            head = "MP3"
        else:
            head = nice(out_codec) if ext == nice(out_codec).upper() else f"{ext} ({nice(out_codec)})"
        bits = [head]
        br = st.get("bit_rate") or info.get("format", {}).get("bit_rate")
        if br and br != "N/A":
            mode = (" VBR (highest setting)" if vbr else " CBR (constant)") if fmt == "mp3" else ""
            bits.append(f"~{round(int(br) / 1000)} kbps{mode}")
        if st.get("sample_rate"):
            bits.append(f"{int(st['sample_rate']) / 1000:g} kHz")
        bits.append({1: "mono", 2: "stereo"}.get(st.get("channels", 2), "multichannel"))
        summary = ", ".join(bits)
    except Exception:
        pass

    if fmt != "mp3" and codec and nice(codec) == nice(out_codec):
        note = (f"This is the site's {src_name} audio saved exactly as streamed, with no conversion, "
                "so no quality was lost.")
    else:
        note = (f"Converted from the best available {origin}. It was already lossy, so this file can't "
                "sound better than the source, but it keeps nearly all of it.")
    if out_codec == "opus":
        note += " Note: Rekordbox, Serato, Traktor and Apple Music can't play Opus. Choose MP3 or M4A for DJ use."
    return {"summary": summary, "note": note}


MP3_RATES = [8, 16, 24, 32, 40, 48, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320]


def cbr_rate(ytdlp, url):
    """Constant bitrate (kbps) matching the source's best audio, capped at 320."""
    try:
        out = subprocess.run(low_priority([ytdlp, "-f", "bestaudio", "--no-playlist", "--print", "%(abr)s", "--", url]),
                             capture_output=True, text=True, timeout=60)
        abr = float(out.stdout.strip().splitlines()[-1])
        return next((r for r in MP3_RATES if r >= abr - 1), 320)
    except Exception:
        return 320


def format_args(fmt, vbr, ytdlp, url):
    if fmt == "m4a":
        # Prefer the AAC stream so it is copied as-is; only converts if a site has no AAC.
        return ["-f", "bestaudio[ext=m4a]/bestaudio", "-x", "--audio-format", "m4a"]
    if fmt == "original":
        return ["-f", "bestaudio", "-x", "--audio-format", "best"]
    return ["-f", "bestaudio", "-x", "--audio-format", "mp3",
            "--audio-quality", "0" if vbr else f"{cbr_rate(ytdlp, url)}K"]


def run_job(job_id, url, fmt, vbr, square, sponsor, ytdlp, ffmpeg, out_dir):
    job = JOBS[job_id]
    # Intermediate files live in their own temp folder, so a cancelled download leaves nothing behind.
    tmp = tempfile.mkdtemp(prefix="quick-crate-")
    pfile = os.path.join(tmp, "convert.progress")
    duration = [0.0]
    cmd = [ytdlp] + format_args(fmt, vbr, ytdlp, url) + [
           "--embed-metadata", "--embed-thumbnail", "--convert-thumbnails", "jpg"] + TAG_ARGS
    if square:
        cmd += ["--ppa", SQUARE_CROP]
    if sponsor:
        cmd += SPONSORBLOCK_ARGS
    cmd += ["--no-playlist", "--newline", "--progress",
           "--ffmpeg-location", os.path.dirname(ffmpeg),
           "--progress-template", "download:PROG %(progress._percent_str)s",
           "--progress-template", "postprocess:PP %(progress.postprocessor)s|%(progress.status)s",
           "--print", "pre_process:TITLE %(title)s",
           "--print", "before_dl:SRC %(acodec)s|%(abr)s",
           "--print", "before_dl:DUR %(duration)s",
           "--postprocessor-args", f"ExtractAudio:-progress {pfile} -nostats",
           "--print", "after_move:FILE %(filepath)s",
           "-o", OUTPUT_NAME, "-P", str(out_dir), "-P", f"temp:{tmp}", "--", url]
    tail = []
    done = threading.Event()

    def watch():
        while not done.wait(0.3):
            try:
                us = [l for l in open(pfile).read().splitlines() if l.startswith("out_time_us=")]
                if us and duration[0] > 0 and job.get("stage") == "convert":
                    job["cpercent"] = max(job["cpercent"], min(99.0, int(us[-1].split("=")[1]) / 1e6 / duration[0] * 100))
            except (OSError, ValueError):
                pass

    threading.Thread(target=watch, daemon=True).start()
    try:
        if job.get("cancel"):
            raise InterruptedError
        # Own process group, so Cancel can stop yt-dlp and the ffmpeg it starts in one go.
        p = subprocess.Popen(low_priority(cmd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             encoding="utf-8", errors="replace", start_new_session=(SYSTEM != "Windows"))
        job["proc"] = p
        for line in p.stdout:
            line = line.rstrip()
            if line.startswith("PROG "):
                m = re.search(r"([\d.]+)%", line)
                if m and job["stage"] in ("prep", "download"):
                    job["stage"] = "download"
                    job["percent"] = float(m.group(1))
            elif line.startswith("TITLE "):
                job["title"] = line[6:]
            elif line.startswith("SRC "):
                job["src"] = line[4:]
            elif line.startswith("DUR "):
                try:
                    duration[0] = float(line[4:])
                except ValueError:
                    pass
            elif line.startswith("FILE "):
                job["file"] = line[5:]
            elif line.startswith("PP "):
                if line == "PP ExtractAudio|started":
                    job["stage"] = "convert"
                elif line in ("PP ExtractAudio|finished", "PP Metadata|started"):
                    job["stage"] = "finish"
            elif line.strip():
                tail.append(line)
        p.wait()
        f = job.get("file")
        if job.get("cancel"):
            if f and os.path.exists(f):  # finished just as Cancel was pressed: honour the cancel
                os.remove(f)
            raise InterruptedError
        if p.returncode == 0 and f and os.path.exists(f):
            job.update(state="done", filename=os.path.basename(f), percent=100, cpercent=100,
                       quality=describe_quality(f, job.get("src", ""), fmt, vbr))
        else:
            errs = [l for l in tail if "ERROR" in l] or tail[-1:]
            job.update(state="error", error=re.sub(r"^ERROR:\s*", "", errs[-1]) if errs else "Download failed")
    except InterruptedError:
        job.update(state="cancelled")
    except Exception as e:
        job.update(state="error", error=str(e))
    finally:
        done.set()
        job.pop("proc", None)
        shutil.rmtree(tmp, ignore_errors=True)


def ytdlp_info():
    """Version and age of the installed yt-dlp (its versions are release dates, e.g. 2026.10.26)."""
    path = tool("yt-dlp")
    if not path:
        return {"installed": False}
    try:
        v = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=30).stdout.strip()
        y, m, d = (int(x) for x in v.split(".")[:3])
        age = (datetime.date.today() - datetime.date(y, m, d)).days
    except Exception:
        v, age = "unknown", None
    return {"installed": True, "version": v, "age_days": age, "old": age is not None and age > YTDLP_OLD_DAYS}


def update_ytdlp():
    """Update yt-dlp the way it was installed: Homebrew if it came from there, otherwise yt-dlp -U."""
    path = tool("yt-dlp")
    if not path:
        return {"ok": False, "message": "yt-dlp wasn't found. " + INSTALL_HINT}
    before = ytdlp_info().get("version")
    real = os.path.realpath(path)
    brew = tool("brew")
    if brew and ("/Cellar/" in real or real.startswith("/opt/homebrew/")):
        cmd = [brew, "upgrade", "yt-dlp"]
    else:
        cmd = [path, "-U"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except Exception as e:
        return {"ok": False, "message": f"Update failed: {e}"}
    after = ytdlp_info().get("version")
    if after and after != before:
        return {"ok": True, "message": f"yt-dlp updated from {before} to {after}.", "version": after}
    out = (r.stdout + r.stderr).strip().splitlines()
    if r.returncode == 0:
        return {"ok": True, "message": f"yt-dlp {after} is already the latest version.", "version": after}
    hint = next((l for l in reversed(out) if l.strip()), "unknown error")
    return {"ok": False, "message": f"Couldn't update yt-dlp: {hint}"}


def choose_folder(current):
    """Show the system folder picker. Returns a path, None if cancelled; raises if no picker exists."""
    if SYSTEM == "Darwin":
        esc = str(current).replace("\\", "\\\\").replace('"', '\\"')
        r = subprocess.run(["osascript", "-e", "activate", "-e",
                            f'POSIX path of (choose folder with prompt "Choose where downloads are saved" '
                            f'default location (POSIX file "{esc}"))'],
                           capture_output=True, text=True)
        if r.returncode != 0:  # cancelled
            return None
        return r.stdout.strip() or None
    script = ("import sys,tkinter as t;from tkinter import filedialog as f;r=t.Tk();r.withdraw();"
              "r.attributes('-topmost',True);print(f.askdirectory(initialdir=sys.argv[1],"
              "title='Choose where downloads are saved'))")
    r = subprocess.run([sys.executable, "-c", script, str(current)], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("No folder picker is available here. Set download_dir in " + str(CONFIG) + " instead.")
    return r.stdout.strip() or None


def reveal(path, select):
    """Open a file, or show it selected in the file manager."""
    if SYSTEM == "Darwin":
        subprocess.Popen(["open", "-R", str(path)] if select else ["open", str(path)])
    elif SYSTEM == "Windows":
        if select:
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            os.startfile(str(path))
    else:
        subprocess.Popen(["xdg-open", str(path.parent if select else path)])


def cancel_job(job):
    """Stop a running download: yt-dlp and the ffmpeg it started (they share a process group)."""
    job["cancel"] = True
    p = job.get("proc")
    if p and p.poll() is None:
        try:
            if SYSTEM == "Windows":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
            else:
                os.killpg(p.pid, signal.SIGTERM)
        except OSError:
            pass


def job_file(job):
    """The job's finished file, only if it is inside the folder that job saved to."""
    f = job and job.get("file")
    if not f:
        return None
    p = Path(f).resolve()
    return p if p.parent == Path(job["dir"]) and p.exists() else None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def host_ok(self):
        return self.headers.get("Host", "") in (f"127.0.0.1:{PORT}", f"localhost:{PORT}")

    def send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(body)).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + ("" if ctype.startswith("image/") else "; charset=utf-8"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def settings(self):
        d = STATE["download_dir"]
        return {"download_dir": str(d), "display": pretty(d)}

    def do_GET(self):
        if not self.host_ok():
            return self.send(403, {"error": "forbidden"})
        ACTIVITY["last"] = time.monotonic()
        if self.path.split("?")[0] in ("/", "/api/ping"):
            # Only a (re)loaded or visible page cancels a goodbye; a status poll still in flight must not.
            ACTIVITY["bye"] = None
        path = self.path.split("?")[0]
        if path == "/":
            return self.send(200, HTML, "text/html")
        if path == "/api/settings":
            return self.send(200, self.settings())
        if path == "/api/ping":
            return self.send(200, {"ok": True})
        if path == "/api/ytdlp":
            return self.send(200, ytdlp_info())
        m = re.fullmatch(r"/api/job/([0-9a-f]+)", path)
        if m and m.group(1) in JOBS:
            job = JOBS[m.group(1)]
            return self.send(200, {k: v for k, v in job.items() if k not in ("file", "dir", "proc", "cancel")})
        m = re.fullmatch(r"/api/art/([0-9a-f]+)", path)
        if m and m.group(1) in JOBS:
            f, ffmpeg = job_file(JOBS[m.group(1)]), tool("ffmpeg")
            if f and ffmpeg:
                r = subprocess.run([ffmpeg, "-v", "error", "-i", str(f), "-an", "-frames:v", "1",
                                    "-c:v", "copy", "-f", "image2pipe", "-"], capture_output=True, timeout=20)
                if r.returncode == 0 and r.stdout:
                    return self.send(200, r.stdout, "image/jpeg")
        self.send(404, {"error": "not found"})

    def do_POST(self):
        # Host check + JSON-only bodies stop other websites from driving this local server.
        if not self.host_ok() or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self.send(403, {"error": "forbidden"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        except ValueError:
            return self.send(400, {"error": "bad request"})
        if self.path == "/api/bye":  # the page is closing (or reloading, which pings again right away)
            ACTIVITY["bye"] = time.monotonic()
            return self.send(200, {"ok": True})
        ACTIVITY["last"], ACTIVITY["bye"] = time.monotonic(), None
        if self.path == "/api/download":
            url = str(body.get("url", "")).strip()
            if not re.match(r"https?://\S+$", url):
                return self.send(200, {"error": "Please paste a full link starting with http:// or https://"})
            ytdlp, ffmpeg = tool("yt-dlp"), tool("ffmpeg")
            missing = [n for n, p in (("yt-dlp", ytdlp), ("ffmpeg", ffmpeg)) if not p]
            if missing:
                return self.send(200, {"error": f"{' and '.join(missing)} wasn't found. " + INSTALL_HINT})
            out_dir = STATE["download_dir"]
            if not out_dir.is_dir():
                return self.send(200, {"error": f"The download folder {pretty(out_dir)} no longer exists. Choose another one."})
            job_id = uuid.uuid4().hex
            JOBS[job_id] = {"state": "running", "stage": "prep", "percent": 0.0, "cpercent": 0.0, "dir": str(out_dir)}
            fmt = body.get("format") if body.get("format") in FORMATS else "mp3"
            threading.Thread(target=run_job, daemon=True,
                             args=(job_id, url, fmt, bool(body.get("vbr")), body.get("square", True) is not False,
                                   bool(body.get("sponsorblock")), ytdlp, ffmpeg, out_dir)).start()
            return self.send(200, {"id": job_id})
        if self.path == "/api/cancel":
            job = JOBS.get(str(body.get("id")))
            if not job or job.get("state") != "running":
                return self.send(404, {"error": "no running download"})
            cancel_job(job)
            return self.send(200, {"ok": True})
        if self.path == "/api/quit":
            for j in JOBS.values():
                if j.get("state") == "running":
                    cancel_job(j)
            self.send(200, {"ok": True})
            print("Quit button pressed, so Quick Crate is stopping.")
            threading.Thread(target=STATE["server"].shutdown, daemon=True).start()
            return
        if self.path == "/api/update-ytdlp":
            return self.send(200, update_ytdlp())
        if self.path == "/api/choose-folder":
            try:
                picked = choose_folder(STATE["download_dir"])
            except RuntimeError as e:
                return self.send(200, {"error": str(e)})
            if picked and Path(picked).is_dir():
                STATE["download_dir"] = Path(picked).resolve()
                save_download_dir(STATE["download_dir"])
            return self.send(200, self.settings())
        if self.path == "/api/open":
            job = JOBS.get(str(body.get("id")))
            f = job_file(job) if job and job.get("state") == "done" else None
            if not f:
                return self.send(404, {"error": "no file"})
            reveal(f, body.get("what") != "file")
            return self.send(200, {"ok": True})
        self.send(404, {"error": "not found"})


APP_WINDOW_BROWSERS = ["Google Chrome", "Microsoft Edge", "Brave Browser", "Chromium", "Vivaldi"]


def app_window_browser():
    """A Chromium-based browser that can show the page as its own app window (no tabs or address bar)."""
    if SYSTEM == "Darwin":
        for name in APP_WINDOW_BROWSERS:
            for root in ("/Applications", str(Path.home() / "Applications")):
                exe = f"{root}/{name}.app/Contents/MacOS/{name}"
                if os.access(exe, os.X_OK):
                    return exe
    elif SYSTEM == "Linux":
        for name in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge", "brave-browser"):
            if shutil.which(name):
                return shutil.which(name)
    return None


def open_page(url):
    """Open the page in a compact app window if possible (like the Mac app), otherwise in a browser tab."""
    exe = None if "--browser-tab" in sys.argv else app_window_browser()
    if exe:
        try:
            subprocess.Popen([exe, f"--app={url}", "--window-size=600,440"], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return
        except OSError:
            pass
    webbrowser.open(url)


def quit_when_idle(srv):
    """Stop the server once the page has gone away and no download is running."""
    while True:
        time.sleep(2)
        if any(j.get("state") == "running" for j in JOBS.values()):
            continue
        now = time.monotonic()
        bye, last = ACTIVITY["bye"], ACTIVITY["last"]
        if (bye is not None and now - bye > QUIT_AFTER_BYE) or now - last > QUIT_AFTER_SILENCE:
            print("Page closed, so Quick Crate is stopping.")
            srv.shutdown()
            return


if __name__ == "__main__":
    try:
        srv = ThreadingHTTPServer((HOST, PORT), Handler)
        STATE["server"] = srv
    except OSError:
        # Already running (e.g. the launcher was clicked twice): just open the page.
        print(f"Quick Crate is already running at http://localhost:{PORT}/")
        if "--no-browser" not in sys.argv:
            open_page(f"http://localhost:{PORT}/")
        sys.exit(0)
    url = f"http://localhost:{PORT}/"
    print(f"Quick Crate running at {url}  (Ctrl+C to stop)")
    for name in ("yt-dlp", "ffmpeg"):
        if not tool(name):
            print(f"Warning: {name} wasn't found. " + INSTALL_HINT)
    if "--no-browser" not in sys.argv:
        threading.Timer(0.5, lambda: open_page(url)).start()
    if "--keep-running" not in sys.argv:
        threading.Thread(target=quit_when_idle, args=(srv,), daemon=True).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    # Give a cancelled download a moment to clean up its temp folder before exiting.
    deadline = time.monotonic() + 5
    while any(j.get("state") == "running" for j in JOBS.values()) and time.monotonic() < deadline:
        time.sleep(0.1)
