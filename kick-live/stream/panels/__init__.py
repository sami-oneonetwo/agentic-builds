"""stream/panels - Panel base class, registry and auto-discovery.

Panel API (exact; downstream agents code against this):

    class Panel:
        key: str          # unique id, shown on the placeholder if the panel fails
        region: str       # a key of stream.layout.LAYOUT; render() gets that box's (w, h)
        def inputs(self, ctx) -> hashable   # cache key: render() runs only when this changes
        def render(self, ctx, size) -> PIL.Image.Image   # mode "RGBA", exactly `size`

Rules the compositor enforces:
  * render() is called only when inputs() returns a value != the previous one (compared with ==).
    Return something cheap and hashable (tuple of strings/ints). Include ctx.frame in the tuple
    when the panel must redraw every frame (ticker, scope, cursor), and keep your own internal
    caches for the expensive parts (pre-rendered text strips etc).
  * A panel whose inputs() or render() raises is caught: the region shows a dark placeholder
    with viewer words (PLACEHOLDER_WORDS, e.g. "chat is catching up…"), the error is logged once
    (stderr + activity.jsonl), and the loop goes on.
  * A panel whose render() exceeds the per-panel budget (compositor.PANEL_BUDGET_MS, 28 ms) for 30 consecutive renders is
    disabled to the placeholder and logged. It is re-enabled after 300 frames for one retry.
  * The RGBA image is alpha-composited onto the panel fill once, at render time, then the
    opaque result is pasted every frame. Draw your own background if you want one.
  * Panels never touch the frame outside their region and never call time.time(): use ctx.now.

register(panel_instance) adds it to PANEL_REGISTRY (dict key -> Panel). discover() imports every
module in this package; import errors are caught and logged, never fatal.
"""
from __future__ import annotations

import importlib
import os
import pkgutil
import sys
import traceback
from typing import Dict, List

from PIL import Image, ImageDraw

from stream import layout as L


class Panel(object):
    key: str = "panel"
    region: str = "stage_body"
    budget_ms = None                 # per-render budget (ms) before the frame-time guard counts a strike;
                                     # None -> compositor.PANEL_BUDGET_MS (28, journal 009). Set a float to override.

    def inputs(self, ctx):
        """Return a hashable cache key. Default: redraw every frame (safe, slow)."""
        return ctx.frame

    def render(self, ctx, size):
        w, h = size
        return Image.new("RGBA", (w, h), (0, 0, 0, 0))

    # helpers panels may use -------------------------------------------------
    @staticmethod
    def base(size, fill=None):
        """Panel-fill RGBA image with a 1 px hairline top border."""
        w, h = size
        img = Image.new("RGBA", (w, h), fill or L.COLORS["panel"])
        d = ImageDraw.Draw(img)
        d.line([(0, 0), (w - 1, 0)], fill=L.COLORS["hairline"], width=1)
        return img

    def __repr__(self):
        return "<Panel %s @%s>" % (self.key, self.region)


PANEL_REGISTRY: Dict[str, Panel] = {}
IMPORT_ERRORS: List[str] = []


def register(panel: Panel) -> Panel:
    if not getattr(panel, "key", None):
        raise ValueError("panel needs a key")
    if panel.region not in L.LAYOUT:
        raise ValueError("panel %s: unknown region %r" % (panel.key, panel.region))
    PANEL_REGISTRY[panel.key] = panel
    return panel


# Viewer-facing words for a failed / disabled panel. The traceback stays in the compositor log; nothing on screen says
# "render() raised" (QA 2026-09-25: internal jargon leaked into viewer-facing text).
PLACEHOLDER_WORDS = {
    # PIP HOLLOW regions (WORLD.md 5)
    "world": "the cave is waking…", "colony": "colony strip restarting…", "keeper": "keeper strip restarting…",
    "chat_log": "chat is catching up…",
    "ticker": "ticker restarting…", "scope": "", "readout": "readout restarting…",
    "countdown": "", "header_left": "PIP HOLLOW", "header_center": "clock restarting…", "header_right": "",
    # legacy keys (regions removed with the pivot; kept so an old module that still registers one degrades in words)
    "chat_pane": "chat is catching up…", "chat_pinned": "chat is catching up…", "founders": "founders list is catching up…",
    "ballot": "ballot restarting…", "activity_feed": "activity feed restarting…",
    "stage_body": "stage restarting…", "stage_title": "stage restarting…", "stage_step": "",
    "ask_card": "last ship card restarting…", "next_up": "next up restarting…",
}


def viewer_words(key: str, note: str = "") -> str:
    """What the placeholder says: plain words, no internals. `note` only picks paused vs restarting."""
    base = PLACEHOLDER_WORDS.get(key, key.replace("_", " ") + " restarting…")
    if base and "over budget" in (note or ""):
        return base.replace("restarting…", "paused (too slow)").replace("catching up…", "paused (too slow)")
    return base


def placeholder(size, key: str, note: str = "panel error") -> Image.Image:
    """Safe dark placeholder shown when a panel raises or is disabled. Shows viewer words, never the exception."""
    w, h = size
    img = Image.new("RGBA", (w, h), "#0E1117")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w - 1, h - 1], outline="#2A1F1F", width=1)
    words = viewer_words(key, note)
    if words and h >= 24 and w >= 80:
        f = L.font("Menlo", 20)
        d.text((8, max(2, h // 2 - 12)), L.truncate("Menlo", 20, words, w - 16), font=f, fill="#8A90A0")
    return img


def discover(log=None) -> Dict[str, Panel]:
    """Import every module in stream/panels/ so their register() calls run. Never raises."""
    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    for _finder, name, _ispkg in sorted(pkgutil.iter_modules([pkg_dir]), key=lambda t: t[1]):
        if name.startswith("_"):
            continue
        modname = __name__ + "." + name
        try:
            if modname in sys.modules:
                importlib.reload(sys.modules[modname])
            else:
                importlib.import_module(modname)
        except Exception:
            msg = "panel module %s failed to import: %s" % (name, traceback.format_exc().strip().splitlines()[-1])
            IMPORT_ERRORS.append(msg)
            if log:
                log(msg)
            else:
                sys.stderr.write(msg + "\n")
    return PANEL_REGISTRY
