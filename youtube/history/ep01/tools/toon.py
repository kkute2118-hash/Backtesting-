"""Tiny flat-cartoon drawing kit: thick outlines, dot eyes, earthy colours.

Everything is drawn on a 2x canvas in 1920x1080 coordinates and scaled down
at the end, so lines come out smooth.
"""
import math, random
from PIL import Image, ImageDraw, ImageFilter

W, H, K = 1920, 1080, 2
INK = (43, 33, 24)
SKIN = (214, 160, 112)
SKIN2 = (190, 135, 92)
SKIN_PALE = (236, 196, 160)
CLOTH = (236, 226, 204)
OCHRE = (204, 150, 72)
BRICK = (178, 92, 58)
BRICK_L = (204, 122, 78)
SAND = (232, 205, 150)
SAND_D = (214, 182, 124)
SKY = (166, 206, 228)
SKY_DUSK = (238, 170, 110)
GRASS = (150, 170, 90)
WATER = (96, 160, 196)
RED = (176, 52, 44)
GREY = (200, 200, 196)
WHITE = (250, 248, 240)
DARK = (70, 58, 50)
NIGHT = (34, 40, 74)


class Canvas:
    def __init__(self, bg=SKY):
        self.im = Image.new("RGB", (W * K, H * K), bg)
        self.d = ImageDraw.Draw(self.im)

    # ---- primitives (coordinates in 1920x1080 space) ----
    def _p(self, pts):
        return [(x * K, y * K) for x, y in pts]

    def poly(self, pts, fill, ow=5, outline=INK):
        self.d.polygon(self._p(pts), fill=fill)
        if ow:
            p = self._p(pts)
            self.d.line(p + [p[0]], fill=outline, width=ow * K, joint="curve")

    def rect(self, x0, y0, x1, y1, fill, ow=5, r=0):
        x0, x1 = sorted((x0, x1)); y0, y1 = sorted((y0, y1))
        box = [x0 * K, y0 * K, x1 * K, y1 * K]
        if r:
            self.d.rounded_rectangle(box, r * K, fill=fill, outline=INK if ow else None, width=ow * K)
        else:
            self.d.rectangle(box, fill=fill, outline=INK if ow else None, width=ow * K)

    def ell(self, cx, cy, rx, ry, fill, ow=5, outline=INK):
        self.d.ellipse([(cx - rx) * K, (cy - ry) * K, (cx + rx) * K, (cy + ry) * K],
                       fill=fill, outline=outline if ow else None, width=ow * K)

    def line(self, pts, fill=INK, w=5):
        p = self._p(pts)
        self.d.line(p, fill=fill, width=int(w * K), joint="curve")
        for x, y in (p[0], p[-1]):
            r = w * K / 2
            self.d.ellipse([x - r, y - r, x + r, y + r], fill=fill)

    def limb(self, pts, fill, w):
        self.line(pts, INK, w + 10)
        self.line(pts, fill, w)

    def arc(self, cx, cy, rx, ry, a0, a1, w=5, fill=INK):
        self.d.arc([(cx - rx) * K, (cy - ry) * K, (cx + rx) * K, (cy + ry) * K], a0, a1, fill=fill, width=int(w * K))

    def chord(self, cx, cy, rx, ry, a0, a1, fill, ow=5):
        self.d.chord([(cx - rx) * K, (cy - ry) * K, (cx + rx) * K, (cy + ry) * K], a0, a1, fill=fill, outline=INK, width=ow * K)

    def save(self, path, vignette=True):
        im = self.im.resize((W, H), Image.LANCZOS)
        if vignette:
            mask = Image.new("L", (W, H), 0)
            md = ImageDraw.Draw(mask)
            md.ellipse([-W * 0.25, -H * 0.3, W * 1.25, H * 1.3], fill=255)
            mask = mask.filter(ImageFilter.GaussianBlur(120))
            dark = Image.new("RGB", (W, H), (40, 30, 20))
            im = Image.composite(im, Image.blend(im, dark, 0.35), mask)
        im.save(path)


# ---------------- people ----------------
ARMS = {
    "down":    [((-12, 70), (-18, 140)), ((12, 70), (18, 140))],
    "wave":    [((-12, 70), (-18, 140)), ((70, -20), (85, -115))],
    "point":   [((-12, 70), (-18, 140)), ((80, 10), (165, -15))],
    "pointl":  [((-80, 10), (-165, -15)), ((12, 70), (18, 140))],
    "hips":    [((-62, 55), (-28, 112)), ((62, 55), (28, 112))],
    "up":      [((-55, -55), (-70, -140)), ((55, -55), (70, -140))],
    "belly":   [((-55, 65), (-12, 105)), ((55, 65), (12, 105))],
    "face":    [((-12, 70), (-18, 140)), ((45, 35), (-20, -70))],
    "ear":     [((-12, 70), (-18, 140)), ((80, -10), (75, -85))],
    "scratch": [((-12, 70), (-18, 140)), ((75, -45), (25, -125))],
    "shrug":   [((-60, 40), (-115, -20)), ((60, 40), (115, -20))],
    "zip":     [((-12, 70), (-18, 140)), ((50, 50), (5, -50))],
    "cross":   [((-50, 55), (40, 65)), ((50, 55), (-40, 72))],
    "hold":    [((-12, 70), (-18, 140)), ((60, 45), (120, 30))],
    "holdup":  [((-12, 70), (-18, 140)), ((60, -40), (90, -140))],
    "both":    [((-60, 45), (-125, 20)), ((60, 45), (125, 20))],
    "work":    [((-45, 60), (40, 110)), ((45, 60), (95, 105))],
    "behind":  [((-35, 70), (-5, 125)), ((35, 70), (5, 125))],
    "whisper": [((-12, 70), (-18, 140)), ((-30, 30), (-55, -60))],
}


def person(c, x, y, s=1.0, skin=SKIN, cloth=CLOTH, cloth2=None, beard=None, beard_len=0, hair=DARK,
           band=None, beads=False, bangles=False, female=False, helmet=False, glasses=False, coat=None,
           pose="down", face="smile", flip=False, kid=False, bald=False, crown=None, lab=False):
    """Draw a standing cartoon person with feet at (x, y). Returns hand positions."""
    u = s * (0.75 if kid else 1.0)
    f = -1 if flip else 1
    P = lambda dx, dy: (x + dx * u * f, y + dy * u)
    body_col = coat or (WHITE if lab else cloth)
    # legs
    for side in (-1, 1):
        c.limb([P(side * 18, -150), P(side * 24, -10)], skin if not coat else (90, 80, 70), 26 * u)
        c.ell(*P(side * 30, -4), 22 * u, 10 * u, INK if coat else skin, 4)
    # torso
    top, bot = -305, -135
    c.poly([P(-52, top + 10), P(52, top + 10), P(66, bot + 10), P(-66, bot + 10)], body_col, 5)
    if cloth2:  # sash over the shoulder
        c.poly([P(-52, top + 12), P(-20, top + 12), P(66, bot + 8), P(30, bot + 8)], cloth2, 4)
    if coat:
        c.line([P(0, top + 15), P(0, bot + 8)], INK, 3)
    # arms
    sh = {-1: P(-48, top + 25), 1: P(48, top + 25)}
    hands = {}
    for side, (el, hd) in zip((-1, 1), ARMS[pose]):
        e = P(-48 * 1 + el[0] + 48, top + 25 + el[1]) if side == -1 else P(48 + el[0] - 48, top + 25 + el[1])
        e = (sh[side][0] + el[0] * u * f, sh[side][1] + el[1] * u)
        h = (sh[side][0] + hd[0] * u * f, sh[side][1] + hd[1] * u)
        sleeve = body_col if (coat or lab) else skin
        c.limb([sh[side], e, h], sleeve, 22 * u)
        if coat or lab:
            c.ell(*h, 14 * u, 14 * u, skin, 4)
        if bangles:
            for t in (0.55, 0.7, 0.85):
                bx, by = e[0] + (h[0] - e[0]) * t, e[1] + (h[1] - e[1]) * t
                c.ell(bx, by, 15 * u, 6 * u, WHITE, 3)
        hands["l" if side == -1 else "r"] = h
    # head
    hx, hy = P(0, -370)
    r = 58 * u
    if female and not bald:
        c.ell(hx, hy - 50 * u, 34 * u, 30 * u, hair, 5)       # bun
    c.ell(hx, hy, r, r * 1.02, skin, 6)
    if not bald and not helmet:
        c.chord(hx, hy, r, r * 1.02, 205, 335, hair, 6)
    if beard:
        bl = 40 + beard_len
        c.poly([(hx - r * 0.85, hy + 5 * u), (hx + r * 0.85, hy + 5 * u), (hx + r * 0.55, hy + bl * u),
                (hx, hy + (bl + 25) * u), (hx - r * 0.55, hy + bl * u)], beard, 5)
    if band:
        by = hy - r * 0.52
        half = math.sqrt(max(r * r - (by - hy) ** 2, 0))
        c.line([(hx - half + 3, by), (hx + half - 3, by)], INK, 16 * u)
        c.line([(hx - half + 5, by), (hx + half - 5, by)], band, 10 * u)
        c.line([(hx + half - 4, by), (hx + half + 14 * u, by + 22 * u)], band, 8 * u)
    if helmet:
        c.chord(hx, hy - r * 0.45, r * 1.1, r * 0.95, 180, 360, (226, 214, 180), 5)
        c.rect(hx - r * 1.3, hy - r * 0.5, hx + r * 1.3, hy - r * 0.38, (226, 214, 180), 4)
    if crown:
        c.poly([(hx - r * 0.8, hy - r * 0.7), (hx - r * 0.8, hy - r * 1.4), (hx - r * 0.4, hy - r * 1.05), (hx, hy - r * 1.5),
                (hx + r * 0.4, hy - r * 1.05), (hx + r * 0.8, hy - r * 1.4), (hx + r * 0.8, hy - r * 0.7)], crown, 4)
    # face
    ey = hy - 8 * u
    ex = 20 * u
    brow = {"angry": (8, -8), "sad": (-8, 8), "shock": (-4, -4)}.get(face, (0, 0))
    for side in (-1, 1):
        exx = hx + side * ex
        if face == "wink" and side == 1:
            c.line([(exx - 8 * u, ey), (exx + 8 * u, ey)], INK, 4 * u)
        elif face == "shock":
            c.ell(exx, ey, 9 * u, 9 * u, WHITE, 3); c.ell(exx, ey, 4 * u, 4 * u, INK, 0)
        else:
            c.ell(exx, ey, 5.5 * u, 6.5 * u, INK, 0)
        b0, b1 = brow
        c.line([(exx - 11 * u, ey - 20 * u + (b0 if side == -1 else b1) * u),
                (exx + 11 * u, ey - 20 * u + (b1 if side == -1 else b0) * u)], INK, 5 * u * (1.6 if beard else 1))
    if glasses:
        for side in (-1, 1):
            c.ell(hx + side * ex, ey, 15 * u, 13 * u, None, 4)
        c.line([(hx - 6 * u, ey), (hx + 6 * u, ey)], INK, 3)
    my = hy + 24 * u
    if face in ("grin", "laugh"):
        c.chord(hx, my - 6 * u, 26 * u, 22 * u, 0, 180, (120, 40, 40), 4)
        c.rect(hx - 18 * u, my - 6 * u, hx + 18 * u, my + 2 * u, WHITE, 0)
    elif face == "shock":
        c.ell(hx, my + 4 * u, 13 * u, 17 * u, (120, 40, 40), 4)
    elif face == "sad":
        c.arc(hx, my + 14 * u, 18 * u, 12 * u, 200, 340, 5 * u)
    elif face == "angry":
        c.line([(hx - 15 * u, my + 4 * u), (hx + 15 * u, my + 2 * u)], INK, 5 * u)
    elif face == "puff":
        c.ell(hx - 32 * u, my - 4 * u, 13 * u, 11 * u, (226, 140, 110), 0)
        c.ell(hx + 32 * u, my - 4 * u, 13 * u, 11 * u, (226, 140, 110), 0)
        c.ell(hx, my + 2 * u, 6 * u, 5 * u, INK, 0)
    elif face == "zip":
        c.line([(hx - 16 * u, my), (hx + 16 * u, my)], INK, 4 * u)
        for k in range(-12, 13, 6):
            c.line([(hx + k * u, my - 5 * u), (hx + k * u, my + 5 * u)], INK, 2 * u)
    elif face == "neutral":
        c.line([(hx - 12 * u, my + 2 * u), (hx + 12 * u, my + 2 * u)], INK, 4 * u)
    else:  # smile, wink, sly
        c.arc(hx + (6 * u if face == "sly" else 0), my - 6 * u, 20 * u, 14 * u, 20, 160, 5 * u)
    if beard and beard_len > 30:   # moustache over long beard
        c.arc(hx, my - 2 * u, 26 * u, 10 * u, 190, 350, 7 * u, (beard[0] - 30, beard[1] - 30, beard[2] - 30))
    if beads:
        for k in range(-3, 4):
            c.ell(hx + k * 11 * u, P(0, -300)[1] + abs(k) * -3 * u + 8 * u, 6 * u, 6 * u, RED, 2)
    return hands


def gappu(c, x, y, s=1.0, pose="down", face="grin", flip=False, young=False):
    return person(c, x, y, s, skin=SKIN, cloth=CLOTH, cloth2=(222, 208, 180), beard=(60, 50, 44) if young else (218, 218, 214),
                  beard_len=20 if young else 60, hair=(60, 50, 44) if young else (200, 200, 196), band=RED, beads=True,
                  pose=pose, face=face, flip=flip)


def villager(c, x, y, s=1.0, female=False, kid=False, pose="down", face="smile", flip=False, tone=0, cloth=None):
    skin = [SKIN, SKIN2, (200, 148, 100)][tone % 3]
    cloth = cloth or [CLOTH, OCHRE, (196, 170, 120)][tone % 3]
    if female:
        return person(c, x, y, s, skin=skin, cloth=cloth, female=True, bangles=True, beads=True, pose=pose, face=face, flip=flip, kid=kid)
    return person(c, x, y, s, skin=skin, cloth=cloth, beard=None if kid else DARK, beard_len=0, band=None if kid else OCHRE,
                  pose=pose, face=face, flip=flip, kid=kid)


def brit(c, x, y, s=1.0, pose="down", face="smile", flip=False, era="1850"):
    coat = (120, 96, 70) if era == "1850" else (150, 130, 100)
    h = person(c, x, y, s, skin=SKIN_PALE, coat=coat, helmet=True, pose=pose, face=face, flip=flip, hair=(150, 110, 70))
    if era == "1850":   # big moustache
        mx, my = x, y - 370 * s + 16 * s
        c.arc(mx - 16 * s, my, 18 * s, 9 * s, 180, 360, 7 * s, (150, 110, 70))
        c.arc(mx + 16 * s, my, 18 * s, 9 * s, 180, 360, 7 * s, (150, 110, 70))
    return h


def scholar(c, x, y, s=1.0, pose="down", face="smile", flip=False, female=False, modern=False):
    return person(c, x, y, s, skin=SKIN if not female else SKIN2, coat=None if modern else (90, 90, 110), lab=modern,
                  glasses=True, female=female, hair=(40, 34, 30), pose=pose, face=face, flip=flip)


# ---------------- props ----------------
def brick(c, x, y, s=1.0, rot=0):
    w, h = 64 * s, 26 * s
    pts = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
    a = math.radians(rot)
    pts = [(x + px * math.cos(a) - py * math.sin(a), y + px * math.sin(a) + py * math.cos(a)) for px, py in pts]
    c.poly(pts, BRICK_L, 4)


def seal(c, x, y, s=1.0):
    c.rect(x - 40 * s, y - 40 * s, x + 40 * s, y + 40 * s, (230, 220, 196), 5, r=6 * s)
    c.ell(x, y + 10 * s, 22 * s, 12 * s, (190, 170, 140), 3)              # bull body
    c.line([(x - 18 * s, y + 4 * s), (x - 30 * s, y - 8 * s)], INK, 3)        # horn
    for k in range(4):
        c.line([(x - 26 * s + k * 16 * s, y - 28 * s), (x - 26 * s + k * 16 * s, y - 16 * s)], INK, 3)


def necklace(c, x, y, s=1.0):
    for k in range(9):
        a = math.radians(200 + k * 17.5)
        c.ell(x + 50 * s * math.cos(a), y - 50 * s * math.sin(a) * -1, 9 * s, 9 * s, RED, 3)


def pot(c, x, y, s=1.0, col=(176, 104, 64)):
    c.ell(x, y, 34 * s, 30 * s, col, 5)
    c.rect(x - 16 * s, y - 40 * s, x + 16 * s, y - 24 * s, col, 4)


def house(c, x, y, w=220, h=170, col=BRICK, door=True, floors=1):
    c.rect(x, y - h, x + w, y, col, 5)
    for row in range(int(h // 28)):
        yy = y - h + 28 * (row + 1)
        c.line([(x + 4, yy), (x + w - 4, yy)], (150, 76, 46), 2)
    if door:
        c.rect(x + w * 0.4, y - 70, x + w * 0.6, y, (90, 60, 40), 4, r=6)
    if floors > 1:
        c.rect(x + w * 0.15, y - h * 0.75, x + w * 0.32, y - h * 0.55, (70, 50, 36), 3)
        c.rect(x + w * 0.68, y - h * 0.75, x + w * 0.85, y - h * 0.55, (70, 50, 36), 3)


def ground(c, y=820, col=SAND, sky=SKY):
    c.rect(-10, y, W + 10, H + 10, col, 0)
    c.line([(-10, y), (W + 10, y)], INK, 5)


def sun(c, x=1650, y=170, col=(250, 214, 120)):
    c.ell(x, y, 70, 70, col, 0)


def clouds(c, seed=1, n=3, col=WHITE):
    rnd = random.Random(seed)
    for _ in range(n):
        x, y = rnd.randint(100, 1800), rnd.randint(80, 260)
        for dx, dy, r in ((0, 0, 50), (45, 10, 40), (-45, 12, 38), (20, -25, 36)):
            c.ell(x + dx, y + dy, r, r * 0.8, col, 0)


def street(c, seed=2, dusk=False, empty=False):
    c.rect(0, 0, W, H, SKY_DUSK if dusk else SKY, 0)
    if not dusk:
        clouds(c, seed)
    sun(c, col=(250, 180, 100) if dusk else (250, 214, 120))
    rnd = random.Random(seed)
    x = -40
    while x < W:
        w = rnd.randint(180, 280); h = rnd.randint(200, 330)
        house(c, x, 700, w, h, BRICK if rnd.random() > 0.3 else BRICK_L, floors=2 if h > 270 else 1)
        if empty and rnd.random() > 0.5:   # cracks
            c.line([(x + w * 0.3, 700 - h + 20), (x + w * 0.4, 700 - h + 80), (x + w * 0.33, 700 - h + 130)], INK, 3)
        x += w + 10
    c.poly([(0, 700), (W, 700), (W, H), (0, H)], SAND, 5)
    c.rect(0, 690, W, 712, (160, 90, 60), 4)   # covered drain along the street


def aerial_city(c, ruined=False):
    c.rect(0, 0, W, H, (200, 176, 126), 0)
    c.poly([(1500, 0), (W, 0), (W, H), (1640, H)], WATER, 5)          # river
    for gx in range(0, 1500, 190):
        for gy in range(0, H, 170):
            col = BRICK if (gx // 190 + gy // 170) % 2 else BRICK_L
            c.rect(gx + 30, gy + 30, gx + 170, gy + 150, col, 4)
            c.rect(gx + 75, gy + 70, gx + 125, gy + 110, SAND_D, 3)     # courtyard
    for gx in range(0, 1500, 190):
        c.line([(gx + 15, 0), (gx + 15, H)], (150, 120, 80), 3)
    for gy in range(0, H, 170):
        c.line([(0, gy + 15), (1500, gy + 15)], (150, 120, 80), 3)


def map_base(c, rivers=True, sea_route=False, dots=(), dim=(), dry=False, zoom="north"):
    c.rect(0, 0, W, H, (120, 176, 206), 0)                             # sea
    land = [(300, 0), (1920, 0), (1920, 1080), (1150, 1080), (1050, 900), (930, 860), (860, 960), (760, 900),
            (700, 780), (600, 760), (520, 640), (380, 600), (250, 560), (120, 520), (0, 500), (0, 0)]
    c.poly(land, (236, 214, 166), 6)
    if rivers:
        c.line([(700, 60), (720, 220), (680, 380), (640, 520), (600, 680), (610, 760)], (90, 150, 196), 9)   # Indus
        c.line([(860, 80), (820, 200), (760, 300), (720, 380)], (90, 150, 196), 7)                            # Ravi side
        col = (196, 180, 140) if dry else (90, 150, 196)
        c.line([(1050, 120), (1010, 300), (930, 470), (820, 620), (700, 760)], col, 9 if not dry else 6)       # Ghaggar-Hakra
    for (x, y) in dots:
        c.ell(x, y, 14, 14, (240, 120, 40), 4)
    for (x, y) in dim:
        c.ell(x, y, 12, 12, (150, 140, 120), 3)
    if sea_route:
        pts = [(600, 790), (450, 820), (300, 760), (180, 640), (90, 560)]
        for a, b in zip(pts, pts[1:]):
            for t in (0.2, 0.5, 0.8):
                c.ell(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, 7, 7, WHITE, 0)
        boat(c, 330, 770, 0.8)


def boat(c, x, y, s=1.0):
    c.poly([(x - 90 * s, y - 20 * s), (x + 90 * s, y - 20 * s), (x + 60 * s, y + 20 * s), (x - 60 * s, y + 20 * s)], (170, 130, 80), 5)
    c.line([(x, y - 20 * s), (x, y - 140 * s)], INK, 5)
    c.poly([(x + 4, y - 135 * s), (x + 80 * s, y - 50 * s), (x + 4, y - 40 * s)], WHITE, 4)


def pyramid_scene(c):
    c.rect(0, 0, W, H, (246, 196, 120), 0)
    sun(c, 1500, 220, (250, 150, 80))
    ground(c, 760, SAND)
    c.poly([(700, 760), (1150, 230), (1600, 760)], (220, 180, 110), 6)
    c.poly([(980, 430), (1320, 430), (1150, 230)], (236, 200, 130), 0)
    for yy in range(300, 760, 60):
        c.line([(1150 - (yy - 230) * 0.85, yy), (1150 + (yy - 230) * 0.85, yy)], (180, 140, 80), 3)
    c.rect(330, 560, 560, 720, (210, 180, 120), 6)                       # stone block


def railway(c):
    c.rect(0, 0, W, H, SKY, 0); clouds(c, 5)
    ground(c, 720, SAND)
    c.poly([(1150, 720), (1350, 470), (1700, 440), (1920, 600), (1920, 720)], SAND_D, 6)   # mound
    for k in range(14):
        brick(c, 1300 + (k % 7) * 75, 620 - (k // 7) * 40 + (k % 2) * 6, 1.0, (k * 13) % 30 - 15)
    c.rect(-10, 860, 1150, 880, (110, 90, 70), 4)
    c.rect(-10, 930, 1150, 950, (110, 90, 70), 4)
    for xx in range(0, 1150, 70):
        brick(c, xx + 30, 905, 1.0)


def train(c, x, y, s=1.0):
    c.rect(x, y - 150 * s, x + 260 * s, y - 30 * s, (60, 60, 70), 6, r=10)
    c.rect(x + 180 * s, y - 230 * s, x + 260 * s, y - 150 * s, (60, 60, 70), 6)
    c.rect(x + 30 * s, y - 220 * s, x + 70 * s, y - 150 * s, (40, 40, 46), 5)
    for k in (60, 140, 220):
        c.ell(x + k * s, y - 20 * s, 32 * s, 32 * s, (40, 40, 46), 5)
    for k, r in ((0, 30), (40, 40), (90, 52)):
        c.ell(x + 50 * s - k * 0.4, y - 260 * s - k, r * s, r * s * 0.8, (230, 230, 230), 0)


def trench(c):
    c.rect(0, 0, W, H, SKY, 0); clouds(c, 7)
    ground(c, 520, SAND)
    c.poly([(300, 600), (1620, 600), (1500, 1000), (420, 1000)], SAND_D, 6)
    for row in range(5):
        for col in range(9):
            c.rect(560 + col * 90 + (row % 2) * 40, 680 + row * 60, 640 + col * 90 + (row % 2) * 40, 730 + row * 60, BRICK_L, 3)


def mound_stupa(c):
    c.rect(0, 0, W, H, SKY, 0); clouds(c, 9)
    ground(c, 760, SAND)
    c.poly([(300, 760), (700, 420), (1300, 400), (1700, 760)], SAND_D, 6)
    c.chord(1000, 420, 150, 130, 180, 360, (200, 170, 120), 6)
    c.rect(985, 250, 1015, 300, (200, 170, 120), 4)
    for col in range(6):
        c.rect(560 + col * 140, 620, 660 + col * 140, 680, BRICK_L, 4)


def kiln(c):
    c.rect(0, 0, W, H, (230, 196, 150), 0)
    ground(c, 800, SAND_D)
    c.chord(1500, 800, 260, 300, 180, 360, BRICK, 6)
    c.ell(1500, 720, 90, 70, (60, 30, 20), 5)
    c.ell(1500, 730, 50, 40, (250, 150, 60), 0)
    for row in range(5):
        for col in range(4):
            brick(c, 300 + col * 70, 780 - row * 30, 1.05)


def drain_cutaway(c):
    c.rect(0, 0, W, H, SKY, 0)
    house(c, 200, 600, 520, 380, BRICK_L, floors=2)
    c.rect(0, 600, W, H, (150, 120, 84), 5)
    c.rect(700, 700, W, 800, (90, 70, 54), 5)                                 # street drain
    c.rect(700, 650, W, 700, (190, 150, 110), 5)                              # cover slabs
    c.line([(460, 600), (520, 720), (720, 750)], (110, 150, 170), 22)         # house drain
    for xx in range(760, W, 120):
        c.line([(xx, 742), (xx + 60, 752)], (120, 170, 200), 6)
    c.rect(1300, 560, 1460, 700, (170, 140, 104), 5)                          # inspection pit


def courtyard(c, well=False):
    c.rect(0, 0, W, H, SKY, 0)
    c.rect(0, 160, W, 760, BRICK, 6)
    for row in range(1, 21):
        c.line([(0, 160 + row * 30), (W, 160 + row * 30)], (150, 76, 46), 2)
    c.rect(200, 280, 1720, 760, SAND_D, 6)
    for k in range(6):                                                            # stairs
        c.rect(1500 + k * 30, 420 + k * 56, 1720, 476 + k * 56, (150, 110, 70), 4)
    c.rect(0, 760, W, H, SAND, 5)
    if well:
        c.ell(1100, 830, 150, 50, BRICK_L, 6)
        c.ell(1100, 820, 110, 34, (40, 60, 80), 4)


def great_bath(c, water=True, people=False, sunrise=False):
    c.rect(0, 0, W, H, SKY_DUSK if sunrise else SKY, 0)
    sun(c, 1600, 200, (250, 190, 110) if sunrise else (250, 214, 120))
    c.rect(0, 380, W, H, BRICK_L, 6)
    for k in range(10):
        c.rect(120 + k * 175, 260, 170 + k * 175, 420, BRICK, 5)
    c.poly([(330, 520), (1590, 520), (1700, 960), (220, 960)], BRICK, 6)
    c.poly([(400, 560), (1520, 560), (1610, 920), (310, 920)], WATER if water else (120, 80, 60), 6)
    for k in range(5):
        c.rect(860 + k * 40, 520 + k * 22, 1060 - k * 40, 540 + k * 22, BRICK_L, 3)


def reservoir(c):
    c.rect(0, 0, W, H, (150, 160, 176), 0)
    for k in range(5):
        x = 200 + k * 360
        for dx, dy, r in ((0, 0, 90), (80, 20, 70), (-80, 22, 70)):
            c.ell(x + dx, 140 + dy, r, r * 0.7, (110, 116, 130), 0)
    rnd = random.Random(3)
    for _ in range(140):
        x, y = rnd.randint(0, W), rnd.randint(220, 760)
        c.line([(x, y), (x - 10, y + 36)], (200, 220, 240), 3)
    c.poly([(150, 620), (1770, 620), (1650, 1000), (270, 1000)], (176, 160, 140), 6)
    c.poly([(260, 700), (1660, 700), (1570, 960), (350, 960)], WATER, 5)
    for k in range(6):
        c.rect(150 + k * 30, 620 + k * 60, 300, 680 + k * 60, (196, 180, 156), 3)


def gate(c):
    c.rect(0, 0, W, H, SKY, 0); clouds(c, 11)
    ground(c, 820, SAND)
    c.rect(300, 300, 760, 820, (196, 180, 156), 6)
    c.rect(1160, 300, 1620, 820, (196, 180, 156), 6)
    c.rect(760, 520, 1160, 820, (60, 46, 36), 6)
    c.rect(560, 330, 1360, 470, (130, 90, 60), 6)
    rnd = random.Random(4)
    for k in range(10):
        x = 610 + k * 74
        kind = rnd.randint(0, 3)
        if kind == 0:
            c.ell(x, 400, 22, 22, None, 6, WHITE)
        elif kind == 1:
            c.line([(x, 370), (x, 430)], WHITE, 8); c.line([(x - 18, 400), (x + 18, 400)], WHITE, 8)
        elif kind == 2:
            c.line([(x - 18, 430), (x, 370), (x + 18, 430)], WHITE, 8)
        else:
            c.rect(x - 16, 380, x + 16, 420, None, 0); c.d.rectangle([(x - 16) * K, 380 * K, (x + 16) * K, 420 * K], outline=WHITE, width=12)


def dock(c):
    c.rect(0, 0, W, H, SKY, 0); clouds(c, 13)
    ground(c, 520, SAND)
    c.rect(200, 600, 1720, 1000, BRICK, 6)
    c.rect(260, 640, 1660, 960, WATER, 5)
    boat(c, 600, 760, 1.0); boat(c, 1150, 820, 1.1)


def market(c):
    street(c, 21)
    for k, col in enumerate(((200, 80, 60), (230, 190, 90), (120, 150, 90))):
        x = 180 + k * 560
        c.poly([(x, 560), (x + 360, 560), (x + 400, 620), (x - 40, 620)], col, 5)
        c.rect(x, 620, x + 360, 760, (170, 130, 90), 5)
        for j in range(4):
            pot(c, x + 60 + j * 80, 600, 0.6, (180, 110 + j * 10, 70))


def field(c, dry=False):
    c.rect(0, 0, W, H, (230, 200, 160) if dry else SKY, 0)
    if not dry:
        clouds(c, 17); sun(c)
    c.rect(0, 560, W, H, (196, 160, 110) if dry else GRASS, 5)
    if dry:
        rnd = random.Random(8)
        for _ in range(40):
            x, y = rnd.randint(0, W), rnd.randint(600, 1060)
            c.line([(x, y), (x + rnd.randint(-60, 60), y + rnd.randint(10, 40)), (x + rnd.randint(-80, 80), y + rnd.randint(40, 70))], (150, 110, 70), 3)
    else:
        for row in range(6):
            for k in range(26):
                x = k * 76 + (row % 2) * 30
                y = 600 + row * 70
                c.line([(x, y + 40), (x + 6, y)], (220, 200, 100), 5)
                if row > 2:
                    c.ell(x + 6, y - 4, 10, 10, WHITE, 2)   # cotton
        c.poly([(1500, 560), (1920, 520), (1920, 600), (1560, 620)], WATER, 4)


def desk(c):
    c.rect(0, 0, W, H, (220, 214, 196), 0)
    c.rect(0, 780, W, H, (160, 120, 80), 5)
    c.rect(300, 640, 1620, 790, (140, 100, 64), 6)
    rnd = random.Random(6)
    for _ in range(14):
        x, y = rnd.randint(320, 1500), rnd.randint(560, 700)
        c.rect(x, y, x + 120, y + 80, WHITE, 3)
        for j in range(3):
            c.line([(x + 15 + j * 32, y + 25), (x + 30 + j * 32, y + 55)], INK, 3)


def lab(c):
    c.rect(0, 0, W, H, (214, 226, 230), 0)
    c.rect(0, 760, W, H, (180, 190, 196), 5)
    c.rect(200, 640, 1720, 780, WHITE, 6)
    for k in range(5):
        c.rect(260 + k * 120, 560, 320 + k * 120, 640, (200, 230, 240), 4, r=8)


def huts(c, dawn=True):
    c.rect(0, 0, W, H, (250, 210, 160) if dawn else SKY, 0)
    sun(c, 300, 300, (250, 190, 110))
    ground(c, 760, (190, 170, 110))
    for k, x in enumerate((900, 1250, 1580)):
        c.rect(x, 560, x + 240, 760, (176, 140, 96), 5)
        c.poly([(x - 30, 570), (x + 120, 440), (x + 270, 570)], (196, 170, 100), 5)
        c.ell(x + 140, 420 - k * 10, 20, 16, (230, 230, 230), 0)
    c.rect(330, 420, 380, 760, (110, 80, 50), 5)                                      # tree
    c.ell(355, 380, 190, 130, (120, 150, 80), 6)


def night_ruins(c):
    c.rect(0, 0, W, H, NIGHT, 0)
    rnd = random.Random(2)
    for _ in range(120):
        x, y = rnd.randint(0, W), rnd.randint(0, 620)
        c.ell(x, y, 3, 3, (250, 240, 200), 0)
    c.ell(1600, 180, 70, 70, (246, 236, 200), 0)
    ground(c, 780, (70, 60, 70))
    for k in range(8):
        h = rnd.randint(60, 220)
        c.rect(120 + k * 220, 780 - h, 260 + k * 220, 780, (110, 70, 60), 5)
    c.chord(1450, 600, 140, 120, 180, 360, (120, 100, 90), 5)


def hall(c):
    c.rect(0, 0, W, H, (196, 150, 104), 0)
    for k in range(7):
        c.rect(80 + k * 280, 120, 140 + k * 280, 800, BRICK, 5)
    c.rect(0, 800, W, H, SAND_D, 5)
    c.ell(960, 900, 520, 110, (176, 130, 90), 5)


def timeline(c):
    c.rect(0, 0, W, H, (236, 214, 166), 0)
    c.line([(120, 600), (1800, 600)], (150, 110, 60), 22)
    c.line([(120, 600), (1800, 600)], (200, 160, 90), 12)
    for x, s in ((300, 0.5), (900, 1.1), (1500, 0.6)):
        c.ell(x, 600, 30, 30, (150, 110, 60), 5)
        for k in range(3):
            house(c, x - 90 * s + k * 60 * s, 540, 50 * s, (60 + k * 30) * s, BRICK_L, door=False)
    c.rect(700, 520, 1100, 680, None, 0)


def kings_parade(c):
    c.rect(0, 0, W, H, SKY, 0); clouds(c, 19)
    ground(c, 840, SAND)


def split_line(c):
    c.line([(960, 0), (960, H)], INK, 10)


def cloud_rain(c, x, y, s=1.0):
    for dx, dy, r in ((0, 0, 60), (55, 12, 45), (-55, 14, 45)):
        c.ell(x + dx * s, y + dy * s, r * s, r * s * 0.8, (170, 176, 190), 4)
    c.ell(x, y + 110 * s, 10 * s, 16 * s, WATER, 3)


def skeleton(c, x, y, s=1.0):
    c.ell(x, y, 26 * s, 24 * s, WHITE, 4)
    c.line([(x + 26 * s, y), (x + 150 * s, y + 10 * s)], WHITE, 8)
    for k in range(4):
        c.line([(x + 50 * s + k * 22 * s, y - 16 * s), (x + 50 * s + k * 22 * s, y + 26 * s)], WHITE, 5)
    c.line([(x + 150 * s, y + 10 * s), (x + 210 * s, y - 20 * s)], WHITE, 7)
    c.line([(x + 150 * s, y + 10 * s), (x + 215 * s, y + 30 * s)], WHITE, 7)


def scale(c, x, y, s=1.0):
    c.line([(x, y), (x, y - 220 * s)], INK, 8)
    c.line([(x - 180 * s, y - 210 * s), (x + 180 * s, y - 210 * s)], INK, 8)
    for side in (-1, 1):
        c.line([(x + side * 170 * s, y - 210 * s), (x + side * 140 * s, y - 120 * s)], INK, 3)
        c.line([(x + side * 170 * s, y - 210 * s), (x + side * 200 * s, y - 120 * s)], INK, 3)
        c.chord(x + side * 170 * s, y - 120 * s, 60 * s, 30 * s, 0, 180, (200, 170, 90), 4)
    c.rect(x - 70 * s, y - 10 * s, x + 70 * s, y + 10 * s, DARK, 4)
    for k in range(5):
        sz = (12 + k * 8) * s
        c.rect(x + 260 * s + k * 90 * s - sz, y - 2 * sz, x + 260 * s + k * 90 * s + sz, y, (190, 170, 150), 4)


def toy_cart(c, x, y, s=1.0):
    c.rect(x - 60 * s, y - 50 * s, x + 60 * s, y, (200, 130, 80), 5)
    c.ell(x - 40 * s, y + 6 * s, 22 * s, 22 * s, (170, 110, 70), 5)
    c.ell(x + 40 * s, y + 6 * s, 22 * s, 22 * s, (170, 110, 70), 5)


def bullock_cart(c, x, y, s=1.0):
    c.ell(x - 150 * s, y - 80 * s, 80 * s, 50 * s, WHITE, 5)
    c.ell(x - 230 * s, y - 120 * s, 35 * s, 30 * s, WHITE, 5)
    c.line([(x - 250 * s, y - 145 * s), (x - 270 * s, y - 180 * s)], INK, 5)
    for k in (-190, -110):
        c.line([(x + k * s, y - 40 * s), (x + k * s, y)], INK, 8)
    c.rect(x - 60 * s, y - 120 * s, x + 140 * s, y - 50 * s, (170, 120, 70), 5)
    c.ell(x + 40 * s, y - 30 * s, 45 * s, 45 * s, (130, 90, 50), 6)


def medal(c, x, y, s=1.0):
    c.poly([(x - 20 * s, y - 80 * s), (x + 20 * s, y - 80 * s), (x + 8 * s, y - 20 * s), (x - 8 * s, y - 20 * s)], (60, 100, 170), 3)
    c.ell(x, y, 34 * s, 34 * s, (240, 196, 70), 5)


def sparkles(c, pts):
    for x, y in pts:
        c.line([(x - 18, y), (x + 18, y)], (250, 230, 120), 6)
        c.line([(x, y - 18), (x, y + 18)], (250, 230, 120), 6)
