"""stream/scenes - renderers that are NOT panels.

A scene is a renderer a panel delegates to for a region's picture. Scenes never register with the
panel registry and never own a region. Today: `hollow.py` (CaveScene, PIP HOLLOW: the 320x110 cave
sim the `world` panel in stream/panels/world.py draws its text layer over; contract in
stream/WORLD_API.md) and `canvas.py` (the legacy reaction-diffusion / flow-field canvas the old
stage_body panel used; kept for `micro.canvas_scene` history, no panel draws it now).
The hot reloader re-executes a changed scene module and then every panel module whose source
mentions `stream.scenes`, so the world panel rebinds to a fresh CaveScene (WORLD_API.md 9).

Legacy contract (canvas): the stage panel owns `stage_body`, asks a scene for an RGBA image of the
region's size and pastes / overlays on top of it.

Contract (every scene module):

    class SomeScene(object):
        name = "some_scene"                        # what state.micro.canvas_scene names it
        def frame(self, ctx, size) -> PIL.Image.Image   # mode RGBA, exactly `size` = (w, h), never raises

Usage from the stage panel:

    from stream.scenes.canvas import CanvasScene
    self.canvas = CanvasScene()                    # one instance per panel; it keeps the sim state
    img = self.canvas.frame(ctx, size)             # once per frame while the CANVAS/ATTRACT scene is up
    img = self.canvas.frame(ctx, size, chip=False, dim=0.6)   # ATTRACT: no chip, dimmer sim under the hook text

Rules a scene follows (same as panels, COMPOSITOR_API.md section 2): never time.time() (ctx.now /
ctx.frame only), never read files (ctx only), nothing under 20 px, colours from stream.layout,
deterministic from `state.micro.canvas_seed` (seeded numpy RNG, no random.random), and a raise
inside the scene is caught by the scene itself -> the last good frame (or a plain fallback) comes
back, one stderr line, so the stage panel never turns into a placeholder because of a scene.
"""
from __future__ import annotations

SCENES = ("reaction_diffusion", "flow_field")   # values state.micro.canvas_scene may take


def get_scene(name=None):
    """Convenience: the CanvasScene instance draws every canvas_scene value; `name` is only a hint."""
    from stream.scenes.canvas import CanvasScene
    return CanvasScene(default_scene=name)
