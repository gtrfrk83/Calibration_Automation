"""Standards Specs panel (Qt twin of specmanager_ui.SpecManagerPanel).

Layout (Option A of the Standards Specs study, as the Tk panel): a standards rail on the left (one card per standard), a header card for the selected
standard on the right (confidence, divisor, period, ranges, assets, approval, sheet issues, actions) and a card with the function-type chips and the table
of ranges.  Presentation only: the stored rows, the printed sheet text, the limits and the uncertainty numbers are untouched; the text of a specification is
formatted for display by the toolkit-free specmanager_view and the printed text is the tooltip of the cell.

    StandardsSpecsPanel(parent)     # the Tk SpecManagerPanel(parent); alias SpecManagerPanel

The data work is specmanager.py (database), specmanager_view.py (display model) and uncertainty_budget.py (Check an EMU), all REUSED.  Dialogs and file pickers
go through the spec_editor module functions (ask_string / show_error / ask_open_path / ask_save_path) so a test can drive them.
"""
from __future__ import annotations

import json

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLayout, QLayoutItem, QLineEdit, QMenu, QPlainTextEdit,
                               QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

import specmanager as sm
import specmanager_view as view
import emu_check_model as emu
import uncertainty_budget as ub
from qtui import theme
from qtui.screens import spec_editor as sed
from qtui.theme import M
from qtui.widgets import Badge, GhostButton, ModalDialog, PrimaryButton, SearchField, SecondaryButton, SegmentedFilter, label, rule

KINDS = ['', 'DCV', 'ACV', 'DCI', 'ACI', 'OHM', 'CAP', 'IND', 'COND', 'FREQ', 'TEMP', 'POWDC', 'POWAC', 'PHASE']
UNITS = {'DCV': 'V', 'ACV': 'V', 'DCI': 'A', 'ACI': 'A', 'OHM': 'ohm', 'OHM2': 'ohm', 'OHM4': 'ohm', 'CAP': 'F', 'FREQ': 'Hz'}
HINT = 'Double-click a row to set its calibrator resolution'
PLACEHOLDER = 'Filter by function / text'
PERIOD_IDS = ('p1', 'p2', 'p3')
COLUMN_KEYS = ('range', 'span', 'freq', 'res') + PERIOD_IDS          # tree columns 0..6; the tooltips use these names


# ------------------------------------------------------------------------------------------------------------------------ small building blocks
def _discard(w: QWidget) -> None:
    """Remove a widget now (deleteLater alone leaves it painted until the event loop runs)."""
    w.hide()
    w.setParent(None)
    w.deleteLater()


class FlowLayout(QLayout):
    """A row of widgets that wraps onto more lines when it is narrower than they are."""

    def __init__(self, parent=None, hgap=M.sm - 2, vgap=M.sm - 2):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self.hgap, self.vgap = hgap, vgap
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return s + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do(self, rect, test):
        m = self.contentsMargins()
        x0, y = rect.x() + m.left(), rect.y() + m.top()
        right = rect.right() - m.right()
        rows, row, x = [], [], x0
        for it in self._items:
            if it.widget() is not None and it.widget().isHidden():
                continue
            sh = it.sizeHint()
            if row and x + sh.width() > right:
                rows.append(row)
                row, x = [], x0
            row.append((it, x, sh))
            x += sh.width() + self.hgap
        if row:
            rows.append(row)
        for row in rows:
            row_h = max(sh.height() for _it, _x, sh in row)
            if not test:
                for it, rx, sh in row:
                    it.setGeometry(QRect(QPoint(rx, y + (row_h - sh.height()) // 2), sh))
            y += row_h + self.vgap
        return (y - self.vgap if rows else y) - rect.y() + m.bottom()

    def clear(self):
        while self._items:
            it = self._items.pop()
            if it.widget() is not None:
                _discard(it.widget())


class ElidedLabel(QLabel):
    """A one-line label that cuts its text with an ellipsis to its width (the full text stays in `full` and in the tooltip when cut)."""

    def __init__(self, text='', role=None, parent=None):
        super().__init__('', parent)
        if role:
            self.setProperty('role', role)
        self.full = text
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(10)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.set_full(text)

    def set_full(self, text):
        self.full = text
        self._cut()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._cut()

    def _cut(self):
        w = self.width()
        if w < 20:
            self.setText(self.full)
            return
        self.setText(view.ellipsize(self.full, w - 2, QFontMetrics(self.font()).horizontalAdvance))

    def sizeHint(self):
        return QSize(QFontMetrics(self.font()).horizontalAdvance(self.full) + 2, super().sizeHint().height())


class Link(QPushButton):
    """Text link (accent colour, underlined on hover, Enter / Space work)."""

    def __init__(self, text, command=None, parent=None):
        super().__init__(text, parent)
        self.setProperty('role', 'ghost')
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self.setAutoDefault(False)
        if command:
            self.clicked.connect(lambda _c=False: command())


class IssuesChip(QAbstractButton):
    """The clickable pill in the header: a dot, '12 sheet issues  ›', colour by the worst issue (good / warn / bad)."""

    def __init__(self, text, kind, command, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.kind = kind if kind in theme.KINDS else 'neutral'
        self.dot = True
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedHeight(M.badge_h)
        self.clicked.connect(lambda _c=False: command())

    def sizeHint(self):
        return QSize(QFontMetrics(self.font()).horizontalAdvance(self.text()) + 38, M.badge_h)

    def paintEvent(self, ev):
        t = theme.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(0, 0, -1, -1)
        hover = self.underMouse()
        fill = t[self.kind + '_dot'] if hover and self.kind != 'neutral' else t[self.kind + '_bg']
        fg = t['on_primary'] if hover and self.kind != 'neutral' else t[self.kind]
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(fill))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.setBrush(QColor(fg if hover else t[self.kind + '_dot']))
        p.drawEllipse(QPoint(14, r.center().y() + 1), 3, 3)
        p.setPen(QColor(fg))
        f = self.font()
        f.setPixelSize(M.font_small)
        f.setWeight(f.Weight.DemiBold)
        p.setFont(f)
        p.drawText(r.adjusted(24, 0, -10, 0), int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), self.text())
        if self.hasFocus():
            p.setPen(QColor(t['focus']))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), r.height() / 2, r.height() / 2)
        p.end()

    def enterEvent(self, ev):
        self.update()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self.update()
        super().leaveEvent(ev)


class RailCard(QFrame):
    """One standard in the rail: model + maker, description, the confidence / divisor chip, the range count and the sheet-issues pill."""

    def __init__(self, panel, sid, info):
        super().__init__()
        self.panel, self.sid, self.info = panel, sid, info
        self.selected, self.hover = False, False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(M.lg + 2, M.md - 1, M.md, M.md)
        lay.setSpacing(M.xs)
        top = QHBoxLayout()
        top.setSpacing(M.sm)
        self.model_label = ElidedLabel(info['model'])
        f = theme.ui_font(15, weight=theme.ui_font().Weight.Bold)
        self.model_label.setFont(f)
        self.model_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.maker_label = ElidedLabel(info['maker'], 'hint')
        top.addWidget(self.model_label)
        top.addWidget(self.maker_label, 1)
        lay.addLayout(top)
        self.desc_label = ElidedLabel(info['desc'], 'hint')
        lay.addWidget(self.desc_label)
        self.chips = QWidget()
        fl = FlowLayout(self.chips, hgap=M.xs + 1, vgap=M.xs)
        self.badges = []
        for text, kind in info['chips']:
            b = Badge(text, kind, small=True)
            fl.addWidget(b)
            self.badges.append(b)
        lay.addSpacing(M.xs)
        lay.addWidget(self.chips)
        self.setToolTip('')

    def chip_kinds(self) -> dict:
        return dict(self.info['chips'])

    def set_selected(self, on):
        self.selected = on
        self.update()

    def enterEvent(self, ev):
        self.hover = True
        self.update()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self.hover = False
        self.update()
        super().leaveEvent(ev)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.panel.select(self.sid)
        super().mousePressEvent(ev)

    def paintEvent(self, ev):
        t = theme.tokens()
        p = QPainter(self)
        r = self.rect()
        p.fillRect(r, QColor(t['select'] if self.selected else (t['row_alt'] if self.hover else t['card'])))
        if self.selected:
            p.fillRect(QRect(0, 0, 4, r.height()), QColor(t['primary']))
        else:
            p.setPen(QColor(t['border']))
            p.drawLine(M.lg, r.bottom(), r.right() - M.md, r.bottom())
        p.end()


class RailScroll(QScrollArea):
    """The scrolling list of cards; Up / Down move through the standards."""

    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Up:
            self.panel._step(-1)
        elif ev.key() == Qt.Key.Key_Down:
            self.panel._step(1)
        else:
            super().keyPressEvent(ev)


class RangeTree(QTreeWidget):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            it = self.currentItem()
            if it is not None and it.parent() is None:
                self.panel._toggle_group(it)
            else:
                self.panel.edit_resolution()
            ev.accept()
            return
        super().keyPressEvent(ev)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.panel._fit_columns()


def _chevron(open_: bool) -> QIcon:
    pm = theme.pixmap('chevron_down', theme.tokens()['muted'], 14)
    if not open_:
        pm = pm.transformed(QTransform().rotate(-90), Qt.TransformationMode.SmoothTransformation)
    return QIcon(pm)


# ------------------------------------------------------------------------------------------------------------------------ the panel
class StandardsSpecsPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        sm.seed()
        self.sel = None
        self._kind = ''
        self._term = ''
        self._info, self._cards, self._rows, self._periods, self._closed = {}, {}, [], [], {}
        self._tips, self._group_keys, self._other_periods, self._items = {}, {}, [], {}
        self._chip_specs, self._shown_n, self._chip_width, self._collapsed_rail = [], -1, 0, False
        self.issues_window = None
        self.check_dialog = None
        self._build()
        self.refresh()

    # ---- the kind / term filters (the Tk StringVars)
    @property
    def kind(self) -> str:
        return self._kind

    @property
    def term(self) -> str:
        return self._term

    def set_kind(self, code: str) -> None:
        if code == self._kind:
            return
        self._kind = code
        self._kind_changed()

    def set_term(self, text: str) -> None:
        if self.search.text() != text:
            self.search.setText(text)
            self.search.flush()
        self._term = text
        self.show_rows()

    # ---- build
    def _build(self):
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(M.lg)
        grid.setVerticalSpacing(M.md)
        self.caption = label('Standards whose published accuracy specifications are used to compute reported uncertainties', 'sub')
        grid.addWidget(self.caption, 0, 0, 1, 2)
        self._build_rail()
        grid.addWidget(self.rail, 1, 0)
        self.right = QWidget()
        self.right_lay = QVBoxLayout(self.right)
        self.right_lay.setContentsMargins(0, 0, 0, 0)
        self.right_lay.setSpacing(M.md)
        grid.addWidget(self.right, 1, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(1, 1)
        self._build_pickbar()
        self._build_header()
        self._build_table()
        self._build_empty_all()

    def _build_rail(self):
        self.rail = QFrame()
        self.rail.setProperty('surface', 'card')
        self.rail.setFixedWidth(300)
        v = QVBoxLayout(self.rail)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(M.lg + 2, M.md + 2, M.lg + 2, M.sm)
        cap = label('STANDARDS', 'hint')
        self.rail_count = label('0', 'hint')
        head.addWidget(cap)
        head.addStretch(1)
        head.addWidget(self.rail_count)
        v.addLayout(head)
        self.rail_scroll = RailScroll(self)
        self.rail_inner = QWidget()
        self.rail_lay = QVBoxLayout(self.rail_inner)
        self.rail_lay.setContentsMargins(0, 0, 0, 0)
        self.rail_lay.setSpacing(0)
        self.rail_lay.addStretch(1)
        self.rail_empty = label('No standards loaded yet.', 'hint', wrap=True)
        self.rail_empty.setContentsMargins(M.lg + 2, M.md, M.lg, M.md)
        self.rail_lay.insertWidget(0, self.rail_empty)
        self.rail_scroll.setWidget(self.rail_inner)
        v.addWidget(self.rail_scroll, 1)
        v.addWidget(rule())
        foot = QHBoxLayout()
        foot.setContentsMargins(M.lg, M.md, M.lg, M.md)
        self.import_btn = SecondaryButton('Import spec JSON...')
        self.import_btn.clicked.connect(lambda _c=False: self.import_json())
        foot.addWidget(self.import_btn)
        v.addLayout(foot)
        foot2 = QHBoxLayout()
        foot2.setContentsMargins(M.lg, 0, M.lg, M.md)
        self.field_btn = SecondaryButton('Field assignments...')
        self.field_btn.setToolTip('Every uncertainty a technician assigned in the field: procedure, point, value, basis, reason, who, when; export to CSV.')
        self.field_btn.clicked.connect(lambda _c=False: self.field_assignments())
        foot2.addWidget(self.field_btn)
        v.addLayout(foot2)

    def field_assignments(self):
        """The lab owner's list of uncertainties assigned in the field (with CSV export)."""
        from .field_uncertainty_panel import FieldAssignmentsDialog
        return FieldAssignmentsDialog(self).run()

    def _build_pickbar(self):
        """Shown instead of the rail when the window is too narrow for it: a selector of the standards."""
        self.pickbar = QWidget()
        h = QHBoxLayout(self.pickbar)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(label('Standard'))
        self.pick_box = QComboBox()
        self.pick_box.setMinimumWidth(200)
        self.pick_box.activated.connect(lambda _i: self._pick_chosen())
        h.addWidget(self.pick_box)
        h.addStretch(1)
        self.pick_import = SecondaryButton('Import spec JSON...')
        self.pick_import.clicked.connect(lambda _c=False: self.import_json())
        h.addWidget(self.pick_import)
        self.pick_field = SecondaryButton('Field assignments...')
        self.pick_field.clicked.connect(lambda _c=False: self.field_assignments())
        h.addWidget(self.pick_field)
        self.right_lay.addWidget(self.pickbar)
        self.pickbar.hide()

    def _build_header(self):
        self.head_card = QFrame()
        self.head_card.setProperty('surface', 'card')
        b = QVBoxLayout(self.head_card)
        b.setContentsMargins(0, 0, 0, 0)
        b.setSpacing(0)
        top = QHBoxLayout()
        top.setContentsMargins(M.xl - 4, M.md, M.xl - 4, M.md)
        top.setSpacing(M.sm)
        self.h_title = label('', 'title')
        self.h_desc = ElidedLabel('', 'sub')
        top.addWidget(self.h_title)
        top.addSpacing(M.sm)
        top.addWidget(self.h_desc, 1)
        self.btn_details = SecondaryButton('Edit details...')
        self.btn_details.setToolTip('Change the name, description, period and other details of this standard (logged in the change log).')
        self.btn_details.clicked.connect(lambda _c=False: self.edit_details())
        self.btn_edit = SecondaryButton('Edit spec...')
        self.btn_export = SecondaryButton('Export JSON...')
        self.btn_emu = PrimaryButton('Check an EMU...')
        self.btn_edit.clicked.connect(lambda _c=False: self.edit_spec())
        self.btn_export.clicked.connect(lambda _c=False: self.export_json())
        self.btn_emu.clicked.connect(lambda _c=False: self.check_emu())
        for x in (self.btn_details, self.btn_edit, self.btn_export, self.btn_emu):
            top.addWidget(x)
        b.addLayout(top)
        b.addWidget(rule())
        stats = QHBoxLayout()
        stats.setContentsMargins(M.xl - 4, M.md, M.xl - 4, M.md)
        stats.setSpacing(0)
        self.stat = {}
        for i, (key, cap) in enumerate((('conf', 'CONFIDENCE ON SHEET'), ('div', 'DIVISOR'), ('period', 'PERIOD'), ('ranges', 'RANGES'))):
            if i:
                stats.addSpacing(M.md)
                stats.addWidget(rule(True))
                stats.addSpacing(M.md)
            blk = QVBoxLayout()
            blk.setSpacing(2)
            blk.addWidget(label(cap, 'hint'))
            vrow = QHBoxLayout()
            vrow.setSpacing(M.md)
            vrow.setContentsMargins(0, 0, 0, 0)
            val = QLabel('')
            f = theme.ui_font(22)
            f.setWeight(f.Weight.Bold)
            val.setFont(f)
            vrow.addWidget(val)
            if key == 'div':
                self.div_link = Link('Set divisor...', self.set_divisor)
                vrow.addWidget(self.div_link)
            vrow.addStretch(1)
            vrow_w = QWidget()
            vrow_w.setLayout(vrow)
            vrow_w.setFixedHeight(36)
            blk.addWidget(vrow_w)
            sub = ElidedLabel('', 'hint')
            blk.addWidget(sub)
            stats.addLayout(blk, 1)
            self.stat[key] = dict(val=val, sub=sub, sub_text='', tip='')
        b.addLayout(stats)
        b.addWidget(rule())
        self.facts_holder = QWidget()
        self.facts = FlowLayout(self.facts_holder, hgap=M.sm, vgap=M.sm)
        fh = QVBoxLayout()
        fh.setContentsMargins(M.xl - 4, M.sm + 2, M.xl - 4, M.sm + 2)
        fh.addWidget(self.facts_holder)
        b.addLayout(fh)
        self.right_lay.addWidget(self.head_card)

    def _build_table(self):
        self.table_card = QFrame()
        self.table_card.setProperty('surface', 'card')
        b = QVBoxLayout(self.table_card)
        b.setContentsMargins(0, 0, 0, 0)
        b.setSpacing(0)
        bar = QHBoxLayout()
        bar.setContentsMargins(M.lg, M.md - 2, M.lg, M.md - 2)
        bar.setSpacing(M.md)
        self.chip_holder = QHBoxLayout()
        self.chip_holder.setSpacing(M.sm)
        self.chip_wrap = QWidget()
        self.chip_wrap.setLayout(self.chip_holder)
        self.chip_wrap.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.chip_filter = None
        self.more_btn = None
        bar.addWidget(self.chip_wrap, 1)
        self.search = SearchField(PLACEHOLDER)
        self.search.setFixedWidth(260)
        self.search.queryChanged.connect(self._query_changed)
        bar.addWidget(self.search)
        b.addLayout(bar)
        b.addWidget(rule())
        self.stack = QStackedWidget()
        self.rows = RangeTree(self)
        self.rows.setColumnCount(7)
        self.rows.setHeaderLabels(['RANGE', 'VALUE SPAN', 'FREQUENCY', 'RESOLUTION', '', '', ''])
        self.rows.setRootIsDecorated(False)
        self.rows.setIndentation(14)
        self.rows.setUniformRowHeights(True)
        self.rows.setAllColumnsShowFocus(True)
        self.rows.setExpandsOnDoubleClick(False)
        self.rows.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.rows.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.rows.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.rows.setFrameShape(QFrame.Shape.NoFrame)
        hh = self.rows.header()
        hh.setStretchLastSection(False)
        hh.setSectionsMovable(False)
        hh.setFixedHeight(M.header_h)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for c in range(7):
            hh.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
        self.rows.headerItem().setTextAlignment(3, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
        self.rows.itemClicked.connect(self._item_clicked)
        self.rows.itemDoubleClicked.connect(self._item_double_clicked)
        self.stack.addWidget(self.rows)
        empty = QWidget()
        ev = QVBoxLayout(empty)
        ev.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_msg = label('', None, wrap=True)
        self.empty_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_msg.setMaximumWidth(460)
        ev.addWidget(self.empty_msg, 0, Qt.AlignmentFlag.AlignCenter)
        self.empty_clear = Link('Clear the filters', self.clear_filters)
        ev.addWidget(self.empty_clear, 0, Qt.AlignmentFlag.AlignCenter)
        self.empty = empty
        self.stack.addWidget(empty)
        b.addWidget(self.stack, 1)
        b.addWidget(rule())
        foot = QHBoxLayout()
        foot.setContentsMargins(M.xl - 4, M.sm, M.xl - 4, M.sm)
        foot.setSpacing(M.md)
        self.count_lbl = label('', 'hint')
        f = self.count_lbl.font()
        foot.addWidget(self.count_lbl)
        self.collapse_link = Link('Collapse all', lambda: self.set_all_groups(False))
        self.expand_link = Link('Expand all', lambda: self.set_all_groups(True))
        foot.addWidget(self.collapse_link)
        foot.addWidget(label('/', 'hint'))
        foot.addWidget(self.expand_link)
        foot.addStretch(1)
        self.hint = label(HINT, 'hint')
        foot.addWidget(self.hint)
        b.addLayout(foot)
        self.right_lay.addWidget(self.table_card, 1)

    def _build_empty_all(self):
        self.empty_all = QFrame()
        self.empty_all.setProperty('surface', 'card')
        v = QVBoxLayout(self.empty_all)
        v.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addStretch(2)
        t = label('No standards loaded', 'title')
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(t)
        m = label("Import a standard's published specification (a spec JSON file) to see its ranges here\nand to use it in the uncertainty budgets.", 'sub')
        m.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(m)
        self.empty_import = PrimaryButton('Import spec JSON...')
        self.empty_import.clicked.connect(lambda _c=False: self.import_json())
        v.addWidget(self.empty_import, 0, Qt.AlignmentFlag.AlignCenter)
        v.addStretch(3)
        self.right_lay.addWidget(self.empty_all, 1)
        self.empty_all.hide()

    # ---- window-size behaviour
    def minimumSizeHint(self):
        """Narrow enough for the rail to collapse into the pick bar (the Tk panel does that below ~940 px)."""
        h = super().minimumSizeHint()
        return QSize(min(h.width(), 760), h.height())

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._layout_for_width()

    def _layout_for_width(self):
        w = view.rail_width(self.width())
        if w is None:
            if not self._collapsed_rail:
                self._collapsed_rail = True
                self.rail.hide()
                self.pickbar.show()
                self.layout().setHorizontalSpacing(0)
        else:
            if self._collapsed_rail:
                self._collapsed_rail = False
                self.pickbar.hide()
                self.rail.show()
                self.layout().setHorizontalSpacing(M.lg)
            if self.rail.width() != w:
                self.rail.setFixedWidth(w)
        self._fit_columns()
        self._chips_resized()

    def rail_visible(self) -> bool:
        return not self._collapsed_rail

    def _fit_columns(self):
        """Give the columns the width of the table: the period columns that fit (three in a wide table, two in a narrow one) share it with the others."""
        tree = self.rows
        avail = tree.viewport().width()
        if avail < 60:
            return
        n = len(view.shown_periods(self._periods, avail))
        if n != self._shown_n and self.sel is not None:
            self._shown_n = n
            self._period_stat()
        want = ['range', 'span', 'freq', 'res'] + list(PERIOD_IDS[:n])
        for c, k in enumerate(COLUMN_KEYS):
            tree.setColumnHidden(c, k not in want)
        weight = {'range': 1.35, 'span': 1.15, 'freq': 0.75, 'res': 0.7, 'p1': 1.3, 'p2': 1.3, 'p3': 1.3}
        least = {'range': 120, 'span': 150, 'freq': 112, 'res': 118, 'p1': 150, 'p2': 150, 'p3': 150}
        total = sum(weight[k] for k in want)
        width = {k: max(least[k], avail * weight[k] / total) for k in want}
        over = sum(width.values()) - avail
        if over > 0:                                       # take the excess from the columns that are wider than their minimum
            room = {k: width[k] - least[k] for k in want}
            tot = sum(room.values())
            if tot > 0:
                for k in want:
                    width[k] -= over * room[k] / tot
        tree.header().blockSignals(True)
        for c, k in enumerate(COLUMN_KEYS):
            if k in want:
                tree.setColumnWidth(c, int(width[k]))
        tree.header().blockSignals(False)

    def displayed_columns(self) -> list:
        return [k for c, k in enumerate(COLUMN_KEYS) if not self.rows.isColumnHidden(c)]

    # ----------------------------------------------------------------------------------------------------
    def refresh(self):
        """Reload the standards from the database (the rail, the header and the table keep the selection)."""
        stds = sm.standards()
        model = self._info[self.sel]['std']['model'] if self.sel in self._info else None
        self._info = {}
        for s in stds:
            div, why = sm.standard(s['id']).divisor()
            self._info[s['id']] = dict(std=s, div=div, why=why, assets=sm.assets_of(s['id']), problems=sm.problems_of(s['id']))
        for card in self._cards.values():
            self.rail_lay.removeWidget(card)
            _discard(card)
        self._cards = {}
        for i, s in enumerate(stds):
            inf = self._info[s['id']]
            chip_text, chip_kind = view.card_chip(s, inf['div'])
            chips = [(chip_text, chip_kind), (f"{s['rows']} range{'' if s['rows'] == 1 else 's'}", 'neutral')]
            if inf['problems']:
                chips.append((f"{len(inf['problems'])} issue{'' if len(inf['problems']) == 1 else 's'}", view.issues_kind(inf['problems'])))
            card = RailCard(self, s['id'], dict(model=s['model'], maker=s['manufacturer'], desc=view.description_of(s), chips=chips))
            self.rail_lay.insertWidget(1 + i, card)
            self._cards[s['id']] = card
        self.rail_empty.setVisible(not stds)
        self.rail_count.setText(str(len(stds)))
        self.pick_box.blockSignals(True)
        self.pick_box.clear()
        self.pick_box.addItems([s['model'] for s in stds])
        self.pick_box.blockSignals(False)
        if self.sel not in self._info:                       # an import replaces a standard under a new id: stay on the same model
            self.sel = next((i for i, v in self._info.items() if v['std']['model'] == model), stds[0]['id'] if stds else None)
        self.pick()

    def select(self, sid):
        if sid == self.sel or sid not in self._info:
            return
        self.sel = sid
        if self._kind not in {k for k, _t, _n, _f in view.kind_chips(sm.rows_of(sid))}:
            self._kind = ''
        self.pick()

    def _step(self, d):
        ids = list(self._info)
        if self.sel in ids:
            self.select(ids[max(0, min(len(ids) - 1, ids.index(self.sel) + d))])

    def _pick_chosen(self, _e=None):
        model = self.pick_box.currentText()
        for sid, i in self._info.items():
            if i['std']['model'] == model:
                self.select(sid)

    def pick(self):
        """Show the selected standard: rail highlight, header, chips and table."""
        has = self.sel is not None
        for sid, card in self._cards.items():
            card.set_selected(sid == self.sel)
        if has:
            self.empty_all.hide()
            self.head_card.show()
            self.table_card.show()
            self._load_rows()
            self.show_rows()
            self._fill_header()
            self.pick_box.blockSignals(True)
            self.pick_box.setCurrentText(self._info[self.sel]['std']['model'])
            self.pick_box.blockSignals(False)
            self._ensure_visible()
        else:
            self._rows, self._periods = [], []
            self.show_rows()
            self.head_card.hide()
            self.table_card.hide()
            self.empty_all.show()

    def _ensure_visible(self):
        card = self._cards.get(self.sel)
        if card is not None:
            self.rail_scroll.ensureWidgetVisible(card, 0, 0)

    def _load_rows(self):
        self._rows = sm.rows_of(self.sel)
        std = self._info[self.sel]['std']
        self._periods, self._other_periods = view.period_columns(self._rows, std.get('period') or '1 yr')
        for i, pid in enumerate(PERIOD_IDS):
            self.rows.headerItem().setText(4 + i, view.period_heading(self._periods[i]) if i < len(self._periods) else '')
        self._fit_columns()
        self._build_chips()

    # ---- function-type chips
    def _build_chips(self):
        self._chip_specs = view.kind_chips(self._rows)
        self._chip_width = 0
        self._render_chips()

    def _render_chips(self):
        """One row of function-type chips; the ones that do not fit go under a 'More' button (a menu), the active one is always shown."""
        while self.chip_holder.count():
            it = self.chip_holder.takeAt(0)
            if it.widget() is not None:
                _discard(it.widget())
        self.chip_filter = self.more_btn = None
        width = self.chip_wrap.width()
        if width < 60:
            width = 10 ** 4
        self._chip_width = width
        fm = QFontMetrics(theme.ui_font(M.font_base, weight=theme.ui_font().Weight.DemiBold))
        specs = self._chip_specs
        active = self._kind
        more_w = fm.horizontalAdvance('More  99') + 40
        need = lambda sp: fm.horizontalAdvance(f'{sp[1]}  {sp[2]}') + 30      # noqa: E731
        shown, used = [], 8
        for spec in specs:
            if used + need(spec) + (more_w if len(shown) < len(specs) - 1 else 0) > width and shown:
                break
            shown.append(spec)
            used += need(spec)
        hidden = [sp for sp in specs if sp not in shown]
        if hidden and active and all(sp[0] != active for sp in shown):                 # keep the chosen type visible
            swap = next(sp for sp in hidden if sp[0] == active)
            hidden.remove(swap)
            hidden.append(shown.pop())
            shown.append(swap)
        if shown:
            self.chip_filter = SegmentedFilter([(code, text, n) for code, text, n, _full in shown])
            for code, text, n, full in shown:
                self.chip_filter._buttons[code].setToolTip(full)
            if active in self.chip_filter._buttons:
                self.chip_filter.set_current(active)
            self.chip_filter.currentChanged.connect(self.set_kind)
            self.chip_holder.addWidget(self.chip_filter)
        if hidden:
            self.more_btn = SecondaryButton(f'More  {len(hidden)}')
            self.more_btn.clicked.connect(lambda _c=False, h=hidden: self._more_menu(h))
            self.chip_holder.addWidget(self.more_btn)
        self.chip_holder.addStretch(1)
        self._hidden_chips = hidden

    def chip_codes(self) -> list:
        return list(self.chip_filter._buttons) if self.chip_filter else []

    def chip_active(self, code: str) -> bool:
        return bool(self.chip_filter and self.chip_filter.current() == code)

    def click_chip(self, code: str) -> None:
        """Click the chip of a function type the way a person does."""
        self.chip_filter._buttons[code].click()

    def _more_menu(self, hidden):
        menu = QMenu(self)
        for code, text, n, full in hidden:
            menu.addAction(f'{text}   {n}   ({full})', lambda c=code: self.set_kind(c))
        menu.exec(self.more_btn.mapToGlobal(QPoint(0, self.more_btn.height())))

    def _chips_resized(self):
        if self._chip_specs and abs(self.chip_wrap.width() - self._chip_width) > 6 and self.chip_wrap.width() > 60:
            self._render_chips()

    def _kind_changed(self):
        if self.chip_filter is None or self._kind not in self.chip_filter._buttons:      # a type under 'More' (or set from outside): bring it into the row
            self._render_chips()
        elif self.chip_filter.current() != self._kind:
            self.chip_filter.set_current(self._kind)
        self.show_rows()

    def _query_changed(self, text):
        self._term = text
        self.show_rows()

    # ---- the header card
    def _fill_header(self):
        t = theme.tokens()
        inf = self._info[self.sel]
        s = inf['std']
        self.h_title.setText(s['model'])
        self.h_desc.set_full(' ·  '.join(x for x in (s['manufacturer'], view.description_of(s)) if x))
        value, note, stated = view.confidence_summary(s['confidence_text'], s['confidence_pct'])
        full_conf = s['confidence_text'] or 'The sheet does not state a confidence level; k = 2 is assumed.'
        self._set_stat('conf', value, note, full_conf, 'text' if stated else 'muted')
        self._set_stat('div', view.divisor_text(inf['div']), inf['why'], inf['why'], 'primary')
        self._shown_n = -1
        self._period_stat()
        self._set_stat('ranges', str(len(self._rows)), view.ranges_note(self._rows), view.ranges_note(self._rows), 'text')
        self.facts.clear()
        self.asset_chips = []
        cap = label('Assets', 'hint')
        self.facts.addWidget(cap)
        if inf['assets']:
            for a, serial in inf['assets']:
                b = Badge(f'{a}  {view.DOT}  {serial}' if serial else a, 'neutral', small=True)
                self.facts.addWidget(b)
                self.asset_chips.append(b)
        else:
            self.none_set = label('none set', 'hint')
            self.facts.addWidget(self.none_set)
        self.assets_link = Link('Set assets...', self.set_assets)
        self.facts.addWidget(self.assets_link)
        appr = QWidget()
        ah = QHBoxLayout(appr)
        ah.setContentsMargins(M.md, 0, 0, 0)
        ah.setSpacing(M.sm)
        ah.addWidget(label('Approved', 'hint'))
        self.approved_label = label(view.approved_text(s))
        ah.addWidget(self.approved_label)
        self.facts.addWidget(appr)
        n = len(inf['problems'])
        self.issues_chip = IssuesChip(view.issues_text(n) + '  ›', view.issues_kind(inf['problems']), self.show_issues)
        self.issues_chip.setToolTip('Show what was found when the specification sheet was read')
        self.facts.addWidget(self.issues_chip)
        self.facts_holder.updateGeometry()

    def _period_stat(self):
        """The Period block: the default period, and which period columns the table shows (the rest are named, not hidden from the reader)."""
        w = self.rows.viewport().width()
        n = len(view.shown_periods(self._periods, w)) if w > 60 else len(self._periods)
        self._shown_n = n
        note = view.period_note(self._periods[:n], self._periods[n:] + self._other_periods)
        self._set_stat('period', self._info[self.sel]['std']['period'] or '', note, note, 'text')

    def _set_stat(self, key, value, sub, full, colour):
        st = self.stat[key]
        st['val'].setText(value)
        sed._tone(st['val'], colour)
        st['sub_text'], st['tip'] = sub, full
        st['sub'].set_full(sub)
        for w in (st['val'], st['sub']):
            w.setToolTip(full)

    def stat_text(self) -> dict:
        return {k: self.stat[k]['val'].text() for k in self.stat}

    # ----------------------------------------------------------------------------------------------------
    def show_rows(self):
        tree = self.rows
        tree.clear()
        self._tips, self._group_keys, self._items = {}, {}, {}
        if self.sel is None:
            self.stack.setCurrentIndex(0)
            self.count_lbl.setText('')
            return
        t = theme.tokens()
        kind, term = self._kind, self._term.strip()
        shown = [r for r in self._rows if view.matches(r, kind, term)]
        closed = self._closed.setdefault(self.sel, set())
        bold = theme.ui_font(M.font_base, weight=theme.ui_font().Weight.Bold)
        for gi, (key, title, rs) in enumerate(view.group_rows(shown)):
            gid = f'g{gi}'
            is_open = key not in closed or bool(term)
            band = QTreeWidgetItem(tree, [title, f"{len(rs)} range{'' if len(rs) == 1 else 's'}"])
            band.setData(0, Qt.ItemDataRole.UserRole, gid)
            band.setIcon(0, _chevron(is_open))
            band.setFirstColumnSpanned(False)
            for c in range(7):
                band.setBackground(c, QColor(t['head_hi']))
                band.setFont(c, bold)
            self._tips[gid] = {'range': title}
            self._group_keys[gid] = (key, title)
            self._items[gid] = band
            last = None
            for n, r in enumerate(rs):
                rng, qual = view.split_label(r['label'])
                cells = [view.spec_cell(r, p) for p in self._periods]
                vals = [rng if rng != last else '', view.span_text(r), view.freq_text(r), view.resolution_text(r)] + [c[0] for c in cells] + [''] * (3 - len(cells))
                leaf = QTreeWidgetItem(band, vals)
                leaf.setData(0, Qt.ItemDataRole.UserRole, str(r['id']))
                leaf.setTextAlignment(3, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter))
                if n % 2:
                    for c in range(7):
                        leaf.setBackground(c, QColor(t['row_alt']))
                tip = {'range': r['label'], 'freq': r['label'] if qual else ''}
                for pid, (_t, raw) in zip(PERIOD_IDS, cells):
                    tip[pid] = raw
                self._tips[str(r['id'])] = tip
                self._items[str(r['id'])] = leaf
                for c, k in enumerate(COLUMN_KEYS):
                    if tip.get(k):
                        leaf.setToolTip(c, tip[k])
                last = rng
            band.setExpanded(is_open)
        self.count_lbl.setText(view.shown_count_text(len(shown), len(self._rows)))
        if shown:
            self.stack.setCurrentIndex(0)
        else:
            msg, can_clear = view.empty_message(len(self._rows), kind, term)
            self.empty_msg.setText(msg)
            self.empty_clear.setVisible(can_clear)
            self.stack.setCurrentIndex(1)

    def empty_visible(self) -> bool:
        return self.stack.currentIndex() == 1

    def band_ids(self) -> list:
        return [g for g in self._group_keys]

    def band_open(self, gid) -> bool:
        return self._items[gid].isExpanded()

    def row_values(self, iid) -> list:
        it = self._items[iid]
        return [it.text(c) for c in range(7)]

    def select_row(self, iid) -> None:
        self.rows.setCurrentItem(self._items[iid])

    def selected_id(self):
        it = self.rows.currentItem()
        return it.data(0, Qt.ItemDataRole.UserRole) if it is not None else None

    def _toggle_group(self, band, state=None):
        gid = band.data(0, Qt.ItemDataRole.UserRole)
        is_open = (not band.isExpanded()) if state is None else state
        band.setExpanded(is_open)
        band.setIcon(0, _chevron(is_open))
        key = self._group_keys[gid][0]
        closed = self._closed.setdefault(self.sel, set())
        (closed.discard if is_open else closed.add)(key)

    def toggle_band(self, gid, state=None):
        self._toggle_group(self._items[gid], state)

    def set_all_groups(self, is_open):
        for gid, band in self._items.items():
            if gid in self._group_keys:
                self._toggle_group(band, is_open)

    def clear_filters(self):
        self._term = ''
        self.search.setText('')
        self._kind = ''
        self._kind_changed()

    def _item_clicked(self, item, _col):
        if item.parent() is None:
            self._toggle_group(item)

    def _item_double_clicked(self, item, _col):
        if item.parent() is not None:
            self.edit_resolution(int(item.data(0, Qt.ItemDataRole.UserRole)))

    # ----------------------------------------------------------------------------------------------------
    def _who(self):
        import getpass
        try:
            return getpass.getuser()
        except Exception:
            return ''

    def set_divisor(self):
        if self.sel is None:
            return
        cur = sm.standard(self.sel).divisor()[0]
        txt = sed.ask_string(self, 'Coverage divisor', 'Divisor that turns the published accuracy into a standard uncertainty (k = 1).\n'
                             'Common: 2 (95 % treated as k = 2), 1.96, 2.576 (99 %), 1.732 (rectangular).\nBlank = use the sheet\'s confidence level.',
                             initialvalue=f'{cur:g}')
        if txt is None:
            return
        try:
            val = float(txt) if txt.strip() else None
            if val is not None and not 1.0 <= val <= 4.0:
                raise ValueError
        except ValueError:
            sed.show_error(self, 'Divisor', 'Enter a number between 1 and 4.')
            return
        reason = sed.ask_string(self, 'Reason', 'Reason for the change (kept in the change log):') or ''
        sm.set_standard_field(self.sel, 'divisor', val, who=self._who(), reason=reason)
        self.refresh()

    DETAIL_CAPTIONS = (('manufacturer', 'Manufacturer'), ('model', 'Model'), ('description', 'Description'), ('period', 'Default period'),
                       ('confidence_text', 'Confidence statement'), ('approved_by', 'Approved by'), ('approve_date', 'Approval date'),
                       ('reference', 'Reference'), ('revision', 'Revision'), ('author', 'Author'))

    def ask_details(self, current: dict):
        """The details form: {field: text} (plus 'reason') or None when cancelled.  A seam for tests, like the sed.ask_* functions."""
        dlg = ModalDialog(self, 'Edit details of the standard', width=620)
        dlg.setWindowTitle(sed._title('Edit details of the standard'))
        dlg.sub_label.setText('The specification rows and limits are not changed here (use Edit spec...). Every change is kept in the change log.')
        dlg.sub_label.show()
        grid = QGridLayout()
        grid.setHorizontalSpacing(M.md)
        grid.setVerticalSpacing(M.sm)
        edits = {}
        for r, (key, cap) in enumerate(self.DETAIL_CAPTIONS):
            grid.addWidget(label(cap, 'hint'), r, 0)
            e = QLineEdit(str(current.get(key, '') or ''))
            e.setAccessibleName(cap)
            grid.addWidget(e, r, 1)
            edits[key] = e
        grid.setColumnStretch(1, 1)
        reason = QLineEdit()
        reason.setAccessibleName('Reason')
        reason.setPlaceholderText('Reason for the change (optional)')
        grid.addWidget(label('Reason', 'hint'), len(edits), 0)
        grid.addWidget(reason, len(edits), 1)
        dlg.body.addLayout(grid)
        dlg.initial_focus = edits['description']
        dlg.add_button('Cancel', cancel=True)
        dlg.add_button('Save', role='primary', default=True)
        if dlg.run() != 'save':
            return None
        out = {k: e.text() for k, e in edits.items()}
        out['reason'] = reason.text()
        return out

    def edit_details(self):
        if self.sel is None:
            return
        std = self._info[self.sel]['std']
        got = self.ask_details({k: std.get(k, '') for k, _c in self.DETAIL_CAPTIONS})
        if got is None:
            return
        reason = got.pop('reason', '')
        try:
            done = sm.set_standard_details(self.sel, got, who=self._who(), reason=reason)
        except ValueError as e:
            sed.show_error(self, 'Edit details', str(e))
            return
        if done:
            self.refresh()

    def set_assets(self):
        if self.sel is None:
            return
        cur = '; '.join(f'{a}:{s}' for a, s in sm.assets_of(self.sel))
        txt = sed.ask_string(self, 'Assets', 'Instrument IDs of the units of this model used as standards.\nFormat  ID:serial; ID:serial', initialvalue=cur)
        if txt is None:
            return
        pairs = []
        for part in txt.split(';'):
            if part.strip():
                a, _, s = part.partition(':')
                pairs.append((a.strip(), s.strip()))
        sm.set_assets(self.sel, pairs)
        self.refresh()

    def edit_resolution(self, rid=None):
        if rid is None:
            sel = self.selected_id()
            if not sel or not str(sel).isdigit():            # nothing selected, or a function group band
                return
            rid = int(sel)
        row = next((r for r in sm.rows_of(self.sel) if r['id'] == rid), None)
        if not row:
            return
        txt = sed.ask_string(self, 'Calibrator resolution', f"Resolution of the calibrator on '{row['label']}' in {row['unit'] or 'SI base units'} "
                             '(the last digit it can set).\nBlank = not recorded.', initialvalue=f"{row['resolution']:g}" if row['resolution'] else '')
        if txt is None:
            return
        try:
            val = float(txt) if txt.strip() else None
            if val is not None and val <= 0:
                raise ValueError
        except ValueError:
            sed.show_error(self, 'Resolution', 'Enter a positive number in SI base units (V, A, ohm, F, Hz).')
            return
        sm.update_row(rid, {'resolution': val}, who=self._who(), reason='resolution entered in the manager')
        self._rows = sm.rows_of(self.sel)
        top = self.rows.verticalScrollBar().value()
        self.show_rows()
        if str(rid) in self._items:
            self.rows.setCurrentItem(self._items[str(rid)])
            self.rows.verticalScrollBar().setValue(top)

    def show_issues(self):
        if self.sel is None:
            return
        probs = sm.problems_of(self.sel)
        model = self._info[self.sel]['std']['model'] if self.sel in self._info else ''
        win = ModalDialog(self, f'Sheet issues found when the {model} specification was read', width=900, modal=False)
        win.setWindowTitle(sed._title(f'Sheet issues found when the {model} specification was read'))
        win.title_label.hide()
        txt = QPlainTextEdit()
        txt.setReadOnly(True)
        txt.setPlainText('\n\n'.join(f"[{p.get('level', '')}] {p.get('where', '')}: {p.get('what', '')}" for p in probs) or 'None found.')
        txt.setMinimumHeight(420)
        win.body.addWidget(txt)
        win.text_widget = txt
        win.add_button('Close', cancel=True)
        win.show()
        self.issues_window = win

    def import_json(self):
        f = sed.ask_open_path(self, 'Import spec JSON', 'Spec JSON (*.json)')
        if not f:
            return
        try:
            with open(f, encoding='utf-8') as fh:
                data = json.load(fh)
            if not sm.import_data(data, who=self._who()):
                raise ValueError('not a specification file')
        except (OSError, ValueError, KeyError) as e:
            sed.show_error(self, 'Import', f'Could not import: {e}')
            return
        self.refresh()

    def edit_spec(self):
        """Open the documented-edit editor (qtui.screens.spec_editor) on the selected standard's sheet."""
        if self.sel is None:
            return
        sed.open_editor(self.window(), self._info[self.sel]['std']['model'], on_saved=self.refresh)

    def export_json(self):
        if self.sel is None:
            return
        f = sed.ask_save_path(self, 'Export JSON', '', 'JSON (*.json)')
        if f:
            with open(f, 'w', encoding='utf-8') as fh:
                json.dump(sm.export_data(self.sel), fh, indent=1)

    # ----------------------------------------------------------------------------------------------------
    def check_emu(self):
        if self.sel is None:
            return
        row = None
        iid = self.selected_id()
        if iid is not None and iid not in self._group_keys:
            row = next((r for r in sm.rows_of(self.sel) if str(r['id']) == str(iid)), None)          # the range selected in the table prefills the point
        self.check_dialog = CheckDialog(self, sm.standard(self.sel), row)
        self.check_dialog.show()                   # the window is non-modal and was never shown: the button appeared to do nothing
        self.check_dialog.raise_()
        self.check_dialog.activateWindow()
        return self.check_dialog


SpecManagerPanel = StandardsSpecsPanel          # the Tk class name, so the Manager shell can host either


class CheckDialog(ModalDialog):
    """Give a nominal test point (with its units); shows the uncertainty that would be REPORTED ON THE CERTIFICATE for it with this standard (emu_check_model: the standard's
    specification row that covers the point, its resolution, any Type A, k = 2, against the scope CMC, the larger one rounded up).  Optionally an uncertainty somebody already
    reported can be entered to be audited against the budget.  The point is prefilled from the row selected in the spec table."""

    # (label, key, hint, unit family): every value box has its own unit box
    FIELDS = (('Nominal test point', 'nominal', 'e.g. 250', 'nominal'), ('Frequency', 'freq', 'AC points only', 'freq'),
              ('Calibrator resolution', 'res', 'optional: blank = from the sheet', 'nominal'), ('Type A std. uncertainty (k = 1)', 'typea', 'optional: repeatability, blank = none', 'nominal'),
              ('Uncertainty already reported', 'reported', 'optional: check it against the budget', 'nominal'))

    def __init__(self, parent, standard, row=None):
        super().__init__(parent, f'Reported uncertainty - {standard.model}', width=860, modal=False)
        self.setWindowTitle(sed._title(f'Reported uncertainty - {standard.model}'))
        self.title_label.hide()
        self.std = standard
        self.v, self.u, self.rowlabels = {}, {}, {}
        form = QGridLayout()
        form.setHorizontalSpacing(M.md)
        form.setVerticalSpacing(M.sm)
        form.addWidget(label('Function'), 0, 0)
        self.kind_box = QComboBox()
        for k in emu.KINDS:
            self.kind_box.addItem(f'{k}  {emu.KIND_NAMES[k]}', k)
        self.kind_box.setAccessibleName('Function')
        self.kind_box.currentIndexChanged.connect(lambda _i: self._kind_changed())
        form.addWidget(self.kind_box, 0, 1, 1, 2)
        for r, (lab, key, hint, family) in enumerate(self.FIELDS, start=1):
            lb = label(lab)
            form.addWidget(lb, r, 0)
            ent = QLineEdit()
            ent.setMinimumWidth(160)
            ent.setAccessibleName(lab)
            ent.returnPressed.connect(self.run_check)
            box = QComboBox()
            box.setAccessibleName(lab + ' unit')
            box.setMinimumWidth(90)
            self.v[key], self.u[key] = ent, box
            if key == 'nominal':
                box.currentTextChanged.connect(self._follow_nominal_unit)
            self.rowlabels[key] = lb
            form.addWidget(ent, r, 1)
            form.addWidget(box, r, 2)
            form.addWidget(label(hint, 'hint'), r, 3)
        form.setColumnStretch(4, 1)
        self.body.addLayout(form)
        self.big = label('', 'section')
        self.big.setAccessibleName('Uncertainty to report')
        self.body.addWidget(self.big)
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setMinimumHeight(220)
        self.body.addWidget(self.out)
        self.add_button('Close', cancel=True)
        self.run_btn = self.add_button('Calculate', role='primary', default=True, close=False, callback=self.run_check)
        self.result = None
        pre = emu.prefill_from_row(row) if row else {'kind': 'DCV', 'nominal': '', 'nominal_unit': '', 'frequency': '', 'frequency_unit': 'Hz'}
        self.kind_box.setCurrentIndex(max(0, self.kind_box.findData(pre['kind'])))
        self._kind_changed()
        if pre.get('nominal'):
            self.set_value('nominal', pre['nominal'])
            self.set_unit('nominal', pre['nominal_unit'])
        if pre.get('frequency'):
            self.set_value('freq', pre['frequency'])
            self.set_unit('freq', pre['frequency_unit'])

    # ---- the inputs
    def kind(self) -> str:
        return self.kind_box.currentData()

    def set_kind(self, kind) -> None:
        self.kind_box.setCurrentIndex(max(0, self.kind_box.findData(kind)))

    def _kind_changed(self):
        kind = self.kind()
        for key in ('nominal', 'res', 'typea', 'reported'):
            box = self.u[key]
            box.blockSignals(True)
            box.clear()
            for name, f in emu.unit_choices(kind):
                box.addItem(name)
            base = [n for n, f in emu.unit_choices(kind) if f == 1.0]      # default to the base unit (V, A, ohm...), not the biggest one in the list
            if base:
                box.setCurrentIndex(max(0, box.findText(base[0])))
            box.blockSignals(False)
        freq = self.u['freq']
        if freq.count() == 0:
            for name, _f in emu.FREQUENCY_UNITS:
                freq.addItem(name)
        ac = kind in emu.AC_KINDS
        for w in (self.rowlabels['freq'], self.v['freq'], self.u['freq']):
            w.setVisible(ac)
        self.out.clear()
        self.big.setText('')

    def _follow_nominal_unit(self, text):
        """Resolution, Type A and the reported figure are in the same family as the nominal: they follow its unit until changed by hand."""
        for key in ('res', 'typea', 'reported'):
            i = self.u[key].findText(text)
            if i >= 0:
                self.u[key].setCurrentIndex(i)

    def value(self, key) -> str:
        return self.kind() if key == 'kind' else self.v[key].text()

    def set_value(self, key, text) -> None:
        if key == 'kind':
            self.set_kind(text)
        else:
            self.v[key].setText(text)

    def unit(self, key) -> str:
        return self.u[key].currentText()

    def set_unit(self, key, text) -> None:
        i = self.u[key].findText(text)
        if i >= 0:
            self.u[key].setCurrentIndex(i)

    def inputs(self) -> emu.Inputs:
        return emu.Inputs(kind=self.kind(), nominal=self.value('nominal'), nominal_unit=self.unit('nominal'), frequency=self.value('freq'), frequency_unit=self.unit('freq'),
                          resolution=self.value('res'), resolution_unit=self.unit('res'), type_a=self.value('typea'), type_a_unit=self.unit('typea'),
                          reported=self.value('reported'), reported_unit=self.unit('reported'))

    def run_check(self):
        res = self.result = emu.compute(self.std, self.inputs())
        if res.error:
            self.big.setText('')
            self.out.setPlainText(res.error)
            sed.show_error(self, 'Reported uncertainty', res.error)
            return False
        self.big.setText(f'Uncertainty to report on the certificate:  \u00b1 {res.cert_text}' + (f'   ({res.relative})' if res.relative else ''))
        self.out.setPlainText('\n'.join(res.lines))
        return False

    run = run_check            # the Tk method name (ModalDialog.run, the modal loop, is not used by this non-modal window)

    def output_text(self) -> str:
        return self.out.toPlainText()

    def cert_text(self) -> str:
        return self.result.cert_text if self.result is not None else ''
