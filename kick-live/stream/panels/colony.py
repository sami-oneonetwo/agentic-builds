"""stream/panels/colony.py - THE LAND strip (OPENWORLD.md 8 row 6; HUD pass 2026-09-26, journal 028): region `land`,
0,522,720,198. One strip under the land instead of three (colony + keeper + ticker): a caption, not a dashboard.

  row 1  HN Medium 24  text   (16,12)   `2 have walked here · 1 more and the cairn is named` / `17 have walked here ·
                                        8 more until the Coast opens` / `17 have walked here` / `nobody has walked here
                                        yet` / warn `3 have walked here · the keepers name the cairn next session` /
                                        `3 have walked here · the keepers are naming the cairn`. THE one home of the
                                        headcount (len(real pip rows that hatched)); no `day N`, no bar.
  row 2  HN Medium 22  text   (16,50)   `AI keepers build this show live from chat's ideas` -- STATIC, every frame (the
                                        owner had to ask in chat what the keepers are, journal 023).
  row 3  HN Medium 22         (16,80)   keeper state, the ONLY rotating text in the footer. Priority: failure (20 s,
                                        warn) `a raising failed · reverting to the last good version` > raising (pinned,
                                        accent) `raising the Ford bridge · asked by @moss_m · 12:40 left` > just raised
                                        (10 min, text) `just raised the Ford bridge · asked by @moss_m` > idle 10 s
                                        alternation (text2): heartbeat fresh `a keeper is on duty now · type !idea <what
                                        to raise>` / stale `no keeper on duty · your !idea waits on the board`,
                                        alternating at 0 awake with `2 sleep at their camps · last here: @atleastonce
                                        14:19`. No traceback text, no version string, no beacon glyph.
  rows 4-5 HN Medium 20 text2 (16,114) / (16,138)  the honesty line, VERBATIM OPENWORLD 12, split at the sentence break,
                                        STATIC every frame: `no camera, no mic, no fake viewers.` / `every name on this
                                        land is a real person in chat. the wind is just the wind.` (ADR-000). If a
                                        fallback font widens a row past 688 px it wraps to a third row, never truncates.

On the cave (no `land`: the rollback week) the same five rows carry the cave's words (`17 have hatched here`, WORLD.md 5
row 9 honesty line), so a panel-only hot-reload never changes the cave's meaning.

Every number is a len() the world computed over real records (test pips carry `_test` and are excluded by the
Land / WorldState); every name passes through the world panel's `shown_name()` (blocklist -> `builder #N`) and is
dropped under !kill. Nothing here is invented; an item that cannot be said whole is skipped, never chopped.
"""
from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional, Tuple

from PIL import ImageDraw

from stream import layout as L
from stream.panels import Panel, register
from stream.state_store import iso_to_epoch
from stream.world import keepers as K          # cave chamber names (the Ledge, East Chamber, ...): one source, rollback week

ROTATE_S = 10.0
HEARTBEAT_FRESH_S = 120.0
FAIL_SHOW_S = 20.0
JUST_RAISED_S = 600.0
MAX_W = 688                                     # 720 - 2 * PAD
F1, F2, F4 = ("HN Medium", 24), ("HN Medium", 22), ("HN Medium", 20)
ROW_Y = (14, 56, 88, 130, 156)            # the 198 px strip (world 456): a row of air over the 174 px plan

KEEPERS_LINE_LAND = ""   # owner 2026-09-26 18:35: no AI/explainer copy on screen          # 482 px HN Medium 22
KEEPERS_LINE_CAVE = ""
HONESTY_LAND = ()   # owner 2026-09-26 18:35: the honesty PRINCIPLE stays (ADR-000); its on-screen recital is gone
