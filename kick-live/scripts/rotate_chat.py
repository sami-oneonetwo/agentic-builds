#!/usr/bin/env python3
"""scripts/rotate_chat.py - IDLEWORLD.md 7.3 / 7.4 / 6.2 row P4: rotate the append-only ledgers of a run dir
(`chat.jsonl`, `wishes.jsonl`) into archives with a manifest, so every reader can replay archive + live as ONE file.

    RUN_DIR=/tmp/lg-x $PYTHON scripts/rotate_chat.py                 # rotate any ledger above 256 MB
    RUN_DIR=/tmp/lg-x $PYTHON scripts/rotate_chat.py --force         # rotate regardless of size (tests, ops)
    RUN_DIR=/tmp/lg-x $PYTHON scripts/rotate_chat.py --dry-run       # say what would rotate, write nothing
    $PYTHON scripts/rotate_chat.py --self-test                       # fixture under /tmp/lg-P4-*, deleted after
    $PYTHON scripts/rotate_chat.py --run-dir L --i-am-the-owner      # the ONLY way this touches the live run dir
                                                                     # (not before W8 lands: see --help)

What a rotation does (per ledger `<name>`, which must be a plain `*.jsonl` basename: `world.json`, `state.json` and
every other run-dir file have their own single writer and are refused by name):
  1. refuse while `$RUN_DIR/pids/compositor.pid` (or any other `pids/*.pid`) names a live process, refuse the live run
     dir without --i-am-the-owner, refuse below `2 x size + 256 MB` free disk, refuse a live file that is not a
     regular file;
  2. rename `<name>` -> `<name>.YYYYMMDDTHHMM.N` (same filesystem, one atomic syscall; N = archive sequence, unique);
  3. if the archive ends in a partial line (no trailing newline), cut that tail off the archive and make it the start
     of the new empty `<name>`, so no record is ever split across two files;
  4. hash and count the archive, append `{file, path, lines, bytes, first_ts, last_ts, sha256, rotated_ts, seq}` to
     `<name-stem>.manifest.json` (atomic tmp + replace), then re-read the archive and verify sha256 + line count.
  If anything fails between the rename and the manifest write, the rename is undone (the tail we moved is appended
  back, the archive is renamed back to `<name>`) as long as the new live file is still ours; if a writer has already
  re-created `<name>`, the archive stays on disk, is named LOUDLY as an orphan no manifest lists, and the exit is 1.
Archives are never deleted here (the rotation archives, never deletes: IDLEWORLD.md 1.5).

Manifest (spec re-anchor for D1 / W8): IDLEWORLD.md 6.2 L795 and 7.3 L868 say `files[]` and `chat.archive/YYYY-MM-DD.jsonl`;
what is on disk is `chat.manifest.json` / `wishes.manifest.json` = `{"schema": 1, "name", "live": "chat.jsonl",
"updated_ts", "archives": [{file, path, lines, bytes, first_ts, last_ts, sha256, rotated_ts, seq}, ...]}` and archives
named `chat.jsonl.YYYYMMDDTHHMM.N` beside the live file (same directory, same filesystem, so the rename is atomic).
Row 13's gates hold either way; readers should import `load_manifest` / `iter_records` here rather than glob.

Read helpers (stdlib only; importable as `from scripts.rotate_chat import iter_records, iter_lines, manifest_path`):
  iter_lines(run_dir, name, cursor=None, verify=True) -> yields (file, end_offset, line_str) across every manifest
      archive in order and then the live file; `cursor={"file": ..., "offset": ...}` resumes after that byte of that
      file; `verify` checks each complete archive's sha256 against the manifest while it is being read (no extra I/O)
      and raises ManifestError on a mismatch, AFTER that archive's lines were yielded (hash-while-streaming). A
      consumer that must not act on unverified rows calls verify_manifest() first.
  iter_records(run_dir, name, cursor=None, verify=True, with_pos=False) -> the same, parsed as dicts (non-dict or
      unparseable lines skipped, as JsonlTail does); with_pos yields (file, end_offset, dict).
  resolve_cursor(run_dir, name, cursor) -> (start_index, start_offset, note): the cursor as iter_lines will honour it.
      A cursor is never seeked past a file's end and never into the middle of a line: a `{file: "chat.jsonl",
      offset: N}` written BEFORE a rotation (state.json's shape today) resumes at N inside the archive that live file
      became (exactly when the cursor carries `archives` = the manifest's archive count at the time, see make_cursor;
      by inference when N is past the live file's end or does not land on a line boundary in it); anything else that
      cannot be placed restarts from the first archive. `note` says why, for the consumer's log.
  make_cursor(run_dir, name, file, offset) -> {"file", "offset", "archives"}: the cursor to persist after a yield.
  verify_manifest(run_dir, name) -> the manifest rows, after hashing every archive up front (raises ManifestError).
  A cursor of the shape `{"file", "offset"}` is what IDLEWORLD.md 7.4 asks `recompute_from_chat` to keep.

Python 3.9 (from __future__ annotations; no match; no X|Y at runtime). Chat text is data: this file never puts a
record's text into a shell string, a path or a log line.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from typing import Any, Dict, Iterator, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LIVE_RUN_DIR = "/Users/sandy/.local/share/kick-live/run-live"
LEDGERS = ("chat.jsonl", "wishes.jsonl")
THRESHOLD_BYTES = 256 * 1024 * 1024
MANIFEST_SCHEMA = 1
_CHUNK = 1 << 20

EXIT_OK = 0
EXIT_REFUSED = 3
EXIT_FAILED = 1


class RefuseError(Exception):
    """A precondition failed; nothing was written."""


class ManifestError(Exception):
    """An archive disagrees with its manifest row."""


# ----------------------------------------------------------------------------------------------------------------------
# paths + manifest
# ----------------------------------------------------------------------------------------------------------------------

def manifest_path(run_dir: str, name: str) -> str:
    stem = name[:-len(".jsonl")] if name.endswith(".jsonl") else name
    return os.path.join(run_dir, stem + ".manifest.json")


def _empty_manifest(name: str) -> Dict[str, Any]:
    return {"schema": MANIFEST_SCHEMA, "name": name, "live": name, "updated_ts": None, "archives": []}


def load_manifest(run_dir: str, name: str) -> Dict[str, Any]:
    """The manifest for `name`, or an empty one when none exists. A malformed manifest raises ManifestError."""
    p = manifest_path(run_dir, name)
    if not os.path.exists(p):
        return _empty_manifest(name)
    try:
        with open(p, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except Exception as e:
        raise ManifestError("manifest %s unreadable: %r" % (os.path.basename(p), e))
    if not isinstance(doc, dict) or not isinstance(doc.get("archives"), list):
        raise ManifestError("manifest %s has no archives[] list" % os.path.basename(p))
    if doc.get("live") and doc.get("live") != name:
        raise ManifestError("manifest %s is for %r, not %r" % (os.path.basename(p), doc.get("live"), name))
    for row in doc["archives"]:
        if not isinstance(row, dict) or not row.get("file"):
            raise ManifestError("manifest %s has a row without a file" % os.path.basename(p))
        if os.path.basename(str(row["file"])) != str(row["file"]) or str(row["file"]).startswith("."):
            raise ManifestError("manifest %s row file is not a plain basename" % os.path.basename(p))
    doc.setdefault("schema", MANIFEST_SCHEMA)
    doc.setdefault("name", name)
    doc.setdefault("live", name)
    return doc


def _atomic_write_json(path: str, doc: Dict[str, Any]) -> None:
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".manifest-", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=1, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o644)                                     # mkstemp gives 0600; the ledgers are 0644
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _iso_now() -> str:
    lt = time.localtime()
    z = time.strftime("%z", lt)
    return time.strftime("%Y-%m-%dT%H:%M:%S", lt) + (z[:3] + ":" + z[3:] if z else "")


# ----------------------------------------------------------------------------------------------------------------------
# readers (the helpers other modules import)
# ----------------------------------------------------------------------------------------------------------------------

def _iter_file_lines(path: str, start: int = 0, want_sha: bool = False
                     ) -> Iterator[Tuple[int, str, Optional[str]]]:
    """Yield (end_offset, line_without_newline, sha_or_None) for every COMPLETE line of `path` after byte `start`.
    The sha (whole-file sha256 hex) rides on a final sentinel (offset -1, "", sha) when want_sha and start == 0.
    A trailing partial line (no newline) is not yielded: it is what a writer is still appending."""
    h = hashlib.sha256() if (want_sha and start == 0) else None
    off = start
    partial = b""
    with open(path, "rb") as fh:
        if start:
            fh.seek(start)
        while True:
            chunk = fh.read(_CHUNK)
            if not chunk:
                break
            if h is not None:
                h.update(chunk)
            data = partial + chunk
            lines = data.split(b"\n")
            partial = lines.pop()
            for ln in lines:
                off += len(ln) + 1
                yield off, ln.decode("utf-8", "replace"), None
    if h is not None:
        # the hash must cover the whole file, including any partial tail we did not yield
        yield -1, "", h.hexdigest()


def _size_or_zero(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _is_line_boundary(path: str, off: int) -> bool:
    """True when `off` is 0, or is <= the file's size and the byte before it is a newline (an end_offset that
    iter_lines yielded for this file). False past EOF, inside a line, or when the file cannot be read."""
    if off <= 0:
        return True
    if off > _size_or_zero(path):
        return False
    try:
        with open(path, "rb") as fh:
            fh.seek(off - 1)
            return fh.read(1) == b"\n"
    except OSError:
        return False


def resolve_cursor(run_dir: str, name: str, cursor: Optional[Dict[str, Any]],
                   man: Optional[Dict[str, Any]] = None) -> Tuple[int, int, Optional[str]]:
    """Where iter_lines will start for `cursor`: (index into archives + [live], byte offset, note).
    `note` is None when the cursor was honoured as written, else the one-line reason it was re-anchored.
    Rules (never seek past EOF, never yield from mid-line, never lose an archive):
      - no cursor, or offset <= 0 of a known file: start of that file (of everything when the file is unknown);
      - `file` == the live name and `archives` (see make_cursor) < the manifest's archive count: the live file was
        rotated since; resume at `offset` inside the archive it became (archives are appended in order);
      - `file` == the live name and `offset` is past the live file's end or not on a line boundary in it: the same
        rotated-under case, inferred; resume in the NEWEST archive at `offset` when that is a boundary there;
      - anything that still cannot be placed on a line boundary of an existing file: replay from the first archive."""
    man = man if man is not None else load_manifest(run_dir, name)
    order: List[str] = [str(r["file"]) for r in man["archives"]] + [name]
    n_arch = len(man["archives"])
    if not cursor:
        return 0, 0, None
    cfile = cursor.get("file")
    try:
        off = int(cursor.get("offset") or 0)
    except (TypeError, ValueError):
        off = 0
    if cfile not in order:
        if cfile is None and off <= 0:
            return 0, 0, None
        return 0, 0, "cursor names an unknown file: replay from the first archive"
    idx = order.index(cfile)
    if off <= 0:
        return idx, 0, None
    note: Optional[str] = None
    then = cursor.get("archives")
    if cfile == name and isinstance(then, int) and not isinstance(then, bool) and 0 <= then < n_arch:
        idx = then
        note = "cursor into %s predates rotation %d: resumed in %s" % (name, then + 1, order[idx])
    elif cfile == name and n_arch and not _is_line_boundary(os.path.join(run_dir, cfile), off):
        idx = n_arch - 1
        note = "cursor offset %d is past the end or inside a line of %s: resumed in %s" % (off, name, order[idx])
    if _is_line_boundary(os.path.join(run_dir, order[idx]), off):
        return idx, off, note
    return 0, 0, "cursor offset %d is not a line boundary of %s: replay from the first archive" % (off, order[idx])


def make_cursor(run_dir: str, name: str, file: str, offset: int, man: Optional[Dict[str, Any]] = None
                ) -> Dict[str, Any]:
    """The cursor to persist after iter_lines yielded (file, offset, ...): carries the archive count so a later
    rotation of the live file is detected exactly, not inferred."""
    man = man if man is not None else load_manifest(run_dir, name)
    return {"file": file, "offset": int(offset), "archives": len(man["archives"])}


def verify_manifest(run_dir: str, name: str) -> List[Dict[str, Any]]:
    """Hash and count every archive the manifest lists, up front; raise ManifestError on the first disagreement
    (missing file, sha256, lines or bytes). Returns the rows. The strict option for a consumer that must not act on
    a row before its archive is known good (iter_lines verifies while streaming, so it raises after yielding)."""
    man = load_manifest(run_dir, name)
    for row in man["archives"]:
        fname = str(row["file"])
        path = os.path.join(run_dir, fname)
        if not os.path.isfile(path):
            raise ManifestError("archive %s listed in the manifest is missing" % fname)
        sha, lines, nbytes, _, _ = _hash_and_count(path)
        if row.get("sha256") and sha != row["sha256"]:
            raise ManifestError("archive %s sha256 mismatch" % fname)
        if row.get("lines") is not None and int(row["lines"]) != lines:
            raise ManifestError("archive %s has %d lines, manifest says %s" % (fname, lines, row["lines"]))
        if row.get("bytes") is not None and int(row["bytes"]) != nbytes:
            raise ManifestError("archive %s is %d bytes, manifest says %s" % (fname, nbytes, row["bytes"]))
    return list(man["archives"])


def iter_lines(run_dir: str, name: str, cursor: Optional[Dict[str, Any]] = None, verify: bool = True
               ) -> Iterator[Tuple[str, int, str]]:
    """Every complete line of `name` across manifest archives (in order) then the live file: (file, end_offset, line).
    `cursor` = {"file": <basename>, "offset": <int>[, "archives": <int>]} resumes after that byte of that file, placed
    by resolve_cursor (a cursor written before a rotation resumes inside the archive; nothing is ever yielded from
    mid-line). `verify=True` checks each fully-read archive's sha256 and line count against the manifest (raises
    ManifestError once that archive has been streamed; verify_manifest() is the up-front check)."""
    man = load_manifest(run_dir, name)
    order: List[str] = [str(r["file"]) for r in man["archives"]] + [name]
    rows_by_file = {str(r["file"]): r for r in man["archives"]}
    start_idx, start_off, _note = resolve_cursor(run_dir, name, cursor, man)
    for i in range(start_idx, len(order)):
        fname = order[i]
        path = os.path.join(run_dir, fname)
        off = start_off if i == start_idx else 0
        if not os.path.exists(path):
            if fname == name:
                return
            raise ManifestError("archive %s listed in the manifest is missing" % fname)
        row = rows_by_file.get(fname)
        want_sha = bool(verify and row is not None and off == 0)
        n = 0
        for end, line, sha in _iter_file_lines(path, off, want_sha):
            if sha is not None:
                if row.get("sha256") and sha != row["sha256"]:
                    raise ManifestError("archive %s sha256 mismatch" % fname)
                if row.get("lines") is not None and int(row["lines"]) != n:
                    raise ManifestError("archive %s has %d lines, manifest says %s" % (fname, n, row["lines"]))
                continue
            n += 1
            yield fname, end, line


def iter_records(run_dir: str, name: str, cursor: Optional[Dict[str, Any]] = None, verify: bool = True,
                 with_pos: bool = False) -> Iterator[Any]:
    """iter_lines parsed as JSON dicts; blank, unparseable and non-dict lines are skipped (the JsonlTail rule)."""
    for fname, end, line in iter_lines(run_dir, name, cursor, verify):
        s = line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        if with_pos:
            yield fname, end, obj
        else:
            yield obj


# ----------------------------------------------------------------------------------------------------------------------
# refusals
# ----------------------------------------------------------------------------------------------------------------------

def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def live_pids(run_dir: str) -> List[Tuple[str, int]]:
    """(pidfile basename, pid) for every pids/*.pid that names a live process; compositor.pid listed first."""
    d = os.path.join(run_dir, "pids")
    out: List[Tuple[str, int]] = []
    if not os.path.isdir(d):
        return out
    names = sorted(os.listdir(d), key=lambda n: (n != "compositor.pid", n))
    for n in names:
        if not n.endswith(".pid"):
            continue
        try:
            with open(os.path.join(d, n), "r", encoding="utf-8") as fh:
                pid = int((fh.read().strip().split() or ["0"])[0])
        except (OSError, ValueError):
            continue
        if pid_alive(pid):
            out.append((n, pid))
    return out


def is_live_run_dir(run_dir: str) -> bool:
    try:
        rd = os.path.realpath(run_dir)
        live = os.path.realpath(LIVE_RUN_DIR)
    except OSError:
        return False
    return rd == live or rd.startswith(live + os.sep)


def free_bytes(path: str) -> int:
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return 0


def refuse_reason(run_dir: str, owner: bool = False, check_pids: bool = True) -> Optional[str]:
    """None when a rotation may proceed, else the one-line reason. Reads only; never creates anything.
    `check_pids=False` skips the live-process check (for read-only listing and the --dry-run size report)."""
    if not run_dir:
        return "no run dir (set RUN_DIR or pass --run-dir; this never defaults to the live run dir)"
    if is_live_run_dir(run_dir) and not owner:
        return "refusing the live run dir %s without --i-am-the-owner" % LIVE_RUN_DIR
    if not os.path.isdir(run_dir):
        return "run dir %s is not a directory" % run_dir
    if check_pids:
        alive = live_pids(run_dir)
        if alive:
            n, pid = alive[0]
            return "refusing: pids/%s names live process %d (rotation is never on air)" % (n, pid)
    return None


def ledger_name_reason(name: str) -> Optional[str]:
    """None when `name` may be rotated, else why not. Only plain `*.jsonl` basenames are ledgers: `world.json`,
    `state.json` and every other run-dir file have exactly one writer of their own (IDLEWORLD.md 0.2 row 2) and a
    0-byte `world.json` left behind by a rename would be read as an empty world."""
    if not isinstance(name, str) or not name:
        return "ledger name is empty"
    if name != os.path.basename(name) or os.sep in name or "/" in name or name.startswith("."):
        return "ledger name must be a plain basename: %r" % name
    if not name.endswith(".jsonl") or name == ".jsonl":
        return "ledger name must end in .jsonl (chat.jsonl, wishes.jsonl); refusing %r" % name
    return None


# ----------------------------------------------------------------------------------------------------------------------
# the rotation
# ----------------------------------------------------------------------------------------------------------------------

def _hash_and_count(path: str) -> Tuple[str, int, int, Optional[str], Optional[str]]:
    """sha256 hex, complete-line count, bytes, first record ts, last record ts (from the `ts` key when parseable)."""
    n = 0
    first_ts: Optional[str] = None
    last_ts: Optional[str] = None
    sha = ""
    first_line: Optional[str] = None
    last_line: Optional[str] = None
    for end, line, s in _iter_file_lines(path, 0, True):
        if s is not None:
            sha = s
            continue
        n += 1
        if first_line is None:
            first_line = line
        last_line = line

    def _ts(line: Optional[str]) -> Optional[str]:
        if not line:
            return None
        try:
            obj = json.loads(line)
        except Exception:
            return None
        if isinstance(obj, dict):
            v = obj.get("ts") or obj.get("created_at") or obj.get("t")
            return str(v) if v is not None else None
        return None

    first_ts, last_ts = _ts(first_line), _ts(last_line)
    return sha, n, os.path.getsize(path), first_ts, last_ts


def _split_partial_tail(archive: str, live: str) -> int:
    """If `archive` does not end in a newline, move its trailing partial line into a NEW `live` file and truncate the
    archive to its last newline. Returns the number of tail bytes moved. Creates `live` (empty) in every case."""
    size = os.path.getsize(archive)
    tail = b""
    if size:
        with open(archive, "rb") as fh:
            back = min(size, 64 * 1024)
            fh.seek(size - back)
            buf = fh.read(back)
            if not buf.endswith(b"\n"):
                while b"\n" not in buf and back < size:          # one line longer than the window: widen it
                    back = min(size, back * 4)
                    fh.seek(size - back)
                    buf = fh.read(back)
                cut = buf.rfind(b"\n")
                tail = buf[cut + 1:]                             # cut == -1 -> the whole file is one partial line
    fd = os.open(live, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        if tail:
            os.write(fd, tail)
        os.fsync(fd)
    finally:
        os.close(fd)
    if tail:
        with open(archive, "r+b") as fh:
            fh.truncate(size - len(tail))
            fh.flush()
            os.fsync(fh.fileno())
    return len(tail)


def _undo_rename(arch: str, live: str, created_live: bool, moved: int, log=print) -> bool:
    """After `os.rename(live, arch)` the rotation failed part-way. Put the ledger back when the new live file is still
    ours (absent, or holding at most the tail WE moved into it): append that tail back, unlink it, rename the archive
    back to `live`. Returns True when restored. Otherwise a writer has re-created `live`: the archive stays on disk
    (never deleted), is named LOUDLY as an orphan no manifest lists, and False is returned."""
    live_size = _size_or_zero(live) if os.path.exists(live) else 0
    ours = (not os.path.exists(live)) or (created_live and live_size <= moved)
    if ours:
        try:
            if live_size:
                with open(live, "rb") as fh:
                    tail = fh.read()
                with open(arch, "ab") as fh:
                    fh.write(tail)
                    fh.flush()
                    os.fsync(fh.fileno())
            if os.path.exists(live):
                os.unlink(live)
            os.rename(arch, live)
            log("rotate: %s restored from %s (%d tail bytes appended back); nothing rotated"
                % (os.path.basename(live), os.path.basename(arch), live_size))
            return True
        except OSError as e:
            log("rotate: could not restore %s: %r" % (os.path.basename(live), e))
    log("rotate: ORPHAN ARCHIVE %s: on disk, listed in NO manifest, %s was re-created by another writer (%d bytes). "
        "Readers will skip its lines until it is added to %s by hand. It is NOT deleted."
        % (os.path.basename(arch), os.path.basename(live), live_size,
           os.path.basename(manifest_path(os.path.dirname(arch), os.path.basename(live)))))
    return False


def rotate_one(run_dir: str, name: str, force: bool = False, threshold: int = THRESHOLD_BYTES,
               dry_run: bool = False, now: Optional[float] = None, log=print,
               dry_note: str = "") -> Optional[Dict[str, Any]]:
    """Rotate one ledger. Returns the new manifest row, or None when nothing rotated. Preconditions (pid, live dir)
    are the caller's (`refuse_reason`); this checks the name, size, file kind and disk."""
    bad = ledger_name_reason(name)
    if bad:
        raise RefuseError(bad)
    live = os.path.join(run_dir, name)
    if not os.path.exists(live):
        log("rotate: %s absent, nothing to do" % name)
        return None
    if os.path.islink(live) or not os.path.isfile(live):
        raise RefuseError("%s is not a regular file" % name)
    size = os.path.getsize(live)
    if size == 0:
        log("rotate: %s is empty, nothing to do" % name)
        return None
    if size < threshold and not force:
        log("rotate: %s is %d bytes (< %d), nothing to do" % (name, size, threshold))
        return None
    need = 2 * size + THRESHOLD_BYTES
    free = free_bytes(run_dir)
    if free < need:
        raise RefuseError("refusing: %d bytes free under %s, need %d (2 x %d + 256 MB)" % (free, run_dir, need, size))
    man = load_manifest(run_dir, name)
    seq = len(man["archives"]) + 1
    stamp = time.strftime("%Y%m%dT%H%M", time.localtime(now if now is not None else time.time()))
    arch_name = "%s.%s.%d" % (name, stamp, seq)
    arch = os.path.join(run_dir, arch_name)
    while os.path.exists(arch):
        seq += 1
        arch_name = "%s.%s.%d" % (name, stamp, seq)
        arch = os.path.join(run_dir, arch_name)
    if dry_run:
        log("rotate: DRY RUN would rename %s (%d bytes) -> %s and append manifest row %d%s"
            % (name, size, arch_name, seq, dry_note))
        return None
    os.rename(live, arch)
    created_live = False
    moved = 0
    try:
        moved = _split_partial_tail(arch, live)
        created_live = True
        if _size_or_zero(arch) == 0:
            # the whole file was one partial line (a writer mid-append, nothing complete): put it back, no archive
            _undo_rename(arch, live, created_live, moved, log=lambda *a: None)
            log("rotate: %s holds only a partial line (%d bytes), nothing complete to rotate" % (name, moved))
            return None
        sha, lines, nbytes, first_ts, last_ts = _hash_and_count(arch)
        row = {"file": arch_name, "path": arch_name, "lines": lines, "bytes": nbytes, "first_ts": first_ts,
               "last_ts": last_ts, "sha256": sha, "rotated_ts": _iso_now(), "seq": seq}
        man["archives"].append(row)
        man["updated_ts"] = row["rotated_ts"]
        _atomic_write_json(manifest_path(run_dir, name), man)
    except BaseException as e:
        # the archive exists but no manifest lists it: undo the rename while the new live file is still ours
        log("rotate: FAILED after renaming %s -> %s: %r" % (name, arch_name, e))
        _undo_rename(arch, live, created_live, moved, log=log)
        raise
    # verify: re-read what we just wrote about
    sha2, lines2, nbytes2, _, _ = _hash_and_count(arch)
    if (sha2, lines2, nbytes2) != (sha, lines, nbytes):
        raise ManifestError("archive %s changed under the rotation" % arch_name)
    log("rotate: %s -> %s  lines=%d bytes=%d sha256=%s..  partial_tail_kept=%d B  manifest rows=%d"
        % (name, arch_name, lines, nbytes, sha[:12], moved, len(man["archives"])))
    return row


def rotate(run_dir: str, names=LEDGERS, force: bool = False, threshold: int = THRESHOLD_BYTES,
           dry_run: bool = False, owner: bool = False, log=print) -> List[Dict[str, Any]]:
    """Check preconditions once, then rotate each named ledger. Raises RefuseError (nothing written); returns the rows
    written. Names are checked before anything else: only plain `*.jsonl` basenames are ledgers. A --dry-run is
    allowed while a pid is alive (it writes nothing) and says so on each line; every other refusal holds for it."""
    for name in names:
        bad = ledger_name_reason(name)
        if bad:
            raise RefuseError(bad)
    dry_note = ""
    reason = refuse_reason(run_dir, owner)
    if reason:
        if dry_run and refuse_reason(run_dir, owner, check_pids=False) is None:
            dry_note = "  (would be refused for real: %s)" % reason
        else:
            raise RefuseError(reason)
    rows: List[Dict[str, Any]] = []
    for name in names:
        row = rotate_one(run_dir, name, force=force, threshold=threshold, dry_run=dry_run, log=log, dry_note=dry_note)
        if row:
            rows.append(row)
    return rows


# ----------------------------------------------------------------------------------------------------------------------
# self-test
# ----------------------------------------------------------------------------------------------------------------------

def _fixture_records(n: int, start: int, rng) -> List[str]:
    """Synthetic chat.jsonl lines in both live shapes. Ids are fake uuids; the only names are fixture_a / fixture_b."""
    out: List[str] = []
    t0 = 1_790_000_000 + start * 7
    for i in range(n):
        k = start + i
        user = "fixture_a" if (k % 3) else "fixture_b"
        mid = str(uuid.UUID(int=rng.getrandbits(128)))
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t0 + k * 7)) + ".%03dZ" % (k % 1000)
        text = "fixture line %d %s" % (k, "x" * (k % 40))
        if k % 5 == 4:
            rec = {"ts": ts, "source": "webhook", "id": mid, "user": user, "user_id": 1000 + (k % 2),
                   "text": text, "broadcaster": "fixture_b"}
        else:
            rec = {"ts": ts, "created_at": ts[:19] + "+00:00", "id": mid, "chatroom_id": 1, "sender_id": 1000 + (k % 2),
                   "username": user, "slug": user, "content": text, "color": "#B9D6F6",
                   "badges": ["broadcaster"] if user == "fixture_b" else [], "type": "message"}
        out.append(json.dumps(rec, ensure_ascii=False))
    return out


def _wish_rows(chat_lines: List[str]) -> List[str]:
    out: List[str] = []
    for ln in chat_lines:
        r = json.loads(ln)
        out.append(json.dumps({"id": r["id"], "ts": r["ts"], "key": r.get("username") or r.get("user"),
                               "by": r.get("username") or r.get("user"), "n": 1, "kind": "plain",
                               "text": r.get("content") or r.get("text"), "verb": None, "hint": None,
                               "wish": True, "head": "build", "first_ever": False,
                               "session": "fixture", "src": "live"}, ensure_ascii=False))
    return out


def self_test(keep: bool = False, log=print) -> int:
    import contextlib
    import io
    import random
    rng = random.Random(4)
    fails: List[str] = []
    n_checks = [0]

    def check(cond: bool, what: str) -> None:
        n_checks[0] += 1
        log("  [%s] %s" % ("ok" if cond else "FAIL", what))
        if not cond:
            fails.append(what)

    def read_bytes(p: str) -> bytes:
        with open(p, "rb") as fh:
            return fh.read()

    def ledger_files(d: str, name: str) -> List[str]:
        return sorted(n for n in os.listdir(d) if n.startswith(name))

    def all_json(lines: List[str]) -> bool:
        try:
            return all(isinstance(json.loads(ln), dict) for ln in lines)
        except Exception:
            return False

    run_dir = tempfile.mkdtemp(prefix="lg-P4-rotate-", dir="/tmp")
    log("self-test fixture: %s  (free %.1f GB)" % (run_dir, free_bytes("/tmp") / 1e9))
    try:
        os.makedirs(os.path.join(run_dir, "pids"))
        chat1 = _fixture_records(600, 0, rng)
        wish1 = _wish_rows(chat1[::2])
        live_chat = os.path.join(run_dir, "chat.jsonl")
        live_wish = os.path.join(run_dir, "wishes.jsonl")
        with open(live_chat, "w", encoding="utf-8") as fh:
            fh.write("\n".join(chat1) + "\n")
        with open(live_wish, "w", encoding="utf-8") as fh:
            fh.write("\n".join(wish1) + "\n")

        # 0. the live-dir guard, checked without touching L (refuse_reason reads only; a fake pid dir is never made)
        check(refuse_reason(LIVE_RUN_DIR, owner=False) is not None, "live run dir refused without --i-am-the-owner")
        check(refuse_reason(os.path.join(LIVE_RUN_DIR, "sub"), owner=False) is not None, "a path under L refused too")
        check(refuse_reason("") is not None and "no run dir" in refuse_reason(""), "empty run dir refused: never defaults to L")
        check(refuse_reason(run_dir) is None, "fixture dir with empty pids/ allowed")

        # 1. refusal while compositor.pid names a live process (this very process)
        pidf = os.path.join(run_dir, "pids", "compositor.pid")
        with open(pidf, "w") as fh:
            fh.write("%d\n" % os.getpid())
        reason = refuse_reason(run_dir)
        check(reason is not None and "compositor.pid" in reason, "refused while compositor.pid alive: %s" % reason)
        try:
            rotate(run_dir, force=True, log=lambda *a: None)
            check(False, "rotate() raised RefuseError with a live compositor.pid")
        except RefuseError:
            check(True, "rotate() raised RefuseError with a live compositor.pid")
        check(not os.path.exists(manifest_path(run_dir, "chat.jsonl")), "no manifest written by the refused rotate")
        # --dry-run while a pid is alive is allowed (writes nothing) and says it would be refused for real
        dry_log: List[str] = []
        rows = rotate(run_dir, force=True, dry_run=True, log=lambda s: dry_log.append(s))
        check(rows == [] and len(dry_log) == 2 and all("DRY RUN" in s and "would be refused for real" in s for s in dry_log)
              and not os.path.exists(manifest_path(run_dir, "chat.jsonl")) and ledger_files(run_dir, "chat.jsonl") == ["chat.jsonl"],
              "--dry-run with a live pid prints 'would rotate ... (would be refused for real)' and writes nothing")
        os.unlink(pidf)
        # a dead pid file does not block
        with open(pidf, "w") as fh:
            fh.write("999999999\n")
        check(refuse_reason(run_dir) is None, "a compositor.pid naming a dead pid does not block")
        os.unlink(pidf)

        # 1b. only plain *.jsonl basenames are ledgers: world.json / state.json are refused and untouched
        world = os.path.join(run_dir, "world.json")
        with open(world, "w", encoding="utf-8") as fh:
            fh.write('{"schema": 2, "fixture": true}\n')
        world_before = read_bytes(world)
        for bad_name in ("world.json", "state.json", "../chat.jsonl", "chat.jsonl.20260927T0000.1", ".jsonl", "pids/x.jsonl"):
            try:
                rotate(run_dir, names=(bad_name,), force=True, log=lambda *a: None)
                check(False, "rotate(%r) refused" % bad_name)
            except RefuseError:
                check(True, "rotate(%r) refused" % bad_name)
        check(read_bytes(world) == world_before and ledger_files(run_dir, "world.json") == ["world.json"],
              "world.json untouched: same bytes, no archive, no world.json.manifest.json")
        check(ledger_files(run_dir, "chat.jsonl") == ["chat.jsonl"] and not os.path.exists(manifest_path(run_dir, "chat.jsonl")),
              "a bad name in the list stops the whole call before any ledger is renamed")

        # 2. baseline replay before any rotation, and a cursor a consumer would hold BEFORE any rotation
        pos0 = [(f, e) for f, e, _ in iter_lines(run_dir, "chat.jsonl")]
        before_chat = [ln for _, _, ln in iter_lines(run_dir, "chat.jsonl")]
        before_wish = [ln for _, _, ln in iter_lines(run_dir, "wishes.jsonl")]
        check(before_chat == chat1, "unrotated replay of chat.jsonl == the %d written lines" % len(chat1))
        check(before_wish == wish1, "unrotated replay of wishes.jsonl == the %d written lines" % len(wish1))
        k_stale = 300
        stale = {"file": pos0[k_stale][0], "offset": pos0[k_stale][1]}           # state.json's shape: {file, offset}
        stale_mc = make_cursor(run_dir, "chat.jsonl", pos0[k_stale][0], pos0[k_stale][1])
        check(stale["file"] == "chat.jsonl" and stale_mc["archives"] == 0, "pre-rotation cursors point at the live file")
        check([ln for _, _, ln in iter_lines(run_dir, "chat.jsonl", cursor=stale)] == chat1[k_stale + 1:],
              "before any rotation the cursor resumes after line %d" % (k_stale + 1))

        # 3. size gate: below threshold with no --force nothing rotates
        rows = rotate(run_dir, force=False, log=lambda *a: None)
        check(rows == [] and os.path.getsize(live_chat) > 0, "below 256 MB without --force: nothing rotated")
        # dry run writes nothing
        rows = rotate(run_dir, force=True, dry_run=True, log=lambda *a: None)
        check(rows == [] and not os.path.exists(manifest_path(run_dir, "chat.jsonl")), "--dry-run writes nothing")

        # 4. first forced rotation (both ledgers)
        rows = rotate(run_dir, force=True, log=log)
        check(len(rows) == 2, "forced rotation wrote 2 manifest rows (chat + wishes)")
        check(os.path.getsize(live_chat) == 0, "new live chat.jsonl is empty")
        man = load_manifest(run_dir, "chat.jsonl")
        r0 = man["archives"][0]
        check(r0["lines"] == len(chat1), "manifest row lines == %d" % len(chat1))
        check(r0["bytes"] == os.path.getsize(os.path.join(run_dir, r0["file"])), "manifest row bytes == archive size")
        check(hashlib.sha256(read_bytes(os.path.join(run_dir, r0["file"]))).hexdigest() == r0["sha256"],
              "manifest sha256 == sha256 of the archive")
        check(r0["first_ts"] == json.loads(chat1[0])["ts"] and r0["last_ts"] == json.loads(chat1[-1])["ts"],
              "first_ts / last_ts are the first and last record ts")
        check(r0["file"].startswith("chat.jsonl.") and r0["file"].endswith(".1"), "archive named chat.jsonl.YYYYMMDDTHHMM.1")
        check((os.stat(manifest_path(run_dir, "chat.jsonl")).st_mode & 0o777) == 0o644, "manifest is 0644")
        after1 = [ln for _, _, ln in iter_lines(run_dir, "chat.jsonl")]
        check(after1 == before_chat, "replay across archive + (empty) live == unrotated replay, line for line")
        # the stale pre-rotation cursor: offset past the end of the (empty) live file -> resumed in the archive
        got = [ln for _, _, ln in iter_lines(run_dir, "chat.jsonl", cursor=stale)]
        check(got == chat1[k_stale + 1:], "stale {file: chat.jsonl, offset} past the empty live file's end resumes in the archive (%d lines, not 0)" % len(got))
        idx, off, note = resolve_cursor(run_dir, "chat.jsonl", stale_mc)
        check(idx == 0 and off == stale["offset"] and note is not None and "predates rotation" in note,
              "make_cursor's archives count places the cursor exactly: %s" % note)
        check([ln for _, _, ln in iter_lines(run_dir, "chat.jsonl", cursor=stale_mc)] == chat1[k_stale + 1:],
              "cursor with archives=0 resumes in archive 1")

        # 5. append more, including a PARTIAL trailing line (a writer mid-append), rotate again -> 2 archives
        chat2 = _fixture_records(350, 600, rng)
        partial = '{"ts":"2026-09-27T00:00:00Z","id":"' + str(uuid.UUID(int=rng.getrandbits(128))) + '","username":"fixture_a"'
        with open(live_chat, "a", encoding="utf-8") as fh:
            fh.write("\n".join(chat2) + "\n" + partial)
        wish2 = _wish_rows(chat2[::2])
        with open(live_wish, "a", encoding="utf-8") as fh:
            fh.write("\n".join(wish2) + "\n")
        # the live file has now grown PAST the stale offset: a naive seek would land mid-line and lose 299 archive lines
        with open(live_chat, "rb") as fh:
            fh.seek(stale["offset"] - 1)
            at = fh.read(1)
        check(at != b"\n", "fixture: the stale offset is not a line boundary in the grown live file (byte %r)" % at)
        got = [ln for _, _, ln in iter_lines(run_dir, "chat.jsonl", cursor=stale)]
        check(got == chat1[k_stale + 1:] + chat2 and all_json(got),
              "stale cursor with the live file grown past it: %d lines, archive tail + every new complete line, no fragment" % len(got))
        got = [ln for _, _, ln in iter_lines(run_dir, "chat.jsonl", cursor=stale_mc)]
        check(got == chat1[k_stale + 1:] + chat2, "the same with archives=0, placed exactly")
        # a cursor inside a line, or past an archive's end, never yields a fragment: it replays from the first archive
        mid = {"file": r0["file"], "offset": pos0[k_stale][1] - 3}
        got = [ln for _, _, ln in iter_lines(run_dir, "chat.jsonl", cursor=mid)]
        check(got == chat1 + chat2 and all_json(got), "cursor inside a line -> replay from the first archive, no fragment")
        past = {"file": r0["file"], "offset": r0["bytes"] + 5}
        got = [ln for _, _, ln in iter_lines(run_dir, "chat.jsonl", cursor=past)]
        check(got == chat1 + chat2, "cursor past an archive's end -> replay from the first archive")
        got = [ln for _, _, ln in iter_lines(run_dir, "chat.jsonl", cursor={"file": "nope.jsonl", "offset": 7})]
        check(got == chat1 + chat2, "cursor naming an unknown file -> replay from the first archive")
        rows = rotate(run_dir, force=True, log=log)
        check(len(rows) == 2, "second forced rotation wrote 2 more rows")
        man = load_manifest(run_dir, "chat.jsonl")
        check(len(man["archives"]) == 2 and man["archives"][1]["file"].endswith(".2"), "manifest lists 2 chat archives, seq .2")
        check(man["archives"][1]["lines"] == len(chat2), "second archive holds exactly the %d complete lines" % len(chat2))
        check(read_bytes(live_chat) == partial.encode("utf-8"), "the partial trailing line moved intact into the new live file")
        check(read_bytes(os.path.join(run_dir, man["archives"][1]["file"])).endswith(b"\n"), "the archive ends with a newline (no split record)")
        # finish the partial line, then replay everything
        rest = ',"content":"fixture tail","type":"message"}\n'
        with open(live_chat, "a", encoding="utf-8") as fh:
            fh.write(rest)
        expected = chat1 + chat2 + [(partial + rest).rstrip("\n")]
        after2 = [ln for _, _, ln in iter_lines(run_dir, "chat.jsonl")]
        check(after2 == expected, "replay across 2 archives + live == unrotated replay of %d lines" % len(expected))
        recs = list(iter_records(run_dir, "chat.jsonl"))
        check(len(recs) == len(expected) and recs[-1].get("content") == "fixture tail"
              and len({r["id"] for r in recs}) == len(recs), "iter_records parses every line, ids unique")
        wall = [ln for _, _, ln in iter_lines(run_dir, "wishes.jsonl")]
        check(wall == wish1 + wish2, "wishes.jsonl replay across archive + live == unrotated")
        # the same replay, written to one file, is byte-identical to the archives + live concatenated in order
        cat = b""
        for r in man["archives"]:
            cat += read_bytes(os.path.join(run_dir, r["file"]))
        cat += read_bytes(live_chat)
        check(cat == ("\n".join(expected) + "\n").encode("utf-8"), "archives + live concatenated == the one unrotated file, byte for byte")

        # 6. cursor resume: {file, offset} from the middle of archive 1 continues into archive 2 and live
        pos = [(f, e) for f, e, _ in iter_lines(run_dir, "chat.jsonl")]
        f_mid, e_mid = pos[len(chat1) // 2 - 1]
        resumed = [ln for _, _, ln in iter_lines(run_dir, "chat.jsonl", cursor={"file": f_mid, "offset": e_mid})]
        check(resumed == expected[len(chat1) // 2:], "cursor {file, offset} resumes mid-archive and crosses into live")
        f_last, e_last = pos[-1]
        check([ln for _, _, ln in iter_lines(run_dir, "chat.jsonl", cursor={"file": f_last, "offset": e_last})] == [],
              "cursor at the live end yields nothing (+0)")
        mc = make_cursor(run_dir, "chat.jsonl", f_last, e_last)
        check(mc == {"file": "chat.jsonl", "offset": e_last, "archives": 2} and resolve_cursor(run_dir, "chat.jsonl", mc) == (2, e_last, None),
              "make_cursor at the live end round-trips with no re-anchor")

        # 7. a failure after the rename undoes it (nothing rotated, nothing lost), or names the orphan loudly
        chat3 = _fixture_records(50, 950, rng)
        partial2 = '{"ts":"2026-09-27T00:01:00Z","id":"' + str(uuid.UUID(int=rng.getrandbits(128))) + '","username":"fixture_b"'
        with open(live_chat, "a", encoding="utf-8") as fh:
            fh.write("\n".join(chat3) + "\n" + partial2)
        live_before = read_bytes(live_chat)
        files_before = ledger_files(run_dir, "chat.jsonl")
        g = globals()
        orig_hash = g["_hash_and_count"]

        def boom(path):
            raise OSError("fixture I/O error while hashing")

        g["_hash_and_count"] = boom
        undo_log: List[str] = []
        try:
            try:
                rotate(run_dir, names=("chat.jsonl",), force=True, log=lambda s: undo_log.append(s))
                check(False, "injected failure after the rename propagates")
            except OSError:
                check(True, "injected failure after the rename propagates")
        finally:
            g["_hash_and_count"] = orig_hash
        check(read_bytes(live_chat) == live_before, "chat.jsonl restored byte for byte, partial tail included")
        check(ledger_files(run_dir, "chat.jsonl") == files_before and len(load_manifest(run_dir, "chat.jsonl")["archives"]) == 2,
              "no orphan archive on disk, manifest still 2 rows")
        check(any("restored" in s for s in undo_log), "the undo is logged")
        # the orphan case, in its own sub-fixture: a foreign writer re-creates chat.jsonl before the manifest is written
        orph = os.path.join(run_dir, "orphan-case")
        os.makedirs(os.path.join(orph, "pids"))
        o_lines = _fixture_records(20, 2000, rng)
        with open(os.path.join(orph, "chat.jsonl"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(o_lines) + "\n")

        def boom_foreign(path):
            with open(os.path.join(orph, "chat.jsonl"), "ab") as fh:     # a writer that ignores pids/ appends
                fh.write(b'{"foreign": true}\n')
            raise OSError("fixture I/O error with a foreign writer")

        g["_hash_and_count"] = boom_foreign
        orphan_log: List[str] = []
        try:
            try:
                rotate(orph, names=("chat.jsonl",), force=True, log=lambda s: orphan_log.append(s))
                check(False, "orphan-case failure propagates")
            except OSError:
                check(True, "orphan-case failure propagates")
        finally:
            g["_hash_and_count"] = orig_hash
        o_files = ledger_files(orph, "chat.jsonl")
        check(len(o_files) == 2 and any("ORPHAN ARCHIVE" in s for s in orphan_log)
              and not os.path.exists(manifest_path(orph, "chat.jsonl")),
              "foreign writer re-created chat.jsonl: archive kept on disk, named as ORPHAN, no manifest, exit path 1")
        check(read_bytes(os.path.join(orph, o_files[1])) == ("\n".join(o_lines) + "\n").encode("utf-8"),
              "the orphan archive holds every original line (never deleted)")
        # a ledger that is ONLY a partial line rotates nothing and is left as it was
        with open(os.path.join(orph, "wishes.jsonl"), "w", encoding="utf-8") as fh:
            fh.write('{"id": "half')
        rows = rotate(orph, names=("wishes.jsonl",), force=True, log=lambda *a: None)
        check(rows == [] and read_bytes(os.path.join(orph, "wishes.jsonl")) == b'{"id": "half'
              and ledger_files(orph, "wishes.jsonl") == ["wishes.jsonl"] and not os.path.exists(manifest_path(orph, "wishes.jsonl")),
              "a ledger holding only a partial line: nothing rotated, file untouched")
        # now the real third rotation of the main fixture
        rows = rotate(run_dir, names=("chat.jsonl",), force=True, log=log)
        rest2 = ',"content":"fixture tail two","type":"message"}\n'
        with open(live_chat, "a", encoding="utf-8") as fh:
            fh.write(rest2)
        expected3 = expected + chat3 + [(partial2 + rest2).rstrip("\n")]
        man = load_manifest(run_dir, "chat.jsonl")
        check(len(rows) == 1 and len(man["archives"]) == 3 and man["archives"][2]["lines"] == len(chat3) + 1,
              "third rotation: 3 archives, the third holds %d lines (%d new + the completed partial from step 5)" % (len(chat3) + 1, len(chat3)))
        after3 = [ln for _, _, ln in iter_lines(run_dir, "chat.jsonl")]
        check(after3 == expected3, "replay across 3 archives + live == unrotated replay of %d lines" % len(expected3))
        vrows = verify_manifest(run_dir, "chat.jsonl")
        check(len(vrows) == 3 and [r["file"] for r in vrows] == [r["file"] for r in man["archives"]],
              "verify_manifest hashes all 3 archives up front and returns the rows")

        # 8. a tampered archive is caught by verify (streaming) and by verify_manifest (up front)
        bad = os.path.join(run_dir, man["archives"][0]["file"])
        with open(bad, "r+b") as fh:
            fh.seek(10)
            fh.write(b"Z")
        try:
            list(iter_lines(run_dir, "chat.jsonl"))
            check(False, "tampered archive raises ManifestError")
        except ManifestError:
            check(True, "tampered archive raises ManifestError")
        try:
            verify_manifest(run_dir, "chat.jsonl")
            check(False, "verify_manifest raises on the tampered archive before any line is read")
        except ManifestError:
            check(True, "verify_manifest raises on the tampered archive before any line is read")
        check(len(list(iter_lines(run_dir, "chat.jsonl", verify=False))) == len(expected3), "verify=False still replays")

        # 9. the CLI: --list needs a run dir; a non-ledger --name exits 3; --dry-run with a live pid exits 0, writes nothing
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc_list_empty = main(["--list", "--run-dir", ""])
            rc_list = main(["--list", "--run-dir", run_dir])
            rc_world = main(["--run-dir", run_dir, "--name", "world.json", "--force"])
            with open(pidf, "w") as fh:
                fh.write("%d\n" % os.getpid())
            man_bytes = read_bytes(manifest_path(run_dir, "chat.jsonl"))
            rc_dry = main(["--run-dir", run_dir, "--dry-run", "--force"])
            rc_live = main(["--run-dir", run_dir, "--force"])
            os.unlink(pidf)
        text = out.getvalue()
        check(rc_list_empty == EXIT_REFUSED and "no run dir" in text, "--list --run-dir '' exits 3 with 'no run dir'")
        check(rc_list == EXIT_OK and "chat.jsonl: 3 archive(s)" in text and "wishes.jsonl: 2 archive(s)" in text, "--list prints both manifests")
        check(rc_world == EXIT_REFUSED and ledger_files(run_dir, "world.json") == ["world.json"], "--name world.json --force exits 3, world.json untouched")
        check(rc_dry == EXIT_OK and "would be refused for real" in text and "DRY RUN, nothing written" in text
              and read_bytes(manifest_path(run_dir, "chat.jsonl")) == man_bytes and len(ledger_files(run_dir, "chat.jsonl")) == 4,
              "--dry-run --force with a live pid exits 0, prints the would-rotate lines, writes nothing")
        check(rc_live == EXIT_REFUSED and read_bytes(manifest_path(run_dir, "chat.jsonl")) == man_bytes, "--force with a live pid exits 3, writes nothing")

        # 10. no name, no text from any record appears in a log line above (data stays data): the only names are fixtures
        check(all(("fixture_a" in ln or "fixture_b" in ln) for ln in expected3), "fixture usernames only")
        check(os.path.isdir(LIVE_RUN_DIR) is False or not os.path.exists(os.path.join(LIVE_RUN_DIR, "chat.manifest.json")),
              "L has no chat.manifest.json: this test never touched the live run dir")
    finally:
        if keep:
            log("kept fixture: %s" % run_dir)
        else:
            shutil.rmtree(run_dir, ignore_errors=True)
            log("cleanup: removed %s (%s)" % (run_dir, "gone" if not os.path.exists(run_dir) else "STILL THERE"))
    if fails:
        log("SELF-TEST FAIL (%d of %d): %s" % (len(fails), n_checks[0], "; ".join(fails)))
        return EXIT_FAILED
    log("SELF-TEST PASS (%d checks)" % n_checks[0])
    return EXIT_OK


# ----------------------------------------------------------------------------------------------------------------------
# cli
# ----------------------------------------------------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-dir", default=os.environ.get("RUN_DIR", ""), help="run dir (default $RUN_DIR; never the live dir)")
    ap.add_argument("--name", action="append",
                    help="ledger basename(s) to rotate, plain *.jsonl only (default: chat.jsonl, wishes.jsonl); "
                         "world.json, state.json and every other run-dir file are refused by name")
    ap.add_argument("--force", action="store_true", help="rotate regardless of size")
    ap.add_argument("--threshold-mb", type=int, default=256, help="rotate above this many MB (default 256)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would rotate, write nothing (allowed while a pid is alive; says so per line)")
    ap.add_argument("--i-am-the-owner", action="store_true",
                    help="allow the live run dir (owner, by hand, stream off). NOT before W8 lands: today's "
                         "state.recompute_from_chat keeps a bare {offset} cursor and reads no manifest, so after a "
                         "rotation the next compositor boot would seek past the end of an empty chat.jsonl and forget "
                         "every chatter in the archive (IDLEWORLD.md 7.4, row 13: tool v1, use v1.1)")
    ap.add_argument("--self-test", action="store_true", help="fixture under /tmp/lg-P4-rotate-*, deleted after")
    ap.add_argument("--keep", action="store_true", help="--self-test: keep the fixture dir")
    ap.add_argument("--list", action="store_true", help="print the manifest(s) and exit")
    a = ap.parse_args(argv)

    if a.self_test:
        return self_test(keep=a.keep)

    names = tuple(a.name) if a.name else LEDGERS
    run_dir = a.run_dir
    if a.list:
        # read-only: the live dir may be listed, a live pid does not matter, but there must BE a run dir
        reason = refuse_reason(run_dir, owner=True, check_pids=False)
        if reason:
            print("rotate_chat: %s" % reason)
            return EXIT_REFUSED
        for name in names:
            bad = ledger_name_reason(name)
            if bad:
                print("rotate_chat: %s" % bad)
                return EXIT_REFUSED
        for name in names:
            try:
                man = load_manifest(run_dir, name)
            except ManifestError as e:
                print("%s: %s" % (name, e))
                continue
            print("%s: %d archive(s)" % (name, len(man["archives"])))
            for r in man["archives"]:
                print("  %s  lines=%s bytes=%s first_ts=%s last_ts=%s sha256=%s"
                      % (r["file"], r.get("lines"), r.get("bytes"), r.get("first_ts"), r.get("last_ts"),
                         (r.get("sha256") or "")[:12]))
        return EXIT_OK

    try:
        rows = rotate(run_dir, names=names, force=a.force, threshold=a.threshold_mb * 1024 * 1024,
                      dry_run=a.dry_run, owner=a.i_am_the_owner)
    except RefuseError as e:
        print("rotate_chat: %s" % e)
        return EXIT_REFUSED
    except Exception as e:                                       # ManifestError, OSError, anything mid-rotation
        print("rotate_chat: FAILED: %r" % (e,))
        return EXIT_FAILED
    if a.dry_run:
        print("rotate_chat: DRY RUN, nothing written under %s" % run_dir)
    else:
        print("rotate_chat: %d ledger(s) rotated under %s" % (len(rows), run_dir))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
