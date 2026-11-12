"""Build a toy-brick minifig on an EQ player race's rest pose and write it as a .glb plus a preview.

The figure is designed once on the male Dwarf skeleton (build). fit() moves it onto another race's skeleton, and
RACES gives each race its skin, hair, extras and clothing colors.

EQ model space: +X forward, +Y the model's left, +Z up; feet at about Z -3.1, head top about Z 3.6.
Each part records the skeleton bone it would follow, for putting it into the game later.

    python -I minifig.py <out.glb> <preview.png> [race code, e.g. hum]
"""
import io, json, math, os, struct, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

# ------------------------------------------------------------------------------------------------ colors
YELLOW = (242, 205, 55)
DARK_GREY = (99, 95, 98)
LIGHT_GREY = (160, 165, 169)
SILVER = (190, 194, 199)
REDDISH_BROWN = (110, 52, 24)
DARK_BROWN = (70, 38, 20)
TAN = (228, 205, 158)
DARK_BLUE = (10, 52, 99)
RED = (180, 26, 20)
GOLD = (205, 160, 50)
BLACK = (27, 42, 52)
WHITE = (244, 244, 244)
DARK_RED = (114, 14, 15)
DARK_GREEN = (24, 70, 50)
GREEN = (35, 120, 65)
SAND_GREEN = (120, 144, 129)
DARK_PURPLE = (63, 26, 90)
MEDIUM_BLUE = (90, 147, 219)
DARK_TURQUOISE = (0, 138, 128)
DARK_ORANGE = (160, 95, 52)
OLIVE = (155, 154, 90)
BRIGHT_LIGHT_YELLOW = (255, 240, 58)
DARK_TAN = (149, 138, 115)
DARK_ELF_SKIN = (70, 78, 105)  # dark blue-grey
ERUDITE_SKIN = (130, 72, 40)   # reddish brown
TROLL_SKIN = (75, 151, 74)     # bright green
FROG_SKIN = (120, 175, 50)     # lime green
FROG_BELLY = (215, 220, 140)   # pale yellow-green throat


# ------------------------------------------------------------------------------------------------ races
class Race:
    """skin: plastic of the face, neck and hands. face: 'dwarf' (grin under a beard), 'male' or 'female'.
    hair: None (bald), 'short', 'long', 'helmet' (the Dwarf's horned helmet), 'lizard' (a brick lizard head in the
    skin plastic; the tail matches it) or 'dragon' (the lizard head with horns and fangs, for the Drakkin).
    ears: None, 'elf' (pointed) or 'cat'. belly: a round belly over the belt, in the shirt's plastic. shirt/trim/belt/arms/hips/legs: clothing plastic. print: 'mail' or 'tunic'."""

    def __init__(self, skin=YELLOW, face='male', hair='short', hair_color=REDDISH_BROWN, brows=(60, 30, 15),
                 ears=None, shirt=DARK_BLUE, trim=LIGHT_GREY, belt=REDDISH_BROWN, arms=None, hips=None,
                 legs=DARK_GREY, print='tunic', belly=False, skin_colors=None):
        self.skin, self.face, self.hair, self.hair_color, self.brows, self.ears = skin, face, hair, hair_color, brows, ears
        self.belly = belly
        self.skin_colors = skin_colors  # several skin plastics, picked in game by the face choice (make_s3d.py)
        self.shirt, self.trim, self.belt, self.legs, self.print = shirt, trim, belt, legs, print
        self.arms = arms or shirt
        self.hips = hips or belt
        self.look = 0  # face print style: 0 the plain face, 1.. other expressions and marks (see face_marks)


def _pair(male, female):
    return {'m': Race(**male), 'f': Race(**{**male, 'face': 'female', 'hair': 'long', **female})}


RACES = {}
for _code, _m, _f in [
    ('dw', dict(face='dwarf', hair='short', print='mail', arms=DARK_BLUE, hips=REDDISH_BROWN),
           dict(hair_color=DARK_ORANGE, shirt=DARK_RED, trim=GOLD, arms=DARK_RED)),
    ('hu', dict(shirt=RED, trim=GOLD, belt=DARK_BROWN, legs=DARK_BLUE, hair_color=DARK_BROWN), {}),
    ('ba', dict(shirt=DARK_GREEN, trim=TAN, belt=DARK_BROWN, legs=REDDISH_BROWN, hair_color=BRIGHT_LIGHT_YELLOW),
           {}),
    ('er', dict(skin=ERUDITE_SKIN, hair=None, brows=BLACK, shirt=DARK_PURPLE, trim=GOLD, belt=GOLD,
                legs=DARK_PURPLE, hips=DARK_PURPLE), dict(hair='long', hair_color=BLACK)),
    ('el', dict(ears='elf', shirt=GREEN, trim=TAN, belt=REDDISH_BROWN, legs=DARK_GREEN, hair_color=DARK_ORANGE), {}),
    ('hi', dict(ears='elf', shirt=WHITE, trim=GOLD, belt=MEDIUM_BLUE, legs=MEDIUM_BLUE, hair_color=TAN), {}),
    ('ha', dict(ears='elf', shirt=DARK_TURQUOISE, trim=TAN, belt=DARK_BROWN, legs=DARK_BROWN,
                hair_color=REDDISH_BROWN), {}),
    ('da', dict(skin=DARK_ELF_SKIN, ears='elf', brows=WHITE, hair_color=WHITE, shirt=BLACK, trim=DARK_PURPLE,
                belt=DARK_RED, legs=BLACK), {}),
    ('tr', dict(skin=TROLL_SKIN, hair='troll',
                skin_colors=[TROLL_SKIN, (125, 130, 60), (90, 115, 140), (125, 95, 130)], shirt=DARK_RED, trim=DARK_TAN, belt=DARK_BROWN, legs=DARK_BROWN, hair_color=BLACK),
           dict(hair='troll')),
    ('og', dict(face='ogre', hair=None, belly=True, shirt=DARK_TAN, trim=DARK_BROWN, belt=DARK_BROWN,
                legs=REDDISH_BROWN), dict(face='ogre', hair_color=BLACK)),
    ('ho', dict(belly=True, shirt=SAND_GREEN, trim=TAN, belt=REDDISH_BROWN, legs=REDDISH_BROWN, hair_color=DARK_BROWN), {}),
    ('gn', dict(shirt=MEDIUM_BLUE, trim=GOLD, belt=DARK_BROWN, legs=DARK_GREY, hair_color=WHITE, brows=LIGHT_GREY), {}),
    ('ik', dict(skin=GREEN, hair='lizard', hair_color=GREEN, print='mail',
                skin_colors=[GREEN, DARK_TAN, REDDISH_BROWN, DARK_TURQUOISE], shirt=OLIVE, trim=DARK_GREEN, belt=DARK_BROWN, legs=DARK_GREEN),
           dict(hair='lizard')),
    ('dk', dict(hair='dragon', print='mail', shirt=DARK_TAN, trim=DARK_BROWN, belt=DARK_BROWN, legs=DARK_BROWN,
                arms=DARK_TAN), dict(hair='dragon')),
    ('fr', dict(skin=FROG_SKIN, hair='frog', print='mail',
                skin_colors=[FROG_SKIN, (45, 115, 60), (40, 110, 200), (230, 110, 30)], shirt=DARK_BLUE, trim=LIGHT_GREY, belt=DARK_BROWN,
                legs=DARK_GREY), dict(hair='frog')),
    ('ke', dict(skin=DARK_ORANGE, hair='cat', ears='cat',
                skin_colors=[DARK_ORANGE, (150, 150, 155), (50, 46, 44), (235, 225, 200)], shirt=DARK_TAN, trim=DARK_BROWN, belt=DARK_BROWN,
                legs=DARK_BROWN, hair_color=DARK_ORANGE), dict(hair='cat')),
]:
    for _g, _r in _pair(_m, _f).items():
        RACES[_code + _g] = _r


# ------------------------------------------------------------------------------------------------ textures
def face_texture(race):
    W, H = 512, 256
    im = Image.new('RGB', (W, H), race.skin)
    d = ImageDraw.Draw(im)
    cx = W // 2  # u = 0.5 faces forward
    light = sum(race.skin) > 400  # cheeks and nose shading only show on light plastic
    if race.face in ('orc', 'ogre'):
        return brute_face(im, d, race, cx)
    if race.face == 'skull':
        return skull_face(im, d, cx)
    for side in (-1, 1):
        ex = cx + side * 34
        d.ellipse((ex - 11, 96, ex + 11, 124), fill=getattr(race, 'eye_color', (20, 20, 20)))  # eye
        d.ellipse((ex - 4 + side * 2, 100, ex + 3 + side * 2, 108), fill=(255, 255, 255))  # glint
        if race.face == 'female':
            d.line([(ex - side * 6, 98), (ex + side * 14, 90)], fill=(20, 20, 20), width=4)  # lash
            d.arc((ex - 20, 74, ex + 20, 94), 200, 340, fill=race.brows, width=4)        # thin brow
        elif race.look % 7 in (1, 5):  # angry: low at the nose, rising outward
            inner, outer = ex - side * 22, ex + side * 22
            d.polygon([(inner, 92), (outer, 78), (outer, 86), (inner, 100)], fill=race.brows)
        elif race.look % 7 == 6:  # bushy
            d.rectangle((ex - 24, 76, ex + 24, 90), fill=race.brows)
        else:
            d.polygon([(ex - 22, 82 - (side > 0) * 6), (ex + 22, 82 - (side < 0) * 6),
                       (ex + 22, 90 - (side < 0) * 6), (ex - 22, 90 - (side > 0) * 6)], fill=race.brows)  # brow
    # Nose and cheek shading in the skin's own tones (the classic orange ones on yellow plastic)
    nose, cheek = ((225, 160, 60), (245, 170, 90)) if tuple(race.skin) == YELLOW else (
        tuple(int(c * 0.85) for c in race.skin), tuple(int(c * 0.6 + t * 0.4) for c, t in zip(race.skin, (240, 110, 90))))
    if light:
        d.ellipse((cx - 14, 120, cx + 14, 146), fill=nose)  # nose shading
    if race.face == 'female':
        d.chord((cx - 22, 150, cx + 22, 176), 0, 180, fill=(190, 30, 40))  # lips
        d.line([(cx - 22, 162), (cx + 22, 162)], fill=(120, 15, 25), width=2)
    elif race.look % 7 == 0 or race.face == 'dwarf':
        d.arc((cx - 40, 150, cx + 40, 185), 20, 160, fill=(20, 20, 20), width=5)  # grin (mostly under the beard)
    if light and race.look % 7 in (0, 2):
        for side in (-1, 1):
            d.ellipse((cx + side * 62 - 14, 140, cx + side * 62 + 14, 160), fill=cheek)  # rosy cheeks
    if race.look % 7:
        face_marks(d, race, cx)
    return im


def face_marks(d, race, cx):
    """The other face prints, so NPCs of one kind (giants, townsfolk) don't all wear the same face."""
    ink, teeth, red = (20, 20, 20), (244, 244, 244), (150, 30, 30)
    k = race.look % 7
    female = race.face == 'female'
    dwarf = race.face == 'dwarf'
    if k == 1:  # scowl
        if not female and not dwarf:
            d.arc((cx - 34, 162, cx + 34, 196), 200, 340, fill=ink, width=5)
    elif k == 2:  # full beard and mustache (women: freckles and a wide smile)
        if female:
            for fx, fy in [(-62, 140), (-52, 150), (-70, 152), (52, 150), (62, 140), (70, 152)]:
                d.ellipse((cx + fx - 3, fy - 3, cx + fx + 3, fy + 3), fill=(170, 90, 40))
        else:
            d.chord((cx - 70, 120, cx + 70, 250), 0, 180, fill=race.hair_color)
            d.polygon([(cx - 48, 150), (cx + 48, 150), (cx + 56, 166), (cx - 56, 166)], fill=race.hair_color)
            d.line([(cx - 20, 176), (cx + 20, 176)], fill=ink, width=4)
    elif k == 3:  # scar over the left eye, a flat mouth
        ex = cx - 34
        d.line([(ex - 14, 74), (ex + 14, 132)], fill=red, width=4)
        for t in (0.3, 0.6):
            x, y = ex - 14 + 28 * t, 74 + 58 * t
            d.line([(x - 8, y + 3), (x + 8, y - 3)], fill=red, width=3)
        if not female and not dwarf:
            d.line([(cx - 26, 168), (cx + 26, 168)], fill=ink, width=5)
    elif k == 4:  # eye patch and a smirk
        ex = cx + 34
        d.line([(ex, 110), (cx - 60, 66), (cx - 256, 66)], fill=ink, width=4)  # strap above the other eye
        d.line([(ex, 110), (cx + 256, 104)], fill=ink, width=4)
        d.ellipse((ex - 16, 92, ex + 16, 128), fill=ink)
        if not female and not dwarf:
            d.arc((cx - 30, 150, cx + 40, 180), 10, 120, fill=ink, width=5)
    elif k == 5:  # shouting: open mouth with teeth
        if not female:
            d.ellipse((cx - 26, 152, cx + 26, 196), fill=(60, 15, 15))
            d.rectangle((cx - 18, 154, cx + 18, 162), fill=teeth)
    elif k == 6:  # mustache and stubble, toothy grin
        if not female:
            for x in range(-60, 61, 10):
                for y in (172, 184, 196):
                    if abs(x) > 8 or y > 180:
                        d.ellipse((cx + x - 2, y - 2, cx + x + 2, y + 2), fill=(90, 80, 70))
            d.chord((cx - 34, 146, cx + 34, 184), 0, 180, fill=ink)
            d.rectangle((cx - 26, 165, cx + 26, 173), fill=teeth)
            d.polygon([(cx - 44, 156), (cx, 146), (cx + 44, 156), (cx + 38, 162), (cx, 154), (cx - 38, 162)],
                      fill=race.hair_color)


def skull_face(im, d, cx):
    """Big black eye sockets, a nose hole, and a row of teeth."""
    ink = (20, 20, 20)
    for side in (-1, 1):
        ex = cx + side * 36
        d.ellipse((ex - 24, 84, ex + 24, 130), fill=ink)
    d.polygon([(cx, 128), (cx - 10, 148), (cx + 10, 148)], fill=ink)  # nose hole
    d.rectangle((cx - 44, 160, cx + 44, 184), fill=ink)  # mouth
    for k in range(-5, 6):  # teeth
        d.rectangle((cx + k * 8 - 3, 162, cx + k * 8 + 3, 182), fill=(244, 244, 244))
    d.line([(cx - 44, 172), (cx + 44, 172)], fill=ink, width=2)
    return im


def brute_face(im, d, race, cx):
    """Orc and ogre faces: a scowl, nostrils and a wide mouth with lower tusks (the 3D tusks stand in front)."""
    ogre = race.face == 'ogre'
    ink = (20, 20, 20)
    for side in (-1, 1):
        ex = cx + side * (30 if ogre else 34)
        if ogre:  # small beady eyes
            d.ellipse((ex - 7, 104, ex + 7, 120), fill=ink)
            d.ellipse((ex - 2, 107, ex + 2, 111), fill=(255, 255, 255))
        else:  # yellow eyes, slit pupils
            d.ellipse((ex - 12, 98, ex + 12, 122), fill=(250, 200, 40), outline=ink, width=3)
            d.ellipse((ex - 3, 100, ex + 3, 120), fill=ink)
        # Angry brow: low and thick at the nose, rising outward
        inner, outer = ex - side * 18, ex + side * 22
        d.polygon([(inner, 96), (outer, 78), (outer, 88), (inner, 104)], fill=race.brows)
    if ogre:  # one heavy brow across
        d.rectangle((cx - 14, 92, cx + 14, 102), fill=race.brows)
    for side in (-1, 1):  # flat nose: two nostrils
        d.ellipse((cx + side * 10 - 5, 132, cx + side * 10 + 5, 140), fill=ink)
    # Wide grim mouth with teeth showing
    top = 162 if ogre else 158
    d.rectangle((cx - 46, top, cx + 46, top + 14), fill=(60, 15, 15))
    for k in range(-3, 4):
        d.rectangle((cx + k * 12 - 4, top + 8, cx + k * 12 + 4, top + 14), fill=(235, 230, 200))
    for side in (-1, 1):
        tx = cx + side * 34
        d.polygon([(tx - 7, top + 14), (tx + 7, top + 14), (tx, top - 14)], fill=(245, 240, 215))  # printed tusks
    return im


def torso_texture(race):
    W = H = 256
    im = Image.new('RGB', (W, H), race.shirt)
    d = ImageDraw.Draw(im)
    if race.print == 'leather':
        # Leather jerkin: stitched edges, a laced front, a shoulder seam
        d.polygon([(96, 0), (160, 0), (128, 40)], fill=race.trim)
        for y in range(48, 180, 22):  # laces
            d.line([(116, y), (140, y + 12)], fill=race.trim, width=4)
            d.line([(140, y), (116, y + 12)], fill=race.trim, width=4)
        for x in range(8, W - 8, 16):  # stitches along the hem and shoulders
            d.line([(x, 182), (x + 8, 182)], fill=race.trim, width=3)
            d.line([(x, 18), (x + 8, 18)], fill=race.trim, width=3)
        d.rectangle((0, 192, W, 222), fill=race.belt)
        d.rectangle((108, 188, 148, 226), fill=GOLD)
        d.rectangle((118, 197, 138, 217), fill=race.belt)
        d.rectangle((0, 222, W, H), fill=race.shirt)
        return im
    if race.print == 'plate':
        # Breastplate: a center ridge, curved chest plates outlined in trim, rivets, and a plated belt
        d.rectangle((0, 0, W, 12), fill=race.trim)
        for side in (-1, 1):
            cx = 128 + side * 58
            d.arc((cx - 56, 20, cx + 56, 116), 20, 160, fill=race.trim, width=5)  # under each side of the chest
        d.line([(128, 12), (128, 186)], fill=race.trim, width=7)
        light = tuple(min(255, c + 40) for c in race.shirt)
        d.line([(120, 14), (120, 184)], fill=light, width=3)  # shine along the ridge
        for x, y in ((30, 30), (226, 30), (30, 150), (226, 150), (70, 172), (186, 172)):
            d.ellipse((x - 5, y - 5, x + 5, y + 5), fill=race.trim)
        for y in (150, 168):
            d.line([(20, y), (236, y)], fill=race.trim, width=3)
        d.rectangle((0, 192, W, 222), fill=race.belt)
        d.rectangle((108, 188, 148, 226), fill=race.trim)
        d.rectangle((0, 222, W, H), fill=race.shirt)
        return im
    if race.print == 'ribs':
        # Rib cage: a spine down the middle and curved ribs, bone over dark gaps
        bone = race.shirt
        d.rectangle((0, 0, W, H), fill=(27, 42, 52))
        d.rectangle((0, 0, W, 14), fill=bone)  # collar bones
        d.rectangle((116, 0, 140, 222), fill=bone)  # spine
        for k in range(6):  # ribs, shorter toward the bottom, curving down at the sides
            y = 26 + k * 27
            inset = 18 + k * 7
            for x0, x1 in ((inset, 112), (144, W - inset)):
                d.rounded_rectangle((x0, y, x1, y + 14), radius=7, fill=bone)
            d.rounded_rectangle((inset - 6, y + 4, inset + 14, y + 26), radius=7, fill=bone)
            d.rounded_rectangle((W - inset - 14, y + 4, W - inset + 6, y + 26), radius=7, fill=bone)
        d.rectangle((60, 196, 196, 224), fill=bone)  # pelvis top
        d.rectangle((0, 222, W, H), fill=bone)
        return im
    if race.print == 'mail':
        # Chain mail shirt: rows of rings over the chest
        for row, y in enumerate(range(14, 190, 14)):
            for x in range(10 + (row % 2) * 7, W - 6, 14):
                d.ellipse((x - 6, y - 5, x + 6, y + 5), outline=race.trim, width=2)
        d.rectangle((0, 0, W, 10), fill=DARK_GREY)            # collar
    else:
        # Tunic: a V neck with trim, a seam down the middle and stitched pockets
        d.polygon([(70, 0), (186, 0), (128, 96)], fill=race.trim)
        # The V shows skin; with several skin colors the shirt can't follow the face choice, so it shows trim
        d.polygon([(88, 0), (168, 0), (128, 74)], fill=race.trim if race.skin_colors else race.skin)
        d.line([(128, 96), (128, 192)], fill=race.trim, width=4)
        for x in (52, 160):
            d.rectangle((x, 120, x + 44, 160), outline=race.trim, width=3)
    d.rectangle((0, 192, W, 222), fill=race.belt)     # belt
    d.rectangle((108, 188, 148, 226), fill=GOLD)          # buckle
    d.rectangle((118, 197, 138, 217), fill=race.belt)
    d.rectangle((0, 222, W, H), fill=race.shirt)           # tunic hem
    return im


def textures(race):
    return {'face': face_texture(race), 'torso': torso_texture(race)}


TEXTURES = textures(RACES['dwm'])


# ------------------------------------------------------------------------------------------------ geometry
class Part:
    """Triangles of one material, oriented outward from center."""

    def __init__(self, name, bone, material, center):
        self.name, self.bone, self.material = name, bone, material
        self.center = np.array(center, dtype=float)
        self.tris = []  # [(p, n, uv) x 3]

    def tri(self, a, b, c, normals=None, uvs=None):
        a, b, c = (np.array(v, dtype=float) for v in (a, b, c))
        n = np.cross(b - a, c - a)
        ln = np.linalg.norm(n)
        if ln < 1e-9:
            return
        n /= ln
        verts = [a, b, c]
        given = normals is not None
        normals = [np.array(x, dtype=float) for x in normals] if given else [n, n, n]
        uvs = list(uvs) if uvs else [(0.02, 0.02)] * 3
        if n @ ((a + b + c) / 3 - self.center) < 0:  # inward: flip the winding
            verts[1], verts[2] = verts[2], verts[1]
            uvs[1], uvs[2] = uvs[2], uvs[1]
            normals[1], normals[2] = normals[2], normals[1]
            if not given:
                normals = [-n, -n, -n]
        self.tris.append(list(zip(verts, normals, uvs)))

    def quad(self, a, b, c, d, uvs=None):
        u = uvs or [None] * 4
        self.tri(a, b, c, uvs=[u[0], u[1], u[2]] if uvs else None)
        self.tri(a, c, d, uvs=[u[0], u[2], u[3]] if uvs else None)


def hexa(part, corners, front_uv=False):
    """Eight corners: bottom ring then top ring, each in order (-x-y, +x-y, +x+y, -x+y)."""
    c = [np.array(p, dtype=float) for p in corners]
    faces = [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    for f in faces:
        uvs = None
        if front_uv and f == (1, 2, 6, 5):  # +X face carries the print: u across (from the model's right), v down
            uvs = [(0, 1), (1, 1), (1, 0), (0, 0)]
        part.quad(*(c[i] for i in f), uvs=uvs)


def box(part, lo, hi):
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    hexa(part, [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)])


def basis(axis):
    axis = axis / np.linalg.norm(axis)
    helper = np.array([0, 0, 1.0]) if abs(axis[2]) < 0.9 else np.array([1.0, 0, 0])
    u = np.cross(axis, helper); u /= np.linalg.norm(u)
    return u, np.cross(axis, u)


def cylinder(part, p0, p1, r0, r1=None, seg=28, caps=(True, True), uv_wrap=False, start_angle=0.0):
    """Cylinder or cone frustum from p0 to p1. uv_wrap maps u around (0.5 at +X) and v down the side."""
    r1 = r0 if r1 is None else r1
    p0, p1 = np.array(p0, float), np.array(p1, float)
    axis = p1 - p0
    if uv_wrap:
        u_dir, v_dir = np.array([1.0, 0, 0]), np.array([0, 1.0, 0])  # around Z: angle 0 is forward
    else:
        u_dir, v_dir = basis(axis)
    ring = []
    for k in range(seg + 1):
        t = start_angle + math.pi + 2 * math.pi * k / seg if uv_wrap else 2 * math.pi * k / seg
        ring.append((math.cos(t) * u_dir + math.sin(t) * v_dir, k / seg))
    side_n = lambda d: d  # radial normals (close enough for gentle cones)
    for k in range(seg):
        (d0, u0), (d1, u1) = ring[k], ring[k + 1]
        a, b = p0 + d0 * r0, p0 + d1 * r0
        c, d = p1 + d1 * r1, p1 + d0 * r1
        uvs = [(u0, 1), (u1, 1), (u1, 0), (u0, 0)]
        part.tri(a, b, c, normals=[side_n(d0), side_n(d1), side_n(d1)], uvs=[uvs[0], uvs[1], uvs[2]])
        part.tri(a, c, d, normals=[side_n(d0), side_n(d1), side_n(d0)], uvs=[uvs[0], uvs[2], uvs[3]])
        if caps[0] and r0 > 0:
            part.tri(p0, a, b)
        if caps[1] and r1 > 0:
            part.tri(p1, d, c)


def knob(part, center, radii, seg=12, rings=5):
    """A whole ellipsoid (a bone end or joint): two half-ellipsoids back to back."""
    bulge(part, center, radii, seg, rings)
    bulge(part, center, (-radii[0], radii[1], radii[2]), seg, rings)


def bulge(part, center, radii, seg=28, rings=8):
    """Half an ellipsoid facing +X (forward), its flat side at center."""
    center, radii = np.array(center, float), np.array(radii, float)
    pt = lambda t, a: center + radii * np.array([math.sin(t), math.cos(t) * math.cos(a), math.cos(t) * math.sin(a)])
    nrm = lambda t, a: (lambda n: n / np.linalg.norm(n))(
        np.array([math.sin(t), math.cos(t) * math.cos(a), math.cos(t) * math.sin(a)]) / radii)
    for i in range(rings):
        t0, t1 = (math.pi / 2) * i / rings, (math.pi / 2) * (i + 1) / rings
        for k in range(seg):
            a0, a1 = 2 * math.pi * k / seg, 2 * math.pi * (k + 1) / seg
            q = [(t0, a0), (t0, a1), (t1, a1), (t1, a0)]
            part.tri(*(pt(*x) for x in q[:3]), normals=[nrm(*x) for x in q[:3]])
            part.tri(*(pt(*x) for x in (q[0], q[2], q[3])), normals=[nrm(*x) for x in (q[0], q[2], q[3])])


def dome(part, center, r, seg=28, rings=8):
    center = np.array(center, float)
    for i in range(rings):
        t0, t1 = (math.pi / 2) * i / rings, (math.pi / 2) * (i + 1) / rings
        for k in range(seg):
            a0, a1 = 2 * math.pi * k / seg, 2 * math.pi * (k + 1) / seg
            pt = lambda t, a: center + r * np.array([math.cos(t) * math.cos(a), math.cos(t) * math.sin(a), math.sin(t)])
            p00, p01, p11, p10 = pt(t0, a0), pt(t0, a1), pt(t1, a1), pt(t1, a0)
            nrm = lambda p: (p - center) / r
            part.tri(p00, p01, p11, normals=[nrm(p00), nrm(p01), nrm(p11)])
            part.tri(p00, p11, p10, normals=[nrm(p00), nrm(p11), nrm(p10)])


# ------------------------------------------------------------------------------------------------ the dwarf
BX = -0.15  # body center, front to back


def reptile_head(part, race, HEAD_TOP):
    """A brick lizard (Iksar) or dragon (Drakkin) head in the skin plastic, on the minifig head: snout with nostrils,
    lower jaw, slit-pupil eyes under brow ridges, a crest of spikes; the dragon adds horns and teeth."""
    S = race.skin
    dragon = race.hair == 'dragon'
    crown = part('crown', 'DWMHEHEAD_DAG', S, (BX, 0, HEAD_TOP + 0.1))
    cylinder(crown, (BX, 0, HEAD_TOP), (BX, 0, HEAD_TOP + 0.18), 0.72, 0.5, seg=40, caps=(False, True))
    snout = part('snout', 'DWMHEHEAD_DAG', S, (BX + 0.95, 0, 2.28))
    hexa(snout, [(BX + 0.45, -0.55, 2.05), (BX + 1.5, -0.34, 2.08), (BX + 1.5, 0.34, 2.08), (BX + 0.45, 0.55, 2.05),
                 (BX + 0.45, -0.55, 2.62), (BX + 1.5, -0.3, 2.4), (BX + 1.5, 0.3, 2.4), (BX + 0.45, 0.55, 2.62)])
    jaw = part('jaw', 'DWMHEHEAD_DAG', S, (BX + 0.85, 0, 1.9))
    hexa(jaw, [(BX + 0.4, -0.5, 1.8), (BX + 1.32, -0.28, 1.84), (BX + 1.32, 0.28, 1.84), (BX + 0.4, 0.5, 1.8),
               (BX + 0.4, -0.5, 1.99), (BX + 1.32, -0.28, 1.99), (BX + 1.32, 0.28, 1.99), (BX + 0.4, 0.5, 1.99)])
    mouth = part('mouth', 'DWMHEHEAD_DAG', BLACK, (BX + 0.9, 0, 2.02))
    box(mouth, (BX + 0.5, -0.4, 1.99), (BX + 1.3, 0.4, 2.06))
    for side in (1, -1):
        y = lambda a, b: sorted((side * a, side * b))
        nostril = part('nostril', 'DWMHEHEAD_DAG', BLACK, (BX + 1.42, side * 0.15, 2.4))
        (y0, y1) = y(0.1, 0.21)
        box(nostril, (BX + 1.35, y0, 2.36), (BX + 1.47, y1, 2.43))
        eye = part('eye', 'DWMHEHEAD_DAG', YELLOW, (BX + 0.56, side * 0.5, 2.66))
        (y0, y1) = y(0.36, 0.64)
        box(eye, (BX + 0.4, y0, 2.55), (BX + 0.72, y1, 2.78))
        pupil = part('pupil', 'DWMHEHEAD_DAG', BLACK, (BX + 0.73, side * 0.5, 2.66))
        (y0, y1) = y(0.47, 0.53)
        box(pupil, (BX + 0.7, y0, 2.56), (BX + 0.74, y1, 2.77))
        brow = part('brow', 'DWMHEHEAD_DAG', S, (BX + 0.55, side * 0.5, 2.86))
        (y0, y1) = y(0.3, 0.7)
        box(brow, (BX + 0.36, y0, 2.78), (BX + 0.8, y1, 2.93))
        if dragon:
            horn = part('horn', 'DWMHEHEAD_DAG', TAN, (BX - 0.6, side * 0.55, HEAD_TOP + 0.25))
            cylinder(horn, (BX - 0.2, side * 0.42, HEAD_TOP - 0.05), (BX - 1.0, side * 0.62, HEAD_TOP + 0.55), 0.17,
                     0.0, seg=14, caps=(True, False))
            for x in (1.05, 1.3):  # fangs down from the upper jaw
                tooth = part('tooth', 'DWMHEHEAD_DAG', WHITE, (BX + x, side * 0.28, 2.0))
                cylinder(tooth, (BX + x, side * 0.27, 2.08), (BX + x, side * 0.27, 1.93), 0.05, 0.0, seg=8,
                         caps=(True, False))
    spike_color = TAN if dragon else DARK_GREEN
    for k, (x, h) in enumerate(((0.3, 0.3), (-0.05, 0.42), (-0.4, 0.36), (-0.72, 0.26))):  # crest down the head
        spike = part(f'spike {k}', 'DWMHEHEAD_DAG', spike_color, (BX + x, 0, HEAD_TOP + 0.35))
        z0 = HEAD_TOP + (0.12 if x > -0.5 else -0.1)
        cylinder(spike, (BX + x, 0, z0 - 0.05), (BX + x - 0.1, 0, z0 + h), 0.13, 0.0, seg=12, caps=(True, False))


def frog_head(part, race, HEAD_TOP):
    """A brick frog (Froglok) head in the skin plastic: a flat top with two big bulging eyes, a wide mouth, two
    nostrils and a pale throat."""
    S = race.skin
    crown = part('crown', 'DWMHEHEAD_DAG', S, (BX, 0, HEAD_TOP + 0.05))
    cylinder(crown, (BX, 0, HEAD_TOP), (BX, 0, HEAD_TOP + 0.08), 0.72, 0.62, seg=40, caps=(False, True))
    throat = part('throat', 'DWMHEHEAD_DAG', FROG_BELLY, (BX + 0.55, 0, 1.97))
    hexa(throat, [(BX + 0.3, -0.55, 1.8), (BX + 0.8, -0.45, 1.8), (BX + 0.8, 0.45, 1.8), (BX + 0.3, 0.55, 1.8),
                  (BX + 0.3, -0.6, 2.14), (BX + 0.82, -0.5, 2.14), (BX + 0.82, 0.5, 2.14), (BX + 0.3, 0.6, 2.14)])
    mouth = part('mouth', 'DWMHEHEAD_DAG', BLACK, (BX + 0.78, 0, 2.17))
    box(mouth, (BX + 0.62, -0.6, 2.14), (BX + 0.84, 0.6, 2.2))
    for side in (1, -1):
        corner = part('mouth corner', 'DWMHEHEAD_DAG', BLACK, (BX + 0.55, side * 0.62, 2.22))
        y0, y1 = sorted((side * 0.56, side * 0.68))
        box(corner, (BX + 0.4, y0, 2.14), (BX + 0.66, y1, 2.28))
        nostril = part('nostril', 'DWMHEHEAD_DAG', BLACK, (BX + 0.73, side * 0.12, 2.5))
        y0, y1 = sorted((side * 0.07, side * 0.17))
        box(nostril, (BX + 0.68, y0, 2.46), (BX + 0.76, y1, 2.53))
        c = (BX + 0.22, side * 0.38, HEAD_TOP)
        bump = part('eye bump', 'DWMHEHEAD_DAG', S, (BX + 0.22, side * 0.38, HEAD_TOP + 0.1))
        cylinder(bump, c, (c[0], c[1], HEAD_TOP + 0.14), 0.33, seg=24, caps=(False, False))
        eye = part('eye', 'DWMHEHEAD_DAG', WHITE, (BX + 0.22, side * 0.38, HEAD_TOP + 0.3))
        dome(eye, (c[0], c[1], HEAD_TOP + 0.14), 0.33)
        pupil = part('pupil', 'DWMHEHEAD_DAG', BLACK, (BX + 0.5, side * 0.38, HEAD_TOP + 0.3))
        y0, y1 = sorted((side * 0.27, side * 0.49))
        box(pupil, (BX + 0.42, y0, HEAD_TOP + 0.2), (BX + 0.56, y1, HEAD_TOP + 0.38))


def troll_head(part, race, HEAD_TOP):
    """A brick troll head in the skin plastic: long hooked nose, heavy brow, small beady eyes, an underbite with
    tusks, big pointed ears and a mohawk in the hair plastic."""
    S = race.skin
    crown = part('crown', 'DWMHEHEAD_DAG', S, (BX, 0, HEAD_TOP + 0.08))
    cylinder(crown, (BX, 0, HEAD_TOP), (BX, 0, HEAD_TOP + 0.14), 0.72, 0.56, seg=40, caps=(False, True))
    brow = part('brow', 'DWMHEHEAD_DAG', S, (BX + 0.7, 0, 2.78))
    hexa(brow, [(BX + 0.45, -0.66, 2.66), (BX + 0.95, -0.55, 2.66), (BX + 0.95, 0.55, 2.66), (BX + 0.45, 0.66, 2.66),
                (BX + 0.45, -0.66, 2.9), (BX + 0.85, -0.55, 2.9), (BX + 0.85, 0.55, 2.9), (BX + 0.45, 0.66, 2.9)])
    nose = part('nose', 'DWMHEHEAD_DAG', S, (BX + 1.05, 0, 2.35))
    cylinder(nose, (BX + 0.7, 0, 2.62), (BX + 1.42, 0, 2.18), 0.17, 0.11, seg=16)
    tip = part('nose tip', 'DWMHEHEAD_DAG', S, (BX + 1.4, 0, 2.1))
    cylinder(tip, (BX + 1.42, 0, 2.2), (BX + 1.36, 0, 1.98), 0.12, 0.05, seg=16)
    jaw = part('jaw', 'DWMHEHEAD_DAG', S, (BX + 0.75, 0, 1.92))
    hexa(jaw, [(BX + 0.4, -0.62, 1.78), (BX + 1.02, -0.5, 1.78), (BX + 1.02, 0.5, 1.78), (BX + 0.4, 0.62, 1.78),
               (BX + 0.4, -0.62, 2.04), (BX + 1.02, -0.5, 2.04), (BX + 1.02, 0.5, 2.04), (BX + 0.4, 0.62, 2.04)])
    mouth = part('mouth', 'DWMHEHEAD_DAG', BLACK, (BX + 0.85, 0, 2.06))
    box(mouth, (BX + 0.65, -0.42, 2.04), (BX + 1.0, 0.42, 2.09))
    for side in (1, -1):
        y = lambda a, b: sorted((side * a, side * b))
        tusk = part('tusk', 'DWMHEHEAD_DAG', WHITE, (BX + 0.98, side * 0.36, 2.15))
        cylinder(tusk, (BX + 0.98, side * 0.36, 2.0), (BX + 1.02, side * 0.4, 2.36), 0.07, 0.0, seg=10,
                 caps=(True, False))
        eye = part('eye', 'DWMHEHEAD_DAG', (240, 200, 40), (BX + 0.73, side * 0.28, 2.56))
        (y0, y1) = y(0.18, 0.38)
        box(eye, (BX + 0.62, y0, 2.48), (BX + 0.75, y1, 2.64))
        pupil = part('pupil', 'DWMHEHEAD_DAG', (180, 20, 20), (BX + 0.76, side * 0.28, 2.56))
        (y0, y1) = y(0.24, 0.32)
        box(pupil, (BX + 0.74, y0, 2.51), (BX + 0.77, y1, 2.61))
        ear = part('ear', 'DWMHEHEAD_DAG', S, (BX - 0.1, side * 1.0, 2.5))
        y0, y1 = side * 0.62, side * 1.35
        hexa(ear, [(BX - 0.25, y0, 2.25), (BX + 0.1, y0, 2.25), (BX + 0.1, y0, 2.75), (BX - 0.25, y0, 2.75),
                   (BX - 0.3, y1, 2.75), (BX - 0.22, y1, 2.75), (BX - 0.15, y0 + side * 0.35, 2.9),
                   (BX - 0.3, y0 + side * 0.35, 2.9)])
    mohawk = part('mohawk', 'DWMHEHEAD_DAG', race.hair_color, (BX - 0.1, 0, HEAD_TOP + 0.3))
    hexa(mohawk, [(BX - 0.75, -0.12, HEAD_TOP - 0.3), (BX + 0.5, -0.12, HEAD_TOP + 0.05),
                  (BX + 0.5, 0.12, HEAD_TOP + 0.05), (BX - 0.75, 0.12, HEAD_TOP - 0.3),
                  (BX - 0.6, -0.09, HEAD_TOP + 0.5), (BX + 0.3, -0.09, HEAD_TOP + 0.55),
                  (BX + 0.3, 0.09, HEAD_TOP + 0.55), (BX - 0.6, 0.09, HEAD_TOP + 0.5)])


def cat_head(part, race, HEAD_TOP):
    """A brick cat (Vah Shir) head in the fur plastic: short muzzle with a nose and mouth, green slit-pupil eyes,
    cheek tufts and dark stripes on the brow. The ears come from race.ears == 'cat'."""
    S = race.skin
    crown = part('crown', 'DWMHEHEAD_DAG', S, (BX, 0, HEAD_TOP + 0.08))
    cylinder(crown, (BX, 0, HEAD_TOP), (BX, 0, HEAD_TOP + 0.14), 0.72, 0.56, seg=40, caps=(False, True))
    muzzle = part('muzzle', 'DWMHEHEAD_DAG', TAN, (BX + 0.8, 0, 2.16))
    hexa(muzzle, [(BX + 0.5, -0.42, 1.95), (BX + 1.02, -0.3, 1.98), (BX + 1.02, 0.3, 1.98), (BX + 0.5, 0.42, 1.95),
                  (BX + 0.5, -0.42, 2.4), (BX + 1.02, -0.3, 2.34), (BX + 1.02, 0.3, 2.34), (BX + 0.5, 0.42, 2.4)])
    nose = part('nose', 'DWMHEHEAD_DAG', (60, 30, 30), (BX + 1.04, 0, 2.3))
    hexa(nose, [(BX + 0.94, -0.06, 2.22), (BX + 1.06, -0.04, 2.22), (BX + 1.06, 0.04, 2.22), (BX + 0.94, 0.06, 2.22),
                (BX + 0.9, -0.16, 2.37), (BX + 1.06, -0.13, 2.36), (BX + 1.06, 0.13, 2.36), (BX + 0.9, 0.16, 2.37)])
    mouth = part('mouth', 'DWMHEHEAD_DAG', BLACK, (BX + 1.03, 0, 2.12))
    box(mouth, (BX + 1.0, -0.02, 2.08), (BX + 1.04, 0.02, 2.22))
    box(mouth, (BX + 1.0, -0.18, 2.08), (BX + 1.04, 0.18, 2.11))
    for side in (1, -1):
        y = lambda a, b: sorted((side * a, side * b))
        eye = part('eye', 'DWMHEHEAD_DAG', (120, 200, 60), (BX + 0.6, side * 0.4, 2.6))
        (y0, y1) = y(0.24, 0.54)
        box(eye, (BX + 0.48, y0, 2.5), (BX + 0.72, y1, 2.72))
        pupil = part('pupil', 'DWMHEHEAD_DAG', BLACK, (BX + 0.73, side * 0.39, 2.61))
        (y0, y1) = y(0.36, 0.42)
        box(pupil, (BX + 0.7, y0, 2.51), (BX + 0.74, y1, 2.71))
        tuft = part('cheek tuft', 'DWMHEHEAD_DAG', TAN, (BX + 0.2, side * 0.78, 2.1))
        (y0, y1) = y(0.6, 0.92)
        ym = y0 + (y1 - y0) * 0.4 if side > 0 else y1 - (y1 - y0) * 0.4  # narrower at the top, against the head
        yi = y0 if side > 0 else y1
        hexa(tuft, [(BX - 0.05, yi, 1.92), (BX + 0.45, yi, 1.92), (BX + 0.45, y1 if side > 0 else y0, 2.02),
                    (BX - 0.05, y1 if side > 0 else y0, 2.02), (BX + 0.05, yi, 2.35), (BX + 0.4, yi, 2.35),
                    (BX + 0.4, ym, 2.3), (BX + 0.05, ym, 2.3)])
    for k, dy in enumerate((-0.18, 0.0, 0.18)):  # stripes on the brow
        stripe = part('stripe', 'DWMHEHEAD_DAG', DARK_BROWN, (BX + 0.7, dy, 2.88))
        box(stripe, (BX + 0.6, dy - 0.04, 2.8 - (0.06 if k == 1 else 0)), (BX + 0.74, dy + 0.04, 3.0))


def dog_head(part, race, HEAD_TOP):
    """A brick dog (kobold) head in the skin plastic: a long muzzle with a black nose and a lighter underside, an
    open lower jaw with white fangs, dark eyes with a glint under a heavy brow. The ears come from race.ears == 'dog'."""
    S, UNDER = race.skin, DARK_TAN
    crown = part('crown', 'DWMHEHEAD_DAG', S, (BX, 0, HEAD_TOP + 0.08))
    cylinder(crown, (BX, 0, HEAD_TOP), (BX, 0, HEAD_TOP + 0.14), 0.72, 0.56, seg=40, caps=(False, True))
    muzzle = part('muzzle', 'DWMHEHEAD_DAG', S, (BX + 1.0, 0, 2.28))
    hexa(muzzle, [(BX + 0.45, -0.44, 2.1), (BX + 1.55, -0.28, 2.14), (BX + 1.55, 0.28, 2.14), (BX + 0.45, 0.44, 2.1),
                  (BX + 0.45, -0.44, 2.55), (BX + 1.55, -0.28, 2.4), (BX + 1.55, 0.28, 2.4), (BX + 0.45, 0.44, 2.55)])
    nose = part('nose', 'DWMHEHEAD_DAG', BLACK, (BX + 1.58, 0, 2.38))
    hexa(nose, [(BX + 1.48, -0.15, 2.3), (BX + 1.64, -0.13, 2.3), (BX + 1.64, 0.13, 2.3), (BX + 1.48, 0.15, 2.3),
                (BX + 1.46, -0.17, 2.46), (BX + 1.62, -0.15, 2.45), (BX + 1.62, 0.15, 2.45), (BX + 1.46, 0.17, 2.46)])
    mouth = part('mouth', 'DWMHEHEAD_DAG', BLACK, (BX + 0.95, 0, 2.08))
    box(mouth, (BX + 0.55, -0.34, 2.03), (BX + 1.4, 0.34, 2.14))
    jaw = part('jaw', 'DWMHEHEAD_DAG', UNDER, (BX + 0.85, 0, 1.94))
    hexa(jaw, [(BX + 0.4, -0.4, 1.82), (BX + 1.35, -0.24, 1.9), (BX + 1.35, 0.24, 1.9), (BX + 0.4, 0.4, 1.82),
               (BX + 0.4, -0.4, 2.04), (BX + 1.35, -0.24, 2.04), (BX + 1.35, 0.24, 2.04), (BX + 0.4, 0.4, 2.04)])
    for side in (1, -1):
        y = lambda a, b: sorted((side * a, side * b))
        fang = part('fang', 'DWMHEHEAD_DAG', WHITE, (BX + 1.38, side * 0.2, 2.06))
        cylinder(fang, (BX + 1.38, side * 0.2, 2.15), (BX + 1.4, side * 0.2, 1.93), 0.06, 0.0, seg=6, caps=(True, False))
        tooth = part('tooth', 'DWMHEHEAD_DAG', WHITE, (BX + 1.22, side * 0.18, 2.1))
        cylinder(tooth, (BX + 1.22, side * 0.18, 2.03), (BX + 1.22, side * 0.18, 2.16), 0.045, 0.0, seg=6, caps=(True, False))
        eye = part('eye', 'DWMHEHEAD_DAG', BLACK, (BX + 0.66, side * 0.33, 2.66))
        (y0, y1) = y(0.2, 0.46)
        box(eye, (BX + 0.56, y0, 2.56), (BX + 0.75, y1, 2.76))
        glint = part('glint', 'DWMHEHEAD_DAG', WHITE, (BX + 0.76, side * 0.38, 2.71))
        (y0, y1) = y(0.34, 0.42)
        box(glint, (BX + 0.74, y0, 2.67), (BX + 0.77, y1, 2.74))
        brow = part('brow', 'DWMHEHEAD_DAG', DARK_BROWN, (BX + 0.62, side * 0.33, 2.84))
        (y0, y1) = y(0.12, 0.56)
        hexa(brow, [(BX + 0.45, y0, 2.78), (BX + 0.78, y0, 2.76), (BX + 0.78, y1, 2.8), (BX + 0.45, y1, 2.82),
                    (BX + 0.45, y0, 2.9), (BX + 0.8, y0, 2.86), (BX + 0.8, y1, 2.92), (BX + 0.45, y1, 2.96)])


def brute_jaw(part, race):
    """Tusks out of the lower jaw; the ogre also gets a jutting underbite."""
    ogre = race.face == 'ogre'
    TUSK = (245, 240, 215)
    front = BX + 0.7
    if ogre:
        jaw = part('jaw', 'DWMHEHEAD_DAG', race.skin, (BX + 0.62, 0, 2.0))
        box(jaw, (BX + 0.3, -0.62, 1.82), (BX + 0.95, 0.62, 2.18))
        front = BX + 0.9
    for side in (1, -1):
        y = side * (0.42 if ogre else 0.34)
        base = (front - 0.08, y, 2.12 if ogre else 2.1)
        tip = (front + (0.12 if ogre else 0.1), y * 1.08, 2.62 if ogre else 2.45)
        tusk = part('tusk', 'DWMHEHEAD_DAG', TUSK, base)
        cylinder(tusk, base, tip, 0.13 if ogre else 0.09, 0.0, caps=(True, False))


def build(race=None):
    """Minifig proportions (legs about as tall as the torso), stretched over the Dwarf's height: feet stay on the
    ground at Z -3.1, and the rest follows its bone wherever it sits. Bones are named for the male Dwarf (DWM...);
    fit() renames them. Each part has a group: 'head' and 'arm L/R' move as rigid pieces, 'body' is stretched."""
    race = race or RACES['dwm']
    parts = []
    group = ['body']

    def part(name, bone, material, center):
        p = Part(name, bone, material, center)
        p.group = group[0]
        parts.append(p)
        return p

    FOOT, KNEE, HIP_TOP, WAIST, SHOULDER_Z, NECK_TOP = -3.1, -2.0, -0.9, -0.45, 1.65, 1.8
    HEAD_TOP = 3.05
    for side, tag in ((1, 'L'), (-1, 'R')):
        y0, y1 = sorted((side * 0.07, side * 1.2))
        ym = side * 0.63
        if getattr(race, 'bony', False):  # skeleton: thin bones with knobbly joints
            thigh = part(f'leg upper {tag}', f'DWMTHTHIGH{tag}_DAG', race.legs, (BX, ym, (KNEE + HIP_TOP) / 2))
            cylinder(thigh, (BX, ym, KNEE), (BX, ym, HIP_TOP), 0.22, seg=12)
            knob(thigh, (BX, ym, HIP_TOP - 0.05), (0.32, 0.32, 0.22))
            knee = part(f'knee {tag}', f'DWMCACALF{tag}_DAG', race.legs, (BX, ym, KNEE))
            knob(knee, (BX, ym, KNEE), (0.3, 0.32, 0.26))
            shin = part(f'leg lower {tag}', f'DWMCACALF{tag}_DAG', race.legs, (BX, ym, (FOOT + 0.4 + KNEE) / 2))
            cylinder(shin, (BX, ym, FOOT + 0.35), (BX, ym, KNEE), 0.18, seg=12)
            foot = part(f'foot {tag}', f'DWMBOFOOT{tag}_DAG', race.legs, (BX + 0.25, ym, FOOT + 0.18))
            box(foot, (BX - 0.3, ym - 0.28, FOOT), (BX + 0.9, ym + 0.28, FOOT + 0.36))
        else:
            thigh = part(f'leg upper {tag}', f'DWMTHTHIGH{tag}_DAG', race.legs, (BX, ym, (KNEE + HIP_TOP) / 2))
            box(thigh, (BX - 0.6, y0, KNEE), (BX + 0.6, y1, HIP_TOP))
            shin = part(f'leg lower {tag}', f'DWMCACALF{tag}_DAG', race.legs, (BX, ym, (FOOT + 0.5 + KNEE) / 2))
            box(shin, (BX - 0.6, y0, FOOT + 0.5), (BX + 0.6, y1, KNEE))
            foot = part(f'foot {tag}', f'DWMBOFOOT{tag}_DAG', race.legs, (BX + 0.15, ym, FOOT + 0.25))
            box(foot, (BX - 0.6, y0, FOOT), (BX + 0.95, y1, FOOT + 0.5))

    hips = part('hips', 'DWMPEPELVIS_DAG', race.hips, (BX, 0, (HIP_TOP + WAIST) / 2))
    box(hips, (BX - 0.6, -1.2, HIP_TOP), (BX + 0.6, 1.2, WAIST))
    for side in (1, -1):  # the hip joint pins on each side
        pin = part('hip pin', 'DWMPEPELVIS_DAG', race.hips, (BX, side * 1.25, HIP_TOP + 0.2))
        cylinder(pin, (BX, side * 1.2, HIP_TOP + 0.22), (BX, side * 1.28, HIP_TOP + 0.22), 0.2)

    torso = part('torso', 'DWMCHCHEST_DAG', 'torso', (BX, 0, (WAIST + SHOULDER_Z) / 2))
    hexa(torso, [(BX - 0.65, -1.3, WAIST), (BX + 0.65, -1.3, WAIST), (BX + 0.65, 1.3, WAIST), (BX - 0.65, 1.3, WAIST),
                 (BX - 0.55, -0.85, SHOULDER_Z), (BX + 0.55, -0.85, SHOULDER_Z), (BX + 0.55, 0.85, SHOULDER_Z),
                 (BX - 0.55, 0.85, SHOULDER_Z)], front_uv=True)

    if race.belly:
        belly = part('belly', 'DWMCHCHEST_DAG', race.shirt, (BX + 0.6, 0, -0.15))
        bulge(belly, (BX + 0.6, 0, -0.15), (0.55, 1.15, 0.8))

    neck = part('neck', 'DWMNENECK_DAG', race.skin, (BX, 0, 1.72))
    cylinder(neck, (BX, 0, SHOULDER_Z), (BX, 0, NECK_TOP), 0.36)

    group[0] = 'head'
    reptile = race.hair in ('lizard', 'dragon', 'cat', 'dog', 'troll', 'frog')  # a sculpted head: no face print
    head = part('head', 'DWMHEHEAD_DAG', race.skin if reptile else 'face', (BX, 0, (NECK_TOP + HEAD_TOP) / 2))
    cylinder(head, (BX, 0, NECK_TOP), (BX, 0, HEAD_TOP), 0.72, seg=48, uv_wrap=not reptile)

    if race.face in ('orc', 'ogre'):
        brute_jaw(part, race)
    if race.hair == 'helmet':
        # The in-game Dwarf gets his beard from the beard attachment (hairpieces.py); BAKED_BEARD=1 for previews
        if os.environ.get('BAKED_BEARD') == '1':
            beard = part('beard', 'DWMHEBEARD1_DAG', REDDISH_BROWN, (BX + 0.75, 0, 1.4))
            hexa(beard, [(BX + 0.5, -0.2, 0.35), (BX + 0.85, -0.14, 0.35), (BX + 0.85, 0.14, 0.35), (BX + 0.5, 0.2, 0.35),
                         (BX + 0.6, -0.68, 2.3), (BX + 0.98, -0.64, 2.3), (BX + 0.98, 0.64, 2.3), (BX + 0.6, 0.68, 2.3)])
            mustache = part('mustache', 'DWMFALIPTOP_DAG', DARK_BROWN, (BX + 0.9, 0, 2.35))
            hexa(mustache, [(BX + 0.72, -0.6, 2.22), (BX + 1.02, -0.6, 2.22), (BX + 1.02, 0.6, 2.22),
                            (BX + 0.72, 0.6, 2.22), (BX + 0.72, -0.38, 2.46), (BX + 1.02, -0.36, 2.46),
                            (BX + 1.02, 0.36, 2.46), (BX + 0.72, 0.38, 2.46)])

        HELM = 2.72
        helm = part('helmet', 'DWMHEHEAD_DAG', SILVER, (BX, 0, HEAD_TOP))
        cylinder(helm, (BX, 0, HELM), (BX, 0, HEAD_TOP + 0.05), 0.8)
        dome(helm, (BX, 0, HEAD_TOP + 0.05), 0.8)
        nose_guard = part('nose guard', 'DWMHEHEAD_DAG', SILVER, (BX + 0.85, 0, HELM))
        box(nose_guard, (BX + 0.72, -0.08, 2.45), (BX + 0.9, 0.08, HELM + 0.1))
        stud = part('helmet stud', 'DWMHEHEAD_DAG', SILVER, (BX, 0, HEAD_TOP + 0.95))
        cylinder(stud, (BX, 0, HEAD_TOP + 0.8), (BX, 0, HEAD_TOP + 1.02), 0.32)
    elif race.hair == 'cat':
        cat_head(part, race, HEAD_TOP)
    elif race.hair == 'dog':
        dog_head(part, race, HEAD_TOP)
    elif race.hair == 'troll':
        troll_head(part, race, HEAD_TOP)
    elif race.hair == 'frog':
        frog_head(part, race, HEAD_TOP)
    elif reptile:
        reptile_head(part, race, HEAD_TOP)
    else:
        # No helmet: the head's own stud on top, under any hair
        stud = part('head stud', 'DWMHEHEAD_DAG', race.skin, (BX, 0, HEAD_TOP + 0.1))
        cylinder(stud, (BX, 0, HEAD_TOP), (BX, 0, HEAD_TOP + 0.2), 0.4)
    if race.hair in ('short', 'long') and (race.ears == 'cat' or getattr(race, 'baked_hair', False) or os.environ.get('BAKED_HAIR') == '1'):  # Vah Shir keep their fur cap (no hair choices)  # in game the hair attachment (hairpieces.py) is the hair
        # A hair piece: a cap above the brows, a rounded crown, and a back that reaches the neck (or the shoulders)
        HC = race.hair_color
        cap = part('hair cap', 'DWMHEHEAD_DAG', HC, (BX, 0, HEAD_TOP))
        cylinder(cap, (BX, 0, 2.78), (BX, 0, HEAD_TOP + 0.12), 0.8, seg=40)
        crown = part('hair crown', 'DWMHEHEAD_DAG', HC, (BX, 0, HEAD_TOP + 0.2))
        cylinder(crown, (BX, 0, HEAD_TOP + 0.12), (BX, 0, HEAD_TOP + 0.3), 0.8, 0.6, seg=40, caps=(False, True))
        low = 1.35 if race.hair == 'long' else 1.95
        back = part('hair back', 'DWMHEHEAD_DAG', HC, (BX - 0.6, 0, (low + 2.8) / 2))
        box(back, (BX - 0.82, -0.8, low), (BX - 0.3, 0.8, 2.8))
        if race.hair == 'long':
            for side in (1, -1):
                lock = part('hair lock', 'DWMHEHEAD_DAG', HC, (BX - 0.1, side * 0.78, 2.1))
                y0, y1 = sorted((side * 0.62, side * 0.9))
                box(lock, (BX - 0.5, y0, low + 0.15), (BX + 0.25, y1, 2.8))
    for side in (1, -1):
        if race.ears == 'elf':
            ear = part('ear', 'DWMHEHEAD_DAG', race.skin, (BX - 0.05, side * 0.95, 2.6))
            y0, y1 = side * 0.6, side * 1.12
            hexa(ear, [(BX - 0.2, y0, 2.3), (BX + 0.1, y0, 2.3), (BX + 0.1, y0 * 1.1, 2.3), (BX - 0.2, y0 * 1.1, 2.3),
                       (BX - 0.3, y1, 3.0), (BX - 0.22, y1, 3.0), (BX - 0.22, y1 * 1.02, 3.0),
                       (BX - 0.3, y1 * 1.02, 3.0)])
        elif race.ears == 'dog':  # tall pointed jackal ears, tan inside, tipped a little outward
            z0, z1 = HEAD_TOP - 0.05, HEAD_TOP + 0.95
            ear = part('ear', 'DWMHEHEAD_DAG', race.hair_color, (BX - 0.15, side * 0.62, HEAD_TOP + 0.35))
            hexa(ear, [(BX - 0.42, side * 0.32, z0), (BX + 0.12, side * 0.32, z0), (BX + 0.12, side * 0.78, z0),
                       (BX - 0.42, side * 0.78, z0), (BX - 0.2, side * 0.8, z1), (BX - 0.14, side * 0.8, z1),
                       (BX - 0.14, side * 0.86, z1), (BX - 0.2, side * 0.86, z1)])
            inner = part('ear inside', 'DWMHEHEAD_DAG', DARK_TAN, (BX + 0.1, side * 0.6, HEAD_TOP + 0.3))
            hexa(inner, [(BX + 0.1, side * 0.4, z0 + 0.12), (BX + 0.16, side * 0.4, z0 + 0.12),
                         (BX + 0.16, side * 0.72, z0 + 0.12), (BX + 0.1, side * 0.72, z0 + 0.12),
                         (BX - 0.13, side * 0.77, z1 - 0.15), (BX - 0.1, side * 0.77, z1 - 0.15),
                         (BX - 0.1, side * 0.8, z1 - 0.15), (BX - 0.13, side * 0.8, z1 - 0.15)])
        elif race.ears == 'cat':
            ear = part('ear', 'DWMHEHEAD_DAG', race.hair_color, (BX - 0.1, side * 0.5, HEAD_TOP + 0.5))
            z0, z1 = HEAD_TOP + 0.2, HEAD_TOP + 0.75
            hexa(ear, [(BX - 0.3, side * 0.25, z0), (BX + 0.1, side * 0.25, z0), (BX + 0.1, side * 0.72, z0),
                       (BX - 0.3, side * 0.72, z0), (BX - 0.14, side * 0.52, z1), (BX - 0.1, side * 0.52, z1),
                       (BX - 0.1, side * 0.56, z1), (BX - 0.14, side * 0.56, z1)])

    for side, tag in ((1, 'L'), (-1, 'R')):
        group[0] = 'head'
        if race.hair == 'helmet':
            horn = part(f'horn {tag}', 'DWMHEHEAD_DAG', TAN, (BX, side * 1.1, HEAD_TOP + 0.4))
            cylinder(horn, (BX, side * 0.7, HEAD_TOP + 0.1), (BX + 0.05, side * 1.25, HEAD_TOP + 0.45), 0.23, 0.13,
                     caps=(False, False))
            horn2 = part(f'horn tip {tag}', 'DWMHEHEAD_DAG', TAN, (BX + 0.1, side * 1.35, HEAD_TOP + 0.8))
            cylinder(horn2, (BX + 0.05, side * 1.25, HEAD_TOP + 0.45), (BX + 0.15, side * 1.38, HEAD_TOP + 1.15), 0.13,
                     0.0, caps=(True, False))

        group[0] = f'arm {tag}'
        shoulder = np.array((BX, side * 0.95, SHOULDER_Z - 0.3))
        upper = part(f'arm upper {tag}', f'DWMBIBICEP{tag}_DAG', race.arms, shoulder + (0, side * 0.5, 0))
        fore = part(f'arm lower {tag}', f'DWMFOFOREARM{tag}_DAG', race.arms, shoulder + (0, side * 1.3, 0))
        if getattr(race, 'bony', False):
            knob(upper, shoulder + (0, side * 0.1, 0), (0.3, 0.26, 0.3))  # shoulder knob
            cylinder(upper, shoulder, shoulder + (0, side * 1.0, 0), 0.16, seg=12)
            knob(fore, shoulder + (0, side * 1.0, 0), (0.24, 0.22, 0.24))  # elbow
            cylinder(fore, shoulder + (0, side * 1.0, 0), shoulder + (0, side * 1.6, 0), 0.14, seg=12)
        else:
            cylinder(upper, shoulder, shoulder + (0, side * 1.0, 0), 0.38, 0.34)
            cylinder(fore, shoulder + (0, side * 1.0, 0), shoulder + (0, side * 1.6, 0), 0.34, 0.31)
        wrist = part(f'wrist {tag}', f'DWMFIHAND{tag}_DAG', race.skin, shoulder + (0, side * 1.7, 0))
        cylinder(wrist, shoulder + (0, side * 1.6, 0), shoulder + (0, side * 1.8, 0), 0.17)
        hand = part(f'hand {tag}', f'DWMFIHAND{tag}_DAG', race.skin, shoulder + (0.0, side * 2.08, 0))
        # The C grip: a short tube across the hand, open toward the front
        c = shoulder + (0, side * 2.08, 0)
        seg = 20
        dy = np.array([0, 0.16, 0])
        for k in range(seg):
            a0, a1 = math.radians(40 + 280 * k / seg), math.radians(40 + 280 * (k + 1) / seg)
            pt = lambda a, r: c + np.array([math.cos(a) * r, 0, math.sin(a) * r])
            i0, o0, o1, i1 = pt(a0, 0.14), pt(a0, 0.32), pt(a1, 0.32), pt(a1, 0.14)
            sub = Part('', '', race.skin, (i0 + o0 + o1 + i1) / 4)  # each slice of the C is convex on its own
            hexa(sub, [i0 - dy, o0 - dy, o1 - dy, i1 - dy, i0 + dy, o0 + dy, o1 + dy, i1 + dy])
            hand.tris += sub.tris
    return parts


# ------------------------------------------------------------------------------------------------ fitting
# Rest-pose joints of the male Dwarf skeleton the figure was designed on
DWARF = {'foot': -2.31, 'hip': 0.33, 'shoulder': 2.38, 'bicep': (-0.22, 0.9, 2.38), 'hand': (-0.79, 2.82, 2.48)}
SHOULDER = 1.35  # where the figure's arms meet the torso
NECK_TOP = 1.8


def landmarks(prefix, bones):
    """The joints fit() needs, from a race's skeleton {bone name: rest-pose position}."""
    b = lambda n: np.array(bones[f'{prefix}{n}_DAG'], float)
    return {'foot': b('BOFOOTL')[2], 'hip': b('THTHIGHL')[2], 'shoulder': b('BIBICEPL')[2],
            'bicep': b('BIBICEPL'), 'hand': b('FIHANDL')}


def fit(parts, prefix, bones):
    """Move a figure built on the Dwarf skeleton onto another race's skeleton (same bone names, other prefix).

    Heights between the foot, hip and shoulder joints are stretched to that race's joints; below the foot and above
    the shoulder they only shift. The head group moves as one piece, and each arm turns at the shoulder to follow
    the race's resting arm (and is shortened or lengthened to its arm's length)."""
    t = landmarks(prefix, bones)
    src = [DWARF['foot'], DWARF['hip'], DWARF['shoulder']]
    dst = [t['foot'], t['hip'], t['shoulder']]

    def zmap(z):
        if z <= src[0]:
            return z + dst[0] - src[0]
        if z >= src[2]:
            return z + dst[2] - src[2]
        k = 0 if z < src[1] else 1
        return dst[k] + (z - src[k]) * (dst[k + 1] - dst[k]) / (src[k + 1] - src[k])

    def arm_angle(bicep, hand):
        return math.atan2(hand[2] - bicep[2], abs(hand[1] - bicep[1]))

    def arm_length(bicep, hand):
        return math.hypot(hand[1] - bicep[1], hand[2] - bicep[2])

    turn = arm_angle(t['bicep'], t['hand']) - arm_angle(DWARF['bicep'], DWARF['hand'])
    stretch = arm_length(t['bicep'], t['hand']) / arm_length(DWARF['bicep'], DWARF['hand'])
    c, s = math.cos(turn), math.sin(turn)
    head_shift = np.array([0, 0, zmap(NECK_TOP) - NECK_TOP])
    for p in parts:
        side = 1 if p.group == 'arm L' else -1
        if p.group == 'body':
            move = lambda v: np.array([v[0], v[1], zmap(v[2])])
            turn_n = lambda n: n
        elif p.group == 'head':
            move = lambda v: v + head_shift
            turn_n = lambda n: n
        else:
            pivot = np.array([BX, side * 0.95, SHOULDER])
            new_pivot = np.array([BX, side * 0.95, zmap(SHOULDER)])

            def move(v, pivot=pivot, new_pivot=new_pivot, side=side):
                r = v - pivot
                a = r[1] * side
                a = a * stretch if a > 0 else a  # lengthen along the arm, past the shoulder
                return new_pivot + np.array([r[0], side * (a * c - r[2] * s), a * s + r[2] * c])

            def turn_n(n, side=side):
                a = n[1] * side
                return np.array([n[0], side * (a * c - n[2] * s), a * s + n[2] * c])
        p.tris = [[(move(v), turn_n(n), uv) for v, n, uv in tri] for tri in p.tris]
        p.center = move(p.center)
        p.bone = prefix + p.bone[3:]
    return parts


def tail(parts, race, prefix, bones, parents):
    """A tapered tail along the race's tail bones (Iksar, Vah Shir), one piece per bone."""
    names = [n for n in bones if 'TAIL' in n and n.startswith(prefix)]
    if not names:
        return parts
    # Follow the chain from the bone whose parent is not a tail bone
    chain = [next(n for n in names if parents[n] not in names)]
    while True:
        nxt = [n for n in names if parents[n] == chain[-1]]
        if not nxt:
            break
        chain.append(nxt[0])
    pts = [np.array(bones[n], float) for n in chain]
    base_r = 0.32
    for k, n in enumerate(chain):
        p0 = pts[k]
        p1 = pts[k + 1] if k + 1 < len(pts) else pts[k] + (pts[k] - pts[k - 1]) * 0.8
        r0 = base_r * (1 - k / len(chain))
        r1 = base_r * (1 - (k + 1) / len(chain))
        piece = Part(f'tail {k}', n, race.hair_color if race.ears == 'cat' or race.hair == 'lizard' else race.skin,
                     (p0 + p1) / 2)
        piece.group = 'tail'
        cylinder(piece, p0, p1, max(r0, 0.03), max(r1, 0.0), seg=16, caps=(k == 0, r1 > 0))
        parts.append(piece)
    return parts


# ------------------------------------------------------------------------------------------------ output
def gl(p):
    x, y, z = p
    return (y, z, x)  # EQ Z-up facing +X -> glTF Y-up facing +Z


def write_glb(path, parts):
    groups = {}
    for p in parts:
        key = p.material if isinstance(p.material, str) else tuple(p.material)
        groups.setdefault(key, []).extend(p.tris)
    bin_ = bytearray()
    doc = {'asset': {'version': '2.0', 'generator': 'minifig'}, 'scene': 0, 'scenes': [{'nodes': [0]}],
           'nodes': [{'mesh': 0, 'name': 'minifig dwarf'}], 'meshes': [{'primitives': []}], 'buffers': [],
           'bufferViews': [], 'accessors': [], 'materials': [], 'textures': [], 'images': [],
           'samplers': [{'magFilter': 9729, 'minFilter': 9987, 'wrapS': 33071, 'wrapT': 33071}]}

    def view(data, target=None):
        while len(bin_) % 4:
            bin_.append(0)
        v = {'buffer': 0, 'byteOffset': len(bin_), 'byteLength': len(data)}
        if target:
            v['target'] = target
        doc['bufferViews'].append(v)
        bin_.extend(data)
        return len(doc['bufferViews']) - 1

    def acc(arr, ctype, typ, target):
        a = {'bufferView': view(arr.tobytes(), target), 'componentType': ctype, 'count': len(arr), 'type': typ}
        if typ == 'VEC3':
            a['min'], a['max'] = arr.min(0).tolist(), arr.max(0).tolist()
        doc['accessors'].append(a)
        return len(doc['accessors']) - 1

    for key, tris in groups.items():
        P = np.array([gl(v[0]) for t in tris for v in t], np.float32)
        N = np.array([gl(v[1]) for t in tris for v in t], np.float32)
        N /= np.linalg.norm(N, axis=1, keepdims=True)
        U = np.array([v[2] for t in tris for v in t], np.float32)
        I = np.arange(len(P), dtype=np.uint32)
        prim = {'attributes': {'POSITION': acc(P, 5126, 'VEC3', 34962), 'NORMAL': acc(N, 5126, 'VEC3', 34962),
                               'TEXCOORD_0': acc(U, 5126, 'VEC2', 34962)},
                'indices': acc(I, 5125, 'SCALAR', 34963)}
        pbr = {'metallicFactor': 0.0, 'roughnessFactor': 0.35}  # glossy plastic
        if isinstance(key, str):
            png = io.BytesIO(); TEXTURES[key].save(png, 'PNG')
            doc['images'].append({'bufferView': view(png.getvalue()), 'mimeType': 'image/png'})
            doc['textures'].append({'source': len(doc['images']) - 1, 'sampler': 0})
            pbr['baseColorTexture'] = {'index': len(doc['textures']) - 1}
        else:
            # glTF colors are linear
            pbr['baseColorFactor'] = [((c / 255) ** 2.2) for c in key] + [1.0]
        doc['materials'].append({'name': str(key), 'pbrMetallicRoughness': pbr})
        prim['material'] = len(doc['materials']) - 1
        doc['meshes'][0]['primitives'].append(prim)
    while len(bin_) % 4:
        bin_.append(0)
    doc['buffers'].append({'byteLength': len(bin_)})
    js = json.dumps(doc, separators=(',', ':')).encode()
    js += b' ' * (-len(js) % 4)
    out = struct.pack('<III', 0x46546C67, 2, 28 + len(js) + len(bin_))
    out += struct.pack('<II', len(js), 0x4E4F534A) + js + struct.pack('<II', len(bin_), 0x004E4942) + bytes(bin_)
    open(path, 'wb').write(out)


def color_at(material, uv):
    if isinstance(material, str):
        im = TEXTURES[material]
        u, v = uv
        return im.getpixel((min(int(u * im.width), im.width - 1), min(int(v * im.height), im.height - 1)))
    return material


def preview(path, parts, size=640, ss=2):
    """Three views (front, three-quarter, side), painter's algorithm, per-pixel-ish via small triangles."""
    S = size * ss
    sheet = Image.new('RGB', (S * 3, S), (52, 58, 70))
    d = ImageDraw.Draw(sheet)
    light = np.array([0.5, 0.7, 0.6]); light /= np.linalg.norm(light)
    allp = np.array([gl(v[0]) for p in parts for t in p.tris for v in t])
    lo, hi = allp.min(0), allp.max(0)
    mid = (lo + hi) / 2
    span = max(hi[1] - lo[1], hi[0] - lo[0], hi[2] - lo[2]) * 1.12  # tall figures and long creatures alike
    for vi, yaw in enumerate((0, 35, 90)):
        a = math.radians(yaw)
        R = np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]])
        items = []
        for p in parts:
            for t in p.tris:
                pts = np.array([R @ (np.array(gl(v[0])) - mid) for v in t])
                n = np.cross(pts[1] - pts[0], pts[2] - pts[0])
                ln = np.linalg.norm(n)
                if ln == 0:
                    continue
                n /= ln
                if n[2] < 0:  # back-facing (camera looks down -Z from +Z)
                    continue
                uv = np.mean([v[2] for v in t], axis=0)
                col = np.array(color_at(p.material, uv), float)
                shade = 0.45 + 0.55 * max(0.0, n @ light) + 0.25 * max(0.0, n[2]) ** 12  # diffuse + plastic glint
                items.append((pts[:, 2].mean(), pts, np.clip(col * shade, 0, 255)))
        items.sort(key=lambda x: x[0])
        for _z, pts, col in items:
            xy = [(vi * S + S / 2 + q[0] / span * S, S / 2 - q[1] / span * S) for q in pts]
            d.polygon(xy, fill=tuple(int(c) for c in col))
    sheet = sheet.resize((size * 3, size), Image.LANCZOS)
    sheet.save(path)


def use(race):
    """Point the shared textures (glb, preview, atlas) at a race's prints."""
    TEXTURES.update(textures(race))


if __name__ == '__main__':
    race = RACES[sys.argv[3]] if len(sys.argv) > 3 else RACES['dwm']
    use(race)
    parts = build(race)
    write_glb(sys.argv[1], parts)
    preview(sys.argv[2], parts)
    print(len(parts), 'parts,', sum(len(p.tris) for p in parts), 'triangles')
