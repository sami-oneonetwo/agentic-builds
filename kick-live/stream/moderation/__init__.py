"""stream.moderation - data package for the chat moderation pipeline (stream/chat_bridge.py).

Contents:
  blocklist.txt   one term per line ('#' comments); slurs, hate terms, sexual terms. ChatBridge matches
                  it against every message AND username on a leet-normalised lowercase form and
                  hot-reloads it within 5 s of a change. A text hit drops the message (and its vote or
                  idea) and is one strike (three burrow the pip for the session, WORLD.md 11.5); a
                  username hit renders the user as "builder #N".
  allowlist.txt   the dictionary allowlist (WORLD.md 11.3; the spec's `allowlist_words.txt`): plain
                  English plus the channel's harmless slang and the Hollow's own words. A word a pip
                  repeats UNPROMPTED (top words, learned words, teach) must be here AND pass the
                  blocklist: stream.chat_bridge.word_ok(word) / filter_words(words). Hot-reloaded like
                  the blocklist. Nicknames and the owner's own bubbles do not need it.

BLOCKLIST_PATH / ALLOWLIST_PATH are the defaults ChatBridge(blocklist_path=None, allowlist_path=None) uses.
"""
from __future__ import annotations

import os

BLOCKLIST_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blocklist.txt")
ALLOWLIST_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "allowlist.txt")

__all__ = ["BLOCKLIST_PATH", "ALLOWLIST_PATH"]
