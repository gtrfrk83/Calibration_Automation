"""Width sharing for the table screens of the data views (the idea of `_ShareWidth` in manager.py): a wide window must not become one huge stretch column
with the other columns pushed to the far right."""
from PySide6.QtCore import QEvent, QObject, QTimer


class ShareWidth(QObject):
    """A wide window shares the width beyond the columns' base widths between them in proportion to `weights` (a spec grid in a 1920 px window is not
    a few narrow columns with an empty stretch column on the right).  Below the base width nothing changes (the grid scrolls)."""
    def __init__(self, table, base, weights):
        super().__init__(table)
        self.table, self.base, self.weights = table, list(base), list(weights)
        table.viewport().installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self.apply)
        return False

    def apply(self):
        try:
            hh = self.table.horizontalHeader()
            extra = max(0, self.table.viewport().width() - sum(self.base) - 4)
            tot = sum(self.weights) or 1
            for i, (w, k) in enumerate(zip(self.base, self.weights)):
                if i < hh.count():
                    hh.resizeSection(i, int(w + extra * k / tot))
        except RuntimeError:
            pass                                                   # the table went away
