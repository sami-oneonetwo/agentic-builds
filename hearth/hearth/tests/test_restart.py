"""Restart a local fixture without feeding historical messages again."""
import json
from pathlib import Path
import tempfile
import unittest

from hearth.chat import ChatTail
from hearth.compositor import Compositor


class RestartTest(unittest.TestCase):
    def test_restart_preserves_heat_and_only_ingests_new_chat(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'chat.jsonl'
            path.write_text(json.dumps({'id': 'one', 'slug': 'fixture', 'content': 'hello'})+'\n')
            a = Compositor(td, 30, None, True, chat_file=str(path))
            a._ingest(100.)
            a.world.heat = 0.
            a._save(101., force=True)
            a.tail.close()
            with path.open('a') as fh:
                fh.write(json.dumps({'id': 'two', 'slug': 'fixture', 'content': 'again'})+'\n')
            b = Compositor(td, 30, None, True, chat_file=str(path))
            self.assertEqual(b.world.heat, 0.)
            self.assertEqual(b.world.people['fixture'].feeds, 1)
            b._ingest(102.)
            self.assertEqual(b.world.people['fixture'].feeds, 2)
            self.assertGreater(b.world.heat, 0.)
            b._save(103., force=True)
            b.tail.close()
            c = Compositor(td, 30, None, True, chat_file=str(path))
            heat = c.world.heat
            c._ingest(104.)
            self.assertEqual(c.world.people['fixture'].feeds, 2)
            self.assertEqual(c.world.heat, heat)
            c.tail.close()

    def test_partial_record_stays_unconsumed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'chat.jsonl'
            record = json.dumps({'id': 'one', 'slug': 'fixture', 'content': 'é'})
            path.write_text(record[:20])
            tail = ChatTail(str(path))
            self.assertEqual(tail.poll(), [])
            checkpoint = tail.checkpoint()
            tail.close()
            with path.open('a') as fh:
                fh.write(record[20:]+'\n')
            resumed = ChatTail(str(path), checkpoint)
            self.assertEqual(resumed.poll()[0]['content'], 'é')
            resumed.close()

    def test_rotation_restarts_from_beginning(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'chat.jsonl'
            path.write_text('{"id":"old"}\n')
            tail = ChatTail(str(path))
            self.assertEqual(tail.poll()[0]['id'], 'old')
            path.rename(Path(td)/'old.jsonl')
            path.write_text('{"id":"new"}\n')
            self.assertEqual(tail.poll()[0]['id'], 'new')
            tail.close()


if __name__ == '__main__':
    unittest.main()
