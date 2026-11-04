"""Callendar-Van Dusen conversion of a resistance to a temperature (Keithley DMM6500 Calibration Manual DMM6500-905-01 Rev. E, pp. 2-21 to 2-24).

    R(T) = R0 (1 + A T + B T^2 + C T^3 (T - 100))     -200 degC to 0 degC          (the C term only below 0 degC)
    R(T) = R0 (1 + A T + B T^2)                        0 degC to 850 degC
    A = alpha (1 + delta / 100)    B = -alpha delta 1E-4    C = -alpha beta 1E-8

`temperature(R, ...)` inverts it; the PT100 parameters of the manual (R0 100, alpha 0.00385055, beta 0.10863, delta 1.4999 = the ITS-90 PT100) are the default.
Pure Python, no I/O.  The manual's own worked example is the regression test: 18.99952 ohm -> -198.8900 degC, 99.99707 -> -0.0075, 189.99234 -> 238.6775 (tests/test_dmm6500_engine.py).
"""
from __future__ import annotations

from decimal import Decimal as D, getcontext

getcontext().prec = 40
PT100 = dict(R0='100', alpha='0.00385055', beta='0.10863', delta='1.4999')


def coefficients(R0='100', alpha='0.00385055', beta='0.10863', delta='1.4999'):
    r0, al, be, de = D(str(R0)), D(str(alpha)), D(str(beta)), D(str(delta))
    return r0, al * (1 + de / 100), -al * de * D('1E-4'), -al * be * D('1E-8')


def resistance(temp, **params):
    """Resistance (ohm) of the RTD at `temp` (degC)."""
    r0, a, b, c = coefficients(**{**PT100, **params})
    t = D(str(temp))
    if t >= 0:
        return float(r0 * (1 + a * t + b * t * t))
    return float(r0 * (1 + a * t + b * t * t + c * t ** 3 * (t - 100)))


def temperature(ohms, **params) -> float:
    """Temperature (degC) of the RTD reading `ohms`: closed form at or above R0, Newton on the polynomial below (exact to far below a microdegree)."""
    r0, a, b, c = coefficients(**{**PT100, **params})
    r = D(str(ohms))
    if r >= r0:
        # b t^2 + a t + (1 - r / r0) = 0 ; the root near zero
        k = 1 - r / r0
        t = (-a + (a * a - 4 * b * k).sqrt()) / (2 * b)
        return float(t)
    t = (r / r0 - 1) / a                                     # first guess, then Newton on f(t) = R(t) / R0 - r / R0
    for _ in range(60):
        f = 1 + a * t + b * t * t + c * t ** 3 * (t - 100) - r / r0
        df = a + 2 * b * t + c * (4 * t ** 3 - 300 * t * t)
        step = f / df
        t -= step
        if abs(step) < D('1E-15'):
            break
    return float(t)
