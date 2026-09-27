"""Small offline regressions for hot-reload bakes and durable wish replay. No live files touched."""
from __future__ import annotations
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stream.world import bake, schema3, wishes
from stream.chat_bridge import ChatBridge

class WorldRegressions(unittest.TestCase):
    def test_concurrent_bakes_same_key_use_private_staging_files(self):
        with tempfile.TemporaryDirectory() as run:
            terrain = SimpleNamespace(seed=1, h=2, w=2)
            a = bake.GroundBake(run, terrain, 0, (-1, 0))
            b = bake.GroundBake(run, terrain, 0, (-1, 0))
            self.assertEqual(a.path, b.path)
            self.assertNotEqual(a.tmp, b.tmp)
            barrier = threading.Barrier(2)
            def paint(arr, *args):
                arr[:] = 91
                barrier.wait(timeout=5)
            for item in (a,b):
                item.paint_strip = paint
                item.paint_props = lambda *args: None
            with patch.object(bake, 'cells_with_marks', return_value=np.zeros((2,2),np.uint8)):
                a.start(); b.start()
                self.assertTrue(a.wait(10)); self.assertTrue(b.wait(10))
            self.assertIsNone(a.error); self.assertIsNone(b.error)
            self.assertTrue((np.load(a.path)==91).all())
            a.close(); b.close()

    def test_new_replay_preserves_executed_verb_not_another_wish(self):
        class Tagger:
            parse_verb = staticmethod(ChatBridge.parse_verb)
            def wish_tag(self, text, kind): return True, 'plant'
        m={'id':'plant-1','name':'fixture','text':'plant a flower','t':time.time()}
        row=schema3.replay_row(m,'plain',1,Tagger())
        self.assertEqual(row['verb'],'plant')
        self.assertFalse(row['wish'])
        m['text']='a lantern'
        row=schema3.replay_row(m,'plain',1,Tagger())
        self.assertIsNone(row['verb']); self.assertTrue(row['wish'])

    def test_old_replay_rows_do_not_duplicate_planting_but_keep_project_history(self):
        now=time.time()
        def row(mid,text,ts,key='fixture'):
            return {'id':mid,'text':text,'ts':wishes._iso(ts),'key':key,'by':key,
                    'kind':'plain','src':'replay','wish':True,'verb':None}
        rows=[row('past-plant','plant a flower',now-20),row('lamp','a lantern',now-10),
              row('castle','build a castle',now-3*86400),row('gone','a banner',now-5,'missing')]
        with tempfile.TemporaryDirectory() as run:
            Path(run,'wishes.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
            world=SimpleNamespace(data={'world':{'placed':[],'wish_post':[]},'pips':{'fixture':{}},'banished':{}})
            scene=SimpleNamespace(world=world,run_dir=run,log=lambda *a:None)
            post=wishes.WishPost(scene); post.boot(now)
            self.assertNotIn('flowerbed',post._clusters)
            self.assertIn('lantern',post._clusters)
            self.assertIn('keep',post._clusters)
            self.assertNotIn('banner',post._clusters)
            self.assertEqual([q['recipe'] for q in post._queue],['lantern'])
            before=len(post._queue); self.assertEqual(post.boot(now),{})
            self.assertEqual(len(post._queue),before)

if __name__ == '__main__': unittest.main(verbosity=2)
