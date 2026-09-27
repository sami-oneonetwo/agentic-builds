"""Render checks with isolated fixtures. Never read or write a live runtime."""
import copy
import hashlib
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from hearth import draw
from hearth.sim import Hearth


def scene(heat=.4, people=0):
    world = Hearth()
    colors = ['#89956c', '#bfa36b', '#ad7152', '#668e91']
    for i in range(people):
        world.ingest({'id': str(i), 'slug': 'fixture-%d' % i,
                      'username': 'fixture-%d' % i, 'color': colors[i % 4],
                      'content': 'warm', 'type': 'message'}, 990.)
    world.heat = world.shown_heat = heat
    return world


class DrawTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for heat in draw._GLOW_STOPS:
            draw._glow_at(heat)

    def test_output_shapes_and_populations(self):
        for count in (0, 1, 8, 32):
            for heat in (0., .12, .4, .7, 1.15):
                with self.subTest(count=count, heat=heat):
                    world = scene(heat, count)
                    frame = draw.render(world, 1000., 0)
                    self.assertEqual(frame.size, (1280, 720))
                    self.assertEqual(frame.mode, 'RGB')
                    self.assertEqual(len(world.people), count)

    def test_render_is_pure_and_deterministic(self):
        world = scene(.7, 8)
        before = copy.deepcopy(world.__dict__)
        a = draw.render(world, 1000., 0)
        b = draw.render(world, 1000., 0)
        self.assertEqual(a.tobytes(), b.tobytes())
        for key in before:
            if key != 'people':
                self.assertEqual(before[key], world.__dict__[key], key)
        self.assertEqual([p.to_dict() for p in before['people'].values()], world.to_dict()['people'])

    def test_no_black_padding_for_any_camera(self):
        for heat in np.linspace(0., 1.15, 32):
            world = scene(float(heat))
            world.shake = 1.
            box = draw._camera_box(world, 1000.)
            self.assertGreaterEqual(min(box[:2]), 0.)
            self.assertLessEqual(box[2], draw.SW)
            self.assertLessEqual(box[3], draw.SH)
            with patch.object(draw, '_glow_at', return_value=Image.new('RGB', (draw.SW, draw.SH), (80, 90, 100))):
                im = np.asarray(draw.render(world, 1000., 0))
            border = np.concatenate((im[0], im[-1], im[:, 0], im[:, -1]))
            self.assertFalse(np.any(np.all(border == 0, axis=1)))

    def test_seating_and_framing_are_continuous(self):
        for heat in (.02, .18, .48, .7, .78, 1.):
            a, b = scene(heat-1e-5, 8), scene(heat+1e-5, 8)
            self.assertLess(abs(draw._seat(8, a.heat)-draw._seat(8, b.heat)), .01)
            self.assertLess(max(abs(x-y) for x,y in zip(draw._camera_box(a, 1000.), draw._camera_box(b, 1000.))), .1)
            ia = np.asarray(draw.render(a, 1000., 0)).astype(float)
            ib = np.asarray(draw.render(b, 1000., 0)).astype(float)
            self.assertLess(np.mean(np.abs(ia-ib)), .8)

    def test_cached_plates_unchanged_by_render(self):
        before = {k: hashlib.sha256(v.tobytes()).digest() for k,v in draw._PLATES.items()}
        for heat in np.linspace(0., 1.15, 21):
            draw.render(scene(float(heat)), 1000., 0)
        self.assertEqual(len(draw._PLATES), len(draw._GLOW_STOPS))
        self.assertEqual(before, {k: hashlib.sha256(v.tobytes()).digest() for k,v in draw._PLATES.items()})
        self.assertEqual(draw._person_sprite.cache_info().maxsize, 256)
        self.assertEqual(draw._bubble.cache_info().maxsize, 128)

    def test_identity_survives_python_hash_seed(self):
        code = ('from hearth.draw import _person_sprite; import hashlib; '
                'print(hashlib.sha256(_person_sprite("fixture-1", "#89956c", 3, False, True).tobytes()).hexdigest())')
        results = []
        for seed in ('1', '99'):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            results.append(subprocess.check_output([sys.executable, '-c', code], env=env))
        self.assertEqual(results[0], results[1])

    def test_crowd_centers_visible(self):
        for heat in (0., .4, 1.15):
            world = scene(heat, 32)
            box = draw._camera_box(world, 1000.)
            for _, x, y in draw._positions(world, draw._seat(32, heat), 1000.):
                self.assertGreaterEqual(x-32, box[0])
                self.assertLessEqual(x+32, box[2])
                self.assertGreaterEqual(y-65, box[1])
                self.assertLessEqual(y+13, box[3])

    def test_people_drawn_only_from_world(self):
        with patch.object(draw, '_draw_person', wraps=draw._draw_person) as person:
            draw.render(scene(), 1000., 0)
            self.assertEqual(person.call_count, 0)
            draw.render(scene(.4, 8), 1000., 0)
            self.assertEqual(person.call_count, 8)

    def test_animation_changes_without_large_frame_pops(self):
        world = scene(.7, 8)
        a = np.asarray(draw.render(world, 1000., 0)).astype(float)
        b = np.asarray(draw.render(world, 1000.+1/30., 1)).astype(float)
        delta = np.mean(np.abs(a-b))
        self.assertGreater(delta, .001)
        self.assertLess(delta, 2.)


if __name__ == '__main__':
    unittest.main()
