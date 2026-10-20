"""Pillow drawing helpers shared by the diagram builders (build-time only; the procedures themselves do not need Pillow)."""
from __future__ import annotations

import math
from pathlib import Path

S = 3        # supersampling: everything is drawn S times larger, then reduced for anti-aliasing


def _fonts():
    from PIL import ImageFont
    base = '/usr/share/fonts/truetype/dejavu/'
    cache = {}

    def get(size, bold=True, mono=False):
        name = ('DejaVuSansMono-Bold.ttf' if bold else 'DejaVuSansMono.ttf') if mono else ('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf')
        key = (round(size * 4), name)
        if key not in cache:
            cache[key] = ImageFont.truetype(base + name, max(1, int(round(size * S))))
        return cache[key]
    return get


def hex_rgb(color):
    color = color.lstrip('#')
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


class Pen:
    """Drawing in logical pixels."""

    def __init__(self, w, h, background):
        from PIL import Image, ImageDraw
        self.w, self.h = w, h
        self.img = Image.new('RGBA', (int(w * S), int(h * S)), background)
        self.d = ImageDraw.Draw(self.img)
        self.font = _fonts()

    def s(self, *v):
        return [x * S for x in v]

    def rect(self, x0, y0, x1, y1, r=0, fill=None, outline=None, width=1):
        self.d.rounded_rectangle(self.s(x0, y0, x1, y1), radius=r * S, fill=fill, outline=outline, width=max(1, int(width * S)) if outline else 0)

    def circle(self, cx, cy, r, fill=None, outline=None, width=1):
        self.d.ellipse(self.s(cx - r, cy - r, cx + r, cy + r), fill=fill, outline=outline, width=max(1, int(width * S)) if outline else 0)

    def arc(self, cx, cy, r, start, end, fill, width=2):
        self.d.arc(self.s(cx - r, cy - r, cx + r, cy + r), start, end, fill=fill, width=max(1, int(width * S)))

    def text(self, x, y, text, size=12, fill='#000000', bold=True, anchor='mm', mono=False):
        self.d.text((x * S, y * S), text, font=self.font(size, bold, mono), fill=fill, anchor=anchor)

    def text_size(self, text, size=12, bold=True):
        l, t, r, b = self.font(size, bold).getbbox(text)
        return (r - l) / S, (b - t) / S

    def line(self, pts, fill, width, caps=True):
        flat = [(x * S, y * S) for x, y in pts]
        self.d.line(flat, fill=fill, width=max(1, int(width * S)), joint='curve')
        if caps:
            r = width * S / 2
            for x, y in (flat[0], flat[-1]):
                self.d.ellipse((x - r, y - r, x + r, y + r), fill=fill)

    def dashed(self, a, b, fill, width=2, dash=7, gap=5):
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
        t = 0.0
        while t < length:
            e = min(t + dash, length)
            self.line([(a[0] + ux * t, a[1] + uy * t), (a[0] + ux * e, a[1] + uy * e)], fill, width, caps=False)
            t += dash + gap

    def polygon(self, pts, fill, outline=None):
        self.d.polygon([(x * S, y * S) for x, y in pts], fill=fill, outline=outline)

    def glow(self, cx, cy, r, color):
        """The lit ring around a 5560A terminal: soft halo plus a bright core ring."""
        from PIL import Image, ImageDraw
        layer = Image.new('RGBA', self.img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        rgb = hex_rgb(color)
        for i in range(9):
            rr = r + (9 - i) * 0.9
            d.ellipse(self.s(cx - rr, cy - rr, cx + rr, cy + rr), outline=rgb + (int(18 + i * 11),), width=max(1, int(1.4 * S)))
        d.ellipse(self.s(cx - r, cy - r, cx + r, cy + r), outline=rgb + (255,), width=max(1, int(2.4 * S)))
        self.img = Image.alpha_composite(self.img, layer)
        self.d = ImageDraw.Draw(self.img)

    def save(self, path, colors=160):
        from PIL import Image
        out = self.img.resize((int(self.w), int(self.h)), Image.LANCZOS)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        if out.getpixel((0, 0))[3] == 255:                  # opaque picture: a palette PNG is much smaller
            out = out.convert('RGB').quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        out.save(path, optimize=True)


def bezier(p0, p1, p2, p3, n=60):
    pts = []
    for i in range(n + 1):
        t = i / n
        a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t ** 3
        pts.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return pts


def smooth(points, rounds=4):
    """Chaikin corner cutting: a polyline with square corners becomes a cable with rounded bends (ends stay put)."""
    pts = list(points)
    for _ in range(rounds):
        out = [pts[0]]
        for a, b in zip(pts, pts[1:]):
            out.append((0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1]))
            out.append((0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1]))
        out.append(pts[-1])
        pts = out
    return pts


def _segdist(p, a, b):
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def sample(points, step=4.0):
    out = []
    for a, b in zip(points, points[1:]):
        n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) // step))
        out += [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(n)]
    out.append(points[-1])
    return out


def min_distance(a_points, b_points):
    """Smallest distance between two polylines (cables), used to keep drawn cables from touching."""
    pa, best = sample(a_points), 1e9
    for p in pa:
        for u, v in zip(b_points, b_points[1:]):
            best = min(best, _segdist(p, u, v))
    return best
