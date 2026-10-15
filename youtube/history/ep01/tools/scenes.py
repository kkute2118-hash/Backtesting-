"""Draw every scene of episode 1 into images/sNN.png:  python scenes.py OUTDIR"""
import sys
from pathlib import Path
from toon import *

S = {}
def scene(f):
    S[f.__name__] = f
    return f

G = gappu
SITES = [(700, 180), (640, 560), (600, 700), (820, 620), (930, 470), (1010, 300), (860, 120), (760, 300),
         (980, 820), (880, 900), (1050, 160), (560, 640), (720, 420), (1100, 260), (940, 760)]


# 1 मिलिए गप्पू काका से
@scene
def s01(c): street(c, 2); c.rect(560, 820, 900, 900, BRICK_L, 5); G(c, 730, 990, 1.45, "wave", "grin")
@scene
def s02(c): aerial_city(c); G(c, 380, 1060, 1.5, "pointl", "grin", flip=True)
@scene
def s03(c):
    street(c, 4); G(c, 620, 1000, 1.4, "belly", "laugh")
    person(c, 1180, 1000, 1.0, skin=SKIN, coat=(70, 110, 170), kid=True, face="shock", hair=DARK)
    person(c, 1420, 1000, 1.0, skin=SKIN2, coat=(200, 80, 90), kid=True, female=True, face="shock", hair=DARK)
@scene
def s04(c):
    pyramid_scene(c)
    for k in range(3): person(c, 600 + k * 70, 760, 0.7, skin=SKIN2, cloth=WHITE, pose="work", face="sad", flip=True)
    person(c, 220, 800, 0.85, skin=SKIN2, cloth=(240, 220, 120), crown=(240, 196, 70), pose="point", face="angry")
@scene
def s05(c): aerial_city(c); sparkles(c, [(400, 300), (1000, 640), (700, 900)])
@scene
def s06(c):
    c.rect(0, 0, W, H, SKY, 0); clouds(c, 3)
    c.poly([(0, 1080), (0, 520), (500, 380), (1400, 360), (1920, 520), (1920, 1080)], (196, 160, 110), 6)
    for row in range(3):
        for k in range(8): house(c, 260 + k * 180, 760 + row * 120, 140, 90, BRICK_L, door=False)
    for yy in (700, 830, 960): c.line([(0, yy), (W, yy)], (160, 120, 80), 4)
    c.ell(960, 345, 70, 34, (240, 150, 60), 5); c.ell(1015, 320, 26, 22, (240, 150, 60), 5)   # sleeping cat


# 2 ईंटों वाली रेल
@scene
def s07(c): street(c, 6); G(c, 960, 1080, 1.9, "holdup", "sly")
@scene
def s08(c):
    railway(c); brit(c, 420, 900, 1.15, "point", "neutral")
    for k in range(3): villager(c, 800 + k * 150, 900, 1.0, pose="work", face="neutral", tone=k)
@scene
def s09(c):
    railway(c); h = villager(c, 1000, 980, 1.3, pose="holdup", face="laugh", tone=1); brick(c, *h["r"], 1.6, -10)
    villager(c, 1500, 760, 0.8, face="shock", tone=2); villager(c, 1680, 760, 0.8, face="shock")
@scene
def s10(c): railway(c); train(c, 420, 860, 1.4); G(c, 1300, 1060, 1.3, "face", "sad")
@scene
def s11(c): railway(c); h = brit(c, 900, 1000, 1.35, "shrug", "neutral"); brick(c, *h["r"], 1.4)
@scene
def s12(c): trench(c); scholar(c, 950, 930, 1.3, "work", "smile", flip=True)
@scene
def s13(c): mound_stupa(c); scholar(c, 1000, 560, 1.0, "up", "laugh")
@scene
def s14(c): map_base(c, dots=[(700, 180), (600, 690)])
@scene
def s15(c):
    street(c, 8)
    for k in range(5): person(c, 300 + k * 150, 1000, 0.95, skin=SKIN_PALE, coat=(60 + k * 15, 60, 80), face="shock", glasses=k % 2 == 0)
    h = brit(c, 1450, 1000, 1.3, "holdup", "grin", era="1920"); seal(c, h["r"][0], h["r"][1] - 30, 1.0)


# 3 हमारा इलाका
@scene
def s16(c): street(c, 10); G(c, 960, 1060, 1.8, "hips", "grin")
@scene
def s17(c): map_base(c, dots=SITES)
@scene
def s18(c):
    pyramid_scene(c); c.rect(0, 820, W, H, SAND, 0)
    person(c, 520, 1000, 1.2, skin=SKIN2, cloth=WHITE, crown=(240, 196, 70), face="neutral")
    person(c, 900, 1000, 1.2, skin=SKIN, cloth=(140, 90, 150), beard=(30, 26, 24), beard_len=30, hair=(30, 26, 24), face="neutral")
    c.rect(1180, 880, 1480, 1000, (170, 120, 70), 5); G(c, 1330, 880, 1.25, "up", "grin")
@scene
def s19(c): timeline(c)
@scene
def s20(c):
    kings_parade(c); G(c, 300, 1000, 1.3, "hold", "sly"); pot(c, 430, 650, 0.6)
    for k, col in enumerate(((240, 196, 70), (200, 60, 60), (90, 120, 200), (230, 230, 230))):
        person(c, 800 + k * 280, 960, 0.9, skin=[SKIN, SKIN2][k % 2], cloth=col, crown=(240, 196, 70), pose="up" if k % 2 else "both", face="shock")


# 4 स्मार्ट शहर
@scene
def s21(c):
    street(c, 12); G(c, 520, 1040, 1.35, "wave", "grin", flip=True)
    villager(c, 1100, 960, 0.85, female=True, tone=1); villager(c, 1350, 960, 0.85, tone=2, pose="hold"); villager(c, 1560, 960, 0.75, kid=True, pose="up")
@scene
def s22(c):
    c.rect(0, 0, W, H, SAND, 0)
    for k in range(0, W, 160): c.line([(k, 200), (k, H)], (190, 150, 100), 4)
    for k in range(200, H, 160): c.line([(0, k), (W, k)], (190, 150, 100), 4)
    a = villager(c, 500, 900, 1.2, pose="both", tone=0); b = villager(c, 1400, 900, 1.2, pose="both", flip=True, tone=1)
    c.line([a["r"], b["r"]], (240, 230, 200), 6)
@scene
def s23(c):
    kiln(c); h = villager(c, 900, 960, 1.3, pose="hold", face="grin", tone=1)
    brick(c, h["r"][0] + 20, h["r"][1], 1.3); c.line([(h["r"][0] - 40, h["r"][1] - 30), (h["r"][0] + 80, h["r"][1] - 30)], (120, 80, 50), 6)
@scene
def s24(c):
    street(c, 14); h = villager(c, 700, 1000, 1.35, female=True, pose="holdup", face="angry")
    brick(c, h["r"][0], h["r"][1] - 20, 1.5, 25); G(c, 1300, 1000, 1.3, "behind", "sad", young=True)
@scene
def s25(c): street(c, 16); G(c, 960, 1070, 1.85, "scratch", "sly")
@scene
def s26(c):
    street(c, 18); c.rect(0, 690, W, 712, (170, 100, 66), 4); G(c, 960, 1040, 1.5, "both", "laugh")
    sparkles(c, [(300, 660), (700, 650), (1250, 660), (1650, 650)])
@scene
def s27(c): drain_cutaway(c); villager(c, 1380, 560, 0.75, pose="work", face="neutral", tone=2)
@scene
def s28(c):
    c.rect(0, 0, 960, H, SKY, 0); c.rect(0, 760, 960, H, SAND, 5); c.rect(0, 720, 960, 760, (170, 100, 66), 4)
    for k in range(3): house(c, 20 + k * 310, 720, 280, 260, BRICK_L)
    G(c, 480, 1040, 1.1, "both", "grin")
    c.rect(960, 0, W, H, (180, 196, 206), 0); c.rect(960, 760, W, H, (150, 150, 150), 5)
    for k in range(3): c.rect(990 + k * 310, 380, 1250 + k * 310, 720, (210, 200, 190), 5)
    c.rect(960, 740, W, 800, (100, 120, 80), 5)
    for k in range(6): c.ell(1000 + k * 160, 750, 30, 14, (120, 140, 90), 3)
    person(c, 1440, 1040, 1.1, skin=SKIN, coat=(80, 120, 170), pose="face", face="angry")
    split_line(c)
@scene
def s29(c):
    courtyard(c); villager(c, 600, 900, 1.1, female=True, pose="work", tone=0); pot(c, 760, 860, 0.9)
    villager(c, 1000, 900, 1.0, tone=1); villager(c, 1580, 640, 0.6, kid=True, pose="up")
@scene
def s30(c): courtyard(c, well=True); h = villager(c, 820, 960, 1.25, female=True, pose="hold", tone=1); pot(c, h["r"][0] + 30, h["r"][1] + 20, 0.9)


# 5 महान स्नानागार
@scene
def s31(c):
    c.rect(0, 0, W, H, SKY, 0); clouds(c, 23); ground(c, 860, SAND)
    c.poly([(200, 860), (520, 420), (1400, 420), (1720, 860)], BRICK_L, 6)
    c.rect(700, 300, 1220, 420, BRICK, 6); c.rect(760, 330, 1160, 400, WATER, 4)
    for k in range(6): c.rect(560 + k * 40, 700 - k * 50, 760, 740 - k * 50, BRICK, 3)
    for k in range(3): villager(c, 640 + k * 70, 860 - k * 60, 0.5, tone=k)
@scene
def s32(c): great_bath(c)
@scene
def s33(c):
    great_bath(c, water=False)
    for k in range(2): villager(c, 700 + k * 500, 960, 1.15, pose="work", face="angry" if k else "neutral", tone=k)
    c.ell(1300, 820, 30, 22, (30, 30, 30), 0)
@scene
def s34(c): great_bath(c); G(c, 960, 1070, 1.8, "zip", "zip")
@scene
def s35(c):
    great_bath(c, sunrise=True)
    for k in range(4): villager(c, 560 + k * 240, 1000 - (k % 2) * 30, 0.95, female=k % 2 == 1, tone=k, cloth=WHITE, face="neutral")
@scene
def s36(c):
    c.rect(0, 0, W, H, SKY, 0); ground(c, 760, SAND)
    c.rect(300, 420, 1620, 760, BRICK_L, 6)
    for k in range(9): c.rect(340 + k * 140, 470, 420 + k * 140, 760, BRICK, 4)
    h = scholar(c, 650, 1040, 1.25, "hold", "angry", modern=True); c.ell(h["r"][0] + 30, h["r"][1] + 30, 45, 55, (200, 170, 110), 5)
    scholar(c, 1300, 1040, 1.25, "pointl", "angry", modern=True, female=True, flip=True)


# 6 धोलावीरा और लोथल
@scene
def s37(c): map_base(c, dots=[(980, 820)]); c.ell(1000, 830, 150, 60, (245, 240, 230), 4); c.ell(980, 820, 14, 14, (240, 120, 40), 4)
@scene
def s38(c):
    reservoir(c)
    for k in range(4): villager(c, 400 + k * 380, 700, 0.75, female=k % 2 == 0, pose="up", face="laugh", tone=k)
@scene
def s39(c): gate(c); villager(c, 960, 1020, 1.1, pose="pointl", face="shock", tone=1, flip=True)
@scene
def s40(c):
    c.rect(0, 0, W, H, SKY, 0); clouds(c, 29); ground(c, 760, SAND)
    for k in range(6): c.rect(100 + k * 300, 560 + (k % 2) * 60, 340 + k * 300, 760, (196, 180, 156), 5)
    h = G(c, 960, 1060, 1.6, "holdup", "laugh"); medal(c, h["r"][0], h["r"][1] + 30, 1.4)
@scene
def s41(c):
    dock(c)
    for k in range(3): villager(c, 400 + k * 200, 560, 0.7, pose="holdup", tone=k)
    pot(c, 1400, 500, 0.7); pot(c, 1500, 500, 0.7)
@scene
def s42(c):
    dock(c)
    for k, x in enumerate((350, 1550)): scholar(c, x, 1060, 1.1, "point" if k == 0 else "pointl", "angry", modern=True, flip=k == 1, female=k == 1)
    scholar(c, 960, 520, 0.7, "up", "shock")
    G(c, 960, 1070, 1.25, "face", "sad")


# 7 व्यापार और लिपि
@scene
def s43(c): market(c); villager(c, 450, 990, 1.0, tone=1, pose="hold"); villager(c, 1050, 990, 1.0, female=True); villager(c, 1600, 990, 1.0, tone=2, pose="wave")
@scene
def s44(c): map_base(c, sea_route=True, dots=[(600, 690)])
@scene
def s45(c):
    market(c)
    person(c, 600, 1010, 1.3, skin=SKIN2, cloth=(120, 80, 140), beard=(30, 26, 24), beard_len=40, hair=(30, 26, 24), pose="point", face="sly")
    h = G(c, 1300, 1010, 1.3, "holdup", "grin", flip=True); necklace(c, h["r"][0], h["r"][1] + 40, 1.0)
@scene
def s46(c): c.rect(0, 0, W, H, (230, 210, 170), 0); c.rect(0, 800, W, H, (170, 130, 90), 5); scale(c, 700, 800, 1.6)
@scene
def s47(c):
    c.rect(0, 0, W, H, (226, 196, 150), 0)
    c.ell(960, 640, 360, 300, SKIN, 8); seal(c, 960, 520, 4.0)
@scene
def s48(c): desk(c); scholar(c, 960, 640, 1.2, "scratch", "sad", modern=False)
@scene
def s49(c): desk(c); G(c, 760, 1060, 1.4, "behind", "wink"); seal(c, 640, 830, 0.8); scholar(c, 1350, 1060, 1.3, "pointl", "shock", flip=True)


# 8 हमारी ज़िंदगी
@scene
def s50(c):
    street(c, 31)
    villager(c, 300, 1000, 1.0, female=True, pose="work", tone=0); pot(c, 430, 960, 0.8)
    villager(c, 750, 1000, 1.0, pose="hold", tone=1); villager(c, 1150, 1000, 0.8, kid=True, pose="up", face="laugh")
    villager(c, 1350, 1000, 0.8, kid=True, pose="wave", face="laugh", tone=2); villager(c, 1700, 1000, 1.0, pose="work", tone=2)
@scene
def s51(c):
    field(c); villager(c, 600, 1000, 1.1, pose="work", tone=1); villager(c, 1000, 980, 1.0, female=True, pose="hold", tone=0)
    c.ell(1450, 900, 110, 60, WHITE, 5); c.ell(1360, 860, 40, 34, WHITE, 5)
@scene
def s52(c):
    c.rect(0, 0, W, H, (200, 160, 120), 0); c.rect(0, 820, W, H, (150, 110, 70), 5)
    h = villager(c, 900, 1060, 1.5, pose="holdup", face="neutral", tone=1); c.ell(h["r"][0], h["r"][1] - 20, 16, 16, RED, 4)
@scene
def s53(c): street(c, 33); villager(c, 960, 1060, 1.7, female=True, pose="hips", face="sly", tone=1, cloth=(140, 100, 60))
@scene
def s54(c):
    street(c, 35)
    person(c, 820, 1050, 1.5, skin=SKIN, cloth=(196, 160, 110), cloth2=(160, 90, 70), beard=(40, 34, 30), beard_len=10, band=(220, 200, 120), face="neutral")
    G(c, 1350, 1040, 1.25, "whisper", "sly")
@scene
def s55(c):
    courtyard(c)
    for k in range(3): villager(c, 450 + k * 450, 980, 0.95, kid=True, pose="up" if k != 1 else "hold", face="laugh", tone=k); toy_cart(c, 560 + k * 450, 960, 0.9)
@scene
def s56(c):
    street(c, 37); h = G(c, 960, 1060, 1.5, "holdup", "neutral")
    c.limb([h["r"], (h["r"][0] - 150, h["r"][1] + 40)], (140, 110, 70), 26)
@scene
def s57(c):
    hall(c)
    for k in range(5): villager(c, 400 + k * 280, 900, 0.95, tone=k, pose="point" if k % 2 else "both", face="angry" if k == 2 else "neutral", flip=k > 2)


# 9 शहर खाली क्यों हुए
@scene
def s58(c):
    c.rect(0, 0, W, H, SKY_DUSK, 0); ground(c, 820, SAND_D)
    c.rect(560, 760, 1360, 880, BRICK, 6); c.line([(900, 760), (930, 820), (910, 880)], INK, 4)
    G(c, 960, 770, 1.3, "behind", "sad")
@scene
def s59(c):
    street(c, 39, dusk=True, empty=True)
    c.ell(700, 960, 60, 32, (150, 110, 70), 5); c.ell(650, 930, 26, 22, (150, 110, 70), 5)
    villager(c, 1500, 980, 0.8, pose="hold", face="sad", flip=True); villager(c, 1650, 980, 0.8, female=True, face="sad", flip=True)
@scene
def s60(c): trench(c); skeleton(c, 700, 840, 1.2); skeleton(c, 1050, 900, 1.0); brit(c, 400, 1000, 1.2, "point", "shock", era="1920")
@scene
def s61(c):
    lab(c); h = scholar(c, 960, 1060, 1.4, "holdup", "neutral", modern=True, female=True)
    c.ell(h["r"][0], h["r"][1] - 40, 40, 36, WHITE, 5)
    c.ell(h["l"][0] - 60, h["l"][1] - 60, 50, 50, (220, 240, 250), 6)
@scene
def s62(c): field(c, dry=True); cloud_rain(c, 960, 200, 1.3); villager(c, 600, 1000, 1.1, pose="up", face="sad"); villager(c, 1350, 1000, 1.1, female=True, face="sad", tone=1)
@scene
def s63(c): map_base(c, dry=True, dots=[(700, 180), (640, 560)], dim=[(1010, 300), (930, 470), (820, 620), (1050, 160), (860, 560)])
@scene
def s64(c):
    c.rect(0, 0, W, H, SKY_DUSK, 0); sun(c, 1700, 400, (250, 160, 90)); ground(c, 760, SAND_D)
    for k in range(6): house(c, 1350 + k * 90, 760, 80, 120, (190, 130, 100), door=False)
    bullock_cart(c, 900, 950, 1.0)
    villager(c, 400, 1000, 0.95, pose="hold", flip=True, tone=1); villager(c, 560, 1000, 0.95, female=True, flip=True)
    villager(c, 1200, 990, 0.7, kid=True, flip=True, tone=2)
@scene
def s65(c):
    huts(c); G(c, 520, 1000, 1.05, "both", "grin")
    for k in range(3): villager(c, 800 + k * 160, 1000, 0.7, kid=True, face="laugh", tone=k)


# 10 हम आज भी यहीं हैं
@scene
def s66(c):
    c.rect(0, 0, 960, H, (230, 200, 150), 0); c.rect(960, 0, W, H, (240, 214, 170), 0)
    villager(c, 480, 1060, 1.45, female=True, pose="hips", tone=1)
    person(c, 1440, 1060, 1.45, skin=SKIN2, cloth=(200, 60, 90), female=True, bangles=True, pose="hips")
    split_line(c)
@scene
def s67(c):
    field(c); bullock_cart(c, 900, 960, 1.2)
    for k in range(4): pot(c, 1350 + k * 110, 980, 0.9)
@scene
def s68(c):
    trench(c); c.poly([(260, 380), (960, 200), (1660, 380)], (240, 236, 220), 6)
    scholar(c, 700, 960, 1.0, "work", "neutral", modern=True); scholar(c, 1150, 960, 1.0, "work", "neutral", modern=True, female=True, flip=True)
    G(c, 1550, 900, 1.0, "holdup", "sly")
@scene
def s69(c): night_ruins(c); h = G(c, 960, 1060, 1.6, "holdup", "grin"); seal(c, h["r"][0], h["r"][1] - 30, 1.2); c.ell(h["r"][0], h["r"][1] - 30, 70, 70, None, 6, (250, 230, 140))
@scene
def s70(c): street(c, 41); G(c, 960, 1070, 1.85, "cross", "puff")
@scene
def s71(c): street(c, 43); G(c, 960, 1080, 2.0, "ear", "smile")


def thumbnail(path):
    from PIL import ImageFont
    c = Canvas(); aerial_city(c); G(c, 520, 1150, 2.1, "pointl", "shock", flip=True)
    c.save(path, vignette=True)
    im = Image.open(path); d = ImageDraw.Draw(im)
    f = ImageFont.truetype("/usr/share/fonts/truetype/freefont/FreeSansBold.ttf", 150, layout_engine=ImageFont.Layout.RAQM)
    for i, line in enumerate(("मैं 4500 साल", "पुराना हूँ!")):
        d.text((980, 260 + i * 190), line, font=f, fill=(255, 220, 90), stroke_width=12, stroke_fill=(30, 20, 10), language="hi")
    im.save(path)


if __name__ == "__main__":
    out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
    only = set(sys.argv[2:])
    for name, f in S.items():
        if only and name not in only:
            continue
        c = Canvas(); f(c); c.save(out / f"{name}.png")
        print(name, end=" ", flush=True)
    if not only:
        thumbnail(out / "thumbnail.png")
    print()
