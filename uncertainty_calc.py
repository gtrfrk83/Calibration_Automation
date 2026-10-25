"""Uncertainty calculator: a GUM / ILAC-P14 style budget from spot readings (repeatability and reproducibility) and Type B components.  Pure Python: no Qt, no files,
no databases.  Display only: it does not touch any procedure, limit or instrument.

    rep = repeatability([10.0001, 10.0003, ...], averaged=1)          # Type A from one set of readings taken under the same conditions
    rpr = reproducibility({'Day 1': [...], 'Day 2': [...]})          # between-group component of readings taken on different days / operators / set-ups
    comps = [component('Standard (certificate)', 0.0004, 'k2'), component('Resolution', 0.00005, 'rect')]
    res = budget(comps, rep=rep, rpr=rpr, tolerance=0.01, cmc=0.0008)

Method (GUM, ILAC-P14 / A2LA practice):
  * Type A repeatability: s = sample standard deviation (n - 1); u = s / sqrt(m), m = readings averaged in the reported result; dof = n - 1.
  * Reproducibility (groups of readings): the between-group standard deviation from a one-way analysis of variance, sigma_b^2 = (MSB - MSW) / n0 (negative -> 0),
    n0 = (N - sum(n_i^2) / N) / (g - 1) (exact for unequal group sizes); dof = g - 1 (an approximation, stated on screen).  Without a separate repeatability set the
    pooled within-group standard deviation (dof N - g) is the repeatability, so nothing is counted twice.
  * Type B: u = value / divisor (k = 2 or 3 normal, 1 = already a standard uncertainty, rectangular sqrt 3, triangular sqrt 6, U-shaped sqrt 2), times the
    sensitivity coefficient c; dof = infinity unless given.
  * Combined u_c = sqrt(sum (c u)^2); effective degrees of freedom by Welch-Satterthwaite; coverage factor k = Student t for 95.45 % at dof_eff truncated to a whole number (GUM G.4; 2.00 for large dof_eff)
    or a fixed k you choose; U = k u_c.  The reported value is rounded UP to 2 significant figures (never smaller than the budget) and never below your CMC, if given.
Every number here is shown to the person, with its working; nothing is hidden."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

INF = float('inf')
P95 = math.erf(2 / math.sqrt(2))                 # 0.9544997...: the coverage probability of k = 2 for a normal distribution

DISTRIBUTIONS = {                                # key -> (label, divisor)
    'k2': ('Normal, k = 2 (certificate, 95 %)', 2.0),
    'k3': ('Normal, k = 3', 3.0),
    'std': ('Already a standard uncertainty (k = 1)', 1.0),
    'rect': ('Rectangular (+/- limits)', math.sqrt(3)),
    'tri': ('Triangular (+/- limits)', math.sqrt(6)),
    'u': ('U-shaped (arcsine)', math.sqrt(2)),
}


class CalcError(ValueError):
    """Something the person typed that cannot be used; the message says what to change."""


def _num(x, what):
    try:
        v = float(x)
    except (TypeError, ValueError):
        raise CalcError(f'{what}: "{x}" is not a number.')
    if math.isnan(v) or math.isinf(v):
        raise CalcError(f'{what}: "{x}" is not a usable number.')
    return v


# ---------------------------------------------------------------------------------------------------------------------------------------- statistics
def mean(values):
    return math.fsum(values) / len(values)


def stdev(values):
    """Sample standard deviation (n - 1)."""
    n = len(values)
    if n < 2:
        raise CalcError('At least 2 readings are needed to work out a standard deviation.')
    m = mean(values)
    return math.sqrt(math.fsum((v - m) ** 2 for v in values) / (n - 1))


def parse_readings(text_or_list):
    """Readings from pasted text (one per line or separated by commas / spaces / semicolons / tabs) or from a list; blanks are skipped."""
    if isinstance(text_or_list, (list, tuple)):
        raw = list(text_or_list)
    else:
        raw = [t for t in str(text_or_list).replace(';', ' ').replace(',', ' ').split()]
    out = []
    for i, t in enumerate(raw, 1):
        if t is None or (isinstance(t, str) and not t.strip()):
            continue
        out.append(_num(t, f'Reading {i}'))
    return out


# ---------------------------------------------------------------------------------------------------------------------------------------- Student t
def _betacf(a, b, x):
    tiny, qab, qap, qam = 1e-300, a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 400):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > tiny else tiny)
        c = 1 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > tiny else tiny)
        c = 1 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1) < 1e-15:
            break
    return h


def _betainc(a, b, x):
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    bt = math.exp(math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1) / (a + b + 2):
        return bt * _betacf(a, b, x) / a
    return 1 - bt * _betacf(b, a, 1 - x) / b


def t_two_sided_probability(t, dof):
    """P(|T| <= t) for Student's t with `dof` degrees of freedom."""
    if dof == INF or dof > 1e7:
        return math.erf(t / math.sqrt(2))
    return 1 - _betainc(dof / 2, 0.5, dof / (dof + t * t))


def t_factor(dof, probability=P95):
    """The coverage factor k for the two-sided `probability` (default 95.45 %, the one k = 2 stands for) at `dof` degrees of freedom."""
    if dof is None or dof == INF or dof > 1e7:
        return 2.0 if probability == P95 else math.sqrt(2) * _inverse_erf(probability)
    lo, hi = 0.0, 1e4
    for _ in range(200):
        mid = (lo + hi) / 2
        if t_two_sided_probability(mid, dof) < probability:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _inverse_erf(y):
    lo, hi = 0.0, 10.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if math.erf(mid) < y:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# ---------------------------------------------------------------------------------------------------------------------------------------- components
@dataclass
class Component:
    name: str
    value: float                      # the quoted value (half-width, expanded uncertainty or standard uncertainty, see `dist`)
    dist: str = 'k2'
    sensitivity: float = 1.0
    dof: float = INF
    kind: str = 'B'                   # 'A' for the ones worked out from readings
    note: str = ''

    @property
    def divisor(self):
        return DISTRIBUTIONS[self.dist][1]

    @property
    def u(self):
        """Standard uncertainty of the quantity itself."""
        return abs(self.value) / self.divisor

    @property
    def contribution(self):
        """Contribution to the combined standard uncertainty: |c| u."""
        return abs(self.sensitivity) * self.u


def component(name, value, dist='k2', sensitivity=1.0, dof=INF, kind='B', note=''):
    if dist not in DISTRIBUTIONS:
        raise CalcError(f'{name}: unknown distribution "{dist}".')
    v = _num(value, f'{name or "Component"} value')
    c = _num(sensitivity, f'{name or "Component"} sensitivity')
    d = INF if dof in (None, '', INF) else _num(dof, f'{name or "Component"} degrees of freedom')
    if d <= 0:
        raise CalcError(f'{name}: the degrees of freedom must be above 0.')
    return Component(name or 'Component', v, dist, c, d, kind, note)


# ---------------------------------------------------------------------------------------------------------------------------------------- Type A
@dataclass
class Repeatability:
    values: list
    averaged: int
    n: int = 0
    mean: float = 0.0
    s: float = 0.0
    u: float = 0.0
    dof: float = 0.0
    from_groups: bool = False

    def component(self):
        note = f'{self.n} readings, s = {self.s:.6g}, averaged m = {self.averaged}: u = s / sqrt(m)'
        if self.from_groups:
            note = f'pooled within-group s from {self.n} readings (dof {self.dof:g}), m = {self.averaged}: u = s / sqrt(m)'
        return Component('Repeatability (Type A)', self.u, 'std', 1.0, self.dof, 'A', note)


def repeatability(values, averaged=None):
    vals = parse_readings(values)
    n = len(vals)
    if n < 2:
        raise CalcError('Repeatability needs at least 2 readings.')
    m = n if averaged in (None, '', 0) else int(_num(averaged, 'Readings averaged'))
    if m < 1:
        raise CalcError('The number of readings averaged in the result must be at least 1.')
    s = stdev(vals)
    return Repeatability(vals, m, n, mean(vals), s, s / math.sqrt(m), n - 1)


@dataclass
class Reproducibility:
    groups: dict
    g: int = 0
    N: int = 0
    grand_mean: float = 0.0
    group_means: dict = field(default_factory=dict)
    msb: float = 0.0
    msw: float = 0.0
    n0: float = 0.0
    sigma_b: float = 0.0
    dof_between: float = 0.0
    dof_within: float = 0.0
    s_within: float = 0.0

    def component(self):
        note = (f'{self.g} groups, {self.N} readings: between-group sigma_b = sqrt((MSB - MSW) / n0) = {self.sigma_b:.6g} '
                f'(MSB {self.msb:.6g}, MSW {self.msw:.6g}, n0 {self.n0:.4g}); dof = g - 1 (approximate)')
        return Component('Reproducibility (Type A)', self.sigma_b, 'std', 1.0, self.dof_between, 'A', note)


def reproducibility(groups):
    """`groups` = {name: readings}.  Groups with fewer than 1 reading are ignored; every group should have at least 2 for the within-group part."""
    clean = {}
    for name, vals in (groups or {}).items():
        v = parse_readings(vals)
        if v:
            clean[str(name)] = v
    g = len(clean)
    if g < 2:
        raise CalcError('Reproducibility needs readings in at least 2 groups (days, operators or set-ups).')
    sizes = {k: len(v) for k, v in clean.items()}
    N = sum(sizes.values())
    if N - g < 1:
        raise CalcError('Reproducibility needs at least 2 readings in one of the groups (to see the repeatability inside a group).')
    means = {k: mean(v) for k, v in clean.items()}
    grand = math.fsum(sum(v) for v in clean.values()) / N
    ssb = math.fsum(sizes[k] * (means[k] - grand) ** 2 for k in clean)
    ssw = math.fsum(math.fsum((x - means[k]) ** 2 for x in clean[k]) for k in clean)
    msb, msw = ssb / (g - 1), ssw / (N - g)
    n0 = (N - math.fsum(n * n for n in sizes.values()) / N) / (g - 1)
    sig2 = max(0.0, (msb - msw) / n0) if n0 > 0 else 0.0
    return Reproducibility(clean, g, N, grand, means, msb, msw, n0, math.sqrt(sig2), g - 1, N - g, math.sqrt(msw))


# ---------------------------------------------------------------------------------------------------------------------------------------- the budget
def ceil_sig(value, sig=2):
    """Round UP to `sig` significant figures (a reported uncertainty must not shrink)."""
    if not value or value <= 0:
        return 0.0
    step = 10 ** (math.floor(math.log10(value)) - sig + 1)
    out = round(math.ceil(round(value / step, 9)) * step, 15)
    return out if out >= value else value


@dataclass
class Result:
    components: list
    u_c: float
    dof_eff: float
    k: float
    k_mode: str
    U: float
    reported: float
    reported_note: str = ''
    tur: float | None = None
    cmc: float | None = None
    notes: list = field(default_factory=list)
    rep: Repeatability | None = None
    rpr: Reproducibility | None = None
    mean_value: float | None = None

    def shares(self):
        """[(component, percent of the combined variance)] in the order of the components."""
        total = math.fsum(c.contribution ** 2 for c in self.components)
        return [(c, (100 * c.contribution ** 2 / total) if total else 0.0) for c in self.components]


def budget(type_b=(), rep=None, rpr=None, k_mode='auto', fixed_k=2.0, tolerance=None, cmc=None, sig=2):
    """Combine everything.  rep / rpr are the results of repeatability() / reproducibility() (or None); type_b a list of component()s.
    k_mode 'auto' = Student t at the effective dof (95.45 %), 'fixed' = fixed_k.  Returns a Result; raises CalcError when there is nothing to combine."""
    comps, notes = [], []
    if rep is not None:
        comps.append(rep.component())
    elif rpr is not None:
        r = Repeatability([], 1, 0, 0.0, rpr.s_within, 0.0, rpr.dof_within, True)
        m = max(1, round(rpr.N / rpr.g))
        r.averaged, r.n, r.u = m, rpr.N, rpr.s_within / math.sqrt(m)
        comps.append(r.component())
        notes.append('No separate repeatability set: the pooled within-group standard deviation is used, with m = the average group size.')
    if rpr is not None:
        comps.append(rpr.component())
    comps.extend(type_b)
    live = [c for c in comps if c.contribution > 0]
    if not live:
        raise CalcError('There is nothing to combine yet: add readings or at least one component with a value.')
    u_c = math.sqrt(math.fsum(c.contribution ** 2 for c in live))
    denom = math.fsum((c.contribution ** 4) / c.dof for c in live if c.dof != INF)
    dof_eff = INF if denom == 0 else u_c ** 4 / denom
    if k_mode == 'fixed':
        k = _num(fixed_k, 'Coverage factor k')
        if k <= 0:
            raise CalcError('The coverage factor must be above 0.')
        mode = f'fixed k = {k:g}'
    else:
        k = t_factor(dof_eff if dof_eff == INF else max(1, math.floor(dof_eff + 1e-9)))     # GUM G.4: the effective dof is truncated down to a whole number
        mode = 'Student t, 95.45 % at the effective degrees of freedom (truncated to a whole number, GUM G.4)'
        if dof_eff != INF and dof_eff < 3:
            notes.append(f'The effective degrees of freedom are only {dof_eff:.2f}: take more readings to bring k down.')
    U = k * u_c
    reported = ceil_sig(U, sig)
    rnote = f'rounded up to {sig} significant figures'
    cmc_v = None
    if cmc not in (None, ''):
        cmc_v = _num(cmc, 'CMC')
        if reported < cmc_v:
            reported, rnote = cmc_v, 'raised to your CMC (a result is never reported below the scope CMC)'
    tur = None
    if tolerance not in (None, ''):
        tol = abs(_num(tolerance, 'Tolerance'))
        tur = tol / reported if reported else None
    mean_value = rep.mean if rep is not None else (rpr.grand_mean if rpr is not None else None)
    return Result(live, u_c, dof_eff, k, mode, U, reported, rnote, tur, cmc_v, notes, rep, rpr, mean_value)
