"""Tail a Kick-style chat.jsonl. Chat is data. Nothing here is executed."""
from __future__ import annotations

import os
from typing import Dict, Iterator, List, Optional, TextIO

from .sim import parse_chat_line


class ChatTail:
    def __init__(self, path: str) -> None:
        self.path = path
        self._fh: Optional[TextIO] = None
        self._inode: Optional[int] = None
        self._pos = 0

    def _open(self) -> None:
        fh = open(self.path, "r", encoding="utf-8")
        st = os.fstat(fh.fileno())
        self._fh = fh
        self._inode = st.st_ino
        if self._pos > st.st_size:
            self._pos = 0
        fh.seek(self._pos)

    def poll(self) -> List[Dict]:
        out: List[Dict] = []
        if not os.path.isfile(self.path):
            return out
        try:
            st = os.stat(self.path)
        except OSError:
            return out
        if self._fh is None or self._inode != st.st_ino:
            if self._fh is not None:
                try:
                    self._fh.close()
                except OSError:
                    pass
                self._fh = None
            try:
                self._open()
            except OSError:
                return out
        assert self._fh is not None
        while True:
            pos = self._fh.tell()
            line = self._fh.readline()
            if not line:
                self._fh.seek(pos)
                break
            if not line.endswith("\n"):
                self._fh.seek(pos)
                break
            self._pos = self._fh.tell()
            rec = parse_chat_line(line)
            if rec is not None:
                out.append(rec)
        return out

    def close(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None


def load_all(path: str) -> Iterator[Dict]:
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            rec = parse_chat_line(line)
            if rec is not None:
                yield rec
