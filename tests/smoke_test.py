#!/usr/bin/env python3
"""End-to-end test of the web version: real downloads through server.py, with yt-dlp and ffmpeg.

It serves generated test audio from a local web server (no internet or real sites needed), starts
server.py with a temporary home folder (your own settings and Downloads are not touched), then checks:
MP3 and M4A downloads with clean "Artist - Title" names and tags, Cancel, the bad-link error, and on
Windows that the conversion runs at Idle priority. Needs yt-dlp and ffmpeg on PATH.

    python3 tests/smoke_test.py
"""
import functools, json, os, platform, shutil, subprocess, sys, tempfile, threading, time, urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8799
API = f"http://127.0.0.1:{PORT}"
WINDOWS = platform.system() == "Windows"


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def tags(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags=artist,title", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    t = json.loads(out)["format"].get("tags", {})
    return {k.lower(): v for k, v in t.items()}


def get(path):
    with urllib.request.urlopen(API + path, timeout=10) as r:
        return json.loads(r.read())


def post(path, body=None):
    req = urllib.request.Request(API + path, data=json.dumps(body or {}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def wait_for(job_id, until=lambda j: j["state"] != "running", timeout=180):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        j = get(f"/api/job/{job_id}")
        if until(j):
            return j
        time.sleep(0.25)
    raise AssertionError(f"job {job_id} timed out: {j}")


def priority_of(name):
    """Windows priority class of a running process, e.g. 'Idle', or None if it isn't running."""
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"(Get-Process -Name {name} -ErrorAction SilentlyContinue | Select-Object -First 1).PriorityClass"],
                       capture_output=True, text=True)
    return r.stdout.strip() or None


def main():
    for t in ("yt-dlp", "ffmpeg", "ffprobe"):
        assert shutil.which(t), f"{t} isn't on PATH"
    work = Path(tempfile.mkdtemp(prefix="quick-crate-test-"))
    media, home = work / "media", work / "home"
    downloads = home / "Downloads"
    media.mkdir(); downloads.mkdir(parents=True)

    short = "Test Artist - Test Track (Official Video).m4a"
    long_ = "Long Artist - Long Mix (Extended Mix).m4a"
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=440:duration=15", "-ac", "2", "-c:a", "aac", "-b:a", "128k", str(media / short))
    ffmpeg("-f", "lavfi", "-i", "sine=frequency=330:duration=1800", "-ac", "2", "-c:a", "aac", "-b:a", "96k", str(media / long_))

    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *a): pass

    class QuietServer(ThreadingHTTPServer):
        def handle_error(self, *a): pass  # yt-dlp probes the file and hangs up early; that's fine

    files = QuietServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(media)))
    threading.Thread(target=files.serve_forever, daemon=True).start()
    url = lambda name: f"http://127.0.0.1:{files.server_address[1]}/" + urllib.request.quote(name)

    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), QUICK_CRATE_PORT=str(PORT))
    log = open(work / "server.log", "w")
    server = subprocess.Popen([sys.executable, str(ROOT / "web" / "server.py"), "--no-browser", "--keep-running"],
                              env=env, stdout=log, stderr=subprocess.STDOUT)
    failed = False
    try:
        for _ in range(60):
            try:
                get("/api/ping"); break
            except OSError:
                time.sleep(0.5)
        else:
            raise AssertionError("server didn't start")

        assert get("/api/settings")["download_dir"] == str(downloads.resolve()), get("/api/settings")
        info = get("/api/ytdlp")
        assert info["installed"], info
        print(f"ok   server up, yt-dlp {info['version']}")

        for fmt, ext in (("mp3", "mp3"), ("m4a", "m4a")):
            j = wait_for(post("/api/download", {"url": url(short), "format": fmt})["id"])
            assert j["state"] == "done", j
            assert j["filename"] == f"Test Artist - Test Track.{ext}", j["filename"]
            t = tags(downloads / j["filename"])
            assert t.get("artist") == "Test Artist" and t.get("title") == "Test Track", t
            print(f"ok   {fmt}: {j['filename']}  ({j['quality']['summary']})")

        job_id = post("/api/download", {"url": url(long_), "format": "mp3"})["id"]
        wait_for(job_id, lambda j: j["state"] != "running" or j.get("stage") == "convert")
        if WINDOWS:
            time.sleep(1)
            prio = priority_of("ffmpeg")
            assert prio == "Idle", f"ffmpeg priority is {prio}, expected Idle"
            print(f"ok   conversion runs at {prio} priority")
        post("/api/cancel", {"id": job_id})
        j = wait_for(job_id)
        assert j["state"] == "cancelled", j
        time.sleep(1)
        assert not list(downloads.glob("Long Artist*")), list(downloads.iterdir())
        print("ok   cancel stops the download and leaves nothing behind")

        r = post("/api/download", {"url": "not a link", "format": "mp3"})
        assert "http" in r.get("error", ""), r
        print("ok   bad links are rejected")
        print("All tests passed.")
    except Exception:
        failed = True
        raise
    finally:
        try:
            post("/api/quit")
        except OSError:
            pass
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            server.kill()
        files.shutdown()
        log.close()
        if failed:
            print("--- server.log ---\n" + (work / "server.log").read_text(errors="replace"))
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
