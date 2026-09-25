"""stream/world/art - the canonical art module of the SETTLEMENT world (top-down, small people-shaped settlers).

The bible is docs/ART.md. Reference renders live in docs/art/final/ and are produced FROM these modules by
docs/art/final/render_final.py. Nothing here reads the clock or the run dir: every function is deterministic in its
arguments and cached, so the compositor can call it on the frame path after a warm-up.

    creatures   render(username, tier, frame, zoom, facing, sun) -> RGBA · genome(username) · shadow(...) ·
                settler_sheet(...) · head_icon(...) · anchor(tier) · FRAMES · TIERS
    tiles       atlas(season) · Ground(cells, season).paint(wind, ripple) / repaint(region) · grade(rgb, hour) ·
                sun_vector(hour) · CAT · T · CELL
    buildings   render(kind, tier, colour, seed, lit, sun) -> (RGBA, (dx, dy)) · footprint(kind, tier)
    props       tree(age, ...) · bush · flowers · stone · cairn · waystone · campfire(phase) · beacon(phase) · glow ·
                cloud_shadow · anchor(spr)
    hud         SIZES (all >= 20 px) · COLOURS · LAYOUT · header · panel · caption · pill · place_pills · minimap

Rules that every module obeys (docs/ART.md): every named settler is a real chatter and is procedural from the
username; no animals or NPCs; one toy-cream face for everyone (never a skin tone); Python 3.9, numpy + pillow only;
everything cached for a 30 fps compositor; every HUD text >= 20 px.
"""
from __future__ import annotations

from . import buildings, creatures, hud, props, tiles  # noqa: F401

__all__ = ["buildings", "creatures", "hud", "props", "tiles", "SUN_EVENING", "SUN_DAWN", "SUN_NIGHT", "warm_up"]

SUN_EVENING = (-0.62, -0.78)     # 18:00: low in the west-north-west (screen top-left)
SUN_DAWN = (0.80, -0.60)         # 06:40: low in the east (screen top-right)
SUN_NIGHT = (0.15, -0.99)        # moonlight from high in the north


def warm_up(usernames, tiers, sun=SUN_EVENING, zoom=1):
    """Pre-render every frame of the given settlers (what a hatch does) and the tile atlas for one sun / zoom."""
    for name, tier in zip(usernames, tiers):
        creatures.settler_sheet(name, tier, zoom, sun)
    tiles.atlas(1.0).prebake()
