#!/usr/bin/env python3
"""scripts/prebake_land.py - OPENWORLD.md 14 step 2: paint the LONGGRASS ground bake for the current season and sun
octant OFFLINE, so the SteadingScene that hot-reloads onto the air opens it in ~10 ms and no frame waits on a bake.

    source scripts/env.sh
    RUN_DIR=/tmp/lg-integ $PYTHON scripts/prebake_land.py [--world MIGRATED.json] [--zoom-075] [--hours H,H,...]

What it does: copies the run dir's world.json (or --world, the migrated copy from `state.py --migrate-copy`), chat.jsonl
and builders.json into a scratch dir under /tmp, boots a real SteadingScene there (the same code path the air will
take: terrain 4471, schema-2 world, marks from the real camps / flowers / fields / wear), waits for its bake thread,
then moves the finished `ground-<seed>-<season>-o<octant>-v<ver>[-p3].npy` file(s) into $RUN_DIR/bake/. The target
run dir's world.json is NEVER written (the scene persists into the scratch copy only). --hours bakes extra sun octants
(local hours) so the swap also has the next octant ready. Exit 0 when every requested bake landed.
Python 3.9; numpy + pillow (through the scene).
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


class _Ctx(object):
    def __init__(self, **kw):
        self.__dict__.update(kw)

    def __getattr__(self, n):
        return None

    def get(self, n, d=None):
        return self.__dict__.get(n, d)


def bake_once(scratch: str, size, hour_shift_s: float, zoom075: bool, log) -> list:
    """Boot a scene in `scratch` with the light's clock shifted by hour_shift_s and return the ready bake paths."""
    if hour_shift_s:
        os.environ["MODE"] = "test"                            # the clock shift is a test-mode hook (nature.clock_shift_s)
        os.environ["KL_CLOCK_SHIFT_S"] = str(hour_shift_s)
    else:
        os.environ.pop("KL_CLOCK_SHIFT_S", None)
    from stream.scenes.steading import SteadingScene
    from stream.world import bake as BK
    sc = SteadingScene(run_dir=scratch, log=log)
    now0 = time.time()
    t0 = time.perf_counter()
    for i in range(20000):
        now = now0 + i / 30.0
        ctx = _Ctx(now=now, frame=i, session={"id": None}, micro={}, mod={}, chat=[], chat_raw=[], compositor_live={"selftest": False})
        sc.frame(ctx, size)
        if sc.refused:
            raise SystemExit("scene refused to boot: %s" % sc.refused)
        if sc.booted:
            if zoom075 and sc.force_zoom is None:
                sc.test_pips = 1                               # lets the 0.75x path build its 3 px/cell manager
                sc.force_zoom = 0.75
            cur = sc.bakes.current
            cur75 = sc._bakes75.current if sc._bakes75 is not None else None
            if cur is not None and cur.ready and not sc.bakes.baking and (not zoom075 or (cur75 is not None and cur75.ready)):
                if sc.worker.pending() == 0:
                    break
        time.sleep(0.005)
    else:
        raise SystemExit("bake did not finish")
    out = []
    for m in (sc.bakes, sc._bakes75):
        if m is not None and m.current is not None and m.current.ready:
            m.current.wait(5.0)
            out.append((m.current.path, m.current.stats()))
    log("baked in %.0f ms wall: %s" % ((time.perf_counter() - t0) * 1000, [os.path.basename(p) for p, _ in out]))
    return out


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--run-dir", default=os.environ.get("RUN_DIR"), help="the run dir whose bake/ receives the files")
    ap.add_argument("--world", help="a migrated world.json to bake from (default: $RUN_DIR/world.json)")
    ap.add_argument("--zoom-075", action="store_true", help="also bake the 3 px/cell file the 0.75x zoom crops")
    ap.add_argument("--hours", help="extra local hours to bake octants for, e.g. 12,18 (default: now only)")
    a = ap.parse_args(argv)
    if not a.run_dir:
        print("prebake_land.py: --run-dir or $RUN_DIR required", file=sys.stderr)
        return 2
    run_dir = os.path.abspath(a.run_dir)
    world = a.world or os.path.join(run_dir, "world.json")
    if not os.path.isfile(world):
        print("prebake_land.py: no world.json at %s" % world, file=sys.stderr)
        return 2
    scratch = tempfile.mkdtemp(prefix="lg-prebake-")
    log = lambda m: sys.stderr.write("prebake: %s\n" % m)   # noqa: E731
    shutil.copy2(world, os.path.join(scratch, "world.json"))
    for f in ("chat.jsonl", "builders.json"):
        src = os.path.join(run_dir, f)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(scratch, f))
    dest = os.path.join(run_dir, "bake")
    os.makedirs(dest, exist_ok=True)
    shifts = [0.0]
    if a.hours:
        h_now = time.localtime().tm_hour + time.localtime().tm_min / 60.0
        for h in a.hours.split(","):
            shifts.append((float(h) - h_now) * 3600.0)
    landed = []
    try:
        for s in shifts:
            for path, st in bake_once(scratch, (1280, 440), s, a.zoom_075, log):
                target = os.path.join(dest, os.path.basename(path))
                shutil.copy2(path, target)
                landed.append((target, os.path.getsize(target), st))
                print("prebaked %s (%.1f MB) season %s octant %s ver %s ms %s" % (
                    target, os.path.getsize(target) / 1e6, st.get("season"), st.get("octant"), st.get("ver"), st.get("ms")))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    print("world.json in %s untouched; %d bake file(s) in %s" % (run_dir, len(landed), dest))
    return 0 if landed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
