#!/usr/bin/env python3
"""cutest-picture-01 entry v1: a baby kitten, drawn procedurally, pure stdlib.

Python 3.13, standard library only. No network, no randomness, fully
deterministic: every run writes identical bytes to /output/entry.png.
Renders at 2x supersampling, then box-downsamples for anti-aliasing.
"""
import math
import os
import struct
import zlib

SS = 2            # supersampling factor
W, H = 1024, 1024  # output size
RW, RH = W * SS, H * SS


# ---------------- PNG encoder ----------------

def _chunk(typ, data):
    c = struct.pack(">I", len(data)) + typ + data
    return c + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)


def write_png(path, rgb, w, h):
    raw = bytearray()
    stride = w * 3
    for y in range(h):
        raw.append(0)  # filter: None
        raw += rgb[y * stride:(y + 1) * stride]
    png = b"\x89PNG\r\n\x1a\n"
    png += _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += _chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


# ---------------- canvas ----------------

class Canvas:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.buf = bytearray(w * h * 3)

    def _set(self, x, y, r, g, b):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            self.buf[i] = r
            self.buf[i + 1] = g
            self.buf[i + 2] = b

    def _blend(self, x, y, r, g, b, a):
        if 0 <= x < self.w and 0 <= y < self.h and a > 0:
            i = (y * self.w + x) * 3
            if a >= 1:
                self.buf[i] = r
                self.buf[i + 1] = g
                self.buf[i + 2] = b
            else:
                self.buf[i] = int(self.buf[i] + (r - self.buf[i]) * a)
                self.buf[i + 1] = int(self.buf[i + 1] + (g - self.buf[i + 1]) * a)
                self.buf[i + 2] = int(self.buf[i + 2] + (b - self.buf[i + 2]) * a)

    def fill_row(self, y, x0, x1, rgb):
        """Opaque horizontal span (clipped)."""
        if y < 0 or y >= self.h:
            return
        x0 = max(0, x0)
        x1 = min(self.w - 1, x1)
        if x1 < x0:
            return
        i0 = (y * self.w + x0) * 3
        self.buf[i0:(y * self.w + x1 + 1) * 3] = bytes(rgb) * (x1 - x0 + 1)

    def vgrad(self, top, bottom):
        for y in range(self.h):
            t = y / (self.h - 1)
            c = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
            self.fill_row(y, 0, self.w - 1, c)

    def ellipse(self, cx, cy, rx, ry, rgb, angle=0.0):
        """Filled ellipse (possibly rotated), opaque, scanline rasterised."""
        c, s = math.cos(angle), math.sin(angle)
        irx2, iry2 = 1.0 / (rx * rx), 1.0 / (ry * ry)
        # vertical extent of the rotated ellipse
        ext = math.sqrt((rx * c) ** 2 + (ry * s) ** 2)
        y0 = max(0, int(math.floor(cy - ext)))
        y1 = min(self.h - 1, int(math.ceil(cy + ext)))
        for y in range(y0, y1 + 1):
            dy = y - cy
            A = c * c * irx2 + s * s * iry2
            B = 2 * dy * c * s * (irx2 - iry2)
            C = dy * dy * (s * s * irx2 + c * c * iry2) - 1.0
            disc = B * B - 4 * A * C
            if disc <= 0:
                continue
            sq = math.sqrt(disc)
            t0 = (-B - sq) / (2 * A)
            t1 = (-B + sq) / (2 * A)
            self.fill_row(y, int(math.ceil(cx + t0)), int(math.floor(cx + t1)), rgb)

    def circle(self, cx, cy, r, rgb, angle=0.0):
        self.ellipse(cx, cy, r, r, rgb, angle)

    def polygon(self, pts, rgb):
        """Filled polygon (list of (x, y)), scanline."""
        ys = [p[1] for p in pts]
        y0 = max(0, int(math.floor(min(ys))))
        y1 = min(self.h - 1, int(math.ceil(max(ys))))
        n = len(pts)
        for y in range(y0, y1 + 1):
            xs = []
            for i in range(n):
                x1, y1p = pts[i]
                x2, y2p = pts[(i + 1) % n]
                if (y1p <= y < y2p) or (y2p <= y < y1p):
                    xs.append(x1 + (y - y1p) * (x2 - x1) / (y2p - y1p))
            xs.sort()
            for k in range(0, len(xs) - 1, 2):
                self.fill_row(y, int(math.ceil(xs[k])), int(math.floor(xs[k + 1])), rgb)

    def soft_circle(self, cx, cy, r, rgb, a):
        """Radial falloff disc (alpha  a at centre -> 0 at edge)."""
        x0 = max(0, int(cx - r))
        x1 = min(self.w - 1, int(cx + r))
        y0 = max(0, int(cy - r))
        y1 = min(self.h - 1, int(cy + r))
        r2 = r * r
        for y in range(y0, y1 + 1):
            dy = y - cy
            for x in range(x0, x1 + 1):
                dx = x - cx
                d2 = dx * dx + dy * dy
                if d2 < r2:
                    t = 1.0 - d2 / r2
                    self._blend(x, y, rgb[0], rgb[1], rgb[2], a * t * t)

    def soft_ellipse(self, cx, cy, rx, ry, rgb, a):
        x0 = max(0, int(cx - rx))
        x1 = min(self.w - 1, int(cx + rx))
        y0 = max(0, int(cy - ry))
        y1 = min(self.h - 1, int(cy + ry))
        for y in range(y0, y1 + 1):
            dy = (y - cy) / ry
            for x in range(x0, x1 + 1):
                dx = (x - cx) / rx
                d2 = dx * dx + dy * dy
                if d2 < 1.0:
                    t = 1.0 - d2
                    self._blend(x, y, rgb[0], rgb[1], rgb[2], a * t * t)

    def stamp(self, cx, cy, r, rgb):
        """Small filled circle (for strokes)."""
        self.ellipse(cx, cy, r, r, rgb)

    def stroke(self, pts, width, rgb):
        """Polyline with round caps, by stamping circles along it."""
        r = width / 2.0
        for i in range(len(pts) - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]
            dist = math.hypot(x2 - x1, y2 - y1)
            steps = max(1, int(dist / (r * 0.8)) + 1)
            for k in range(steps + 1):
                t = k / steps
                self.stamp(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t, r, rgb)

    def bezier(self, p0, p1, p2, width, rgb):
        pts = []
        for k in range(25):
            t = k / 24.0
            mt = 1 - t
            pts.append((mt * mt * p0[0] + 2 * mt * t * p1[0] + t * t * p2[0],
                        mt * mt * p0[1] + 2 * mt * t * p1[1] + t * t * p2[1]))
        self.stroke(pts, width, rgb)

    def heart(self, cx, cy, s, rgb):
        """Small heart: two circles + rotated square."""
        self.circle(cx - 0.38 * s, cy - 0.15 * s, 0.42 * s, rgb)
        self.circle(cx + 0.38 * s, cy - 0.15 * s, 0.42 * s, rgb)
        q = 0.62 * s
        self.polygon([(cx - q, cy), (cx, cy - q * 0.55), (cx + q, cy),
                      (cx, cy + q * 1.15)], rgb)

    def sparkle(self, cx, cy, s, rgb):
        self.polygon([(cx, cy - s), (cx + 0.28 * s, cy - 0.28 * s),
                      (cx + s, cy), (cx + 0.28 * s, cy + 0.28 * s),
                      (cx, cy + s), (cx - 0.28 * s, cy + 0.28 * s),
                      (cx - s, cy), (cx - 0.28 * s, cy - 0.28 * s)], rgb)


def rot(x, y, px, py, ang):
    c, s = math.cos(ang), math.sin(ang)
    dx, dy = x - px, y - py
    return (px + dx * c - dy * s, py + dx * s + dy * c)


# ---------------- palette ----------------
CREAM = (255, 246, 232)
FUR = (249, 180, 91)        # warm apricot
FUR_DARK = (232, 148, 52)
FUR_LIGHT = (255, 214, 150)
PINK = (255, 179, 193)
PINK_DARK = (242, 125, 147)
DARK = (51, 36, 26)         # eyes / outline
AMBER = (201, 138, 75)
BLUSH = (255, 158, 178)
WHITE = (255, 255, 255)


def draw(c, S):
    """Draw the kitten scene. All coords in output pixels; S = supersample."""
    def X(v):
        return v * S

    # --- background: soft vertical gradient + bokeh ---
    c.vgrad((255, 222, 232), (255, 243, 226))
    for (bx, by, br, col) in [
            (150, 180, 90, (255, 214, 228)), (880, 150, 100, (255, 232, 196)),
            (920, 820, 85, (255, 214, 228)), (110, 780, 80, (255, 234, 205)),
            (700, 90, 70, (255, 242, 218))]:
        c.circle(X(bx), X(by), X(br), col)

    # floating hearts + sparkles (soft, small)
    for (hx, hy, hs) in [(140, 330, 26), (890, 300, 22), (840, 130, 16), (180, 140, 15)]:
        c.heart(X(hx), X(hy), X(hs), (255, 190, 205))
    for (sx, sy, ss) in [(250, 220, 14), (790, 210, 12), (900, 620, 12), (120, 620, 10)]:
        c.sparkle(X(sx), X(sy), X(ss), WHITE)

    # --- ground shadow ---
    c.soft_ellipse(X(512), X(905), X(300), X(42), (214, 150, 150), 0.30)

    # --- tail (behind body, right side) ---
    c.bezier((X(700), X(850)), (X(835), X(835)), (X(845), X(695)), X(60), FUR_DARK)
    c.bezier((X(700), X(850)), (X(835), X(835)), (X(845), X(695)), X(52), FUR)
    c.bezier((X(700), X(850)), (X(835), X(835)), (X(845), X(695)), X(30), FUR_LIGHT)
    c.circle(X(845), X(695), X(26), FUR_LIGHT)

    # --- body ---
    c.ellipse(X(512), X(800), X(223), X(188), FUR_DARK)  # outline
    c.ellipse(X(512), X(800), X(215), X(180), FUR)
    c.ellipse(X(512), X(840), X(115), X(100), CREAM)  # belly
    # front paws
    c.ellipse(X(425), X(935), X(55), X(38), CREAM)
    c.ellipse(X(600), X(935), X(55), X(38), CREAM)

    # --- tiny chick friend cuddling at the kitten's left paw ---
    YELLOW = (255, 217, 77)
    YELLOW_DARK = (242, 183, 5)
    ORANGE = (244, 130, 32)
    c.ellipse(X(283), X(878), X(50), X(46), YELLOW)          # chick body
    c.circle(X(300), X(822), X(35), YELLOW)                  # chick head
    c.ellipse(X(262), X(882), X(20), X(30), YELLOW_DARK, angle=-0.4)  # wing
    c.polygon([(X(330), X(812)), (X(330), X(828)), (X(352), X(820))], ORANGE)  # beak
    c.circle(X(312), X(810), X(5), DARK)                     # eye
    c.circle(X(314), X(808), X(2), WHITE)                    # eye shine
    c.soft_circle(X(292), X(830), X(12), BLUSH, 0.5)         # cheek blush
    c.stroke([(X(292), X(790)), (X(284), X(772))], X(5), YELLOW_DARK)  # head tuft
    c.stroke([(X(300), X(788)), (X(300), X(770))], X(5), YELLOW_DARK)
    c.ellipse(X(272), X(928), X(12), X(6), ORANGE)           # feet
    c.ellipse(X(296), X(928), X(12), X(6), ORANGE)

    # --- head group (tilted ~13 deg around neck) ---
    tilt = math.radians(13)
    px, py = X(512), X(650)

    def R(x, y):
        return rot(X(x), X(y), px, py, tilt)

    # head outline first (ears drawn next cover the top arc; head covers the rest)
    hx, hy = R(512, 485)
    c.circle(hx, hy, X(248), FUR_DARK)

    # ears: pointed triangles with lightly rounded tips (base hides inside head)
    for (ex, ey, sgn) in [(360, 305, -1), (664, 295, 1)]:
        tip = R(ex + sgn * 14, ey - 100)
        b1 = R(ex - 72, ey + 55)
        b2 = R(ex + 72, ey + 55)
        # darker outline: same triangle grown ~7% around its centroid
        cxp = (tip[0] + b1[0] + b2[0]) / 3.0
        cyp = (tip[1] + b1[1] + b2[1]) / 3.0
        c.polygon([(cxp + (p[0] - cxp) * 1.07, cyp + (p[1] - cyp) * 1.07)
                   for p in (tip, b1, b2)], FUR_DARK)
        c.polygon([tip, b1, b2], FUR)
        # inner ear: smaller triangle, fully inside
        tip2 = R(ex + sgn * 10, ey - 66)
        i1 = R(ex - 36, ey + 38)
        i2 = R(ex + 36, ey + 38)
        c.polygon([tip2, i1, i2], PINK)

    # head (covers ear bases and the inner part of the outline ring)
    c.circle(hx, hy, X(240), FUR)
    # muzzle (two cream cheeks)
    for (mx, my) in [(470, 578), (556, 574)]:
        mxr, myr = R(mx, my)
        c.ellipse(mxr, myr, X(72), X(48), CREAM)
    # blush
    for (bx, by) in [(392, 566), (634, 558)]:
        bxr, byr = R(bx, by)
        c.soft_circle(bxr, byr, X(48), BLUSH, 0.55)

    # eyes: amber ring, dark pupil, big highlights
    for (ex, ey) in [(428, 482), (598, 472)]:
        exr, eyr = R(ex, ey)
        c.ellipse(exr, eyr, X(50), X(60), AMBER)
        c.ellipse(exr, eyr, X(38), X(50), DARK)
        hx1, hy1 = R(ex - 14, ey - 22)
        c.circle(hx1, hy1, X(15), WHITE)
        hx2, hy2 = R(ex + 13, ey + 20)
        c.circle(hx2, hy2, X(7), WHITE)

    # nose + mouth
    nx, ny = R(512, 566)
    c.polygon([(nx - X(26), ny - X(12)), (nx + X(26), ny - X(12)),
               (nx, ny + X(20))], PINK_DARK)
    c.circle(nx, ny + X(4), X(13), PINK_DARK)
    # omega mouth: two arcs
    for (mx0, my0) in [(486, 586), (514, 586)]:
        mxr, myr = R(mx0, my0)
        pts = []
        for k in range(13):
            a = math.pi * (0.15 + 0.7 * k / 12.0)
            pts.append((mxr + X(24) * math.cos(a), myr + X(20) * math.sin(a)))
        c.stroke(pts, X(7), DARK)
    # whiskers
    for sgn in (-1, 1):
        for (wy, spread) in [(558, 95), (578, 105), (598, 95)]:
            p1 = R(512 + sgn * 60, wy)
            p2 = R(512 + sgn * (60 + spread), wy - 14)
            c.stroke([p1, p2], X(4), (190, 150, 125))

    # tiny flower at the base of the right ear
    fx, fy = R(700, 305)
    for k in range(5):
        a = 2 * math.pi * k / 5 - math.pi / 2
        c.circle(fx + X(20) * math.cos(a), fy + X(20) * math.sin(a), X(15), PINK)
    c.circle(fx, fy, X(13), (255, 205, 92))


def downsample(src, w, h, ss):
    """Box-downsample ss x ss -> w x h RGB bytes."""
    out = bytearray(w * h * 3)
    sw = w * ss
    for y in range(h):
        for x in range(w):
            r = g = b = 0
            for dy in range(ss):
                base = ((y * ss + dy) * sw + x * ss) * 3
                for dx in range(ss):
                    i = base + dx * 3
                    r += src[i]
                    g += src[i + 1]
                    b += src[i + 2]
            n = ss * ss
            o = (y * w + x) * 3
            out[o] = (r + n // 2) // n
            out[o + 1] = (g + n // 2) // n
            out[o + 2] = (b + n // 2) // n
    return bytes(out)


def main():
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    c = Canvas(RW, RH)
    draw(c, SS)
    rgb = downsample(c.buf, W, H, SS)
    write_png(os.path.join(out_dir, "entry.png"), rgb, W, H)


if __name__ == "__main__":
    main()
