"""Undo/redo history for annotation operations only.

Actions are plain dicts so they serialise trivially and stay decoupled from
the widgets.  Supported kinds:

    add     {ann}                     - object was added to the store
    remove  {index, ann}              - object was removed
    move    {ann_id, dx, dy}          - object translated by (dx, dy)
    clear   {items:[(index, ann)]}    - everything cleared at once
"""

import logging

log = logging.getLogger(__name__)


class History:
    def __init__(self, store, on_change=None):
        self.store = store
        self.on_change = on_change  # callback(region=None) after each change
        self._undo_stack = []
        self._redo_stack = []

    # -------------------------------------------------------------- helpers
    def _notify(self):
        if self.on_change:
            self.on_change(None)

    def push(self, action):
        self._undo_stack.append(action)
        self._redo_stack.clear()

    def clear(self):
        self._undo_stack.clear()
        self._redo_stack.clear()

    @property
    def can_undo(self):
        return bool(self._undo_stack)

    @property
    def can_redo(self):
        return bool(self._redo_stack)

    # ----------------------------------------------------------------- undo
    def undo(self):
        if not self._undo_stack:
            return False
        action = self._undo_stack.pop()
        kind = action["kind"]
        if kind == "add":
            self.store.remove(self.store.find(action["ann"].id))
        elif kind == "remove":
            self.store.insert(action["index"], action["ann"])
        elif kind == "move":
            ann = self.store.find(action["ann_id"])
            if ann:
                ann.translate(-action["dx"], -action["dy"])
        elif kind == "clear":
            for index, ann in sorted(action["items"], key=lambda t: t[0]):
                self.store.insert(index, ann)
        log.debug("Undo %s", kind)
        self._redo_stack.append(action)
        self._notify()
        return True

    # ----------------------------------------------------------------- redo
    def redo(self):
        if not self._redo_stack:
            return False
        action = self._redo_stack.pop()
        kind = action["kind"]
        if kind == "add":
            self.store.add(action["ann"])
        elif kind == "remove":
            # Undo re-inserted the object, so it is present again.
            self.store.remove(action["ann"])
        elif kind == "move":
            ann = self.store.find(action["ann_id"])
            if ann:
                ann.translate(action["dx"], action["dy"])
        elif kind == "clear":
            action["items"] = list(enumerate(self.store.items))
            self.store.clear()
        log.debug("Redo %s", kind)
        self._undo_stack.append(action)
        self._notify()
        return True

    # ------------------------------------------------------- action factory
    def push_add(self, ann):
        self.push({"kind": "add", "ann": ann})

    def push_remove(self, ann):
        try:
            index = self.store.items.index(ann)
        except ValueError:
            return
        self.push({"kind": "remove", "index": index, "ann": ann})

    def push_move(self, ann, dx, dy):
        self.push({"kind": "move", "ann_id": ann.id, "dx": dx, "dy": dy})

    def push_clear(self):
        if not self.store.items:
            return
        self.push({"kind": "clear", "items": list(enumerate(self.store.items))})
