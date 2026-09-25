"""stream.moderation - data package for the chat moderation pipeline (stream/chat_bridge.py).

Contents:
  blocklist.txt   one term per line ('#' comments); slurs, hate terms, sexual terms. ChatBridge matches
                  it against every message AND username on a leet-normalised lowercase form and
                  hot-reloads it within 5 s of a change. A text hit drops the message (and its vote or
                  idea); a username hit renders the user as "builder #N".

BLOCKLIST_PATH is the default path ChatBridge(blocklist_path=None) uses.
"""
from __future__ import annotations

import os

BLOCKLIST_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "blocklist.txt")

__all__ = ["BLOCKLIST_PATH"]
