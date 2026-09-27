"""Tail a Kick-style chat.jsonl. Chat is data. Nothing here is executed."""
from __future__ import annotations

import os
from typing import Dict, Iterator, List, Optional, TextIO

from .sim import parse_chat_line


class ChatTail:
    def __init__(self, path: str, cursor: Optional[Dict] = None) -> None:
        self.path = path
        self._fh: Optional[TextIO] = None
        self._inode: Optional[int] = None
        self._pos = 0
        self._device: Optional[int] = None
        if cursor and cursor.get("path") == os.path.realpath(path):
            try:
                st = os.stat(path)
                offset = int(cursor["offset"])
                if (st.st_ino == cursor["inode"] and st.st_dev == cursor["device"]
                        and 0 <= offset <= st.st_size):
                    self._pos = offset
                    self._inode = st.st_ino
                    self._device = st.st_dev
            except (OSError, KeyError, TypeError, ValueError):
                pass

    def checkpoint(self) -> Dict:
        return {"path": os.path.realpath(self.path), "offset": self._pos,
                "inode": self._inode, "device": self._device}

    def _open(self) -> None:
        fh = open(self.path, "r", encoding="utf-8")
        st = os.fstat(fh.fileno())
        if self._inode is not None and (self._inode != st.st_ino or self._device != st.st_dev):
            self._pos = 0
        self._fh = fh
        self._inode = st.st_ino
        self._device = st.st_dev
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
        if st.st_size < self._pos:
            self._fh.seek(0)
            self._pos = 0
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
