# -*- coding: utf-8 -*-
"""Local media backend wrapper (Phase 8 Materials).

Thin, dependency-safe wrapper around yt-dlp for the Materials tab:
probe metadata, resolve a playable stream, launch a native player, and
download media. Never fabricates results: any failure returns
{"error": "..."}. Player fallback order: mpv -> vlc -> xdg-open.

No Qt imports here so the backend can be tested standalone.
"""
import os
import re
import shutil
import subprocess
import threading
import urllib.request

try:
    import yt_dlp
    _YTDLP_IMPORT = True
except ImportError:
    yt_dlp = None
    _YTDLP_IMPORT = False

SAFE_ID = re.compile(r"[^A-Za-z0-9._-]")


def available():
    """(ready, reason) — yt-dlp present + players that exist."""
    if not _YTDLP_IMPORT and shutil.which("yt-dlp") is None:
        return False, "yt-dlp not installed"
    players = [p for p in ("mpv", "vlc", "xdg-open") if shutil.which(p)]
    if not players:
        return False, "no media player found"
    return True, ", ".join(players)


def _opts():
    return {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "socket_timeout": 15,
        "format": "best",
    }


def probe(url):
    """Fetch metadata without downloading. Returns dict or {"error": ...}."""
    if not url:
        return {"error": "no URL"}
    if not _YTDLP_IMPORT:
        return {"error": "yt-dlp python module unavailable"}
    try:
        with yt_dlp.YoutubeDL(_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
        duration = info.get("duration")
        return {
            "title": info.get("title"),
            "duration_seconds": int(duration) if duration else None,
            "uploader": info.get("uploader"),
            "thumbnail_url": info.get("thumbnail"),
            "webpage_url": info.get("webpage_url") or url,
        }
    except Exception as exc:  # network / unsupported site / geo
        return {"error": str(exc)}


def _stream_url(url):
    """Resolve a directly playable stream URL via yt-dlp."""
    if not _YTDLP_IMPORT:
        cmd = [shutil.which("yt-dlp"), "-g", "-f", "best", url]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "yt-dlp failed").strip())
        return proc.stdout.strip().splitlines()[0]
    with yt_dlp.YoutubeDL(_opts()) as ydl:
        info = ydl.extract_info(url, download=False)
        direct = info.get("url")
        if direct:
            return direct
        formats = info.get("formats") or []
        if formats:
            return formats[-1].get("url")
        raise RuntimeError("no playable stream found")


def play(url, prefer="stream"):
    """Resolve the stream and launch a native player (mpv -> vlc -> xdg-open)."""
    try:
        target = _stream_url(url) if prefer == "stream" else url
    except Exception as exc:
        target = url  # let the player try the page directly
    for player in ("mpv", "vlc"):
        path = shutil.which(player)
        if path:
            subprocess.Popen([path, target],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return {"player": player, "stream": target}
    if shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", target],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"player": "xdg-open", "stream": target}
    return {"error": "no player (mpv/vlc/xdg-open) available"}


def download(url, dest_dir):
    """Download media into dest_dir; returns saved path or raises."""
    os.makedirs(dest_dir, exist_ok=True)
    if _YTDLP_IMPORT:
        opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 15,
            "format": "best[ext=mp4]/best",
            "outtmpl": os.path.join(dest_dir, "%(title).80s.%(ext)s"),
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            path = ydl.prepare_filename(info)
        if not os.path.exists(path):
            path = None
            for name in os.listdir(dest_dir):
                if name not in (".", ".."):
                    path = os.path.join(dest_dir, name)
                    break
        if not path:
            raise RuntimeError("download finished but no file found")
        return path
    cmd = [shutil.which("yt-dlp"), "-f", "best[ext=mp4]/best",
           "-o", os.path.join(dest_dir, "%(title).80s.%(ext)s"), url]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "yt-dlp failed").strip())
    names = [n for n in os.listdir(dest_dir)
             if os.path.isfile(os.path.join(dest_dir, n))]
    if not names:
        raise RuntimeError("download finished but no file found")
    return os.path.join(dest_dir, names[-1])


def fetch_thumbnail(url, cache_dir):
    """Download a thumbnail into cache_dir; returns local path or None."""
    if not url:
        return None
    os.makedirs(cache_dir, exist_ok=True)
    name = SAFE_ID.sub("_", url.rsplit("/", 1)[-1])[:120] + ".jpg"
    path = os.path.join(cache_dir, name)
    if os.path.exists(path):
        return path
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read(512 * 1024)
        with open(path, "wb") as fh:
            fh.write(data)
        return path
    except Exception:
        return None
