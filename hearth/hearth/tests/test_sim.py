#!/usr/bin/env python
"""Sim checks. No renderer. No live dirs."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from hearth.sim import ASH_MAX, Hearth, clean_text, mood_of  # noqa: E402


def msg(slug, text, i=0):
    return {"id": "m-%s-%d" % (slug, i), "slug": slug, "username": slug,
            "content": text, "color": "#C8A078", "type": "message"}


class SimTest(unittest.TestCase):
    def test_empty_hill_has_no_people(self):
        h = Hearth()
        self.assertEqual(h.people, {})
        h.tick(10.0, 1.0 / 30)
        self.assertEqual(h.people, {})

    def test_one_chat_makes_a_person_forever(self):
        h = Hearth()
        h.ingest(msg("jo", "hey"), 1.0)
        self.assertIn("jo", h.people)
        for i in range(400):
            h.tick(1.0 + i * 0.5, 0.5)
        self.assertIn("jo", h.people)
        self.assertEqual(len(h.people), 1)

    def test_talk_raises_heat(self):
        h = Hearth()
        h.heat = 0.12
        before = h.heat
        for i in range(6):
            h.ingest(msg("jo", "wood %d" % i, i), 2.0 + i * 2.0)
        self.assertGreater(h.heat, before)
        self.assertEqual(len(h.people), 1)

    def test_silence_cools(self):
        h = Hearth()
        h.heat = 0.6
        for i in range(200):
            h.tick(10.0 + i * 0.25, 0.25)
        self.assertLess(h.heat, 0.1)

    def test_duplicate_id_ignored(self):
        h = Hearth()
        rec = msg("jo", "hey", 1)
        h.ingest(rec, 1.0)
        h.ingest(rec, 1.1)
        self.assertEqual(h.people["jo"].feeds, 1)

    def test_volume_can_wildfire(self):
        h = Hearth()
        h.heat = 0.5
        names = ["a", "b", "c", "d", "e", "f", "g", "h", "i"]
        now = 50.0
        for i, n in enumerate(names):
            h.ingest(msg(n, "go", i), now + i * 0.2)
        self.assertGreaterEqual(h.heat, 0.5)
        # eight mouths in eight seconds should shove
        self.assertIn(h.mood, ("bonfire", "wildfire"))

    def test_ash_match_relights(self):
        h = Hearth()
        h.heat = 0.0
        h.mood = "ash"
        h.ingest(msg("jo", "hey"), 1.0)
        self.assertGreater(h.heat, ASH_MAX)
        self.assertNotEqual(mood_of(h.heat), "ash")

    def test_torch_needs_three_mouths(self):
        h = Hearth()
        h.heat = 0.0
        h.mood = "ash"
        h.ingest(msg("a", "rise", 1), 1.0)
        h.ingest(msg("b", "rise", 2), 1.2)
        mid = h.heat
        h.ingest(msg("c", "rise", 3), 1.4)
        self.assertGreater(h.heat, mid)
        self.assertGreaterEqual(h.heat, 0.3)

    def test_quiet_people_do_not_feed(self):
        h = Hearth()
        h.ingest(msg("old", "once"), 1.0)
        for i in range(50):
            h.tick(2.0 + i, 1.0)
        cold = h.heat
        # they still exist, heat is not propped up by ghosts
        self.assertIn("old", h.people)
        self.assertEqual(h.voices(200.0), [])

    def test_clean_emote(self):
        self.assertEqual(clean_text("[emote:1730752:emojiAngel] hi"), "* hi")

    def test_save_load_keeps_people(self):
        h = Hearth()
        h.ingest(msg("jo", "hey"), 1.0)
        h.heat = 0.33
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "hearth.json")
            h.save(path)
            b = Hearth()
            b.load(path)
        self.assertIn("jo", b.people)
        self.assertAlmostEqual(b.heat, 0.33, places=5)

    def test_no_invented_slug(self):
        h = Hearth()
        h.ingest({"id": "x", "content": "hi", "type": "message"}, 1.0)
        self.assertEqual(h.people, {})


if __name__ == "__main__":
    unittest.main()
