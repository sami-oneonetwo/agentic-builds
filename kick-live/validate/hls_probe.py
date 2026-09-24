#!/usr/bin/env python
"""hls_probe.py - viewer-QA tool for the kick-live stream.

Given an HLS source it verifies the stream is genuinely watchable and writes a
structured pass/fail report.  It never posts anything to Kick; it only reads
public data (channel API, playback manifest, segments).

Source selection (exactly one):
  --url URL|PATH      master or media playlist, http(s) or a local file
  --channel NAME      fetch playback_url from the Kick public channel API
  --local             $RUN_DIR/hls/index.m3u8 (local test output of stream/run.sh)

Steps: fetch master -> pick highest-bandwidth variant -> fetch media playlist ->
download the last --seconds of segments -> concatenate -> ffprobe (codec, size,
fps, bitrate, audio) -> ffmpeg blackdetect/freezedetect/silencedetect/volumedetect ->
frame grid + last frame PNGs -> latency (now - PROGRAM-DATE-TIME of last segment)
-> manifest fetch ms and download speed vs bitrate.

Output: OUT/probe.json, OUT/frame_grid.png, OUT/last_frame.png, OUT/ffmpeg_analysis.log
and one verdict line on stdout.  Exit 0 = pass, 1 = fail, 2 = error (no manifest,
channel offline, tool failure).

Runs on Python 3.9 with stdlib + requests (optional) + pillow (optional, for the grid).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import urllib.error

# --------------------------------------------------------------------------- env
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)


def _pick_exe(*cands):
    for c in cands:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


RUN_DIR = os.environ.get("RUN_DIR") or os.path.join(REPO, "run")
FFMPEG = os.environ.get("FFMPEG") or _pick_exe(
    os.path.expanduser("~/.local/bin/ffmpeg-static"), shutil.which("ffmpeg")) or "ffmpeg"
FFPROBE = os.environ.get("FFPROBE") or _pick_exe(
    os.path.expanduser("~/.local/bin/ffprobe-static"), shutil.which("ffprobe")) or "ffprobe"
KICK_CHANNEL = os.environ.get("KICK_CHANNEL", "atleastonce")
# {slug} template; override only for offline testing against a local server.
KICK_API_URL = os.environ.get("KICK_API_URL") or "https://kick.com/api/v2/channels/{slug}"
STREAM_WIDTH = int(os.environ.get("STREAM_WIDTH", "1280") or 1280)
STREAM_HEIGHT = int(os.environ.get("STREAM_HEIGHT", "720") or 720)

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
HTTP_TIMEOUT = 20            # per connect / per read (seconds)
# Wall-clock cap for one HTTP transfer.  Per-read timeouts never fire on a server that
# trickles bytes, so without this a single slow segment could hang the probe forever.
HTTP_TOTAL_TIMEOUT = float(os.environ.get("HLS_PROBE_HTTP_TOTAL_TIMEOUT", "120") or 120)

try:  # optional
    import requests  # type: ignore
except Exception:  # pragma: no cover
    requests = None

VERBOSE = True


def log(msg):
    if VERBOSE:
        sys.stderr.write("[hls_probe] %s\n" % msg)
        sys.stderr.flush()


class ProbeError(Exception):
    """Fatal: the probe could not run (exit 2)."""


def utcnow():
    return _dt.datetime.now(_dt.timezone.utc)


def iso(ts):
    if ts.tzinfo is not None:
        ts = ts.astimezone(_dt.timezone.utc)
    return ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# --------------------------------------------------------------------------- fetch
def is_http(u):
    return u.lower().startswith(("http://", "https://"))


def _iter_body(reader, chunk=1 << 16):
    """Yield body chunks as they arrive.

    Uses read1() (at most one socket recv per call) instead of read(n)/iter_content(n),
    which block inside recv until n bytes have accumulated: against a server that
    trickles bytes, that never returns and no wall-clock check could run.
    """
    read1 = getattr(reader, "read1", None)
    while True:
        if read1 is not None:
            try:
                c = read1(chunk, decode_content=True)   # urllib3 2.x: honour Content-Encoding
            except TypeError:
                c = read1(chunk)                        # http.client.HTTPResponse
        else:
            c = reader.read(chunk)
        if not c:
            return
        yield c


def _collect_capped(reader, url, t0, dest=None):
    """Read the body to dest (path) or memory, enforcing HTTP_TOTAL_TIMEOUT.

    Returns (bytes_or_None, size).  Raises ProbeError (never retried) on the cap.
    """
    n = 0
    buf = []
    fh = open(dest, "wb") if dest else None
    try:
        for chunk in _iter_body(reader):
            if fh is not None:
                fh.write(chunk)
            else:
                buf.append(chunk)
            n += len(chunk)
            if time.monotonic() - t0 > HTTP_TOTAL_TIMEOUT:
                raise ProbeError("download exceeded %.0fs wall clock (%d bytes so far): %s"
                                 % (HTTP_TOTAL_TIMEOUT, n, url.split("?")[0]))
    finally:
        if fh is not None:
            fh.close()
    return (None if fh is not None else b"".join(buf)), n


def http_get(url, stream_to=None, retries=3):
    """GET with browser UA and exponential backoff on 403/429/5xx and network errors.

    Returns (status, bytes_or_None, elapsed_s, size_bytes, final_url).  When stream_to is
    a path the body is written there and bytes is None.  404 returns immediately (no
    retry).  final_url is the URL after redirects; relative playlist references must be
    resolved against it, not the requested URL.  A transfer that exceeds
    HTTP_TOTAL_TIMEOUT raises ProbeError immediately (not retried).
    """
    delay = 1.0
    last_err = None
    for attempt in range(1, retries + 1):
        t0 = time.monotonic()
        final_url = url
        try:
            if requests is not None:
                r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT,
                                 stream=True)
                status = r.status_code
                final_url = r.url or url
                if status == 200:
                    try:
                        body, n = _collect_capped(r.raw, url, t0, dest=stream_to)
                    finally:
                        r.close()
                    return status, body, time.monotonic() - t0, n, final_url
                body = r.content[:200] if not stream_to else b""
                r.close()
            else:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                try:
                    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                        status = resp.status
                        final_url = resp.geturl() or url
                        body, n = _collect_capped(resp, url, t0, dest=stream_to)
                        return status, body, time.monotonic() - t0, n, final_url
                except urllib.error.HTTPError as e:
                    status = e.code
                    body = b""
            # non-200
            if status in (404, 410):
                return status, body, time.monotonic() - t0, 0, final_url
            if status in (403, 429) or status >= 500:
                last_err = "HTTP %d" % status
            else:
                return status, body, time.monotonic() - t0, 0, final_url
        except ProbeError:
            raise
        except Exception as e:  # network / timeout
            last_err = "%s: %s" % (type(e).__name__, e)
        if attempt < retries:
            log("fetch %s failed (%s); retry in %.0fs" % (url.split("?")[0][-60:], last_err, delay))
            time.sleep(delay)
            delay = min(delay * 2, 120)
    raise ProbeError("fetch failed after %d attempts: %s (%s)" % (retries, last_err, url.split("?")[0]))


def fetch_text(src):
    """Return (text, elapsed_ms, http_status_or_None, final_src) for a URL or local path.

    final_src is the post-redirect URL (or the expanded local path); use it as the base
    for relative references.  A UTF-8 BOM is stripped.
    """
    if is_http(src):
        status, body, el, _n, final = http_get(src)
        if status != 200:
            snippet = (body or b"")[:120].decode("utf-8", "replace").strip()
            if status in (404, 410):
                raise ProbeError("no manifest: HTTP %d for %s (channel offline / not streaming)%s"
                                 % (status, src.split("?")[0], (" - " + snippet) if snippet else ""))
            raise ProbeError("manifest fetch HTTP %d for %s %s" % (status, src.split("?")[0], snippet))
        return body.decode("utf-8", "replace").lstrip("﻿"), round(el * 1000, 1), status, final
    path = os.path.expanduser(src)
    if not os.path.isfile(path):
        raise ProbeError("no manifest: local file not found: %s (is the local HLS output running?)" % path)
    t0 = time.monotonic()
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        txt = fh.read()
    return txt.lstrip("﻿"), round((time.monotonic() - t0) * 1000, 1), None, path


def fetch_file(src, dest):
    """Download/copy src to dest. Return (elapsed_s, size_bytes)."""
    if is_http(src):
        status, _b, el, n, _final = http_get(src, stream_to=dest)
        if status != 200:
            raise ProbeError("segment fetch HTTP %d: %s" % (status, src.split("?")[0]))
        return el, n
    path = os.path.expanduser(src)
    if not os.path.isfile(path):
        raise ProbeError("segment missing: %s" % path)
    t0 = time.monotonic()
    shutil.copyfile(path, dest)
    return time.monotonic() - t0, os.path.getsize(dest)


def resolve(base, ref):
    if is_http(ref):
        return ref
    if is_http(base):
        return urllib.parse.urljoin(base, ref)
    if os.path.isabs(ref):
        return ref
    return os.path.normpath(os.path.join(os.path.dirname(os.path.expanduser(base)), ref))


# --------------------------------------------------------------------------- m3u8
_ATTR_RE = re.compile(r'([A-Z0-9-]+)=("(?:[^"\\]|\\.)*"|[^,]*)')


def parse_attrs(s):
    out = {}
    for k, v in _ATTR_RE.findall(s):
        if v.startswith('"') and v.endswith('"'):
            v = v[1:-1]
        out[k] = v
    return out


def parse_pdt(s):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d+)?\s*(Z|z|[+-]\d{2}:?\d{2})?", s.strip())
    if not m:
        return None
    y, mo, d, hh, mm, ss, frac, tz = m.groups()
    micro = int(round(float(frac) * 1e6)) if frac else 0
    tzinfo = _dt.timezone.utc
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        tzs = tz[1:].replace(":", "")
        tzinfo = _dt.timezone(sign * _dt.timedelta(hours=int(tzs[:2]), minutes=int(tzs[2:])))
    try:
        return _dt.datetime(int(y), int(mo), int(d), int(hh), int(mm), int(ss), micro, tzinfo)
    except ValueError:
        return None


def parse_master(text, base):
    """Return list of variant dicts, or [] if this is not a master playlist."""
    variants = []
    lines = [l.strip() for l in text.splitlines()]
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF:"):
            a = parse_attrs(line[len("#EXT-X-STREAM-INF:"):])
            uri = None
            for nxt in lines[i + 1:]:
                if nxt and not nxt.startswith("#"):
                    uri = nxt
                    break
            if not uri:
                continue
            res = a.get("RESOLUTION", "")
            w = h = None
            if "x" in res:
                try:
                    w, h = [int(x) for x in res.lower().split("x")]
                except ValueError:
                    pass
            try:
                bw = int(a.get("BANDWIDTH", "0"))
            except ValueError:
                bw = 0
            fr = None
            if a.get("FRAME-RATE"):
                try:
                    fr = float(a["FRAME-RATE"])
                except ValueError:
                    pass
            variants.append({
                "name": a.get("VIDEO") or a.get("NAME") or res or ("variant%d" % (len(variants) + 1)),
                "bandwidth": bw,
                "resolution": res or None,
                "width": w, "height": h,
                "frame_rate": fr,
                "codecs": a.get("CODECS"),
                "uri": resolve(base, uri),
            })
    return variants


def parse_media(text, base):
    segs = []
    info = {"target_duration": None, "endlist": False, "media_sequence": 0, "init": None,
            "playlist_type": None}
    pending_dur = None
    pending_pdt = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXT-X-TARGETDURATION:"):
            try:
                info["target_duration"] = float(line.split(":", 1)[1])
            except ValueError:
                pass
        elif line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            try:
                info["media_sequence"] = int(line.split(":", 1)[1])
            except ValueError:
                pass
        elif line.startswith("#EXT-X-PLAYLIST-TYPE:"):
            info["playlist_type"] = line.split(":", 1)[1].strip()
        elif line.startswith("#EXT-X-ENDLIST"):
            info["endlist"] = True
        elif line.startswith("#EXT-X-MAP:"):
            a = parse_attrs(line[len("#EXT-X-MAP:"):])
            if a.get("URI"):
                info["init"] = resolve(base, a["URI"])
        elif line.startswith("#EXT-X-PROGRAM-DATE-TIME:"):
            pending_pdt = parse_pdt(line.split(":", 1)[1])
        elif line.startswith("#EXTINF:"):
            try:
                pending_dur = float(line[len("#EXTINF:"):].split(",", 1)[0])
            except ValueError:
                pending_dur = None
        elif line.startswith("#"):
            continue
        else:
            segs.append({"uri": resolve(base, line), "duration": pending_dur, "pdt": pending_pdt})
            pending_dur = None
            pending_pdt = None
    # fill missing durations from target duration
    for s in segs:
        if s["duration"] is None:
            s["duration"] = info["target_duration"] or 2.0
    # if only some segments carry PDT, extrapolate forward
    last_pdt = None
    for s in segs:
        if s["pdt"] is not None:
            last_pdt = s["pdt"]
        elif last_pdt is not None:
            s["pdt"] = last_pdt
        if s["pdt"] is not None:
            last_pdt = s["pdt"] + _dt.timedelta(seconds=s["duration"])
    return segs, info


def is_master(text):
    return "#EXT-X-STREAM-INF" in text


# --------------------------------------------------------------------------- kick api
def kick_get_channel(name):
    """Return the channel JSON.  Uses monitor/kick_api.get_channel when importable."""
    for p in (REPO, os.path.join(REPO, "monitor")):
        if p not in sys.path:
            sys.path.insert(0, p)
    get_channel = None
    try:
        from monitor.kick_api import get_channel as _gc  # type: ignore
        get_channel = _gc
    except Exception:
        try:
            from kick_api import get_channel as _gc  # type: ignore
            get_channel = _gc
        except Exception:
            get_channel = None
    if get_channel is not None:
        try:
            try:
                data = get_channel(name, api_url=KICK_API_URL)
            except TypeError:  # older signature without api_url
                data = get_channel(name)
            if isinstance(data, dict) and data.get("playback_url"):
                log("channel JSON via monitor/kick_api.get_channel")
                return data
            log("monitor/kick_api.get_channel returned no playback_url; using inline fetch")
        except Exception as e:
            st = getattr(e, "status", None)
            if st in (403, 429):
                # Cloudflare block / rate limit: retrying with the same UA seconds later only
                # burns requests.  Stop here; the caller/orchestrator backs off.
                raise ProbeError("Kick API HTTP %d for channel %s (blocked / rate limited); "
                                 "not retrying" % (st, name))
            log("monitor/kick_api.get_channel failed (%s); using inline fetch" % e)
    url = KICK_API_URL.replace("{slug}", urllib.parse.quote(name))
    status, body, el, _n, _final = http_get(url, retries=4)
    if status != 200:
        raise ProbeError("Kick API HTTP %d for %s" % (status, url))
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        raise ProbeError("Kick API returned non-JSON for %s" % url)
    log("channel JSON via inline fetch (%d ms)" % int(el * 1000))
    return data


# --------------------------------------------------------------------------- media tools
def run(cmd, timeout=180):
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except FileNotFoundError:
        raise ProbeError("tool not found: %s" % cmd[0])
    except subprocess.TimeoutExpired:
        raise ProbeError("tool timed out: %s" % " ".join(cmd[:3]))
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def frac(s):
    if not s or s in ("0/0", "N/A"):
        return None
    if "/" in s:
        a, b = s.split("/", 1)
        try:
            a, b = float(a), float(b)
        except ValueError:
            return None
        return a / b if b else None
    try:
        return float(s)
    except ValueError:
        return None


def ffprobe_info(path, total_bytes):
    rc, out, err = run([FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path])
    if rc != 0:
        raise ProbeError("ffprobe failed (%d): %s" % (rc, err.strip()[-300:]))
    try:
        j = json.loads(out)
    except ValueError:
        raise ProbeError("ffprobe produced no JSON")
    fmt = j.get("format", {})
    duration = None
    try:
        duration = float(fmt.get("duration"))
    except (TypeError, ValueError):
        pass
    vs = [s for s in j.get("streams", []) if s.get("codec_type") == "video"]
    aus = [s for s in j.get("streams", []) if s.get("codec_type") == "audio"]
    video = {"codec": None, "w": None, "h": None, "fps": None, "bitrate_kbps": None, "pix_fmt": None,
             "profile": None, "duration_s": None}
    audio = {"codec": None, "rate": None, "ch": None, "mean_volume_db": None, "max_volume_db": None}
    if vs:
        v = vs[0]
        try:  # video track can be shorter than the container (audio tail); frame targets use this
            video["duration_s"] = round(float(v.get("duration")), 3)
        except (TypeError, ValueError):
            pass
        video["codec"] = v.get("codec_name")
        video["profile"] = v.get("profile")
        video["pix_fmt"] = v.get("pix_fmt")
        video["w"] = v.get("width")
        video["h"] = v.get("height")
        fps = frac(v.get("avg_frame_rate")) or frac(v.get("r_frame_rate"))
        video["fps"] = round(fps, 3) if fps else None
        br = None
        try:
            br = float(v.get("bit_rate"))
        except (TypeError, ValueError):
            pass
        br_src = "stream"
        if not br:
            try:
                br = float(fmt.get("bit_rate"))
                br_src = "container"
            except (TypeError, ValueError):
                br = None
        if not br and duration:
            br = total_bytes * 8.0 / duration
            br_src = "computed"
        video["bitrate_kbps"] = round(br / 1000.0, 1) if br else None
        video["bitrate_source"] = br_src if br else None
    if aus:
        a = aus[0]
        audio["codec"] = a.get("codec_name")
        try:
            audio["rate"] = int(a.get("sample_rate"))
        except (TypeError, ValueError):
            pass
        audio["ch"] = a.get("channels")
    return duration, video, audio, len(vs), len(aus)


_BLACK_RE = re.compile(r"black_start:\s*([\d.]+)\s+black_end:\s*([\d.]+)\s+black_duration:\s*([\d.]+)")
_FREEZE_START_RE = re.compile(r"lavfi\.freezedetect\.freeze_start:\s*([\d.]+)")
_FREEZE_END_RE = re.compile(r"lavfi\.freezedetect\.freeze_end:\s*([\d.]+)")
_SIL_START_RE = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SIL_END_RE = re.compile(r"silence_end:\s*([\d.]+)\s*\|\s*silence_duration:\s*([\d.]+)")
_MEANVOL_RE = re.compile(r"mean_volume:\s*(-?[\d.]+|-inf)\s*dB")
_MAXVOL_RE = re.compile(r"max_volume:\s*(-?[\d.]+|-inf)\s*dB")


def ffmpeg_analyse(path, has_audio, duration, log_path):
    vf = "blackdetect=d=1:pic_th=0.98,freezedetect=n=-60dB:d=2"
    cmd = [FFMPEG, "-hide_banner", "-nostats", "-nostdin", "-v", "info", "-i", path,
           "-filter_complex"]
    if has_audio:
        cmd += ["[0:v:0]%s[v];[0:a:0]silencedetect=n=-50dB:d=3,volumedetect[a]" % vf,
                "-map", "[v]", "-map", "[a]"]
    else:
        cmd += ["[0:v:0]%s[v]" % vf, "-map", "[v]"]
    cmd += ["-f", "null", "-"]
    rc, _out, err = run(cmd, timeout=300)
    with open(log_path, "w") as fh:
        fh.write("$ " + " ".join(cmd) + "\n\n" + err)
    dur = duration or 0.0

    black = [(float(a), float(b), float(c)) for a, b, c in _BLACK_RE.findall(err)]
    starts = [float(x) for x in _FREEZE_START_RE.findall(err)]
    ends = [float(x) for x in _FREEZE_END_RE.findall(err)]
    freezes = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else dur
        freezes.append((s, max(e, s), max(e - s, 0.0)))
    sil_starts = [float(x) for x in _SIL_START_RE.findall(err)]
    sil_ends = [(float(a), float(b)) for a, b in _SIL_END_RE.findall(err)]
    silences = []
    for i, s in enumerate(sil_starts):
        if i < len(sil_ends):
            e, d = sil_ends[i]
        else:
            e, d = dur, max(dur - max(s, 0.0), 0.0)
        silences.append((max(s, 0.0), e, d))

    def _vol(rx):
        m = rx.findall(err)
        if not m:
            return None
        v = m[-1]
        return -999.0 if v == "-inf" else float(v)

    errors = [l for l in err.splitlines() if re.search(r"\b(error|corrupt|invalid|missing)\b", l, re.I)
              and "freezedetect" not in l and "blackdetect" not in l]
    return {
        "rc": rc,
        "black": black,
        "freezes": freezes,
        "silences": silences,
        "mean_volume_db": _vol(_MEANVOL_RE),
        "max_volume_db": _vol(_MAXVOL_RE),
        "error_lines": errors[:10],
        "error_count": len(errors),
    }


def extract_frames(path, duration, n, workdir, last_out, video_duration=None, fps=None):
    """One decode pass: n evenly spaced frames (exact, via select) plus the last frame.

    Input-side -ss seeking is unreliable on concatenated MPEG-TS (lands mid-GOP near the
    end), so instead the whole tail file is decoded once and frames are picked by
    timestamp.  Returns (frames, last_ok) where frames is a list of (t, png_path).

    Targets are t_k = off + k*step for k in [0, n).  The select expression is O(1) in n
    (a per-term sum fails to parse in ffmpeg's expression evaluator beyond ~64 terms):
    a frame is chosen when it is the first frame at or past a target boundary.  The span
    is clamped to the video track's duration (minus two frame periods) so the last target
    cannot fall past the final video frame when the audio track runs longer.
    """
    dur = duration or 1.0
    vdur = video_duration if (video_duration and 0 < video_duration <= dur + 0.5) else dur
    margin = 2.0 / fps if (fps and fps > 0) else 0.1
    span = max(vdur - margin, 0.05)
    step = span / n
    off = step / 2.0
    targets = [off + k * step for k in range(n)]
    k_expr = "floor((t-%.6f)/%.6f)" % (off, step)
    kp_expr = "floor((prev_t-%.6f)/%.6f)" % (off, step)
    grid_expr = "between(%s\\,0\\,%d)*gt(%s\\,%s)" % (k_expr, n - 1, k_expr, kp_expr)
    last_t = max(span - 0.5, 0.0)
    fc = ("[0:v:0]setpts=PTS-STARTPTS,split=2[g0][l0];"
          "[g0]select='%s'[g];[l0]select='gte(t\\,%.4f)'[l]" % (grid_expr, last_t))
    pattern = os.path.join(workdir, "grid_%02d.png")
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-i", path,
           "-filter_complex", fc,
           "-map", "[g]", "-fps_mode", "vfr", "-f", "image2", pattern,
           "-map", "[l]", "-fps_mode", "vfr", "-update", "1", "-f", "image2", last_out]
    rc, _o, err = run(cmd, timeout=300)
    if rc != 0:
        log("frame extraction ffmpeg rc=%d: %s" % (rc, err.strip()[-200:]))
    frames = []
    for i in range(n):
        p = pattern % (i + 1)  # image2 numbers from 1
        if os.path.isfile(p) and os.path.getsize(p) > 0:
            frames.append((targets[i] if i < len(targets) else None, p))
    if len(frames) != n:
        log("expected %d grid frames, got %d" % (n, len(frames)))
    last_ok = os.path.isfile(last_out) and os.path.getsize(last_out) > 0
    if not last_ok and frames:
        shutil.copyfile(frames[-1][1], last_out)
        last_ok = True
        log("last frame fell back to final grid frame")
    return frames, last_ok


def tile_frames(frames, rows, cols, out_path, grid_width=1280):
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore
    except Exception as e:
        log("pillow unavailable (%s); falling back to ffmpeg tile" % e)
        return tile_frames_ffmpeg(frames, rows, cols, out_path, grid_width)
    if not frames:
        return False
    first = Image.open(frames[0][1])
    w, h = first.size
    cell_w = max(64, grid_width // cols)
    cell_h = max(36, int(round(cell_w * h / float(w))))
    grid = Image.new("RGB", (cell_w * cols, cell_h * rows), (16, 16, 16))
    try:
        font = ImageFont.load_default(size=max(12, cell_h // 14))
    except Exception:
        font = ImageFont.load_default()
    draw = ImageDraw.Draw(grid)
    for idx, (t, p) in enumerate(frames[: rows * cols]):
        try:
            im = Image.open(p).convert("RGB").resize((cell_w, cell_h), Image.BILINEAR)
        except Exception as e:
            log("tile: bad frame %s (%s)" % (p, e))
            continue
        x = (idx % cols) * cell_w
        y = (idx // cols) * cell_h
        grid.paste(im, (x, y))
        label = "+%.1fs" % t
        draw.rectangle([x + 4, y + 4, x + 4 + 8 * len(label) + 8, y + 4 + max(12, cell_h // 14) + 6],
                       fill=(0, 0, 0))
        draw.text((x + 8, y + 6), label, fill=(255, 255, 255), font=font)
    grid.save(out_path)
    return True


def tile_frames_ffmpeg(frames, rows, cols, out_path, grid_width=1280):
    if not frames:
        return False
    cell_w = grid_width // cols
    inputs = []
    for _t, p in frames[: rows * cols]:
        inputs += ["-i", p]
    n = len(frames[: rows * cols])
    fc = "".join("[%d:v]scale=%d:-2[s%d];" % (i, cell_w, i) for i in range(n))
    fc += "".join("[s%d]" % i for i in range(n)) + "concat=n=%d:v=1:a=0,tile=%dx%d[out]" % (n, cols, rows)
    rc, _o, err = run([FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y"] + inputs +
                      ["-filter_complex", fc, "-map", "[out]", "-frames:v", "1", out_path])
    if rc != 0:
        log("ffmpeg tile failed: %s" % err.strip()[-160:])
    return rc == 0 and os.path.isfile(out_path)


# --------------------------------------------------------------------------- main
def fmt_intervals(iv, limit=4):
    parts = ["%.1f-%.1fs" % (a, b) for a, b, _d in iv[:limit]]
    if len(iv) > limit:
        parts.append("+%d more" % (len(iv) - limit))
    return ", ".join(parts)


def probe(args):
    global VERBOSE
    VERBOSE = not args.quiet
    fetched_at = utcnow()
    result = {
        "source": None,
        "source_kind": None,
        "channel": None,
        "fetched_at": iso(fetched_at),
        "variants": [],
        "chosen": None,
        "manifest": {},
        "video": {},
        "audio": {},
        "checks": {},
        "latency_s": None,
        "frame_grid": None,
        "last_frame": None,
        "verdict": "error",
        "reasons": [],
        "out_dir": None,
    }

    # ---- source
    channel_json = None
    if args.channel:
        result["source_kind"] = "channel"
        result["channel"] = args.channel
        channel_json = kick_get_channel(args.channel)
        live = channel_json.get("livestream")
        result["channel_live"] = bool(live and live.get("is_live"))
        if live:
            result["channel_viewer_count"] = live.get("viewer_count")
            result["channel_title"] = live.get("session_title")
        src = channel_json.get("playback_url")
        if not src:
            raise ProbeError("channel %s: API returned no playback_url" % args.channel)
        log("channel %s: livestream=%s playback_url=%s" % (
            args.channel, "live" if result["channel_live"] else "null/offline", src.split("?")[0]))
    elif args.local:
        result["source_kind"] = "local"
        src = os.path.join(RUN_DIR, "hls", "index.m3u8")
    else:
        result["source_kind"] = "url"
        src = args.url
    result["source"] = src.split("?")[0] if is_http(src) else os.path.abspath(os.path.expanduser(src))

    # ---- master playlist
    try:
        text, ms, status, base = fetch_text(src)
    except ProbeError as e:
        if channel_json is not None and not result.get("channel_live"):
            raise ProbeError("channel %s is offline (API livestream=null); %s" % (args.channel, e))
        raise
    # A live hls muxer rewrites index.m3u8 in place, so a read can land on an empty file.
    for _retry in range(4):
        if text.lstrip().startswith("#EXTM3U"):
            break
        log("manifest empty/not M3U yet (%d bytes); retrying in 0.5s" % len(text))
        time.sleep(0.5)
        text, ms, status, base = fetch_text(src)
    result["manifest"]["master_fetch_ms"] = ms
    if status is not None:
        result["manifest"]["master_http_status"] = status
    if is_http(src) and base.split("?")[0] != src.split("?")[0]:
        log("manifest redirected to %s" % base.split("?")[0])
        result["manifest"]["redirected_to"] = base.split("?")[0]
    if not text.lstrip().startswith("#EXTM3U"):
        raise ProbeError("not an HLS playlist (no #EXTM3U, %d bytes): %s" % (len(text), result["source"]))

    media_src = base
    if is_master(text):
        variants = parse_master(text, base)
        if not variants:
            raise ProbeError("master playlist has EXT-X-STREAM-INF but no usable variants")
        variants.sort(key=lambda v: v["bandwidth"], reverse=True)
        for v in variants:
            log("variant %-12s bw=%-9d res=%-10s fps=%-5s codecs=%s" % (
                v["name"], v["bandwidth"], v["resolution"] or "?", v["frame_rate"] or "?", v["codecs"] or "?"))
        chosen = variants[0]
        result["variants"] = [{k: v[k] for k in ("name", "bandwidth", "resolution", "frame_rate", "codecs")}
                              for v in variants]
        result["chosen"] = {k: chosen[k] for k in ("name", "bandwidth", "resolution", "frame_rate", "codecs")}
        result["chosen"]["uri"] = chosen["uri"].split("?")[0]
        media_src = chosen["uri"]
        log("chosen variant: %s (%d bps)" % (chosen["name"], chosen["bandwidth"]))
        text, ms, status, media_src = fetch_text(media_src)
        result["manifest"]["media_fetch_ms"] = ms
        if status is not None:
            result["manifest"]["media_http_status"] = status
        if not text.lstrip().startswith("#EXTM3U"):
            raise ProbeError("variant playlist is not an HLS playlist (no #EXTM3U, %d bytes): %s"
                             % (len(text), media_src.split("?")[0]))
    else:
        result["manifest"]["media_fetch_ms"] = ms
        log("media playlist given directly (no variants)")

    segs, info = parse_media(text, media_src)
    result["manifest"].update({
        "segments": len(segs),
        "target_duration": info["target_duration"],
        "live": not info["endlist"],
        "playlist_type": info["playlist_type"],
        "media_sequence": info["media_sequence"],
        "has_pdt": any(s["pdt"] for s in segs),
        "fmp4": bool(info["init"]),
    })
    if not segs:
        raise ProbeError("manifest has no segments (channel offline or stream just started): %s"
                         % media_src.split("?")[0])

    # ---- pick last N seconds
    want = float(args.seconds)
    picked = []
    acc = 0.0
    for s in reversed(segs):
        picked.insert(0, s)
        acc += s["duration"] or 0.0
        if acc >= want:
            break
    log("segments in playlist=%d, downloading last %d (%.1fs)" % (len(segs), len(picked), acc))

    # ---- latency
    last = segs[-1]
    if last["pdt"] is not None:
        result["latency_s"] = round((utcnow() - last["pdt"]).total_seconds(), 1)
        result["latency_detail"] = "now - PROGRAM-DATE-TIME of last segment (%s)" % iso(last["pdt"])
        if not result["manifest"]["live"]:
            result["latency_detail"] += "; playlist has ENDLIST (VOD), latency is informational only"
    else:
        result["latency_detail"] = "no EXT-X-PROGRAM-DATE-TIME in playlist"

    # ---- output dir
    out_dir = args.out or os.path.join(RUN_DIR, "probe", fetched_at.strftime("%Y%m%dT%H%M%SZ"))
    os.makedirs(out_dir, exist_ok=True)
    result["out_dir"] = os.path.abspath(out_dir)

    tmp = tempfile.mkdtemp(prefix="hls_probe_")
    try:
        # ---- download
        ext = os.path.splitext(urllib.parse.urlparse(picked[0]["uri"]).path)[1].lower() or ".ts"
        if ext not in (".ts", ".m4s", ".mp4", ".aac", ".m2ts", ".mpg", ".mpegts"):
            ext = ".ts"
        concat_ext = ".mp4" if (info["init"] or ext in (".m4s", ".mp4")) else ".ts"
        concat_path = os.path.join(tmp, "concat" + concat_ext)
        total_bytes = 0
        total_time = 0.0
        seg_files = []
        if info["init"]:
            p = os.path.join(tmp, "init.mp4")
            el, n = fetch_file(info["init"], p)
            total_bytes += n
            total_time += el
            seg_files.append(p)
        for i, s in enumerate(picked):
            p = os.path.join(tmp, "seg_%03d%s" % (i, ext))
            el, n = fetch_file(s["uri"], p)
            total_bytes += n
            total_time += el
            seg_files.append(p)
        with open(concat_path, "wb") as out:
            for p in seg_files:
                with open(p, "rb") as fh:
                    shutil.copyfileobj(fh, out)
        dl_kbps = (total_bytes * 8.0 / total_time / 1000.0) if total_time > 0 else None
        result["download"] = {
            "segments": len(picked),
            "seconds_requested": want,
            "seconds_got": round(acc, 2),
            "bytes": total_bytes,
            "elapsed_s": round(total_time, 3),
            "speed_kbps": round(dl_kbps, 1) if dl_kbps else None,
        }
        log("downloaded %d bytes in %.2fs (%s kbps)" % (total_bytes, total_time,
                                                          ("%.0f" % dl_kbps) if dl_kbps else "?"))
        if args.keep:
            keep_dir = os.path.join(out_dir, "segments")
            os.makedirs(keep_dir, exist_ok=True)
            for p in seg_files + [concat_path]:
                shutil.copy2(p, keep_dir)

        # ---- ffprobe
        duration, video, audio, n_video, n_audio = ffprobe_info(concat_path, total_bytes)
        result["video"] = video
        result["audio"] = audio
        result["analysed_duration_s"] = round(duration, 2) if duration else None
        if n_video == 0:
            raise ProbeError("no video stream in downloaded segments")
        log("ffprobe: %s %sx%s @%s fps, %s kbps; audio %s %s Hz %s ch; duration %.2fs" % (
            video["codec"], video["w"], video["h"], video["fps"], video["bitrate_kbps"],
            audio["codec"], audio["rate"], audio["ch"], duration or 0.0))

        # ---- ffmpeg detectors
        an = ffmpeg_analyse(concat_path, n_audio > 0, duration, os.path.join(out_dir, "ffmpeg_analysis.log"))
        result["audio"]["mean_volume_db"] = an["mean_volume_db"]
        result["audio"]["max_volume_db"] = an["max_volume_db"]
        dur = duration or acc or 1.0

        checks = {}
        black_total = sum(d for _a, _b, d in an["black"])
        black_pass = black_total <= 0.25 * dur
        checks["black"] = {
            "pass": black_pass,
            "detail": ("no black intervals (blackdetect d=1 pic_th=0.98)" if not an["black"] else
                       "black %.1fs of %.1fs (%d interval%s: %s)" % (
                           black_total, dur, len(an["black"]), "" if len(an["black"]) == 1 else "s",
                           fmt_intervals(an["black"]))),
            "black_s": round(black_total, 2),
        }
        frozen_total = sum(d for _a, _b, d in an["freezes"])
        checks["frozen"] = {
            "pass": frozen_total <= 0.25 * dur,
            "detail": ("no frozen intervals (freezedetect n=-60dB d=2)" if not an["freezes"] else
                       "frozen %.1fs of %.1fs (%d interval%s: %s)" % (
                           frozen_total, dur, len(an["freezes"]), "" if len(an["freezes"]) == 1 else "s",
                           fmt_intervals(an["freezes"]))),
            "frozen_s": round(frozen_total, 2),
        }
        if n_audio == 0:
            checks["silent"] = {"pass": False, "detail": "no audio stream", "silent_s": None}
        else:
            sil_total = sum(d for _a, _b, d in an["silences"])
            maxv = an["max_volume_db"]
            meanv = an["mean_volume_db"]
            quiet = maxv is not None and maxv <= -50.0
            sil_pass = sil_total < 0.5 * dur and not quiet
            det = []
            if an["silences"]:
                det.append("silence %.1fs of %.1fs (%s)" % (sil_total, dur, fmt_intervals(an["silences"])))
            else:
                det.append("no silence intervals (silencedetect n=-50dB d=3)")
            det.append("mean %s dB, max %s dB" % (
                ("%.1f" % meanv) if meanv is not None else "?", ("%.1f" % maxv) if maxv is not None else "?"))
            if quiet:
                det.append("max volume <= -50 dB: effectively silent")
            checks["silent"] = {"pass": sil_pass, "detail": "; ".join(det), "silent_s": round(sil_total, 2)}
        w, h = video["w"] or 0, video["h"] or 0
        checks["resolution"] = {
            "pass": w >= args.min_width and h >= args.min_height,
            "detail": "%dx%d (min %dx%d)" % (w, h, args.min_width, args.min_height),
        }
        fps = video["fps"] or 0.0
        checks["fps"] = {
            "pass": fps >= args.min_fps,
            "detail": "%.2f fps (min %.0f)" % (fps, args.min_fps),
        }
        br = video["bitrate_kbps"]
        if dl_kbps is None:
            checks["download_speed"] = {"pass": False, "detail": "download time not measurable", "ratio": None}
        elif not br:
            checks["download_speed"] = {"pass": True, "ratio": None,
                                        "detail": "%.0f kbps download; stream bitrate unknown" % dl_kbps}
        else:
            ratio = dl_kbps / br
            checks["download_speed"] = {
                "pass": ratio >= 1.5,
                "ratio": round(ratio, 2),
                "detail": "%.0f kbps download vs %.0f kbps stream = %.1fx (need >= 1.5x)" % (dl_kbps, br, ratio),
            }
        checks["decode"] = {
            "pass": an["rc"] == 0 and an["error_count"] <= 5,
            "detail": ("ffmpeg decode ok" if an["rc"] == 0 and an["error_count"] == 0 else
                       "ffmpeg rc=%d, %d error line%s%s" % (
                           an["rc"], an["error_count"], "" if an["error_count"] == 1 else "s",
                           (": " + an["error_lines"][0][:120]) if an["error_lines"] else "")),
        }
        checks["manifest"] = {
            "pass": len(segs) >= 1 and acc >= min(want, 2.0),
            "detail": "%d segment%s, target %ss, %s, master fetch %s ms, media fetch %s ms" % (
                len(segs), "" if len(segs) == 1 else "s", info["target_duration"],
                "live" if result["manifest"]["live"] else "VOD/ENDLIST",
                result["manifest"].get("master_fetch_ms"), result["manifest"].get("media_fetch_ms")),
        }
        result["checks"] = checks

        # ---- frames
        rows, cols = args.grid
        last_path = os.path.join(out_dir, "last_frame.png")
        frames, last_ok = extract_frames(concat_path, duration, rows * cols, tmp, last_path,
                                         video_duration=video.get("duration_s"), fps=video.get("fps"))
        grid_path = os.path.join(out_dir, "frame_grid.png")
        if frames and tile_frames(frames, rows, cols, grid_path):
            result["frame_grid"] = os.path.abspath(grid_path)
        else:
            log("frame grid not produced")
        if last_ok:
            result["last_frame"] = os.path.abspath(last_path)
        # A grid denser than the decoded frame count cannot be filled; expect what exists.
        expect = rows * cols
        if video.get("fps"):
            expect = max(1, min(expect, int((video.get("duration_s") or dur) * video["fps"]) - 2))
        checks["frames"] = {
            "pass": len(frames) >= expect and result["last_frame"] is not None,
            "detail": "%d/%d grid frames%s, last frame %s" % (
                len(frames), rows * cols,
                (" (only %d frames decodable)" % expect) if expect < rows * cols else "",
                "ok" if result["last_frame"] else "missing"),
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [k for k, c in result["checks"].items() if not c["pass"]]
    result["reasons"] = ["%s: %s" % (k, result["checks"][k]["detail"]) for k in failed]
    result["verdict"] = "pass" if not failed else "fail"
    return result


def write_result(result, out_dir):
    path = os.path.join(out_dir, "probe.json")
    with open(path, "w") as fh:
        json.dump(result, fh, indent=2, sort_keys=False)
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="hls_probe.py",
        description=__doc__.split("\n\n")[0] + "  See module docstring for details.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  hls_probe.py --url $RUN_DIR/hls_fixture/index.m3u8\n"
            "  hls_probe.py --local --seconds 10 --grid 3x3\n"
            "  hls_probe.py --channel atleastonce --out /tmp/probe\n"
            "exit codes: 0 pass, 1 fail, 2 error (offline / no manifest / tool failure)"),
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--url", help="m3u8 URL (http/https) or local path (master or media playlist)")
    g.add_argument("--channel", metavar="NAME", help="Kick channel slug; playback_url from the public API")
    g.add_argument("--local", action="store_true", help="probe $RUN_DIR/hls/index.m3u8")
    ap.add_argument("--seconds", type=float, default=10, help="tail seconds of segments to analyse (default 10)")
    ap.add_argument("--grid", default="3x3", help="frame grid RxC (default 3x3)")
    ap.add_argument("--out", help="output dir (default $RUN_DIR/probe/<utc-ts>/)")
    ap.add_argument("--min-width", type=int, default=STREAM_WIDTH, help="resolution check (default $STREAM_WIDTH or 1280)")
    ap.add_argument("--min-height", type=int, default=STREAM_HEIGHT, help="resolution check (default $STREAM_HEIGHT or 720)")
    ap.add_argument("--min-fps", type=float, default=24.0, help="fps check threshold (default 24)")
    ap.add_argument("--keep", action="store_true", help="keep downloaded segments under OUT/segments/")
    ap.add_argument("--print-json", action="store_true", help="also print probe.json to stdout")
    ap.add_argument("-q", "--quiet", action="store_true", help="no progress on stderr")
    args = ap.parse_args(argv)

    m = re.match(r"^(\d+)x(\d+)$", args.grid.lower())
    if not m or int(m.group(1)) < 1 or int(m.group(2)) < 1:
        ap.error("--grid must look like 3x3")
    args.grid = (int(m.group(1)), int(m.group(2)))
    if args.seconds <= 0:
        ap.error("--seconds must be > 0")

    # SIGTERM/SIGHUP: raise so subprocess.run kills the running ffmpeg/ffprobe child and the
    # temp dir is removed by probe()'s finally.  Without this the child is orphaned.
    def _on_signal(signum, _frame):
        raise ProbeError("terminated by signal %d" % signum)
    for _sig in (signal.SIGTERM, signal.SIGHUP):
        try:
            signal.signal(_sig, _on_signal)
        except (ValueError, OSError):  # not main thread / unsupported
            pass

    def _error_json(msg):
        # Only when the caller chose the location; never create <utc-ts> dirs for errors.
        if not args.out:
            return
        try:
            os.makedirs(args.out, exist_ok=True)
            write_result({"source": args.url or (args.channel and ("channel:" + args.channel)) or "local",
                          "fetched_at": iso(utcnow()), "verdict": "error", "reasons": [msg],
                          "checks": {}, "video": {}, "audio": {}, "variants": [], "chosen": None,
                          "latency_s": None, "frame_grid": None, "last_frame": None}, args.out)
        except Exception as we:  # pragma: no cover
            sys.stderr.write("[hls_probe] could not write error probe.json: %s\n" % we)

    try:
        result = probe(args)
    except ProbeError as e:
        sys.stderr.write("[hls_probe] ERROR: %s\n" % e)
        print("ERROR %s" % e)
        _error_json(str(e))
        return 2
    except KeyboardInterrupt:
        print("ERROR interrupted")
        _error_json("interrupted")
        return 2
    except Exception as e:  # unexpected: still no traceback on stdout, but keep detail on stderr
        import traceback
        traceback.print_exc(file=sys.stderr)
        print("ERROR unexpected %s: %s" % (type(e).__name__, e))
        _error_json("unexpected %s: %s" % (type(e).__name__, e))
        return 2

    path = write_result(result, result["out_dir"])
    v = result["video"]
    a = result["audio"]
    summary = "%s %s %sx%s@%s %skbps %s/%s/%sch%s%s -> %s" % (
        result["verdict"].upper(),
        result["source"] if len(result["source"]) < 70 else "..." + result["source"][-67:],
        v.get("w"), v.get("h"), ("%g" % v["fps"]) if v.get("fps") else "?",
        ("%.0f" % v["bitrate_kbps"]) if v.get("bitrate_kbps") else "?",
        a.get("codec") or "noaudio", a.get("rate") or "?", a.get("ch") or "?",
        (" latency=%.1fs" % result["latency_s"]) if result.get("latency_s") is not None else "",
        (" reasons=[%s]" % "; ".join(result["reasons"])) if result["reasons"] else "",
        path,
    )
    print(summary)
    if args.print_json:
        print(json.dumps(result, indent=2))
    return 0 if result["verdict"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
