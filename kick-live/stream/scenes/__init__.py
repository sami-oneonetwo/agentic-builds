"""stream/scenes - stage-body scenes that are NOT panels.

A scene is a renderer the stage-body panel (stream/panels/stage.py) delegates to when the stage
is in a mode that needs its own drawing (CANVAS, ATTRACT background, ...). Scenes never register
with the panel registry and never own a region: the stage panel owns `stage_body`, asks a scene
for an RGBA image of the region's size and pastes / overlays on top of it.

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
