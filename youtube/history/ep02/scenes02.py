"""Draw episode 2's scenes: python scenes02.py script.json images/"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ep01" / "tools"))
from toon import *

G = gappu
D = {}
def sc(f):
    D[f.__name__] = f
    return f


def ruins_ground(c, dusk=False):
    c.rect(0, 0, W, H, SKY_DUSK if dusk else SKY, 0)
    if not dusk: clouds(c, 51)
    ground(c, 760, SAND_D)
    rnd = random.Random(3)
    for k in range(9):
        h = rnd.randint(60, 200)
        c.rect(60 + k * 210, 760 - h, 210 + k * 210, 760, BRICK_L, 5)
        c.line([(100 + k * 210, 760 - h + 10), (120 + k * 210, 760 - h + 50)], INK, 3)


@sc
def gappu_hello(c): street(c, 52); G(c, 960, 1070, 1.8, "wave", "laugh")
@sc
def gappu_sad_ruins(c): ruins_ground(c, dusk=True); G(c, 960, 1060, 1.45, "behind", "sad")
@sc
def city_then_empty(c):
    street(c, 53); c.rect(960, 0, W, H, (0, 0, 0), 0)
    c2 = Canvas(); street(c2, 53, dusk=True, empty=True)
    c.im.paste(c2.im.crop((960 * K, 0, W * K, H * K)), (960 * K, 0))
    for k in range(3): villager(c, 200 + k * 230, 1000, 0.9, female=k == 1, tone=k, pose="wave" if k == 2 else "down")
    split_line(c)
@sc
def three_questions(c):
    c.rect(0, 0, W, H, (230, 205, 160), 0)
    for k, (x, col) in enumerate(((380, RED), (960, WATER), (1540, (200, 150, 60)))):
        c.ell(x, 420, 210, 210, WHITE, 6)
        c.ell(x, 420, 170, 170, col, 0)
    for k in range(3):   # sword, wave, sun
        pass
    c.line([(300, 500), (460, 340)], (230, 230, 230), 22); c.line([(330, 420), (390, 480)], INK, 10)
    for k in range(3): c.arc(960, 420 + k * 40 - 40, 120, 40, 200, 340, 12, WHITE)
    c.ell(1540, 420, 80, 80, (250, 214, 120), 0)
    for a in range(0, 360, 45):
        import math
        c.line([(1540 + 100 * math.cos(math.radians(a)), 420 + 100 * math.sin(math.radians(a))),
                (1540 + 140 * math.cos(math.radians(a)), 420 + 140 * math.sin(math.radians(a)))], (250, 214, 120), 10)
    G(c, 960, 1180, 1.0, "shrug", "shock")
@sc
def gappu_judge(c):
    c.rect(0, 0, W, H, (196, 150, 104), 0); c.rect(0, 820, W, H, SAND_D, 5)
    c.rect(560, 640, 1360, 860, (140, 96, 60), 6)
    G(c, 960, 1000, 1.35, "holdup", "sly")
@sc
def timeline_rope(c): timeline(c); G(c, 1700, 1070, 0.8, "pointl", "smile", flip=True)
@sc
def dig_layers(c):
    c.rect(0, 0, W, 300, SKY, 0); c.rect(0, 300, W, H, (196, 160, 110), 0)
    for k, col in enumerate(((176, 140, 96), (160, 122, 84), (186, 150, 104), (150, 112, 78), (172, 134, 92))):
        c.rect(0, 300 + k * 156, W, 456 + k * 156, col, 4)
    for k in range(6): brick(c, 300 + k * 260, 380, 1.3, (k * 17) % 30 - 15)
    for k in range(8): c.rect(200 + k * 200, 900, 330 + k * 200, 950, BRICK_L, 4)
    scholar(c, 1650, 300, 0.75, "point", "smile", flip=True)
@sc
def crooked_walls(c):
    c.rect(0, 0, W, H, SKY, 0); ground(c, 840, SAND)
    house(c, 200, 840, 700, 380, BRICK_L)
    c.poly([(420, 840), (440, 460), (470, 460), (480, 840)], (150, 110, 80), 5)
    c.poly([(640, 840), (610, 520), (640, 520), (690, 840)], (150, 110, 80), 5)
    for k in range(6): brick(c, 1150 + (k % 3) * 90, 800 - (k // 3) * 40, 1.3, (k * 23) % 40 - 20)
    villager(c, 1550, 1000, 1.0, pose="hold", face="neutral", tone=1)
@sc
def kiln_in_street(c):
    street(c, 54); c.chord(960, 900, 230, 260, 180, 360, BRICK, 6); c.ell(960, 830, 80, 60, (60, 30, 20), 5); c.ell(960, 840, 46, 34, (250, 150, 60), 0)
    for k in range(3): c.ell(900 + k * 60, 560 - k * 30, 40, 32, (200, 200, 200), 0)
    villager(c, 520, 1000, 0.95, pose="work", tone=2); pot(c, 1400, 960, 0.9)
@sc
def blocked_drain(c):
    street(c, 55); c.rect(0, 690, W, 712, (110, 90, 60), 4)
    for k in range(9): c.ell(150 + k * 200, 700, 40, 18, (110, 120, 60), 3)
    G(c, 960, 1060, 1.5, "face", "angry")
@sc
def gappu_think(c):
    c.rect(0, 0, W, H, (226, 196, 150), 0)
    for k, (x, y, r) in enumerate(((1300, 300, 30), (1380, 220, 45), (1500, 140, 70))): c.ell(x, y, r, r * 0.8, WHITE, 5)
    c.line([(1470, 140), (1530, 140)], INK, 8); c.line([(1500, 110), (1500, 125)], INK, 8); c.ell(1500, 165, 6, 6, INK, 0)
    G(c, 900, 1080, 1.9, "scratch", "sly")
@sc
def wheeler_arrives(c): mound_stupa(c); brit(c, 600, 1000, 1.25, "point", "neutral", era="1920"); villager(c, 1300, 980, 0.9, pose="work", tone=1)
@sc
def skeletons_found(c): trench(c); skeleton(c, 650, 820, 1.2); skeleton(c, 1050, 900, 1.0); skeleton(c, 1250, 760, 0.8)
@sc
def wheeler_shouts(c): trench(c); skeleton(c, 900, 860, 1.1); brit(c, 450, 1000, 1.35, "up", "shock", era="1920")
@sc
def newspaper_headline(c):
    c.rect(0, 0, W, H, (90, 80, 70), 0); c.rect(360, 120, 1560, 980, (236, 230, 214), 6)
    c.rect(420, 180, 1500, 300, INK, 0)
    for r in range(10): c.line([(420, 380 + r * 52), (900, 380 + r * 52)], (120, 120, 120), 8)
    c.rect(960, 360, 1500, 700, (200, 196, 186), 4); skeleton(c, 1050, 540, 1.3)
    for r in range(4): c.line([(960, 760 + r * 52), (1500, 760 + r * 52)], (120, 120, 120), 8)
@sc
def gappu_finger_up(c): street(c, 56); G(c, 960, 1070, 1.85, "holdup", "sly")
@sc
def dales_lab(c): lab(c); h = scholar(c, 900, 1060, 1.3, "holdup", "neutral", modern=True); c.ell(h["r"][0], h["r"][1] - 40, 40, 36, WHITE, 5); skeleton(c, 1250, 700, 0.9)
@sc
def layers_skeletons(c):
    c.rect(0, 0, W, H, (196, 160, 110), 0)
    for k, col in enumerate(((176, 140, 96), (160, 122, 84), (186, 150, 104), (150, 112, 78))):
        c.rect(0, 100 + k * 245, W, 345 + k * 245, col, 4)
        skeleton(c, 300 + k * 380, 230 + k * 245, 0.9)
@sc
def no_battle_signs(c):
    ruins_ground(c)
    for x in (480, 960, 1440):
        c.ell(x, 400, 120, 120, WHITE, 6); c.line([(x - 80, 320), (x + 80, 480)], RED, 16)
    c.ell(480, 410, 40, 60, (240, 120, 40), 0)                     # fire
    c.line([(910, 450), (1010, 350)], (200, 200, 200), 14)          # sword
    c.rect(1400, 360, 1480, 440, (150, 140, 130), 4)                 # broken wall
@sc
def dales_article(c):
    c.rect(0, 0, W, H, (214, 226, 230), 0); c.rect(300, 140, 1100, 960, (246, 242, 230), 6)
    for r in range(13): c.line([(360, 220 + r * 55), (1040, 220 + r * 55)], (120, 120, 120), 8)
    scholar(c, 1450, 1050, 1.35, "holdup", "laugh", modern=True)
@sc
def gappu_shrug(c): ruins_ground(c); G(c, 960, 1070, 1.7, "shrug", "sly")
@sc
def indus_river(c):
    c.rect(0, 0, W, H, SKY, 0); clouds(c, 57)
    c.rect(0, 520, W, H, GRASS, 5)
    c.poly([(0, 760), (W, 640), (W, 900), (0, 1000)], WATER, 6)
    for k in range(5): house(c, 200 + k * 260, 640, 200, 160, BRICK_L, door=k % 2 == 0)
    boat(c, 1300, 820, 0.9)
@sc
def flood_silt(c):
    c.rect(0, 0, W, H, (196, 160, 110), 0)
    for k in range(6):
        col = (170, 150, 120) if k % 2 else (120, 140, 150)
        c.rect(0, 120 + k * 160, W, 280 + k * 160, col, 4)
    scholar(c, 960, 1060, 1.2, "point", "shock", modern=True)
@sc
def platform_rebuild(c):
    c.rect(0, 0, W, H, SKY, 0); c.poly([(0, 900), (W, 860), (W, H), (0, H)], WATER, 5)
    c.rect(500, 640, 1420, 900, BRICK, 6); house(c, 650, 640, 300, 220, BRICK_L); house(c, 1000, 640, 300, 260, BRICK_L)
    villager(c, 1600, 880, 0.9, pose="holdup", face="laugh", tone=1)
@sc
def scientists_argue(c):
    c.rect(0, 0, W, H, (214, 226, 230), 0); c.rect(0, 840, W, H, (180, 190, 196), 5)
    c.rect(700, 300, 1220, 640, WHITE, 6); c.poly([(720, 600), (900, 420), (1000, 520), (1200, 340), (1200, 620), (720, 620)], (150, 180, 200), 3)
    scholar(c, 450, 1060, 1.2, "point", "angry", modern=True); scholar(c, 1500, 1060, 1.2, "pointl", "angry", modern=True, female=True, flip=True)
@sc
def sky_clouds(c):
    c.rect(0, 0, W, H, (150, 170, 196), 0); ground(c, 860, GRASS)
    for k in range(4): cloud_rain(c, 300 + k * 440, 220, 1.2)
    G(c, 960, 1070, 1.2, "up", "neutral")
@sc
def world_map_dry(c):
    c.rect(0, 0, W, H, (120, 176, 206), 0)
    c.poly([(200, 300), (700, 220), (900, 420), (760, 700), (400, 760), (180, 560)], (236, 214, 166), 6)    # Egypt / Africa
    c.poly([(820, 200), (1250, 160), (1350, 380), (1100, 520), (880, 430)], (236, 214, 166), 6)               # West Asia
    c.poly([(1320, 260), (1760, 240), (1820, 620), (1560, 900), (1380, 620)], (236, 214, 166), 6)              # India
    for x, y in ((500, 450), (1080, 330), (1560, 420)): sun(c, x, y, (250, 150, 80))
@sc
def egypt_mesopotamia_dry(c):
    c.rect(0, 0, 640, H, (246, 196, 120), 0); c.poly([(120, 760), (320, 380), (520, 760)], (220, 180, 110), 5)
    c.rect(640, 0, 1280, H, (236, 200, 150), 0); c.rect(800, 520, 1120, 760, (200, 160, 110), 5); c.rect(860, 400, 1060, 520, (200, 160, 110), 5)
    c.rect(1280, 0, W, H, (230, 200, 160), 0)
    c.rect(1280, 760, W, H, (196, 160, 110), 4); cloud_rain(c, 1600, 260, 1.0)
    c.rect(0, 760, 1280, H, (214, 182, 124), 4)
    c.line([(640, 0), (640, H)], INK, 8); c.line([(1280, 0), (1280, H)], INK, 8)
@sc
def scientists_samples(c):
    lab(c)
    for k in range(4): c.rect(380 + k * 280, 380, 450 + k * 280, 640, [(170, 140, 100), (140, 140, 150), (190, 170, 130), (120, 130, 150)][k], 5, r=10)
    scholar(c, 1600, 1060, 1.2, "pointl", "smile", modern=True, female=True, flip=True)
@sc
def dry_field(c): field(c, dry=True); villager(c, 700, 1000, 1.1, pose="face", face="sad"); villager(c, 1250, 1000, 1.05, female=True, face="sad", tone=1)
@sc
def empty_market(c):
    market(c); c.rect(0, 0, W, H, (0, 0, 0), 0) if False else None
    G(c, 1500, 1060, 1.15, "both", "sad")
@sc
def map_rivers(c): map_base(c, dots=[(1010, 300), (930, 470), (820, 620), (1050, 160), (980, 820), (700, 180), (640, 560)])
@sc
def map_river_dry(c): map_base(c, dry=True, dots=[(700, 180), (640, 560), (1250, 380), (1300, 250)], dim=[(1010, 300), (930, 470), (820, 620), (1050, 160)])
@sc
def families_walk(c):
    c.rect(0, 0, W, H, SKY_DUSK, 0); sun(c, 1700, 380, (250, 160, 90)); ground(c, 760, SAND_D)
    bullock_cart(c, 1000, 960, 1.0)
    for k in range(4): villager(c, 300 + k * 160, 1000, 0.9, female=k % 2 == 1, kid=k == 3, pose="hold" if k == 0 else "down", flip=False, tone=k)
@sc
def woman_leaving(c): street(c, 58, dusk=True, empty=True); h = villager(c, 960, 1070, 1.6, female=True, pose="pointl", face="smile", tone=1, flip=True); pot(c, 1250, 1000, 0.9)
@sc
def trade_boat(c): map_base(c, sea_route=True, dots=[(600, 690)])
@sc
def clay_tablet(c):
    c.rect(0, 0, W, H, (120, 100, 80), 0); c.rect(560, 160, 1360, 920, (196, 170, 130), 8, r=40)
    for r in range(9):
        for k in range(10): c.line([(640 + k * 70, 240 + r * 72), (670 + k * 70, 260 + r * 72)], (120, 96, 70), 7)
@sc
def bead_maker_idle(c):
    c.rect(0, 0, W, H, (200, 160, 120), 0); c.rect(0, 820, W, H, (150, 110, 70), 5)
    villager(c, 900, 1060, 1.4, pose="belly", face="sad", tone=1); necklace(c, 1300, 900, 1.2)
@sc
def market_dusk(c): street(c, 59, dusk=True, empty=True); G(c, 960, 1060, 1.3, "behind", "sad")
@sc
def villages(c):
    huts(c)
    for k in range(3): villager(c, 700 + k * 200, 1000, 0.8, tone=k, female=k == 1)
@sc
def village_life(c):
    huts(c); villager(c, 600, 1000, 0.95, female=True, pose="work"); pot(c, 760, 960, 0.8)
    c.ell(1250, 900, 110, 60, WHITE, 5); c.ell(1160, 860, 40, 34, WHITE, 5)
@sc
def four_causes(c):
    c.rect(0, 0, W, H, (236, 214, 166), 0)
    cols = (WATER, (250, 190, 90), (150, 140, 120), (176, 104, 64))
    for k in range(4):
        x, y = (480, 1440)[k % 2], (300, 760)[k // 2]
        c.rect(x - 330, y - 200, x + 330, y + 200, cols[k], 6, r=30)
    for k in range(3): c.arc(480, 300 + k * 40 - 40, 120, 40, 200, 340, 12, WHITE)
    sun(c, 1440, 300, (250, 150, 60))
    c.line([(200, 760), (420, 700), (600, 780), (760, 720)], (200, 190, 160), 14)
    boat(c, 1440, 820, 0.8)
    G(c, 960, 1180, 0.85, "both", "sly")
@sc
def ruins_day(c): ruins_ground(c); c.rect(860, 300, 1060, 400, (240, 236, 220), 4)
@sc
def stupa(c): mound_stupa(c); G(c, 1500, 1060, 1.1, "pointl", "sly", flip=True)
@sc
def salt_bricks(c):
    c.rect(0, 0, W, H, (214, 190, 150), 0)
    for r in range(6):
        for k in range(8): c.rect(160 + k * 200 + (r % 2) * 80, 140 + r * 120, 330 + k * 200 + (r % 2) * 80, 240 + r * 120, BRICK_L, 4)
    rnd = random.Random(9)
    for _ in range(90): c.ell(rnd.randint(150, 1800), rnd.randint(140, 860), 8, 8, (250, 250, 250), 0)
    scholar(c, 1650, 1060, 1.0, "work", "neutral", modern=True, female=True, flip=True)
@sc
def vedic_tease(c):
    c.rect(0, 0, W, H, (250, 210, 150), 0); sun(c, 960, 260, (250, 170, 80)); ground(c, 820, GRASS)
    c.poly([(860, 820), (960, 700), (1060, 820)], (230, 120, 50), 5)      # fire altar
    for k in range(4): person(c, 520 + k * 300 + (200 if k > 1 else 0), 1000, 0.9, skin=SKIN, cloth=WHITE, beard=(40, 34, 30) if k % 2 else None, pose="both", face="smile")
@sc
def gappu_ear(c): street(c, 60); G(c, 960, 1080, 2.0, "ear", "smile")


def thumbnail(path):
    from PIL import ImageFont
    c = Canvas(); ruins_ground(c, dusk=True); G(c, 520, 1150, 2.1, "shrug", "shock")
    c.save(path, vignette=True)
    im = Image.open(path); d = ImageDraw.Draw(im)
    f = ImageFont.truetype("/usr/share/fonts/truetype/freefont/FreeSansBold.ttf", 140, layout_engine=ImageFont.Layout.RAQM)
    for i, line in enumerate(("शहर खाली", "क्यों हुआ?")):
        d.text((960, 260 + i * 180), line, font=f, fill=(255, 220, 90), stroke_width=12, stroke_fill=(30, 20, 10), language="hi")
    im.save(path)


if __name__ == "__main__":
    sc_ = json.load(open(sys.argv[1], encoding="utf-8")); out = Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
    for ch in sc_["chapters"]:
        for s in ch["shots"]:
            c = Canvas(); D[s["scene"]](c); c.save(out / f"{s['id']}.png")
    thumbnail(out / "thumbnail.png")
    print("done")
