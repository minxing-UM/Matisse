"""Reentrant FIFO admission for foreground turns and opportunistic idle work."""

import threading
from collections import deque
from contextlib import contextmanager


class GenerationQueue:
    def __init__(self):
        self._condition = threading.Condition()
        self._waiting = deque()
        self._owner = None
        self._depth = 0
        self._kind = None

    def __enter__(self):
        identity = threading.get_ident()
        with self._condition:
            if self._owner == identity:
                self._depth += 1
                return self
            ticket = object()
            self._waiting.append(ticket)
            try:
                self._condition.wait_for(
                    lambda: self._owner is None and self._waiting[0] is ticket
                )
            except BaseException:
                self._waiting.remove(ticket)
                self._condition.notify_all()
                raise
            self._waiting.popleft()
            self._owner = identity
            self._depth = 1
            self._kind = "reply"
        return self

    def __exit__(self, *exc):
        self._release()

    def _release(self):
        with self._condition:
            if self._owner != threading.get_ident():
                raise RuntimeError("Generation queue released by a different thread.")
            self._depth -= 1
            if self._depth == 0:
                self._owner = None
                self._kind = None
                self._condition.notify_all()

    @contextmanager
    def background(self):
        """Never start another idle task ahead of a waiting user request."""
        with self._condition:
            admitted = self._owner is None and not self._waiting
            if admitted:
                self._owner = threading.get_ident()
                self._depth = 1
                self._kind = "thought"
        try:
            yield admitted
        finally:
            if admitted:
                self._release()

    def snapshot(self):
        with self._condition:
            return {"kind": self._kind, "waiting": len(self._waiting)}
