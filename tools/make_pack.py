#!/usr/bin/env python3
"""Generates the HandCannon resource pack (3D revolver model, textures, item definition), a zip, and preview.png.
Usage: python3 tools/make_pack.py [output_dir]   (needs Pillow)

The model is built from boxes in model units (16 = one block). The barrel points north (-z), the grip is at the
back (+z). How it sits in hand / inventory / item frames is set in DISPLAY below: tweak those numbers and re-run."""
import json, os, sys, shutil, zipfile, hashlib, math, random
from PIL import Image, ImageDraw

OUT = sys.argv[1] if len(sys.argv) > 1 else "resourcepack"
NS = "handcannon"
shutil.rmtree(OUT, ignore_errors=True)
def path(*p):
    f = os.path.join(OUT, *p); os.makedirs(os.path.dirname(f), exist_ok=True); return f
def wjson(p, obj): json.dump(obj, open(p, "w"), indent=1)

# ---------------- textures (16x16, procedural) ----------------
# FINISH picks the metal colours: "stainless" (bright frame, dark cylinder), "blued" (deep blue-black) or "black"
FINISH = "stainless"
PALETTES = {
    "stainless": {"frame": (176, 180, 186), "cylinder": (78, 80, 86), "polished": (206, 208, 212)},
    "blued":     {"frame": (34, 40, 58), "cylinder": (34, 40, 58), "polished": (150, 152, 158)},
    "black":     {"frame": (40, 41, 44), "cylinder": (88, 90, 96), "polished": (176, 180, 186)},
}
PAL = PALETTES[FINISH]
rng = random.Random(7)
def clamp(v): return max(0, min(255, int(v)))
def shade(c, f): return tuple(clamp(v * f) for v in c[:3]) + (255,)
def tex_metal(base, noise=8, edge=True):
    """Clean cartoon metal: flat colour, a soft light band at the top and shade at the bottom, a bright edge line.
    (noise is kept for the callers but no longer speckles the surface.)"""
    im = Image.new("RGBA", (16, 16)); px = im.load()
    for y in range(16):
        f = 1.0 + (0.12 if y < 4 else 0) - (0.1 if y > 12 else 0)
        for x in range(16): px[x, y] = shade(base, f)
    if edge:
        for x in range(16): px[x, 1] = shade(base, 1.3)
    return im
def tex_flutes(base, vertical):
    """One plain flute per face that stops short of both ends. Rows on the side faces, columns on top/bottom."""
    im = tex_metal(base, 6, edge=False); px = im.load()
    for t in range(3, 13):
        for k in range(6, 10):
            x, y = (k, t) if vertical else (t, k)
            px[x, y] = shade(base, 0.6)
    return im
def tex_knurl(base):
    im = tex_metal(base, 0, edge=False); px = im.load()
    for y in range(16):
        for x in range(16):
            if (x + y) % 2 == 0: px[x, y] = shade(base, 0.8)
    return im
def tex_wood(base, streak):
    """Smooth polished wood: soft broad grain running along the piece and a highlight stripe."""
    im = Image.new("RGBA", (16, 16)); px = im.load()
    for y in range(16):
        for x in range(16):
            g = math.sin(x * 0.8 + math.sin(y * 0.3) * 1.2) * 6
            c = [base[0] + g, base[1] + g * 0.6, base[2] + g * 0.35]
            if x in (4, 5): c = [v * 1.12 for v in c]          # polish highlight
            px[x, y] = tuple(clamp(v) for v in c) + (255,)
    return im
def tex_bore():
    im = tex_metal(PAL["frame"], edge=False); d = ImageDraw.Draw(im)
    d.ellipse((1, 1, 14, 14), fill=shade(PAL["frame"], 0.8), outline=shade(PAL["frame"], 1.2))   # crowned muzzle
    d.ellipse((4, 4, 11, 11), fill=(10, 10, 12, 255))
    return im
def flat(c, noise=3): return tex_metal(c, noise, edge=False)

TEX = {"frame": tex_metal(PAL["frame"]), "cylinder": tex_metal(PAL["cylinder"], 6, edge=False),
       "cyl_h": tex_flutes(PAL["cylinder"], False), "cyl_v": tex_flutes(PAL["cylinder"], True),
       "polished": tex_metal(PAL["polished"], 5), "knurl": tex_knurl(PAL["polished"]),
       "bore": tex_bore(), "dark": flat((24, 24, 28)), "black": flat((30, 30, 32), 2), "orange": flat((255, 110, 30), 6),
       "wood": tex_wood((176, 82, 52), 0.72), "wood_dark": tex_wood((104, 70, 44), 0.75)}
FULL_UV = {"bore", "cyl_h", "cyl_v", "knurl"}   # these textures are stretched over the whole face
for k, im in TEX.items(): im.save(path("assets", NS, "textures", "item", "hand_cannon", k + ".png"))

# ---------------- geometry: hand cannon ----------------
elements = []
def box(frm, to, tex, faces_tex=None, rot=None):
    """faces_tex overrides the texture for some faces, e.g. {"north": "bore"}. rot = (axis, angle, origin)."""
    faces = {}
    sx, sy, sz = (to[i] - frm[i] for i in range(3))
    dims = {"north": (sx, sy), "south": (sx, sy), "east": (sz, sy), "west": (sz, sy), "up": (sx, sz), "down": (sx, sz)}
    for f, (w, h) in dims.items():
        t = (faces_tex or {}).get(f, tex)
        uv = [0, 0, 16, 16] if t in FULL_UV else [0, 0, round(min(16, w), 2), round(min(16, h), 2)]
        faces[f] = {"uv": uv, "texture": "#" + t}
    e = {"from": [round(v, 3) for v in frm], "to": [round(v, 3) for v in to], "faces": faces}
    if rot: e["rotation"] = {"axis": rot[0], "angle": rot[1], "origin": list(rot[2])}
    elements.append(e)

def round_prism(cx, cy, diameter, z0, z1, tex, faces_tex=None):
    """A roundish prism along z: two crossed slabs, plus the same pair turned 45 degrees (looks octagonal end-on).
    Each slab's ends are pushed out a touch further than the last so no two end faces share a plane (no z-fighting)."""
    r, w = diameter / 2, diameter * 0.46 / 2
    origin = (cx, cy, (z0 + z1) / 2)
    i = 0
    for rot in (None, ("z", 45, origin)):
        for half_x, half_y in ((r, w), (w, r)):
            d = 0.04 * i
            box((cx - half_x, cy - half_y, z0 - d), (cx + half_x, cy + half_y, z1 + d), tex, faces_tex, rot)
            i += 1

# barrel: short, fat and round (snubnose) with a flat sighting rib on top
round_prism(8, 13.0, 4.6, -6.0, 2.7, "frame")
box((6.4, 11.4, -6.26), (9.6, 14.6, -6.16), "bore")                  # muzzle: one cap carries the bore, just in front
box((7.0, 14.9, -6.0), (9.0, 15.8, 2.7), "frame")                    # top rib
box((7.4, 15.6, -5.9), (8.6, 17.2, -4.0), "frame")                   # ramped front sight
box((7.35, 16.3, -5.7), (8.65, 17.0, -5.0), "orange")                # sight insert
# full-length underlug with the ejector rod showing through a slot
box((6.6, 8.6, -5.8), (9.4, 11.4, 2.7), "frame")
box((6.5, 9.4, -3.6), (9.5, 10.6, 1.6), "dark")                      # slot
box((6.45, 9.75, -3.4), (9.55, 10.25, 1.5), "polished")              # ejector rod
box((6.4, 9.5, -3.5), (9.6, 10.5, -2.4), "knurl")                    # knurled rod tip
# cylinder: fat and long, long flutes, bevelled front
FLUTES = {"east": "cyl_h", "west": "cyl_h", "up": "cyl_v", "down": "cyl_v"}
round_prism(8, 10.5, 9.6, 3.0, 12.0, "cylinder", FLUTES)
round_prism(8, 10.5, 8.6, 2.4, 3.0, "cylinder")                      # bevel
box((7.2, 9.7, 2.0), (8.8, 11.3, 2.4), "polished")                   # centre pin / ejector star
# frame
box((6.0, 4.0, 1.6), (10.0, 13.6, 2.6), "frame")                     # yoke
box((6.0, 4.0, 2.6), (10.0, 6.0, 12.0), "frame")                     # under the cylinder
box((6.2, 15.0, 2.6), (9.8, 16.2, 15.4), "frame")                    # top strap
box((5.5, 4.0, 12.0), (10.5, 16.0, 16.4), "frame")                   # recoil shield / rear frame
box((6.6, 16.2, 12.6), (9.4, 17.6, 15.2), "black")                   # adjustable rear sight
box((7.6, 17.0, 12.5), (8.4, 17.7, 15.3), "dark")                    # rear sight notch
box((4.9, 10.8, 12.6), (5.5, 12.8, 15.4), "polished", {"west": "knurl"})   # cylinder release latch (left side)
box((10.5, 8.0, 13.0), (10.7, 9.0, 14.0), "polished")                # side plate screw
# target hammer: tall, with a wide serrated spur drooping back over the grip
box((7.0, 14.5, 15.4), (9.0, 19.2, 17.6), "polished")
box((7.1, 18.2, 15.0), (8.9, 19.6, 17.4), "polished")
HAMMER_ROT = ("x", 22.5, (8, 18.6, 17.4))
box((6.3, 17.8, 17.0), (9.7, 19.4, 21.0), "polished", {"up": "knurl"}, HAMMER_ROT)
# rounded trigger guard and a curved, polished trigger
box((7.0, 1.4, 8.6), (9.0, 2.4, 13.6), "frame")                      # bottom
box((7.0, 3.4, 7.4), (9.0, 5.8, 8.4), "frame")                       # front
box((7.0, 2.3, 7.6), (9.0, 3.3, 9.6), "frame", rot=("x", 45, (8, 2.8, 8.6)))     # rounded front corner
box((7.0, 2.3, 12.6), (9.0, 3.3, 14.6), "frame", rot=("x", -45, (8, 2.8, 13.6)))  # rounded back corner
box((7.0, 3.2, 13.6), (9.0, 4.6, 14.6), "frame")                     # rises into the grip frame
box((7.5, 3.8, 10.4), (8.5, 5.8, 11.4), "polished")
box((7.5, 2.0, 10.6), (8.5, 4.0, 11.6), "polished", rot=("x", 22.5, (8, 4, 11.1)))   # tip curls forward
# grip: rounded finger-groove target grip, raked back, wrapping the backstrap, on a flared walnut base
GRIP_ROT = ("x", -22.5, (8, 6, 16))
box((5.6, -8.0, 13.6), (10.4, 5.2, 18.8), "wood", rot=GRIP_ROT)      # core
box((5.2, -7.6, 14.2), (10.8, 4.6, 18.2), "wood", rot=GRIP_ROT)      # sides bulge out
box((6.1, -7.7, 13.1), (9.9, 4.8, 19.4), "wood", rot=GRIP_ROT)       # front and back bulge out
box((4.9, -5.2, 15.0), (11.1, 1.8, 18.4), "wood", rot=GRIP_ROT)      # palm swell
for y in (1.6, -1.6, -4.8):                                          # finger ridges on the front strap
    box((6.6, y, 12.8), (9.4, y + 1.2, 13.4), "wood", rot=GRIP_ROT)
box((6.2, 3.0, 16.0), (9.8, 6.6, 19.6), "wood", rot=("x", -45, (8, 5, 16.6)))   # backstrap curve up behind the hammer
box((5.0, -9.6, 12.8), (11.0, -7.8, 20.0), "wood_dark", rot=GRIP_ROT)  # flared base
box((5.6, -10.2, 13.4), (10.4, -9.6, 19.4), "wood_dark", rot=GRIP_ROT)
box((6.5, 3.9, 12.8), (9.5, 6.0, 16.0), "frame")                     # grip frame under the hammer

GUN = elements

# ---------------- geometry: nail bat ----------------
# A normal-sized bat standing upright (knob at the bottom, head at the top), centred on x = z = 8.
rng_bat = random.Random(11)
def tex_bat_wood():
    im = Image.new("RGBA", (16, 16)); px = im.load()
    for y in range(16):
        for x in range(16):
            g = math.sin(x * 0.7 + math.sin(y * 0.25) * 1.5) * 6 + (10 if x in (4, 5) else 0)
            px[x, y] = (clamp(206 + g), clamp(150 + g * 0.8), clamp(70 + g * 0.4), 255)
    return im
def tex_rust():
    im = Image.new("RGBA", (16, 16)); px = im.load()
    for y in range(16):
        for x in range(16):
            px[x, y] = shade((112, 68, 48), 1.12 if y < 6 else 1.0)
    return im
def tex_nail_head():
    im = tex_rust(); d = ImageDraw.Draw(im)
    d.ellipse((2, 2, 13, 13), fill=(138, 98, 72, 255), outline=(70, 44, 30, 255))
    return im
BAT_TEX = {"wood": tex_bat_wood(), "end": tex_bat_wood(), "rust": tex_rust(), "nail_head": tex_nail_head()}
for k, im in BAT_TEX.items(): im.save(path("assets", NS, "textures", "item", "nail_bat", k + ".png"))
FULL_UV.add("nail_head")

elements = []
def round_rod(cx, cz, diameter, y0, y1, tex, faces_tex=None):
    """Roundish rod along y (crossed slabs, plus the pair turned 45 degrees), ends staggered so nothing z-fights."""
    r, w = diameter / 2, diameter * 0.46 / 2
    origin = (cx, (y0 + y1) / 2, cz)
    i = 0
    for rot in (None, ("y", 45, origin)):
        for hx, hz in ((r, w), (w, r)):
            d = 0.03 * i
            box((cx - hx, y0 - d, cz - hz), (cx + hx, y1 + d, cz + hz), tex, faces_tex, rot)
            i += 1
ENDS = {"up": "end", "down": "end"}
round_rod(8, 8, 2.9, -7.4, -6.4, "wood", ENDS)        # knob
round_rod(8, 8, 1.7, -6.4, 4.0, "wood")               # handle
round_rod(8, 8, 2.1, 4.0, 8.0, "wood")                # taper
round_rod(8, 8, 2.6, 8.0, 11.5, "wood")
round_rod(8, 8, 3.1, 11.5, 14.5, "wood")
round_rod(8, 8, 3.5, 14.5, 21.8, "wood")              # barrel
round_rod(8, 8, 3.1, 21.8, 22.6, "wood", ENDS)        # rounded end cap

# rusty nails hammered through the head: some show their points, some their heads
def nail(y, direction, tilt, point, length):
    """direction: 0..7 around the bat (45 degree steps); tilt: 0, 22.5 or -22.5 up/down (only for the 4 straight directions)."""
    straight = direction % 2 == 0
    axis_dir = direction // 2 % 2       # 0 -> along x, 1 -> along z
    sign = 1 if direction in (0, 1, 2, 7) and direction != 2 else -1
    sign = [1, 1, 1, -1, -1, -1, -1, 1][direction]
    r0, r1 = 1.2, 1.75 + length
    t = 0.18
    if axis_dir == 0 or not straight:
        lo_, hi_ = sorted((8 + sign * r0, 8 + sign * r1))
        frm, to = (lo_, y - t, 8 - t), (hi_, y + t, 8 + t)
        hfrm, hto = ((hi_ - 0.25, y - 0.6, 7.4), (hi_, y + 0.6, 8.6)) if sign > 0 else ((lo_, y - 0.6, 7.4), (lo_ + 0.25, y + 0.6, 8.6))
        hfaces = {"east": "nail_head", "west": "nail_head"}
    else:
        lo_, hi_ = sorted((8 + sign * r0, 8 + sign * r1))
        frm, to = (8 - t, y - t, lo_), (8 + t, y + t, hi_)
        hfrm, hto = ((7.4, y - 0.6, hi_ - 0.25), (8.6, y + 0.6, hi_)) if sign > 0 else ((7.4, y - 0.6, lo_), (8.6, y + 0.6, lo_ + 0.25))
        hfaces = {"north": "nail_head", "south": "nail_head"}
    if straight and tilt:
        rot = ("z" if axis_dir == 0 else "x", tilt, (8, y, 8))
    elif not straight:
        rot = ("y", 45 if direction in (1, 5) else -45, (8, y, 8))
    else:
        rot = None
    if point:
        box(frm, to, "rust", rot=rot)
        # thinner tip
        if axis_dir == 0 or not straight:
            tip = (hi_ - 0.8, y - 0.1, 7.9) if sign > 0 else (lo_ - 0.6, y - 0.1, 7.9)
            box(tip, (tip[0] + 1.4 - (0 if sign > 0 else 0), y + 0.1, 8.1), "rust", rot=rot)
        else:
            tip = (7.9, y - 0.1, hi_ - 0.8) if sign > 0 else (7.9, y - 0.1, lo_ - 0.6)
            box(tip, (8.1, y + 0.1, tip[2] + 1.4), "rust", rot=rot)
    else:
        # a short stub of shank with the flat head showing
        if axis_dir == 0 or not straight:
            frm, to = ((8 + r0, y - t, 8 - t), (8 + r0 + 0.9, y + t, 8 + t)) if sign > 0 else ((8 - r0 - 0.9, y - t, 8 - t), (8 - r0, y + t, 8 + t))
            hfrm, hto = ((to[0], y - 0.55, 7.45), (to[0] + 0.25, y + 0.55, 8.55)) if sign > 0 else ((frm[0] - 0.25, y - 0.55, 7.45), (frm[0], y + 0.55, 8.55))
        else:
            frm, to = ((8 - t, y - t, 8 + r0), (8 + t, y + t, 8 + r0 + 0.9)) if sign > 0 else ((8 - t, y - t, 8 - r0 - 0.9), (8 + t, y + t, 8 - r0))
            hfrm, hto = ((7.45, y - 0.55, to[2]), (8.55, y + 0.55, to[2] + 0.25)) if sign > 0 else ((7.45, y - 0.55, frm[2] - 0.25), (8.55, y + 0.55, frm[2]))
        box(frm, to, "rust", rot=rot)
        box(hfrm, hto, "rust", hfaces, rot=rot)

NAILS = [  # (height, direction 0-7, tilt, shows point?, length)
    (21.2, 0, 22.5, True, 2.6), (20.6, 3, 0, True, 2.2), (20.0, 4, -22.5, False, 0), (19.4, 6, 22.5, True, 2.8),
    (18.7, 1, 0, False, 0), (18.2, 5, 0, True, 2.4), (17.5, 2, -22.5, True, 2.0), (16.9, 7, 0, False, 0),
    (16.2, 0, -22.5, True, 2.2), (15.6, 4, 22.5, True, 2.6), (15.1, 6, 0, False, 0), (21.6, 2, 22.5, False, 0),
    (13.4, 3, 0, True, 1.6), (12.6, 6, -22.5, True, 1.4),
]
for n in NAILS: nail(*n)
BAT = elements

# ---------------- geometry: tommy gun ----------------
# Modelled on the M1-style layout (plain barrel, wooden forend, boxy receiver, raked pistol grip, long stock),
# with cartoon proportions: everything chunkier, and a huge drum magazine.
# Built like the hand cannon: barrel toward north (-z), stock at the back (+z).
def tex_steel(): return tex_metal((44, 48, 60), 7)
def tex_drum():
    im = tex_metal((58, 62, 74), 6, edge=False); px = im.load()
    for x in range(16):   # a pressed ring around the face of the drum
        for y in range(16):
            r = math.hypot(x - 7.5, y - 7.5)
            if 5.6 < r < 6.6: px[x, y] = shade((58, 62, 74), 0.7)
            elif 6.6 <= r < 7.2: px[x, y] = shade((58, 62, 74), 1.3)
    return im
TOMMY_TEX = {"steel": tex_steel(), "polished": tex_metal((176, 180, 188), 5), "dark": flat((22, 22, 26)),
             "bore": tex_bore(), "walnut": tex_wood((150, 90, 58), 0.78), "walnut_dark": tex_wood((96, 56, 34), 0.8), "drum": tex_drum(), "drum_side": tex_metal((58, 62, 74), 6, edge=False),
             "drum_plate": tex_metal((46, 50, 60), 5, edge=False)}
for k, im in TOMMY_TEX.items(): im.save(path("assets", NS, "textures", "item", "tommy_gun", k + ".png"))
FULL_UV.add("drum")

elements = []
def round_prism_x(cy, cz, diameter, x0, x1, tex, faces_tex=None):
    """Roundish prism along x (for the drum): crossed slabs, plus the pair turned 45 degrees, ends staggered."""
    r, w = diameter / 2, diameter * 0.46 / 2
    origin = ((x0 + x1) / 2, cy, cz)
    i = 0
    for rot in (None, ("x", 45, origin)):
        for hy, hz in ((r, w), (w, r)):
            d# receiver: a chunky box with protective ears round the rear sight
box((6.0, 8.4, 0.0), (10.0, 12.6, 15.0), "steel")
box((6.6, 9.0, -1.0), (9.4, 12.2, 0.0), "steel")                     # front collar where the barrel screws in
box((6.3, 12.6, 11.6), (7.3, 14.4, 14.4), "steel")                   # sight ears
box((8.7, 12.6, 11.6), (9.7, 14.4, 14.4), "steel")
box((7.3, 12.6, 12.6), (8.7, 13.6, 13.6), "dark")                    # rear sight aperture between the ears
box((10.0, 10.6, 5.0), (10.9, 11.7, 6.4), "polished")                # charging knob (right side)
box((10.0, 10.0, 7.2), (10.15, 11.6, 10.8), "dark")                  # ejection port (right side)
box((5.85, 8.8, 10.4), (6.0, 9.6, 11.8), "polished")                 # fire selector (left side)
box((5.85, 8.8, 12.4), (6.0, 9.6, 13.6), "polished")                 # safety (left side)
box((6.4, 7.2, 9.2), (9.6, 8.4, 15.0), "steel")                      # trigger housing
# long plain barrel with a front sight
round_prism(8, 11.0, 2.6, -15.0, -1.0, "steel")
round_prism(8, 11.0, 3.2, -14.6, -13.2, "steel")                     # front sight base
box((7.4, 12.4, -14.4), (8.6, 14.0, -13.4), "steel")                 # front sight blade
box((6.9, 9.9, -15.3), (9.1, 12.1, -15.2), "bore")                   # muzzle
# horizontal wooden forend under the barrel
box((6.4, 7.6, -10.4), (9.6, 10.6, -1.2), "walnut")
box((6.0, 8.0, -10.0), (10.0, 10.2, -1.6), "walnut")                 # rounded sides
box((5.95, 8.9, -9.4), (10.05, 9.3, -2.2), "walnut_dark")            # finger groove along each side
box((7.6, 6.6, -10.0), (8.4, 7.6, -9.2), "polished")                 # sling swivel
# vertical front grip hanging straight down from the forend
box((6.7, 1.4, -7.4), (9.3, 7.7, -4.6), "walnut")
box((6.4, 2.0, -7.0), (9.6, 7.2, -5.0), "walnut")                    # rounded sides
for y in (5.8, 4.2, 2.6):                                            # finger ridges on the front
    box((6.9, y, -7.9), (9.1, y + 0.7, -7.4), "walnut")
box((6.5, 1.0, -7.2), (9.5, 1.4, -4.8), "walnut_dark")               # base
# the big drum, its round face pointing forward (toward the muzzle). The face is built from concentric raised
# steps (not a printed ring), so every layer lines up.
round_prism(8, 1.8, 13.6, 2.4, 8.4, "drum_side")
round_prism(8, 1.8, 14.2, 2.7, 3.2, "steel")                         # rolled rims
round_prism(8, 1.8, 14.2, 7.6, 8.1, "steel")
round_prism(8, 1.8, 11.0, 2.18, 8.62, "drum_plate")                  # face plate
round_prism(8, 1.8, 8.2, 1.96, 8.84, "drum_side")                    # pressed centre
round_prism(8, 1.8, 3.2, 1.72, 9.08, "polished")                     # centre hub
box((6.7, 1.4, 1.3), (9.3, 2.2, 1.7), "polished")                    # winding key on the front
box((6.6, 7.4, 1.6), (9.4, 8.5, 9.2), "steel")                       # magazine well
# trigger guard and trigger
box((7.0, 4.8, 10.2), (9.0, 5.6, 13.8), "steel")
box((7.05, 5.2, 9.6), (8.95, 7.4, 10.4), "steel")
box((7.0, 4.6, 9.8), (9.0, 5.6, 11.0), "steel", rot=("x", 45, (8, 5.2, 10.4)))   # rounded front corner
box((7.5, 5.6, 11.2), (8.5, 7.4, 12.0), "polished", rot=("x", 22.5, (8, 7, 11.6)))  # trigger
# pistol grip raked back, finger grooves on the front, flared at the bottom
PG = ("x", -22.5, (8, 7.6, 15.4))
box((6.4, 0.8, 13.6), (9.6, 7.6, 17.2), "walnut", rot=PG)
box((6.0, 1.2, 14.1), (10.0, 7.2, 16.7), "walnut", rot=PG)           # rounded sides
for y in (5.6, 4.0, 2.4):                                            # finger ridges
    box((6.7, y, 13.1), (9.3, y + 0.8, 13.6), "walnut", rot=PG)
box((5.9, 0.0, 13.3), (10.1, 0.8, 17.6), "walnut", rot=PG)           # flared bottom
# long stock: a narrow wrist off the back of the receiver, dropping toward a tall butt with a steel plate
box((6.6, 8.4, 15.0), (9.4, 12.2, 21.0), "walnut")                   # wrist
box((9.4, 9.6, 17.8), (9.55, 10.4, 18.6), "polished")                # stock bolt
ST = ("x", 22.5, (8, 11.6, 20.0))
box((6.5, 8.0, 19.0), (9.5, 12.0, 30.0), "walnut", rot=ST)
box((6.2, 8.4, 19.6), (9.8, 11.6, 29.6), "walnut", rot=ST)           # rounded sides
box((6.5, 5.6, 25.6), (9.5, 8.0, 30.0), "walnut", rot=ST)            # butt gets taller toward the shoulder
box((6.2, 6.0, 26.2), (9.8, 8.4, 29.6), "walnut", rot=ST)
box((6.4, 5.4, 30.0), (9.6, 12.2, 30.6), "steel", rot=ST)            # butt plate
box((7.6, 4.6, 27.8), (8.4, 5.6, 28.6), "polished", rot=ST)          # sling swivel
TOMMY = elements

# ---------------- geometry: double-barrel shotgun ----------------
# A side-by-side double modelled on a fine English sidelock (blued barrels with gold bands, case-hardened action,
# figured walnut, cheekpiece, black recoil pad), with cartoon proportions: short fat barrels, chunky everything.
rng_sg = random.Random(23)
def tex_case():
    """Colour case-hardening, cartoon style: a few big soft patches of grey, blue and amber."""
    from PIL import ImageFilter
    im = Image.new("RGBA", (16, 16)); px = im.load()
    blobs = [(2, 3, (150, 154, 162)), (11, 2, (108, 118, 142)), (6, 9, (164, 134, 92)), (13, 12, (132, 136, 146)), (2, 14, (112, 120, 140))]
    for y in range(16):
        for x in range(16):
            px[x, y] = min(blobs, key=lambda b: (b[0] - x) ** 2 + (b[1] - y) ** 2)[2] + (255,)
    return im.filter(ImageFilter.GaussianBlur(1.6))
def tex_figured(base):
    """Dark walnut with soft, swirly figure."""
    im = Image.new("RGBA", (16, 16)); px = im.load()
    for y in range(16):
        for x in range(16):
            g = math.sin(x * 0.7 + math.sin(y * 0.4) * 2.0) * 9 + (8 if x in (4, 5) else 0)
            px[x, y] = (clamp(base[0] + g), clamp(base[1] + g * 0.55), clamp(base[2] + g * 0.3), 255)
    return im
def tex_checkered(base):
    im = tex_figured(base); px = im.load()
    for y in range(16):
        for x in range(16):
            if (x + y) % 3 == 0 or (x - y) % 3 == 0: px[x, y] = shade(px[x, y], 0.84)
    return im
SG_TEX = {"blued": tex_metal((30, 34, 48), 5), "case": tex_case(), "gold": tex_metal((214, 168, 72), 10),
          "orange": flat((255, 110, 30), 6), "bore": tex_bore(), "dark": flat((22, 22, 26)),
          "polished": tex_metal((176, 180, 188), 5), "walnut": tex_figured((112, 58, 30)),
          "checkered": tex_checkered((112, 58, 30)), "rubber": flat((26, 26, 28), 3)}
for k, im in SG_TEX.items(): im.save(path("assets", NS, "textures", "item", "shotgun", k + ".png"))

elements = []
# two fat barrels side by side, a flat rib on top with an orange bead and a little rear sight
for bx, d in ((6.3, 0.0), (9.7, 0.02)):   # d: the right barrel's parts sit a hair apart so overlaps never z-fight
    round_prism(bx, 11.0, 3.4, -14.0, 4.6, "blued")
    round_prism(bx, 11.0 + d, 3.8, 3.0 + d, 3.6 + d, "gold")            # gold band near the breech
    box((bx - 1.25, 9.75, -14.32), (bx + 1.25, 12.25, -14.22), "bore")  # muzzle
box((7.3, 12.2, -14.0), (8.7, 13.1, 4.6), "blued")                     # top rib
box((7.3, 9.0, -13.0), (8.7, 10.0, 4.5), "blued")                      # bottom rib
box((7.6, 13.1, -13.7), (8.4, 13.9, -12.9), "orange")                  # bead
box((7.4, 13.1, -1.2), (8.6, 14.1, -0.6), "dark")                      # folding rear sight
# case-hardened action: a chunky box, rounded fences behind the barrels, side plates running back
box((4.8, 7.6, 4.6), (11.2, 12.6, 10.4), "case")
round_prism(6.3, 11.0, 4.0, 4.4, 5.4, "case")                          # fences
round_prism(9.7, 11.02, 4.0, 4.42, 5.42, "case")
box((4.6, 7.2, 9.8), (11.4, 11.4, 14.6), "case")                       # side plates
box((4.5, 9.2, 11.0), (4.6, 9.8, 11.6), "gold")                        # lock pins
box((11.4, 9.2, 11.0), (11.5, 9.8, 11.6), "gold")
# top lever and safety on the tang
box((7.3, 12.6, 10.0), (8.7, 13.4, 13.6), "case")
box((6.8, 12.8, 12.6), (9.2, 13.8, 14.2), "case")                      # thumbpiece
box((7.5, 11.4, 14.8), (8.5, 12.0, 15.8), "gold")                      # safety slide
# splinter forend under the barrels, checkered on the sides
box((5.4, 7.4, -6.0), (10.6, 9.8, 4.6), "walnut", {"east": "checkered", "west": "checkered"})
box((5.8, 7.8, -7.2), (10.2, 9.6, -6.0), "walnut")                     # rounded tip
# rounded trigger guard and two triggers
box((7.0, 4.2, 8.2), (9.0, 5.0, 12.6), "blued")
box((7.05, 4.8, 7.6), (8.95, 7.6, 8.4), "blued")
box((7.0, 4.4, 7.8), (9.0, 5.4, 9.0), "blued", rot=("x", 45, (8, 5.0, 8.4)))
box((7.0, 4.4, 12.0), (9.0, 5.4, 13.2), "blued", rot=("x", -45, (8, 5.0, 12.6)))
box((7.5, 5.2, 9.2), (8.5, 7.6, 10.0), "gold", rot=("x", 22.5, (8, 7.2, 9.6)))      # front trigger
box((7.5, 5.2, 10.8), (8.5, 7.6, 11.6), "gold", rot=("x", 22.5, (8, 7.2, 11.2)))    # back trigger
# stock: a checkered wrist dropping to a pistol grip, then a figured butt with a cheekpiece and a recoil pad
WR = ("x", 22.5, (8, 11.0, 14.0))
box((6.0, 6.6, 14.0), (10.0, 11.2, 20.0), "checkered", rot=WR)         # wrist
PG = ("x", -22.5, (8, 7.0, 18.0))
box((6.3, 1.6, 16.2), (9.7, 7.4, 19.8), "checkered", rot=PG)           # pistol grip
box((6.1, 1.0, 16.0), (9.9, 1.6, 20.0), "dark", rot=PG)                # grip cap
box((5.8, 4.6, 19.2), (10.2, 9.8, 29.6), "walnut")                     # butt
box((6.1, 9.8, 20.4), (9.9, 10.5, 29.6), "walnut")                     # rounded comb
BELLY = ("x", 22.5, (8, 5.0, 19.4))
box((6.0, 1.2, 19.4), (10.0, 9.0, 30.4), "walnut", rot=BELLY)          # underside sloping down to the toe
box((5.3, 5.4, 21.4), (5.8, 9.2, 28.2), "walnut")                      # cheekpiece (left side)
box((5.6, -2.8, 29.6), (10.4, 10.7, 31.0), "rubber")                   # recoil pad
box((7.6, 0.4, 25.4), (8.4, 1.2, 26.2), "polished", rot=BELLY)         # sling swivel
SHOTGUN = elements

# ---------------- maths for preview + auto-centring ----------------
def rot_axis(v, axis, deg, origin):
    a = math.radians(deg); c, s = math.cos(a), math.sin(a)
    x, y, z = (v[i] - origin[i] for i in range(3))
    if axis == "x": y, z = y * c - z * s, y * s + z * c
    elif axis == "y": x, z = x * c + z * s, -x * s + z * c
    else: x, y = x * c - y * s, x * s + y * c
    return (x + origin[0], y + origin[1], z + origin[2])
def elem_corners(e):
    f, t = e["from"], e["to"]
    pts = [(x, y, z) for x in (f[0], t[0]) for y in (f[1], t[1]) for z in (f[2], t[2])]
    if "rotation" in e:
        r = e["rotation"]; pts = [rot_axis(p, r["axis"], r["angle"], r["origin"]) for p in pts]
    return pts
def middle(els):
    allp = [p for e in els for p in elem_corners(e)]
    lo = [min(p[i] for p in allp) for i in range(3)]; hi = [max(p[i] for p in allp) for i in range(3)]
    return [(lo[i] + hi[i]) / 2 for i in range(3)]

def display_rotate(v, rot):   # Minecraft applies display rotations as R = Rx * Ry * Rz (z first)
    for ax, d in zip("zyx", rot[::-1]): v = rot_axis(v, ax, d, (0, 0, 0))
    return v
def centred(els, rot, scale, nudge=(0, 0, 0)):
    """Display entry that puts the model's middle on the slot's middle, then nudges it (model units)."""
    c = middle(els)
    off = display_rotate(tuple(c[i] - 8 for i in range(3)), rot)
    return {"rotation": list(rot), "translation": [round(-scale * off[i] + nudge[i], 3) for i in range(3)],
            "scale": [scale] * 3}

# How the gun sits. Big on purpose: the gun is meant to look comically oversized.
GUN_DISPLAY = {
    "gui":                   centred(GUN, (0, 90, 0), 0.52),
    "ground":                centred(GUN, (0, 90, 0), 0.34),
    "fixed":                 centred(GUN, (0, 90, 0), 0.55),          # item frames
    "head":                  centred(GUN, (0, 0, 0), 0.6, (0, 8, 0)),
    "firstperson_righthand": centred(GUN, (0, 0, 0), 0.62, (4, -1, -6)),
    "firstperson_lefthand":  centred(GUN, (0, 0, 0), 0.62, (4, -1, -6)),
    "thirdperson_righthand": centred(GUN, (0, 0, 0), 0.62, (0, 3, -3)),
    "thirdperson_lefthand":  centred(GUN, (0, 0, 0), 0.62, (0, 3, -3)),
}
# In hand, a model's -z (north) points away from the player, so the guns (built barrel to -z) need no turn.
TOMMY_DISPLAY = {
    "gui":                   centred(TOMMY, (0, 90, 0), 0.33),
    "ground":                centred(TOMMY, (0, 90, 0), 0.26),
    "fixed":                 centred(TOMMY, (0, 90, 0), 0.36),
    "head":                  centred(TOMMY, (0, 0, 0), 0.4, (0, 8, 0)),
    "firstperson_righthand": centred(TOMMY, (0, 0, 0), 0.5, (3, -1, -4)),
    "firstperson_lefthand":  centred(TOMMY, (0, 0, 0), 0.5, (3, -1, -4)),
    "thirdperson_righthand": centred(TOMMY, (0, 0, 0), 0.5, (0, 3, -1)),
    "thirdperson_lefthand":  centred(TOMMY, (0, 0, 0), 0.5, (0, 3, -1)),
}
SHOTGUN_DISPLAY = {
    "gui":                   centred(SHOTGUN, (0, 90, 0), 0.33),
    "ground":                centred(SHOTGUN, (0, 90, 0), 0.26),
    "fixed":                 centred(SHOTGUN, (0, 90, 0), 0.36),
    "head":                  centred(SHOTGUN, (0, 0, 0), 0.4, (0, 8, 0)),
    "firstperson_righthand": centred(SHOTGUN, (0, 0, 0), 0.5, (3, -1, -4)),
    "firstperson_lefthand":  centred(SHOTGUN, (0, 0, 0), 0.5, (3, -1, -4)),
    "thirdperson_righthand": centred(SHOTGUN, (0, 0, 0), 0.5, (0, 3, -1)),
    "thirdperson_lefthand":  centred(SHOTGUN, (0, 0, 0), 0.5, (0, 3, -1)),
}
# The bat is held like a sword: these are vanilla's handheld transforms, turned 45 degrees further because the
# bat model stands upright where a sword sprite runs corner to corner.
BAT_DISPLAY = {
    "gui":                   centred(BAT, (0, 0, -45), 0.62),
    "ground":                centred(BAT, (0, 0, 0), 0.4),
    "fixed":                 centred(BAT, (0, 0, -45), 0.68),
    "head":                  centred(BAT, (0, 180, 0), 0.7, (0, 10, 0)),
    "thirdperson_righthand": {"rotation": [0, -90, 10], "translation": [0, 7.5, 0.5], "scale": [0.75] * 3},
    "thirdperson_lefthand":  {"rotation": [0, 90, -10], "translation": [0, 7.5, 0.5], "scale": [0.75] * 3},
    "firstperson_righthand": {"rotation": [0, -90, -20], "translation": [1.13, 5.5, 1.13], "scale": [0.62] * 3},
    "firstperson_lefthand":  {"rotation": [0, 90, 20], "translation": [1.13, 5.5, 1.13], "scale": [0.62] * 3},
}

def write_item(name, els, tex, display, particle):
    model = {"textures": {**{k: f"{NS}:item/{name}/{k}" for k in tex}, "particle": f"{NS}:item/{name}/{particle}"},
             "gui_light": "side", "elements": els, "display": display}
    wjson(path("assets", NS, "models", "item", name + ".json"), model)
    wjson(path("assets", NS, "items", name + ".json"), {"model": {"type": "minecraft:model", "model": f"{NS}:item/{name}"}})
write_item("hand_cannon", GUN, TEX, GUN_DISPLAY, "frame")
write_item("nail_bat", BAT, BAT_TEX, BAT_DISPLAY, "wood")
write_item("tommy_gun", TOMMY, TOMMY_TEX, TOMMY_DISPLAY, "steel")
write_item("shotgun", SHOTGUN, SG_TEX, SHOTGUN_DISPLAY, "blued")
# pack.mcmeta: resource pack format 88 = Minecraft 26.2
wjson(path("pack.mcmeta"), {"pack": {"description": "HandCannon weapons", "min_format": [88, 0], "max_format": [99, 0]}})

zpath = OUT.rstrip("/") + ".zip"
with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
    for root, _, files in os.walk(OUT):
        for f in files:
            full = os.path.join(root, f); z.write(full, os.path.relpath(full, OUT))
print("zip:", zpath, "sha1:", hashlib.sha1(open(zpath, "rb").read()).hexdigest())

# ---------------- preview.png: textured orthographic renders, one row per item ----------------
# corners in texture order (top-left, top-right, bottom-right, bottom-left) as Minecraft maps face UVs
FACE_IDX = {"north": (5, 4, 0, 1), "south": (6, 7, 3, 2), "east": (7, 5, 1, 3), "west": (4, 6, 2, 0),
            "up": (4, 5, 7, 6), "down": (2, 3, 1, 0)}
def face_quads(e):
    f, t = e["from"], e["to"]
    c = [(x, y, z) for y in (f[1], t[1]) for z in (f[2], t[2]) for x in (f[0], t[0])]   # index: bit0 x, bit1 z, bit2 y
    if "rotation" in e:
        r = e["rotation"]; c = [rot_axis(p, r["axis"], r["angle"], r["origin"]) for p in c]
    for name, idx in FACE_IDX.items():
        yield name, [c[i] for i in idx], e["faces"][name]["texture"][1:], e["faces"][name]["uv"]
def render(els, tex, yaw, pitch, roll=0, size=420, pad=30):
    centre = middle(els)
    def view(p):
        p = rot_axis(p, "z", roll, centre); p = rot_axis(p, "y", yaw, centre); return rot_axis(p, "x", pitch, centre)
    quads = []
    light = (0.35, 0.8, 0.5); ln = math.sqrt(sum(v * v for v in light)); light = tuple(v / ln for v in light)
    N = 6
    def lerp(a, b, t): return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))
    for e in els:
        for name, pts, tname, uv in face_quads(e):
            v = [view(p) for p in pts]
            a = [v[1][i] - v[0][i] for i in range(3)]; b = [v[2][i] - v[0][i] for i in range(3)]
            n = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
            nl = math.sqrt(sum(x * x for x in n)) or 1; n = tuple(-x / nl for x in n)   # outward normal
            if n[2] <= 0: continue   # facing away (camera looks down -z from +z)
            sh = 0.5 + 0.5 * max(0, sum(n[i] * light[i] for i in range(3)))
            im = tex[tname].load()
            depth = sum(p[2] for p in v) / 4
            for i in range(N):
                for j in range(N):
                    def at(u, w): return lerp(lerp(v[0], v[1], u), lerp(v[3], v[2], u), w)
                    cell = [at(i / N, j / N), at((i + 1) / N, j / N), at((i + 1) / N, (j + 1) / N), at(i / N, (j + 1) / N)]
                    tx = int(uv[0] + (uv[2] - uv[0]) * (i + 0.5) / N) % 16; ty = int(uv[1] + (uv[3] - uv[1]) * (j + 0.5) / N) % 16
                    quads.append((depth, cell, tuple(clamp(c * sh * 1.1) for c in im[tx, ty][:3])))
    xs = [p[0] for q in quads for p in q[1]]; ys = [p[1] for q in quads for p in q[1]]
    s = (size - 2 * pad) / max(max(xs) - min(xs), max(ys) - min(ys))
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    im = Image.new("RGBA", (size, size), (38, 40, 46, 255)); d = ImageDraw.Draw(im)
    for _, v, col in sorted(quads, key=lambda q: q[0]):
        d.polygon([(size / 2 + (p[0] - cx) * s, size / 2 - (p[1] - cy) * s) for p in v], fill=col + (255,), outline=col + (255,))
    return im
rows = [[render(GUN, TEX, -90, 0), render(GUN, TEX, -130, 18), render(GUN, TEX, 180, 8), render(GUN, TEX, 0, 0)],
        [render(TOMMY, TOMMY_TEX, -90, 0), render(TOMMY, TOMMY_TEX, -130, 18), render(TOMMY, TOMMY_TEX, 180, 8), render(TOMMY, TOMMY_TEX, -60, -15)],
        [render(SHOTGUN, SG_TEX, -90, 0), render(SHOTGUN, SG_TEX, -130, 18), render(SHOTGUN, SG_TEX, 180, 8), render(SHOTGUN, SG_TEX, -60, -15)],
        [render(BAT, BAT_TEX, 0, 0, -90), render(BAT, BAT_TEX, 30, 20, -90), render(BAT, BAT_TEX, 0, 90), render(BAT, BAT_TEX, 0, 0, -45)]]
pv = Image.new("RGBA", (420 * 4, 420 * len(rows)))
for r, row in enumerate(rows):
    for i, v in enumerate(row): pv.paste(v, (420 * i, 420 * r))
pv.save("preview.png"); print("preview.png written")
