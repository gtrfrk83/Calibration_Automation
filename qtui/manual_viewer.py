"""Show a manufacturer manual (PDF) inside the suite, at a chosen page.

    manual_viewer.open_manual(parent, pdf_path, page=14)    -> the viewer window (or None after handing the file to the system viewer)
    manual_viewer.open_for_model(parent, '5522A', page=14)  -> same, finding the PDF with manuals.find(); a message box says where to put manuals if none is found

QtPdf is an optional part of PySide6; where it is missing the file is opened in the computer's own PDF viewer (at the page when the viewer understands '#page=').
The viewer only reads the file."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget

import manuals

try:
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPdfWidgets import QPdfView
    HAVE_PDF = True
except ImportError:                                    # a PySide6 built without the PDF modules
    HAVE_PDF = False

_open: list = []                                       # keeps the windows alive


def have_pdf_viewer() -> bool:
    return HAVE_PDF


class ManualWindow(QMainWindow):
    def __init__(self, path, page=None, parent=None):
        super().__init__(parent)
        self.path = Path(path)
        self.setWindowTitle(f'Manual - {self.path.name}')
        self.resize(980, 860)
        self.doc = QPdfDocument(self)
        self.doc.load(str(self.path))
        self.view = QPdfView(self)
        self.view.setDocument(self.doc)
        self.view.setPageMode(QPdfView.PageMode.MultiPage)
        self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(6, 6, 6, 6)
        bar = QHBoxLayout()
        self.prev_b, self.next_b = QPushButton('< Previous'), QPushButton('Next >')
        self.spin = QSpinBox()
        self.spin.setMinimum(1)
        self.count_l = QLabel('')
        for w in (self.prev_b, self.spin, self.count_l, self.next_b):
            bar.addWidget(w)
        bar.addStretch(1)
        self.fit_b = QPushButton('Fit width')
        self.page_b = QPushButton('Fit page')
        bar.addWidget(self.fit_b)
        bar.addWidget(self.page_b)
        lay.addLayout(bar)
        lay.addWidget(self.view, 1)
        self.setCentralWidget(body)
        self.prev_b.clicked.connect(lambda: self.go(self.page() - 1))
        self.next_b.clicked.connect(lambda: self.go(self.page() + 1))
        self.spin.editingFinished.connect(lambda: self.go(self.spin.value()))
        self.fit_b.clicked.connect(lambda: self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth))
        self.page_b.clicked.connect(lambda: self.view.setZoomMode(QPdfView.ZoomMode.FitInView))
        self.view.pageNavigator().currentPageChanged.connect(self._shown)
        n = max(1, self.doc.pageCount())
        self.spin.setMaximum(n)
        self.count_l.setText(f'of {n}')
        self.go(page or 1)

    def page(self):
        return self.view.pageNavigator().currentPage() + 1

    def go(self, page):
        """Show 1-based `page` (kept inside the document)."""
        page = max(1, min(int(page), max(1, self.doc.pageCount())))
        self.view.pageNavigator().jump(page - 1, QPointF(0, 0), 0)
        self._shown(page - 1)

    def _shown(self, index):
        self.spin.blockSignals(True)
        self.spin.setValue(index + 1)
        self.spin.blockSignals(False)
        self.prev_b.setEnabled(index > 0)
        self.next_b.setEnabled(index + 1 < self.doc.pageCount())


def open_manual(parent, path, page=None):
    path = Path(path)
    if not path.is_file():
        QMessageBox.warning(parent, 'Manual', f'The manual file was not found:\n{path}')
        return None
    if not HAVE_PDF:
        url = QUrl.fromLocalFile(str(path))
        if page:
            url.setFragment(f'page={int(page)}')
        QDesktopServices.openUrl(url)
        return None
    win = ManualWindow(path, page, parent)
    _open.append(win)
    win.destroyed.connect(lambda _o=None, w=win: _open.remove(w) if w in _open else None)
    win.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    win.show()
    return win


def open_for_model(parent, model, page=None):
    found = manuals.find(model)
    if not found:
        where = '\n'.join(str(f) for f in manuals.folders())
        QMessageBox.information(parent, 'Manual', f'No manual for "{model}" was found.\n\nPut the PDF (file name containing the model number) in one of:\n{where}')
        return None
    return open_manual(parent, found[0], page)
