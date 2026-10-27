"""Procedure Generator, the table-review workspace (Qt): choose the pages of the verification tables, read them with Claude (or type rows), and check EVERY row against the
rendered page image before anything is built.

    ReviewPage(store, project, parent=None)        signals: backRequested(), changed()
        left   a zoomable page image (the rendered PNG, never extracted text), page paging, zoom buttons, Ctrl+wheel
        right  the candidate rows (accept / edit / reject), their flags, the 'I have checked this page' tick

All the rules (what a flag is, when a page counts as checked, what Build needs) are in procedure_generator.py; this file only shows and collects.  The API call is made by
procedure_generator_ai.extract in a worker thread; tests set `run_sync` and give a `client_factory`.
Dialogs go through the module functions below (a test replaces them)."""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel, QListWidget, QListWidgetItem, QScrollArea, QSpinBox, QSplitter,
                               QStyledItemDelegate, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

import procedure_generator as pg
import procedure_generator_ai as ai

from .. import theme
from ..theme import M
from ..widgets import Badge, Banner, GhostButton, MessageDialog, PrimaryButton, SecondaryButton, label

COLUMNS = (('status', 'Use'), ('page', 'Page'), ('step', 'Step'), ('function', 'Function'), ('section', 'Section'), ('range', 'Range'), ('nominal', 'Nominal'),
           ('frequency', 'Frequency'), ('level', 'Level'), ('low', 'Low limit'), ('high', 'High limit'), ('accuracy', 'Accuracy'), ('tc_type', 'TC'), ('flags', 'Flags / notes'))
EDITABLE = {'page', 'step', 'function', 'section', 'range', 'nominal', 'frequency', 'level', 'low', 'high', 'accuracy', 'tc_type'}
STATUS_TEXT = {pg.STATUS_CANDIDATE: 'Undecided', pg.STATUS_ACCEPTED: 'Accepted', pg.STATUS_EDITED: 'Edited', pg.STATUS_REJECTED: 'Rejected'}
THUMBS = 12


def _info(parent, title, text):
    MessageDialog(parent, 'info', title, text).run()


def _error(parent, title, text):
    MessageDialog(parent, 'error', title, text).run()


def _ask(parent, title, text, yes='Yes', no='Cancel') -> bool:
    return MessageDialog(parent, 'question', title, text, buttons=((no, 'no', None), (yes, 'yes', 'primary')), cancel_key='no').run() == 'yes'


class ImageViewer(QWidget):
    """A page image with zoom (buttons, Ctrl+wheel) and paging.  The image is the rendered PNG of the page."""
    pageRequested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(M.sm)
        bar = QHBoxLayout()
        self.prev_btn = SecondaryButton('Prev', on_click=lambda: self.pageRequested.emit(self.page - 1))
        self.next_btn = SecondaryButton('Next', on_click=lambda: self.pageRequested.emit(self.page + 1))
        self.title = label('', 'section')
        self.zoom_out_btn = SecondaryButton('-', on_click=lambda: self.set_zoom(self.zoom / 1.25))
        self.zoom_in_btn = SecondaryButton('+', on_click=lambda: self.set_zoom(self.zoom * 1.25))
        self.fit_btn = SecondaryButton('Fit width', on_click=self.fit_width)
        self.zoom_label = label('100 %', 'hint')
        for w in (self.prev_btn, self.next_btn, self.title):
            bar.addWidget(w)
        bar.addStretch(1)
        for w in (self.zoom_out_btn, self.zoom_label, self.zoom_in_btn, self.fit_btn):
            bar.addWidget(w)
        lay.addLayout(bar)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(False)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image = QLabel()
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll.setWidget(self.image)
        self.scroll.viewport().installEventFilter(self)
        lay.addWidget(self.scroll, 1)
        self.page, self.zoom, self._pix, self.path, self.pages = 0, 1.0, None, None, 0

    def eventFilter(self, obj, ev):
        if obj is self.scroll.viewport() and ev.type() == ev.Type.Wheel and ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.set_zoom(self.zoom * (1.15 if ev.angleDelta().y() > 0 else 1 / 1.15))
            return True
        return super().eventFilter(obj, ev)

    def show_page(self, path, page: int, pages: int, title: str = ''):
        self.page, self.pages, self.path = page, pages, path
        self._pix = QPixmap(str(path)) if path else None
        self.title.setText(title or f'Page {page}' + (f' of {pages}' if pages else ''))
        self.prev_btn.setEnabled(page > 1)
        self.next_btn.setEnabled(bool(pages) and page < pages)
        if self._pix is None or self._pix.isNull():
            self.image.setText('No page image')
            self.image.setPixmap(QPixmap())
            self.image.adjustSize()
            return
        self.fit_width()

    def fit_width(self):
        if self._pix is None or self._pix.isNull():
            return
        avail = max(200, self.scroll.viewport().width() - 4)
        self.set_zoom(avail / self._pix.width() if self._pix.width() else 1.0)

    def set_zoom(self, z: float):
        self.zoom = max(0.1, min(4.0, z))
        self.zoom_label.setText(f'{round(self.zoom * 100)} %')
        if self._pix is not None and not self._pix.isNull():
            scaled = self._pix.scaled(int(self._pix.width() * self.zoom), int(self._pix.height() * self.zoom), Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation)
            self.image.setPixmap(scaled)
            self.image.resize(scaled.size())


class FunctionDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        box = QComboBox(parent)
        box.addItems(list(pg.GEN_KINDS))
        return box

    def setEditorData(self, editor, index):
        i = editor.findText(index.data() or '')
        editor.setCurrentIndex(max(0, i))

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText())


class _Done(QObject):
    finished = Signal(object, object)             # (ExtractResult | None, error text)


class ReviewPage(QWidget):
    backRequested = Signal()
    changed = Signal()

    def __init__(self, store: pg.Store, project: pg.Project, parent=None, client_factory=None, sleep=None):
        super().__init__(parent)
        self.store, self.p = store, project
        self.client_factory, self.sleep = client_factory, sleep
        self.run_sync = False
        self._building = False
        self._busy = False
        self.fid = ''
        self.view_page = 1
        self.thumb_start = 1
        self._done = _Done(self)
        self._done.finished.connect(self._reading_finished)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(M.md)
        # ---- top bars (two short rows so the page never forces the window wider)
        top = QHBoxLayout()
        self.back_btn = GhostButton('Back to the project', on_click=self.backRequested.emit)
        top.addWidget(self.back_btn)
        top.addWidget(label('Manual', 'kvkey'))
        self.file_box = QComboBox()
        self.file_box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.file_box.setMinimumContentsLength(12)
        self.file_box.currentIndexChanged.connect(self._file_changed)
        top.addWidget(self.file_box, 1)
        root.addLayout(top)
        top2 = QHBoxLayout()
        top2.addWidget(label('Table pages  from', 'kvkey'))
        self.first_spin = QSpinBox()
        self.last_spin = QSpinBox()
        for s in (self.first_spin, self.last_spin):
            s.setRange(1, 99999)
        top2.addWidget(self.first_spin)
        top2.addWidget(label('to', 'kvkey'))
        top2.addWidget(self.last_spin)
        self.use_btn = SecondaryButton('Use these pages', on_click=self.use_pages)
        top2.addWidget(self.use_btn)
        top2.addStretch(1)
        self.read_btn = PrimaryButton('Read the pages with Claude', on_click=self.read_pages)
        top2.addWidget(self.read_btn)
        root.addLayout(top2)
        self.notice = Banner('', 'info')
        self.notice.hide()
        root.addWidget(self.notice)
        # ---- page thumbnails
        strip = QHBoxLayout()
        self.thumb_prev = SecondaryButton('<', on_click=lambda: self._thumbs_go(-THUMBS))
        self.thumb_next = SecondaryButton('>', on_click=lambda: self._thumbs_go(THUMBS))
        self.thumb_range = label('', 'hint')
        self.goto_spin = QSpinBox()
        self.goto_spin.setRange(1, 99999)
        self.goto_btn = SecondaryButton('Go to page', on_click=lambda: self.show_page(self.goto_spin.value(), jump=True))
        for w in (self.thumb_prev, self.thumb_next, self.thumb_range):
            strip.addWidget(w)
        strip.addStretch(1)
        strip.addWidget(self.goto_spin)
        strip.addWidget(self.goto_btn)
        root.addLayout(strip)
        self.thumbs = QListWidget()
        self.thumbs.setViewMode(QListWidget.ViewMode.IconMode)
        self.thumbs.setFlow(QListWidget.Flow.LeftToRight)
        self.thumbs.setWrapping(False)
        self.thumbs.setMovement(QListWidget.Movement.Static)
        self.thumbs.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.thumbs.setIconSize(QSize(72, 92))
        self.thumbs.setFixedHeight(92 + M.font_base * 3 + 18)
        self.thumbs.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.thumbs.itemClicked.connect(lambda it: self.show_page(int(it.data(Qt.ItemDataRole.UserRole)), jump=True))
        root.addWidget(self.thumbs)
        # ---- viewer | rows
        split = QSplitter(Qt.Orientation.Horizontal)
        self.viewer = ImageViewer()
        self.viewer.pageRequested.connect(lambda n: self.show_page(n, jump=True))
        split.addWidget(self.viewer)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(M.sm)
        self.rows_title = label('Rows read from the pages', 'section')
        rl.addWidget(self.rows_title)
        bar = QHBoxLayout()
        self.accept_btn = SecondaryButton('Accept', on_click=lambda: self._decide(pg.STATUS_ACCEPTED))
        self.reject_btn = SecondaryButton('Reject', on_click=lambda: self._decide(pg.STATUS_REJECTED))
        self.add_btn = SecondaryButton('Add row', on_click=self.add_row)
        self.del_btn = SecondaryButton('Delete row', on_click=self.delete_rows)
        self.accept_btn.setToolTip('Accept the selected rows (you have checked them against the page image)')
        self.reject_btn.setToolTip('Reject the selected rows: they are left out of the procedure')
        self.add_btn.setToolTip('Type a row by hand (it needs the page it comes from)')
        self.del_btn.setToolTip('Delete a row you typed by hand (a row the reader returned is rejected, not deleted)')
        for w in (self.accept_btn, self.reject_btn, self.add_btn, self.del_btn):
            bar.addWidget(w)
        bar.addStretch(1)
        rl.addLayout(bar)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([t for _k, t in COLUMNS])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed | QAbstractItemView.EditTrigger.AnyKeyPressed)
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.setItemDelegateForColumn(3, FunctionDelegate(self.table))
        self.table.itemChanged.connect(self._cell_changed)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        rl.addWidget(self.table, 1)
        self.check_box = QCheckBox('')
        self.check_box.toggled.connect(self._check_toggled)
        rl.addWidget(self.check_box)
        self.summary = label('', 'hint', wrap=True)
        rl.addWidget(self.summary)
        rl.addWidget(label('Not verified (carried into the procedure)', 'section'))
        self.unverified = QListWidget()
        self.unverified.setMaximumHeight(M.row_h * 3)
        self.table.setMinimumWidth(0)
        self.viewer.setMinimumWidth(0)
        right.setMinimumWidth(0)
        rl.addWidget(self.unverified)
        split.addWidget(right)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        root.addWidget(split, 1)
        self.set_project(project)

    # ------------------------------------------------------------------ project / files
    def set_project(self, project: pg.Project):
        self.p = project
        self._building = True
        self.file_box.clear()
        for f in project.files_of(pg.ROLE_SPEC):
            self.file_box.addItem(f'{f.original}  ({f.pages} pages)' if f.pages else f.original, f.id)
        self._building = False
        self._file_changed()

    def _spec_file(self):
        return self.p.file(self.fid) if self.fid else None

    def _file_changed(self, *_):
        if self._building:
            return
        self.fid = self.file_box.currentData() or ''
        f = self._spec_file()
        total = f.pages if f and f.pages else 99999
        for s in (self.first_spin, self.last_spin, self.goto_spin):
            s.setMaximum(total)
        sel = self.p.pages.get(self.fid)
        self.first_spin.setValue(sel[0] if sel else 1)
        self.last_spin.setValue(sel[1] if sel else min(total, 1))
        self.thumb_start = (sel[0] if sel else 1)
        self.view_page = sel[0] if sel else 1
        self.read_btn.setEnabled(bool(f))
        self.use_btn.setEnabled(bool(f))
        self.refresh()

    # ------------------------------------------------------------------ pages
    def use_pages(self):
        f = self._spec_file()
        if f is None:
            return
        try:
            pg.set_pages(self.p, self.fid, self.first_spin.value(), self.last_spin.value())
        except ValueError as exc:
            _error(self, 'Table pages', str(exc))
            return
        self.store.save(self.p)
        self.notify(f'Table pages {self.first_spin.value()}-{self.last_spin.value()} of {f.original} chosen.')
        self.refresh()
        self.changed.emit()

    def _thumbs_go(self, delta):
        f = self._spec_file()
        total = f.pages if f and f.pages else 99999
        self.thumb_start = max(1, min(max(1, total - THUMBS + 1), self.thumb_start + delta))
        self._fill_thumbs()

    def _fill_thumbs(self):
        f = self._spec_file()
        self.thumbs.clear()
        if f is None:
            self.thumb_range.setText('')
            return
        total = f.pages or self.thumb_start + THUMBS - 1
        last = min(total, self.thumb_start + THUMBS - 1)
        sel = self.p.pages.get(self.fid)
        for n in range(self.thumb_start, last + 1):
            try:
                png = ai.page_png(self.store, self.p, self.fid, n, 36)
                icon = QIcon(QPixmap(str(png)).scaled(72, 92, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            except ai.RenderError as exc:
                icon = QIcon()
                self.notify(str(exc), 'warn')
            used = bool(sel and sel[0] <= n <= sel[1])
            it = QListWidgetItem(icon, f'p. {n}' + ('  (table)' if used else ''))
            it.setData(Qt.ItemDataRole.UserRole, n)
            it.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            if used:
                it.setForeground(QBrush(QColor(theme.tokens()['good'])))
            if n == self.view_page:
                it.setSelected(True)
            self.thumbs.addItem(it)
        self.thumb_range.setText(f'Pages {self.thumb_start}-{last}' + (f' of {f.pages}' if f.pages else ''))
        self.thumb_prev.setEnabled(self.thumb_start > 1)
        self.thumb_next.setEnabled(bool(f.pages) and last < f.pages)

    def show_page(self, n: int, jump=False):
        f = self._spec_file()
        if f is None:
            self.viewer.show_page(None, 0, 0)
            return
        n = max(1, min(n, f.pages or n))
        self.view_page = n
        if jump and not (self.thumb_start <= n < self.thumb_start + THUMBS):
            self.thumb_start = n
            self._fill_thumbs()
        try:
            png = ai.page_png(self.store, self.p, self.fid, n, ai.load_settings()['dpi'])
        except ai.RenderError as exc:
            self.viewer.show_page(None, n, f.pages, f'Page {n}')
            self.notify(str(exc), 'warn')
            return
        self.viewer.show_page(png, n, f.pages)
        self._sync_check()

    # ------------------------------------------------------------------ the rows
    def _rows(self):
        return [r for r in self.p.rows if not self.fid or r.file_id in ('', self.fid)]

    def refresh(self):
        self._fill_thumbs()
        self.show_page(self.view_page)
        self.fill_table()

    def _flag_text(self, r: pg.Row) -> str:
        flags = pg.validate_row(r, self.p)
        bits = [('ERROR: ' if f.level == 'error' else 'check: ') + f.text for f in flags]
        return ' | '.join(bits)

    def fill_table(self):
        self._building = True
        rows = self._rows()
        self.table.setRowCount(len(rows))
        t = theme.tokens()
        for i, r in enumerate(rows):
            flags = pg.validate_row(r, self.p)
            worst = 'bad' if any(f.level == 'error' for f in flags) else ('warn' if flags else 'good')
            for c, (key, _title) in enumerate(COLUMNS):
                if key == 'status':
                    text = STATUS_TEXT[r.status]
                elif key == 'page':
                    text = str(r.page or '')
                elif key == 'flags':
                    text = self._flag_text(r)
                else:
                    text = getattr(r, key)
                it = QTableWidgetItem(text)
                it.setData(Qt.ItemDataRole.UserRole, r.id)
                if key not in EDITABLE:
                    it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if r.status == pg.STATUS_REJECTED:
                    it.setForeground(QBrush(QColor(t['muted'])))
                elif key in ('status', 'flags'):
                    it.setForeground(QBrush(QColor(t[worst if r.status != pg.STATUS_CANDIDATE or worst != 'good' else 'muted'])))
                if key == 'flags':
                    it.setToolTip(text)
                if r.model_values and key in r.model_values and r.model_values[key] != getattr(r, key):
                    it.setToolTip(f'The reader returned: {r.model_values[key] or "(empty)"}')
                self.table.setItem(i, c, it)
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(len(COLUMNS) - 1, max(self.table.columnWidth(len(COLUMNS) - 1), 220))
        self._building = False
        self._update_summary()

    def _selected_ids(self):
        ids = []
        for idx in self.table.selectionModel().selectedRows():
            it = self.table.item(idx.row(), 0)
            if it is not None:
                ids.append(it.data(Qt.ItemDataRole.UserRole))
        return ids

    def _selection_changed(self):
        ids = self._selected_ids()
        if len(ids) == 1:
            r = self.p.row(ids[0])
            if r is not None and r.file_id == self.fid and r.page and r.page != self.view_page:
                self.show_page(r.page, jump=True)

    def _cell_changed(self, item):
        if self._building:
            return
        rid = item.data(Qt.ItemDataRole.UserRole)
        key = COLUMNS[item.column()][0]
        if key not in EDITABLE:
            return
        text = item.text().strip()
        try:
            pg.edit_row(self.p, rid, **{key: int(text) if key == 'page' and text.isdigit() else (0 if key == 'page' else text)})
        except KeyError:
            return
        self.store.save(self.p)
        self.fill_table()
        self._sync_check()
        self.changed.emit()

    def _decide(self, status):
        ids = self._selected_ids()
        if not ids:
            self.notify('Select one or more rows first.', 'warn')
            return
        for rid in ids:
            pg.set_status(self.p, rid, status)
        self.store.save(self.p)
        self.fill_table()
        self._sync_check()
        self.changed.emit()

    def add_row(self):
        f = self._spec_file()
        if f is None:
            self.notify('Upload a spec sheet or manual first.', 'warn')
            return
        page = self.view_page
        r = pg.Row('', file_id=self.fid, page=page, source='typed', status=pg.STATUS_CANDIDATE, function='DCV')
        pg.add_rows(self.p, [r])
        self.store.save(self.p)
        self.fill_table()
        self.table.selectRow(self.table.rowCount() - 1)
        self.changed.emit()

    def delete_rows(self):
        ids = [i for i in self._selected_ids() if (self.p.row(i) and self.p.row(i).source == 'typed')]
        if not ids:
            self.notify('Only rows typed by hand can be deleted; reject a row the reader returned.', 'warn')
            return
        self.p.rows = [r for r in self.p.rows if r.id not in ids]
        self.store.save(self.p)
        self.fill_table()
        self.changed.emit()

    # ------------------------------------------------------------------ the page check
    def _page_key(self):
        return f'{self.fid}:{self.view_page}'

    def _sync_check(self):
        n = self.view_page
        has_rows = any(r.file_id == self.fid and r.page == n and r.status in pg.IN_PROCEDURE for r in self.p.rows)
        self._building = True
        self.check_box.setText(f'I have checked every accepted number on page {n} against the page image.')
        self.check_box.setEnabled(has_rows)
        self.check_box.setChecked(self._page_key() in self.p.checked)
        self.check_box.setToolTip('' if has_rows else 'This page has no accepted rows.')
        self._building = False

    def _check_toggled(self, on):
        if self._building:
            return
        pg.confirm_page(self.p, self.fid, self.view_page, on)
        self.store.save(self.p)
        self._update_summary()
        self.changed.emit()

    # ------------------------------------------------------------------ summary
    def _update_summary(self):
        p = self.p
        count = {s: sum(1 for r in p.rows if r.status == s) for s in pg.STATUSES}
        need = sorted({pg.row_page_key(r) for r in pg.in_procedure(p)})
        done = [k for k in need if k in set(p.checked)]
        self.summary.setText(f'{len(p.rows)} row(s): {count[pg.STATUS_ACCEPTED]} accepted, {count[pg.STATUS_EDITED]} edited, {count[pg.STATUS_REJECTED]} rejected, '
                             f'{count[pg.STATUS_CANDIDATE]} undecided.  Pages checked against the image: {len(done)} of {len(need)}.')
        self.unverified.clear()
        for line in pg.unverified_list(p):
            self.unverified.addItem(line)
        if not p.rows:
            self.unverified.addItem('(nothing yet)')
        g = pg.gate(p)
        self.rows_title.setText('Rows read from the pages' + ('' if g.stage not in ('ready',) else '  -  ready to build'))

    def notify(self, text, kind='info'):
        self.notice.set_kind({'bad': 'error'}.get(kind, kind))
        self.notice.text_label.setTextFormat(Qt.TextFormat.PlainText)          # text from the API or a file name is never read as HTML
        self.notice.set_text(text)
        self.notice.setVisible(bool(text))

    # ------------------------------------------------------------------ reading with Claude
    def read_pages(self):
        f = self._spec_file()
        if f is None:
            return
        sel = self.p.pages.get(self.fid)
        if not sel:
            self.notify('Choose the table pages first (From / To, then "Use these pages").', 'warn')
            return
        if self._busy:
            return
        if not ai.get_key():
            self.notify('No API key. Add one in Settings (or set ANTHROPIC_API_KEY). You can still type the rows by hand with "Add row by hand".', 'warn')
            return
        n = sel[1] - sel[0] + 1
        settings = ai.load_settings()
        if not _ask(self, 'Read the pages with Claude',
                    f'The {n} page image(s) ({sel[0]}-{sel[1]}) of "{f.original}" will be sent to the Claude API ({settings["model"]}) to be read into rows. '
                    'Only the page images are sent. Every row still has to be checked by you against the page before a procedure can be built.',
                    yes='Send and read', no='Cancel'):
            return
        self._busy = True
        self.read_btn.setEnabled(False)
        self.notify(f'Reading {n} page(s) ... this can take a minute.', 'info')
        fid, first, last = self.fid, sel[0], sel[1]

        def work():
            try:
                res = ai.extract(self.store, self.p, fid, first, last, client_factory=self.client_factory, **({'sleep': self.sleep} if self.sleep else {}), settings=settings)
                self._done.finished.emit(res, '')
            except ai.ExtractError as exc:
                self._done.finished.emit(None, ai.scrub(str(exc)))
            except Exception as exc:                                # never lose the window to a bug in the call
                self._done.finished.emit(None, ai.scrub(f'{type(exc).__name__}: {exc}'))
        self._job = (fid, first, last)
        if self.run_sync:
            work()
        else:
            threading.Thread(target=work, daemon=True).start()

    def _reading_finished(self, res, error):
        self._busy = False
        self.read_btn.setEnabled(True)
        fid, first, last = self._job
        if error:
            self.notify(error, 'error')
            return
        added = pg.add_rows(self.p, res.rows, replace_model_rows_of=(fid, first, last))
        self.p.extraction = dict(model=res.model, at=pg._now(), pages=[first, last], rows=len(added), requests=res.requests, attempts=res.attempts,
                                 input_tokens=res.input_tokens, output_tokens=res.output_tokens, notes=res.notes[:5])
        self.store.save(self.p)
        self.fill_table()
        self._sync_check()
        self.notify(f'{len(added)} row(s) read from pages {first}-{last}. Nothing is accepted yet: check each row against the page image.' + (' ' + ' '.join(res.notes[:1]) if res.notes else ''), 'info')
        self.changed.emit()
