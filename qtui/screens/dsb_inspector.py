"""Datasheet Builder (Qt): the right-hand Inspector for the selected row (Test point, Limits and tolerance, Uncertainty source, Several rows at once, Asymmetrical
tolerance, Resolution and decimals, Rules for this section, Row options).  It only shows and collects values: GridModel.panel_state() fills it and
GridModel.calc_row() uses what form() returns.  The Low / High limit boxes are READ-ONLY (they show what the tolerance works out); an old sheet's typed limit
pair is flagged and offered 'Clear typed limits'.  Port of datasheet_builder_ui.Inspector; no Tk import."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton, QScrollArea,
                               QVBoxLayout, QWidget)

import datasheet_builder_ui_model as M
import dsb_sensors as sens
from qtui import widgets
from qtui.screens import dsb_common as C
from qtui.theme import M as SZ

CHIP_LABELS = {'iv': '% of reading', 'fs': '% of range', 'floor': 'Floor', 'db': '± dB', 'calc': 'Calculator'}


class RadioVar:
    """get() / set() over a group of radio buttons keyed by value (the multiple-rows spacing)."""

    def __init__(self):
        self.group = QButtonGroup()
        self.buttons = {}

    def add(self, key, rb):
        self.buttons[key] = rb
        self.group.addButton(rb)

    def get(self):
        return next((k for k, b in self.buttons.items() if b.isChecked()), '')

    def set(self, key):
        b = self.buttons.get(key)
        if b is not None:
            b.setChecked(True)


class FreqBox(QWidget):
    """A number and a unit picker (Hz, kHz, MHz, GHz) in one box: the value reads and writes as text such as '1 MHz', so nothing downstream changes.
    Typing the unit yourself still works ('1 MHz' in the number box)."""
    UNITS = ('Hz', 'kHz', 'MHz', 'GHz')

    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.edit = QLineEdit()
        self.unit = QComboBox()
        self.unit.addItems(self.UNITS)
        self.unit.setMinimumContentsLength(3)
        self.unit.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.unit)

    def get_value(self):
        t = self.edit.text().strip()
        if not t:
            return ''
        if any(ch.isalpha() for ch in t):                      # the unit was typed in the box: leave it alone
            return t
        return f'{t} {self.unit.currentText()}'

    def set_value(self, v):
        t = '' if v is None else str(v).strip()
        parts = t.split()
        square = len(parts) == 3 and parts[2] == 'square'
        if square:
            parts = parts[:2]
        if len(parts) == 2 and parts[1] in self.UNITS:
            self.edit.setText(parts[0])
            self.unit.setCurrentText(parts[1])
        else:
            self.edit.setText(t)
            if not t:
                self.unit.setCurrentText('Hz')


class SensorBox(QWidget):
    """'Sourced as' of a temperature row: a thermocouple type or an RTD (dsb_sensors.sensor_types()), plus a button that gives the whole section the same choice.
    get_value() / set_value() work with the sensor KEY ('' = not chosen yet)."""
    NONE = '(choose how it is sourced)'

    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.combo = QComboBox()
        self.combo.setMinimumContentsLength(4)
        self.combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.section_btn = QPushButton('Whole section')
        self.section_btn.setToolTip('Give every row of this section the choice in the box.')
        lay.addWidget(self.combo, 1)
        lay.addWidget(self.section_btn)

    def set_choices(self, pairs):
        have = [self.combo.itemData(i) for i in range(1, self.combo.count())]
        if have == [k for k, _l in pairs]:
            return
        keep = self.get_value()
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem(self.NONE, '')
        for k, lab in pairs:
            self.combo.addItem(lab, k)
        self.combo.blockSignals(False)
        self.set_value(keep)

    def get_value(self):
        return self.combo.currentData() or ''

    def set_value(self, key):
        i = self.combo.findData(key or '')
        self.combo.setCurrentIndex(i if i >= 0 else 0)


class CoilBox(QWidget):
    """'Driven through the 50-turn coil' of a clamp-meter current row: a check box plus a button that gives the whole section the same choice.  get_value() / set_value() work
    with a bool.  The calibrator then sources nominal / 50 and the uncertainty is the coil's (dsb_coil, coil_rule)."""

    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.check = QCheckBox('Through the 50-turn coil')
        self.section_btn = QPushButton('Whole section')
        self.section_btn.setToolTip('Give every row of this section the choice in the box.')
        lay.addWidget(self.check, 1)
        lay.addWidget(self.section_btn)

    def get_value(self):
        return self.check.isChecked()

    def set_value(self, on):
        self.check.setChecked(bool(on))


class LevelBox(QWidget):
    """The signal level of a frequency / period / bandwidth test: a number and a unit picker (V, mV, µV, Vpp, mVpp, µVpp).  The value is stored in the basis of the
    function (volts rms; the scope functions store volts peak-to-peak).  V / mV / µV is a sine wave in rms and Vpp / mVpp / µVpp a square wave in peak-to-peak, the way the
    calibrator takes them, so NO conversion is made between the two: the number is only scaled to volts.  The waveform itself is not stored in the datasheet."""
    UNITS = ('V', 'mV', '\u00b5V', 'Vpp', 'mVpp', '\u00b5Vpp')
    SCALE = {'V': 1, 'mV': 1e-3, '\u00b5V': 1e-6, 'Vpp': 1, 'mVpp': 1e-3, '\u00b5Vpp': 1e-6}

    def __init__(self):
        super().__init__()
        self.basis = 'rms'
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.edit = QLineEdit()
        self.unit = QComboBox()
        self.unit.addItems(self.UNITS)
        self.unit.setMinimumContentsLength(5)
        self.unit.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.unit)

    def set_basis(self, basis):
        self.basis = 'pp' if basis == 'pp' else 'rms'
        now = self.unit.currentText()
        if not self.edit.text().strip():                                  # nothing typed: the default unit of the stored basis
            if now in ('V', 'Vpp'):
                self.unit.setCurrentText('Vpp' if self.basis == 'pp' else 'V')
        elif now == 'V' and self.basis == 'pp':                           # a peak-to-peak function stores Vpp ...
            self.unit.setCurrentText('Vpp')
        # ... but a Vpp level on an rms function is a square wave the person chose: never turned back into V when the point is shown again

    def get_value(self):
        t = self.edit.text().strip()
        if not t:
            return ''
        if any(ch.isalpha() for ch in t.replace('e', '').replace('E', '')) or '\u00b5' in t:      # a unit typed in the box itself: leave it alone
            return t
        from decimal import Decimal
        unit = self.unit.currentText()
        try:
            value = Decimal(t.replace(',', '.')) * Decimal(str(self.SCALE[unit]))
        except Exception:
            return t
        text = f'{value.normalize():f} V'.replace('+', '')
        return text + (' square' if unit.endswith('pp') and self.basis == 'rms' else '')       # Vpp on an rms function is a square wave: kept with the point

    def set_value(self, v):
        t = '' if v is None else str(v).strip()
        parts = t.split()
        square = len(parts) == 3 and parts[2] == 'square'            # the older '1 V square' text: shown as Vpp
        if square:
            parts = parts[:2]
        if len(parts) == 2 and parts[1] in self.UNITS:               # '1 Vpp' (peak to peak, shown as it was typed)
            self.edit.setText(parts[0])
            self.unit.setCurrentText(parts[1])
        elif len(parts) == 2 and parts[1] in ('V', 'mV', '\u00b5V', 'uV'):
            self.edit.setText(parts[0])
            self.unit.setCurrentText('\u00b5V' if parts[1] == 'uV' else parts[1])
            if self.basis == 'pp' or square:
                self.unit.setCurrentText({'V': 'Vpp', 'mV': 'mVpp', '\u00b5V': '\u00b5Vpp'}[self.unit.currentText()])
        else:
            self.edit.setText(t)
            if not t:
                self.unit.setCurrentText('Vpp' if self.basis == 'pp' else 'V')


class Chip(QPushButton):
    """A tick box drawn as a pill.  Space / Enter / click toggles it."""

    def __init__(self, text: str):
        super().__init__(text)
        self.setCheckable(True)
        self.setProperty('role', 'chip')
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAutoDefault(False)


class Section(QWidget):
    """One inspector section: a rule, a clickable title (v open / > closed) with a note at the right, and a body that shows when open."""

    def __init__(self, title: str, note: str = '', open_: bool = True, on_toggle=None):
        super().__init__()
        self.title, self.open, self.on_toggle, self.note_text = title, open_, on_toggle, note
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(widgets.rule())
        head = QHBoxLayout()
        head.setContentsMargins(0, 4, 0, 2)
        self.name = QPushButton()
        self.name.setProperty('role', 'ghost')
        self.name.setStyleSheet('text-align: left;')
        self.name.setCursor(Qt.CursorShape.PointingHandCursor)
        self.name.setAutoDefault(False)
        self.name.clicked.connect(lambda _c=False: self.toggle())
        self.note = widgets.label(note, 'hint')
        head.addWidget(self.name, 1)
        head.addWidget(self.note)
        lay.addLayout(head)
        self.body = QWidget()
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 0, 0, 6)
        self.body_lay.setSpacing(SZ.sm - 2)
        lay.addWidget(self.body)
        self.set_open(open_)

    def toggle(self):
        self.set_open(not self.open)

    def set_open(self, value):
        self.open = bool(value)
        self.name.setText(('v  ' if self.open else '>  ') + self.title)
        self.body.setVisible(self.open)
        if self.on_toggle:
            self.on_toggle()

    def set_note(self, text, active=False):
        self.note.setText(text if text else self.note_text)


class _EntryKeys(QObject):
    """Enter in a box = Calc; Esc = put the boxes back from the sheet (what the Tk bindings did)."""

    def __init__(self, win, w):
        super().__init__(w)
        self.win = win
        w.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.KeyPress:
            if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.win.calc()
                return True
            if ev.key() == Qt.Key.Key_Escape:
                self.win.sync()
                return True
        return False


class Inspector(QFrame):
    SECTION_ORDER = ('point', 'tol', 'res', 'uncert', 'multi', 'asym', 'rules', 'row')

    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.win = win
        self.setProperty('surface', 'card')
        self.sides = {'plus': M.GridModel.blank_side(), 'minus': M.GridModel.blank_side()}
        self.operand_now = 'plus'
        self.v: dict = {}
        self.b: dict = {}
        self.types: dict = {}
        self.cells: dict = {}
        self.entries: list = []
        self._defs, self._choices, self._state = [], [], {}
        self._visible: dict = {}
        self.sections: dict = {}
        self._groups: dict = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 8, 4, 8)
        outer.setSpacing(2)
        top = QHBoxLayout()
        self.title_l = widgets.label('ROW', 'section')
        self.of_l = widgets.label('', 'hint')
        self.hide_b = C.button('Hide >', win.toggle_inspector, compact=True, tooltip='Hide the row panel to give the sheet the room (Ctrl+I brings it back).')
        top.addWidget(self.title_l)
        top.addWidget(self.of_l)
        top.addStretch(1)
        top.addWidget(self.hide_b)
        outer.addLayout(top)
        self.sub_l = widgets.label('', 'sub', wrap=True)
        outer.addWidget(self.sub_l)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName('root')
        self.inner_lay = QVBoxLayout(inner)
        self.inner_lay.setContentsMargins(0, 0, 8, 0)
        self.inner_lay.setSpacing(0)
        self.scroll.setWidget(inner)
        outer.addWidget(self.scroll, 1)

        self._build_point(self._section('point', 'Test point', '', True))
        self._build_tolerance(self._section('tol', 'Limits and tolerance', '', True))
        self._build_res(self._section('res', 'Resolution and decimals', '', True, 'Display Decs., Meas Res and Auto Res: the display resolution of the range.'))
        self._build_uncertainty(self._section('uncert', 'Uncertainty source', '', True,
                                              'Rule 5: which standards sheet the uncertainty of this row comes from. A row with no source keeps the uncertainty blank on the report (never zero).'))
        self._build_multi(self._section('multi', 'Several rows at once', 'Multiple', False, 'Multiple Test Points: make a run of rows between a lowest and a highest value.'))
        self._build_asym(self._section('asym', 'Asymmetrical tolerance', 'Operand', False, 'Asymmetrical Tol and Operand: a different tolerance above and below the nominal.'))
        self._build_rules(self._section('rules', 'Rules for this section', 'Definitions', False, 'Test Point Definitions: the rules of the test point calculator for this section.'))
        self._build_row(self._section('row', 'Row options', '', True))
        self.inner_lay.addStretch(1)
        for e in self.entries:
            C_keys = _EntryKeys(win, e.lineEdit() if isinstance(e, QComboBox) else e)       # noqa: F841
        self._pack_sections(self.SECTION_ORDER)

    # ---- building
    def _section(self, name, title, note, open_, hint=''):
        sec = Section(title, note, open_)
        if hint:
            C.tip(sec.name, hint)
            C.tip(sec.note, hint)
        self.sections[name] = sec
        self.inner_lay.addWidget(sec)
        return sec.body_lay

    def _pack_sections(self, names):
        for n, sec in self.sections.items():
            sec.setVisible(n in names)
        if hasattr(self, 'btns'):
            self.btns.setVisible('tol' in names)

    def _cell(self, group, name, label, widget=None, hint='', entry=True):
        """One labelled box inside a two-per-line group (`group` is a name made by _group)."""
        f = QWidget()
        lay = QVBoxLayout(f)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        lab = widgets.label(label, 'hint')
        lay.addWidget(lab)
        w = widget if widget is not None else QLineEdit()
        lay.addWidget(w)
        if widget is None and entry:
            self.entries.append(w)
        if hint:
            C.tip(w, hint)
            C.tip(lab, hint)
        self.cells[name] = f
        f._label = lab
        self._groups[group][1].append(name)
        return w

    def _group(self, parent_lay, name, wide=()):
        box = QWidget()
        grid = QGridLayout(box)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(SZ.sm)
        grid.setVerticalSpacing(SZ.xs)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self._groups[name] = (grid, [], wide)
        parent_lay.addWidget(box)
        return box

    def _arrange(self, name):
        grid, names, wide = self._groups[name]
        for n in names:
            grid.removeWidget(self.cells[n])
        r = c = 0
        for n in names:
            w = self.cells[n]
            if not self._visible.get(n, True):
                w.setVisible(False)
                continue
            if n in wide:
                if c:
                    r, c = r + 1, 0
                grid.addWidget(w, r, 0, 1, 2)
                w.setVisible(True)                                    # after addWidget: a first-time reparent hides the widget
                r += 1
                continue
            grid.addWidget(w, r, c)
            w.setVisible(True)
            c += 1
            if c == 2:
                r, c = r + 1, 0

    def _combo(self, items=(), editable=False):
        b = QComboBox()
        b.setEditable(editable)
        b.addItems(list(items))
        b.setMinimumContentsLength(4)
        b.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        return b

    def _build_point(self, lay):
        self._group(lay, 'point', wide=('func', 'sensor', 'coil'))
        func = self._combo()
        self._cell('point', 'func', 'This row tests', func, 'What this row measures. Pick it for a new row; on a test row it moves the row to that section.')
        func.activated.connect(lambda _i: self.win.function_chosen(func.currentText()))
        self.func_box = func
        self.v['func'] = C.Bind(func)
        self.nominal_e = self._cell('point', 'nominal', 'Nominal Value', None, 'The value to test, for example 5. The unit comes from Units.')
        self.v['nominal'] = C.Bind(self.nominal_e)
        self.units_c = self._cell('point', 'units', 'Units', self._combo(editable=True), 'The unit the numbers in these boxes are in (Units of Measure). Display only.')
        self.entries.append(self.units_c)
        self.v['units'] = C.Bind(self.units_c)
        self.freq_box = FreqBox()
        self.entries.append(self.freq_box.edit)
        self.v['freq'] = C.Bind(self._cell('point', 'freq', 'Frequency', self.freq_box, 'For AC and frequency tests: type the number and pick the unit (Hz, kHz, MHz, GHz).'))
        self.level_box = LevelBox()
        self.entries.append(self.level_box.edit)
        self.v['level'] = C.Bind(self._cell('point', 'level', 'Signal level', self.level_box, 'The level of the signal applied while a frequency, period or bandwidth is tested: type the number and pick the unit (V, mV, \u00b5V, Vpp ...). A level in the other basis than the one the test stores (rms or peak-to-peak) is converted for a sine wave.'))
        self.v['expect'] = C.Bind(self._cell('point', 'expect', 'Beeper should be', self._combo(['on', 'off'])))
        self.sensor_box = SensorBox()
        self.v['sensor'] = C.Bind(self._cell('point', 'sensor', 'Sourced as', self.sensor_box, 'How the temperature is sourced: the thermocouple type or RTD the calibrator simulates. It decides which standard rows and which scope lines give the uncertainty, so it must be chosen for every temperature row. "Whole section" gives every row of this section the same choice.'))
        self.sensor_box.set_choices(sens.sensor_types())
        self.sensor_box.section_btn.clicked.connect(lambda: self.win.sensor_section(self.sensor_box.get_value()))
        self.coil_box = CoilBox()
        self.v['coil'] = C.Bind(self._cell('point', 'coil', 'Clamp meter', self.coil_box, 'Tick this when the calibrator drives this current through the 50-turn coil (Fluke 5500A/COIL). '
                                           'The nominal stays what the clamp reads; the calibrator sources nominal / 50, and the uncertainty is the coil\'s own (RSS with the clamp / coil '
                                           'interaction). "Whole section" gives every row of this section the same choice.'))
        self.coil_box.section_btn.clicked.connect(lambda: self.win.coil_section(self.coil_box.get_value()))
        self.point_names = ('func', 'nominal', 'units', 'freq', 'level', 'expect', 'sensor', 'coil')

    def _build_tolerance(self, lay):
        # The limits come first: LOW and HIGH (absolute).  They are READ-ONLY displays of what the tolerance below works out; the tolerance chips / boxes,
        # Asymmetrical tolerance and Calc are the only way to change them.
        self._group(lay, 'limit')
        self.low_e = self._cell('limit', 'low', 'Low limit', None, 'The lowest reading that passes (absolute value, for example 4.9965 V). Worked out from the tolerance below; it cannot be typed.')
        self.high_e = self._cell('limit', 'high', 'High limit', None, 'The highest reading that passes (absolute value, for example 5.0035 V). Worked out from the tolerance below; it cannot be typed.')
        for e in (self.low_e, self.high_e):
            e.setReadOnly(True)
        self.v['low'], self.v['high'] = C.Bind(self.low_e), C.Bind(self.high_e)
        self.limit_note = C.small('Calculated from the tolerance below; they are read-only here.')
        lay.addWidget(self.limit_note)
        self.clear_typed_b = C.button('Clear typed limits', self.win.clear_typed_limits,
                                      tooltip='This row still has limits that were typed earlier. Clear them so the limits come from the tolerance (or press Calc to replace them).')
        lay.addWidget(self.clear_typed_b, 0, Qt.AlignmentFlag.AlignLeft)
        self.chip_frame = QWidget()
        self.chip_lay = C.FlowLayout(self.chip_frame)
        self.chips = []
        for key, label, hint in M.SPEC_TYPES:
            chip = Chip(CHIP_LABELS[key])
            C.tip(chip, f'{label}: {hint}')
            chip.clicked.connect(lambda _c=False: self.types_changed())
            self.chip_lay.addWidget(chip)
            self.chips.append(chip)
            self.types[key] = C.Bind(chip)
        lay.addWidget(self.chip_frame)
        # Asymmetrical tolerance: which side the boxes below are for (the two radios drive the Operand box kept in the Asymmetrical section)
        self.side_box = QWidget()
        sl = QHBoxLayout(self.side_box)
        sl.setContentsMargins(0, 2, 0, 2)
        sl.setSpacing(10)
        sl.addWidget(widgets.label('Boxes below are for:', 'hint'))
        self.side_plus, self.side_minus = QRadioButton('+ above'), QRadioButton('\u2212 below')
        for rb, tip in ((self.side_plus, 'Type the tolerance for readings ABOVE the nominal.'), (self.side_minus, 'Type the tolerance for readings BELOW the nominal.')):
            C.tip(rb, tip)
            rb.clicked.connect(lambda _c=False: self.side_clicked())
            sl.addWidget(rb)
        self.side_plus.setChecked(True)
        sl.addStretch(1)
        lay.addWidget(self.side_box)
        # Asymmetrical tolerance is floor values only: one box for the side above the nominal and one for the side below, both in view
        self._group(lay, 'asym_floor')
        # low side on the left, high side on the right (the order the cells are created in is the order they are laid out)
        self.v['floor_minus'] = C.Bind(self._cell('asym_floor', 'floor_minus', 'Floor below nominal (\u2212)', None, 'A fixed amount (in the Units) taken from the nominal for the low limit, for example 1.'))
        self.v['floor_plus'] = C.Bind(self._cell('asym_floor', 'floor_plus', 'Floor above nominal (+)', None, 'A fixed amount (in the Units) added to the nominal for the high limit, for example 2.'))
        self._legacy_asym = False
        # Several rows at once: how the rows are spaced (shown while 'Make several rows at once' is ticked)
        self.mode_box = QWidget()
        ml = QVBoxLayout(self.mode_box)
        ml.setContentsMargins(0, 2, 0, 2)
        ml.setSpacing(2)
        ml.addWidget(widgets.label('Several rows: spacing', 'hint'))
        modes = QGridLayout()
        self.mode_var = RadioVar()
        for i, (key, label, hint) in enumerate(M.MULTI_MODES):
            rb = QRadioButton(label)
            C.tip(rb, hint)
            self.mode_var.add(key, rb)
            modes.addWidget(rb, i // 2, i % 2)
        self.mode_var.set('span')
        self.v['multi_mode'] = self.mode_var
        ml.addLayout(modes)
        lay.addWidget(self.mode_box)
        self.passfail_l = C.small('This test is pass / fail: there is no tolerance to type.')
        lay.addWidget(self.passfail_l)
        self._group(lay, 'tol', wide=('calc',))
        iv_box = QWidget()
        ivl = QHBoxLayout(iv_box)
        ivl.setContentsMargins(0, 0, 0, 0)
        ivl.setSpacing(6)
        iv_e = QLineEdit()
        self.iv_ppm_cb = QCheckBox('ppm')
        C.tip(self.iv_ppm_cb, 'Tick when the number is parts per million of the value instead of percent.')
        self.iv_ppm_cb.setMinimumWidth(16 + 8 + self.iv_ppm_cb.fontMetrics().horizontalAdvance('ppm') + 14)       # the last letter was clipped
        ivl.addWidget(iv_e, 1)
        ivl.addWidget(self.iv_ppm_cb)
        self._cell('tol', 'iv', '% of reading', iv_box, 'How many percent of the value being tested, for example 0.05 (% of I.V., the input value).')
        self.entries.append(iv_e)
        C.tip(iv_e, 'How many percent of the value being tested, for example 0.05 (% of I.V., the input value).')
        self.v['iv'] = C.Bind(iv_e)
        self.b['iv_ppm'] = C.Bind(self.iv_ppm_cb)
        for key, label, hint in (('fs', '% of range', 'How many percent of the full scale of the range, for example 0.01 (% of F.S.).'),
                                 ('fs_scale', 'F.S. (full scale)', 'The full scale of the range this row is on, for example 10 V. Leave it as it is to keep the range.'),
                                 ('floor', 'Floor (fixed value)', 'A fixed amount added to the tolerance, in the Units, for example 20.'),
                                 ('db', '± dB', 'A tolerance in dB, for example 0.5.'),
                                 ('calc', 'Accuracy statement, as the manual prints it', 'Calculator: for example 0.05 % of reading + 2 counts.')):
            self.v[key] = C.Bind(self._cell('tol', key, label, None, hint))
        self.tol_names = ('iv', 'fs', 'fs_scale', 'floor', 'db', 'calc')
        self.hint_l = C.small('Tick a tolerance type to show its box.')
        lay.addWidget(self.hint_l)
        self.aside_l = C.ToneLabel('', 'warn')                     # which tolerance types Asymmetrical set aside (they come back when it is unticked)
        self.aside_l.hide()
        lay.addWidget(self.aside_l)
        self.preview_l = C.ToneLabel('', 'info')                  # what Calc would give for the boxes as they are now (nothing is changed until Calc)
        self.preview_l.hide()
        lay.addWidget(self.preview_l)
        self._pv_sig = None
        self._pv_timer = QTimer(self)
        self._pv_timer.setInterval(450)
        self._pv_timer.timeout.connect(self.refresh_preview)
        self._pv_timer.start()
        self.btns = QWidget()                                   # the footer of the panel: always in view at the bottom right, outside the scrolling sections
        bl = QHBoxLayout(self.btns)
        bl.setContentsMargins(0, 4, 8, 0)
        bl.setSpacing(8)
        bl.addStretch(1)
        self.calc_b = C.button('Calc', self.win.calc, 'primary', tooltip='Work out the calibration tolerance of this row from the boxes and put it in the sheet (Enter in any box does the same).')
        self.copy_b = C.button('Copy tolerance to rows below', self.win.copy_down, tooltip='Give the rows under this one, in the same section, the same tolerance as this row.')
        bl.addWidget(self.copy_b)
        bl.addWidget(self.calc_b)
        self.layout().addWidget(self.btns)

    def _build_uncertainty(self, lay):
        self.uncert_l = C.ToneLabel('')
        lay.addWidget(self.uncert_l)

    def set_uncertainty(self, text, level='ok'):
        """Rule 5 for the selected row (text from GridModel.uncertainty_line()); a row with no source is shown in the warning colour."""
        self.uncert_l.setText(text or 'Not worked out for this row.')
        self.uncert_l.set_tone({'warn': 'warn', 'info': 'info'}.get(level, 'ok'))

    def _build_multi(self, lay):
        self.multi_cb = QCheckBox('Make several rows at once')
        C.tip(self.multi_cb, 'Multiple Test Points: Nominal Value is the lowest, High is the last. Choose below how the rows are spaced.')
        self.multi_cb.clicked.connect(lambda _c=False: self.multi_changed())
        lay.addWidget(self.multi_cb)
        self.b['multi'] = C.Bind(self.multi_cb)
        self.multi_box = QWidget()
        mb = QVBoxLayout(self.multi_box)
        mb.setContentsMargins(0, 0, 0, 0)
        mb.addWidget(widgets.label('Pick how the rows are spaced under Limits and tolerance.', 'hint'))
        self._group(mb, 'multi')
        self.v['multi_high'] = C.Bind(self._cell('multi', 'multi_high', 'High (last value)', None, 'The last value the rows should reach.'))
        self.v['multi_n'] = C.Bind(self._cell('multi', 'multi_n', 'n (how many / step)', None, 'How many points (Lo to High) or the size of the step (n %, n Units, n ppm).'))
        lay.addWidget(self.multi_box)

    def _build_asym(self, lay):
        self.asym_cb = QCheckBox('Different tolerance above and below')
        C.tip(self.asym_cb, 'Asymmetrical Tol: the limit below the nominal differs from the one above it. Two floor boxes appear, low on the left and high on the right. The other tolerance types are set aside while this is ticked and come back when you untick it.')
        self.asym_cb.clicked.connect(lambda _c=False: self.asym_changed())
        lay.addWidget(self.asym_cb)
        self.b['asym'] = C.Bind(self.asym_cb)
        self.asym_box = QWidget()
        al = QVBoxLayout(self.asym_box)
        al.setContentsMargins(0, 4, 0, 0)
        al.addWidget(widgets.label('Type a floor value for the side above and one for the side below the nominal (under Limits and tolerance), then press Calc.', 'hint', wrap=True))
        self.operand_box = self._combo(['±', '+', '-'])           # holds the side; the two radios under Limits and tolerance change it
        self.operand_box.setVisible(False)
        self.operand_box.setEnabled(False)
        self.v['operand'] = C.Bind(self.operand_box)
        lay.addWidget(self.asym_box)

    def _build_res(self, lay):
        self._group(lay, 'res')
        self.v['decs'] = C.Bind(self._cell('res', 'decs', 'Decimals shown', None,
                                           'Display Decs.: how many decimal places the instrument shows in these units, for example 4 for 5.0000. Auto Res turns it into the resolution.'))
        self.res_e = self._cell('res', 'res', 'Resolution', None, 'Meas Res: the smallest step the instrument display shows in this range, for example 10 µV. Rows on the same range share it.')
        self.res_e.setEnabled(False)
        self.v['res'] = C.Bind(self.res_e)
        self.auto_cb = QCheckBox('Work out from the decimals')
        C.tip(self.auto_cb, 'Auto Res: work the resolution out from Display Decs (or from the decimals you typed in Nominal Value).')
        self.auto_cb.clicked.connect(lambda _c=False: self.auto_changed())
        lay.addWidget(self.auto_cb)
        self.b['auto_res'] = C.Bind(self.auto_cb)

    def _build_rules(self, lay):
        lay.addWidget(widgets.label('Test point rules (pick one to change it)', 'hint'))
        self.def_box = self._combo()
        self.def_box.activated.connect(lambda _i: self.win.definition_chosen(self.def_box.currentText()))
        C.tip(self.def_box, 'Test Point Definitions: the rules of the test point calculator for this section. Pick one to change it, or New rule...')
        lay.addWidget(self.def_box)
        self.v['definition'] = C.Bind(self.def_box)

    def _build_row(self, lay):
        lay.addWidget(widgets.label('Row remark (optional)', 'hint'))
        self.remark_e = QLineEdit()
        C.tip(self.remark_e, 'A note the operator sees with this row. A * appears next to its step number.')
        self.remark_e.returnPressed.connect(lambda: self.win.remark_set())
        self.remark_e.editingFinished.connect(lambda: self.win.remark_set(quiet=True))
        lay.addWidget(self.remark_e)
        self.run_cb = QCheckBox('Run this row')
        C.tip(self.run_cb, 'Untick to keep the row on the sheet but leave it out of the procedure.')
        self.run_cb.setChecked(True)
        self.run_cb.clicked.connect(lambda _c=False: self.win.run_set())
        lay.addWidget(self.run_cb)
        self.remark_v, self.run_v = C.Bind(self.remark_e), C.Bind(self.run_cb)

    # ---- visibility
    def _mark_aside(self):
        """Asymmetrical uses the floor boxes only: the other tolerance chips are greyed and a line names the ones that were set aside."""
        on = bool(self.b['asym'].get()) and not self._legacy_asym
        keys = [k for k, _l, _h in M.SPEC_TYPES]
        for k, chip in zip(keys, self.chips):
            chip.setEnabled(not (on and k != 'floor'))
        before = getattr(self, '_types_before_asym', None) or {}
        names = [CHIP_LABELS[k] for k in keys if k != 'floor' and before.get(k)]
        if on and names:
            self.aside_l.setText('Set aside while Asymmetrical is ticked (they come back when you untick it): ' + ', '.join(names) + '.')
            self.aside_l.show()
        else:
            self.aside_l.hide()

    def _form_signature(self):
        try:
            return repr(sorted(self.form().items(), key=lambda kv: kv[0]))
        except Exception:
            return None

    def refresh_preview(self):
        """Every so often: when the boxes differ from what the row has, show the limits Calc would give (grey), or what is wrong (amber).  Changes nothing."""
        if not self.isVisible() or not hasattr(self, 'preview_l'):
            return
        sig = self._form_signature()
        if sig is None or sig == self._pv_sig or not self.win.model.selected_row():
            return
        self._pv_sig = sig
        try:
            kind, text = self.win.model.preview_limits(self.form(), self.win.model.sel_key)
        except Exception:
            self.preview_l.hide()
            return
        if not text:
            self.preview_l.hide()
            return
        self.preview_l.setText(('Calc would give: ' if kind == 'limits' else 'Not ready: ') + text)
        self.preview_l.set_tone('info' if kind == 'limits' else 'warn')
        self.preview_l.show()

    def types_changed(self):
        self.show_fields()

    def multi_changed(self):
        self.show_fields()

    def auto_changed(self):
        self.res_e.setEnabled(not self.b['auto_res'].get())

    def asym_changed(self):
        on = bool(self.b['asym'].get())
        if on:
            self.save_side()                                   # keep what was typed for the ordinary tolerance
            self._types_before_asym = {k: bool(self.types[k].get()) for k in M.SPEC_ORDER}
            self._legacy_asym = False
            for k in M.SPEC_ORDER:
                self.types[k].set(k == 'floor')                # asymmetrical = floor values only
            self.v['floor_plus'].set(self.sides['plus'].get('floor', ''))
            self.v['floor_minus'].set(self.sides['minus'].get('floor', ''))
        else:
            self.sides['plus']['floor'] = self.v['floor_plus'].get() or self.sides['plus'].get('floor', '')
            before = getattr(self, '_types_before_asym', None)
            if before:                                          # the types that were ticked before Asymmetrical was ticked come back
                for k in M.SPEC_ORDER:
                    self.types[k].set(before.get(k, False))
                self._types_before_asym = None
        self.operand_box.setEnabled(on and self._legacy_asym)
        self.operand_now = 'plus'
        self.v['operand'].set('+' if on and self._legacy_asym else '±')
        self.load_side()
        self._sync_side()
        self.show_fields()
        self._mark_aside()

    def operand_changed(self):
        self.save_side()
        self.operand_now = 'minus' if self.v['operand'].get() == '-' else 'plus'
        self.load_side()
        self._sync_side()

    def side_clicked(self):
        self.v['operand'].set('-' if self.side_minus.isChecked() else '+')
        self.operand_changed()

    def _sync_side(self):
        self.side_minus.setChecked(self.v['operand'].get() == '-')
        self.side_plus.setChecked(self.v['operand'].get() != '-')

    def save_side(self):
        s = self.sides[self.operand_now]
        s.update(iv=self.v['iv'].get(), iv_ppm=self.b['iv_ppm'].get(), fs=self.v['fs'].get(), floor=self.v['floor'].get(), db=self.v['db'].get(), calc=self.v['calc'].get())

    def load_side(self):
        s = self.sides[self.operand_now]
        self.v['iv'].set(s['iv']), self.b['iv_ppm'].set(bool(s['iv_ppm'])), self.v['fs'].set(s['fs']), self.v['floor'].set(s['floor']), self.v['db'].set(s['db'])
        self.v['calc'].set(s['calc'])

    def show_fields(self):
        st = self._state
        fields = st.get('fields', {})
        self.level_box.set_basis(fields.get('level_basis', 'rms'))
        want = {'func': True, 'nominal': True, 'units': True, 'freq': fields.get('frequency', False), 'level': fields.get('amplitude', False),
                'expect': fields.get('expect', False), 'sensor': fields.get('sensor', False), 'coil': fields.get('coil', False),
                'iv': self.types['iv'].get(), 'fs': self.types['fs'].get(), 'fs_scale': self.types['fs'].get(), 'floor': self.types['floor'].get(),
                'db': self.types['db'].get(), 'calc': self.types['calc'].get(), 'low': False, 'high': False}      # the grid shows the limits; the read-only boxes only took room
        passfail = bool(st.get('passfail'))
        asym = bool(self.b['asym'].get()) and not passfail
        floor_only = asym and not self._legacy_asym
        if floor_only:                                            # asymmetrical: the two floor boxes only, no tolerance types
            for k in self.tol_names:
                want[k] = False
        want['floor_plus'] = want['floor_minus'] = floor_only
        if passfail:
            for k in self.tol_names:
                want[k] = False
            want['low'] = want['high'] = False
        typed_limits = bool(st.get('typed_limits')) and not passfail
        self.limit_note.setText(M.TYPED_LIMITS_NOTE if typed_limits else '')
        self.limit_note.setVisible(typed_limits)                  # only an old sheet's typed limits need a word of explanation
        self.clear_typed_b.setVisible(typed_limits)
        self._visible = want
        self._arrange_all()
        self.chip_frame.setVisible(not passfail and not floor_only)
        self.passfail_l.setVisible(passfail)
        self.hint_l.setVisible(not passfail and not floor_only and not any(self.types[k].get() for k in M.SPEC_ORDER))
        self.multi_box.setVisible(bool(self.b['multi'].get()))
        self.asym_box.setVisible(bool(self.b['asym'].get()))
        self.side_box.setVisible(asym and self._legacy_asym)
        self.mode_box.setVisible(bool(self.b['multi'].get()) and not passfail)
        self.sections['multi'].set_note('ON' if self.b['multi'].get() else '', self.b['multi'].get())
        self.sections['asym'].set_note('ON' if self.b['asym'].get() else '', self.b['asym'].get())

    def _arrange_all(self):
        for name in self._groups:
            self._arrange(name)

    def state_passfail(self):
        return bool(self._state.get('passfail'))

    # ---- model <-> boxes
    def set_header(self, row, total):
        if row['kind'] == 'header':
            self.title_l.setText('SECTION')
            self.of_l.setText(f'Row {row["n"]} of {total}')
            self.sub_l.setText(row['function'])
        elif row['kind'] == 'blank':
            self.title_l.setText('NEW ROW')
            self.of_l.setText('')
            self.sub_l.setText('Choose what this row tests, then type the value to test.')
        else:
            self.title_l.setText(f'ROW {row["n"]}')
            self.of_l.setText(f'Row {row["n"]} of {total}')
            self.sub_l.setText(row['function'])               # no step number on screen (the printed sheet keeps it)

    def load(self, state):
        """Fill the boxes from GridModel.panel_state()."""
        self._state = state
        form = state['form']
        self.sides = {'plus': dict(form['plus']), 'minus': dict(form['minus'])}
        self.operand_now = 'plus'
        self._types_before_asym = None
        self._pv_sig = None
        if hasattr(self, 'preview_l'):
            self.preview_l.hide()
        for k in ('nominal', 'units', 'freq', 'level', 'expect', 'sensor', 'coil', 'fs_scale', 'multi_high', 'multi_n', 'decs', 'res', 'multi_mode', 'low', 'high'):
            self.v[k].set(form[k])
        for k in M.SPEC_ORDER:
            self.types[k].set(k in form['types'])
        self.b['multi'].set(bool(form['multi'])), self.b['asym'].set(bool(form['asym'])), self.b['auto_res'].set(bool(form['auto_res']))
        self.v['operand'].set('+' if form['asym'] else '±')
        self._legacy_asym = bool(form['asym']) and bool(set(form['types']) - {'floor'})        # a stored asymmetrical row with other tolerance types keeps the full boxes
        self.operand_box.setEnabled(bool(form['asym']) and self._legacy_asym)
        self.v['floor_plus'].set(form['plus'].get('floor', ''))
        self.v['floor_minus'].set(form['minus'].get('floor', ''))
        self._sync_side()
        self.load_side()
        C.set_items(self.units_c, state['unit_choices'])
        self.units_c.setEditText(form['units'])
        self._choices = self.win.model.function_choices()
        C.set_items(self.func_box, [c['label'] for c in self._choices])
        self.v['func'].set(state['function'])
        self.func_box.setEnabled(bool(state['can_edit'] or state['kind'] == 'blank'))
        defs = self.win.model.definition_rows(state['fid']) if state['fid'] else []
        self._defs = defs
        C.set_items(self.def_box, ['New rule...'] + [d['label'] for d in defs])
        self.v['definition'].set('')
        self.auto_changed()
        if form['asym']:
            self.sections['asym'].set_open(True)
        header = state['kind'] == 'header'
        self._pack_sections(('rules',) if header and state['fid'] else () if header else self.SECTION_ORDER)
        if header and state['fid']:
            self.sections['rules'].set_open(True)
        self.show_fields()
        usable = bool(state['can_edit'])
        blank = state['kind'] == 'blank'
        self.copy_b.setText('Use tolerance of row above' if blank else 'Copy tolerance to rows below')
        self.calc_b.setEnabled(usable)
        self.copy_b.setEnabled(usable or blank)
        self._mark_aside()
        self._pv_sig = self._form_signature()               # the boxes as the row has them: only a change from here is previewed
        try:
            self.set_uncertainty(*self.win.model.uncertainty_line())
        except Exception:                                    # the source line is information only: never stop the panel from loading
            self.set_uncertainty('')

    def adopt_tolerance(self, form):
        """Put another row's tolerance (a panel form) in the tolerance boxes, leaving the value being typed alone."""
        self.sides = {'plus': dict(form['plus']), 'minus': dict(form['minus'])}
        for k in M.SPEC_ORDER:
            self.types[k].set(k in form['types'])
        self.v['fs_scale'].set(form['fs_scale'])
        self.b['asym'].set(bool(form['asym']))
        self.v['operand'].set('+' if form['asym'] else '±')
        self.operand_box.setEnabled(bool(form['asym']))
        self.operand_now = 'plus'
        self._sync_side()
        self.load_side()
        self.show_fields()

    def form(self):
        """The boxes as a form dict for GridModel.calc_row()."""
        asym = bool(self.b['asym'].get())
        types = [k for k in M.SPEC_ORDER if self.types[k].get()]
        plus, minus = dict(self.sides['plus']), dict(self.sides['minus'])
        if asym and not self._legacy_asym:
            types = ['floor']
            plus, minus = dict(M.GridModel.blank_side(), floor=self.v['floor_plus'].get()), dict(M.GridModel.blank_side(), floor=self.v['floor_minus'].get())
        else:
            self.save_side()
            plus, minus = dict(self.sides['plus']), dict(self.sides['minus'])
        return dict(types=types, plus=plus, minus=minus, asym=asym,
                    operand='-' if self.v['operand'].get() == '-' else '+', fs_scale=self.v['fs_scale'].get(), nominal=self.v['nominal'].get(), units=self.v['units'].get(),
                    freq=self.v['freq'].get(), level=self.v['level'].get(), expect=self.v['expect'].get() or 'on', sensor=self.v['sensor'].get(), coil=bool(self.v['coil'].get()), multi=bool(self.b['multi'].get()),
                    multi_mode=self.v['multi_mode'].get() or 'span', multi_high=self.v['multi_high'].get(), multi_n=self.v['multi_n'].get(), decs=self.v['decs'].get(),
                    res=self.v['res'].get(), auto_res=bool(self.b['auto_res'].get()))

    def definition_id(self, label):
        return next((d['id'] for d in self._defs if d['label'] == label), None)


SpecPanel = Inspector
