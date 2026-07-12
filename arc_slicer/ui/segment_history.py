from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
import weakref

try:
    from PyQt6.QtGui import QUndoCommand, QUndoStack
except ImportError:  # Supports the project's deliberately small headless Qt surface.
    class QUndoCommand:
        def __init__(self, text: str = ""):
            self._text = text

    class QUndoStack:
        def __init__(self, _parent=None):
            self._commands = []
            self._index = 0
            self._clean_index = 0
            self._limit = 0

        def setUndoLimit(self, limit): self._limit = int(limit)
        def undoLimit(self): return self._limit
        def clear(self): self._commands = []; self._index = 0; self._clean_index = 0
        def setClean(self): self._clean_index = self._index
        def isClean(self): return self._clean_index == self._index
        def canUndo(self): return self._index > 0
        def canRedo(self): return self._index < len(self._commands)
        def count(self): return len(self._commands)
        def index(self): return self._index
        def push(self, command):
            del self._commands[self._index:]
            self._commands.append(command)
            self._index += 1
            if self._limit and len(self._commands) > self._limit:
                self._commands.pop(0); self._index -= 1
            command.redo()
        def undo(self):
            if self.canUndo(): self._index -= 1; self._commands[self._index].undo()
        def redo(self):
            if self.canRedo(): self._commands[self._index].redo(); self._index += 1


@dataclass(frozen=True)
class SegmentHistoryItem:
    uid: str
    created_order: int
    start_text: str
    end_text: str
    speed_override_text: str
    link_group_id: str | None


@dataclass(frozen=True)
class SegmentHistoryState:
    source_key: str
    rows: tuple[SegmentHistoryItem, ...]
    selected_uid: str


class SegmentSnapshotCommand(QUndoCommand):
    def __init__(
        self,
        text: str,
        before: SegmentHistoryState,
        after: SegmentHistoryState,
        restore: Callable[[SegmentHistoryState], None],
    ):
        super().__init__(text)
        self.before = before
        self.after = after
        self._restore_ref = weakref.WeakMethod(restore) if hasattr(restore, "__self__") else None
        self._restore = restore if self._restore_ref is None else None
        self._skip_first_redo = True

    def _apply(self, state: SegmentHistoryState) -> None:
        callback = self._restore_ref() if self._restore_ref is not None else self._restore
        if callback is not None:
            callback(state)

    def undo(self) -> None:
        self._apply(self.before)

    def redo(self) -> None:
        if self._skip_first_redo:
            self._skip_first_redo = False
            return
        self._apply(self.after)
