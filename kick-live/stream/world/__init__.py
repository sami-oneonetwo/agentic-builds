"""stream/world - the PIP HOLLOW world core (WORLD.md sections 3, 6, 12 rows 1-4).

Modules
  pips.py       sprite generator: 4 angular stencils x parts hashed from the Kick username, tiers, frames,
                reject-and-reseed, bounded cache, `--sheet` review image
  behaviour.py  entities + per-frame events: nameless seed -> hatch after the hold, wander, face the newest
                speaker, walk-to platform, hop, blink, energy, curl, sleep/wake at 20 min, credits walk
  state.py      world.json in $RUN_DIR: schema, atomic writes, daily .bak, builders.json join, counts
                recomputed from chat.jsonl by (session, owner) with a cursor, tiers, minutes present
  ../scenes/hollow.py  CaveScene.frame(ctx, size): the 320x110 sim upscaled 4x, glow, drips, moss, sky + moon,
                graceful-degrade ladder, last-good-frame, the honesty check every frame

The exact API the other module agents code against is in stream/WORLD_API.md. The art rule is
docs/art-rules.md. Python 3.9 (from __future__ import annotations; no match; no X | Y at runtime).

HONESTY (WORLD.md 1, 10, 11): every animate entity is one real person who chatted. Synthetic pips exist
only under KL_TEST_PIPS=N and only when `test_pips_allowed()` says so: run dir under /tmp AND a test mode
(--self-test or MODE=test) is active. The scene asserts every frame that len(entities) == len(entities
hatched from real chat records) whenever that returns 0.
"""
from __future__ import annotations

import os

SIM_W, SIM_H = 320, 110          # the sim grid; 1 sim px = 4x4 screen px = 1 thumbnail px
UPSCALE = 4
HOLD_S = 3.0                     # the moderation hold (CONCEPT 7.1 step 1); the seed is nameless for exactly this long
SLEEP_AFTER_S = 20.0 * 60.0      # awake = the owner chatted in the last 20 min of this session

__all__ = ["SIM_W", "SIM_H", "UPSCALE", "HOLD_S", "SLEEP_AFTER_S", "test_pips_allowed"]


def _under_tmp(path: str) -> bool:
    rp = os.path.realpath(path or "")
    return rp.startswith("/tmp/") or rp.startswith("/private/tmp/")


def test_pips_allowed(run_dir: str, ctx=None, env=None) -> int:
    """How many synthetic pips this run may create (0 in every normal case).

    Non-zero only when ALL hold: KL_TEST_PIPS=N > 0 in the environment, `run_dir` resolves under /tmp, and a
    test mode is active: `ctx.compositor_live["selftest"]` is true (the compositor's --self-test), or
    MODE=test, or ctx.selftest is true (a standalone harness says so explicitly). The live dirs
    (~/.local/share/kick-live/run, run-live) can never qualify: they are not under /tmp."""
    env = os.environ if env is None else env
    try:
        n = int(env.get("KL_TEST_PIPS") or 0)
    except Exception:
        n = 0
    if n <= 0:
        return 0
    if not _under_tmp(run_dir):
        return 0
    test_mode = env.get("MODE") == "test"
    if ctx is not None:
        try:
            live = getattr(ctx, "compositor_live", None) or {}
            test_mode = test_mode or bool(live.get("selftest")) or bool(getattr(ctx, "selftest", False))
        except Exception:
            pass
    return n if test_mode else 0
