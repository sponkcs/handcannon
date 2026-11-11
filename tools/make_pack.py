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
# A side-by-side double modelled on a fine English sidelock (blued barrels, case-hardened action, figured walnut,
# cheekpiece, black recoil pad), with cartoon proportions: fat barrels, chunky everything, no gold trim, and the
# stock sawn off behind the pistol grip.
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
SG_TEX = {"blued": tex_metal((30, 34, 48), 5), "case": tex_case(),
          "orange": flat((255, 110, 30), 6), "bore": tex_bore(), "dark": flat((22, 22, 26)),
          "polished": tex_metal((176, 180, 188), 5), "walnut": tex_figured((112, 58, 30)),
          "checkered": tex_checkered((112, 58, 30)), "rubber": flat((26, 26, 28), 3)}
for k, im in SG_TEX.items(): im.save(path("assets", NS, "textures", "item", "shotgun", k + ".png"))

elements = []
# two fat barrels side by side, a flat rib on top with an orange bead and a little rear sight
for bx in (6.3, 9.7):
    round_prism(bx, 11.0, 3.4, -14.0, 4.6, "blued")
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
# top lever on the tang
box((7.3, 12.6, 10.0), (8.7, 13.4, 13.6), "case")
box((6.8, 12.8, 12.6), (9.2, 13.8, 14.2), "case")                      # thumbpiece
# splinter forend under the barrels, checkered on the sides
box((5.4, 7.4, -6.0), (10.6, 9.8, 4.6), "walnut", {"east": "checkered", "west": "checkered"})
box((5.8, 7.8, -7.2), (10.2, 9.6, -6.0), "walnut")                     # rounded tip
# rounded trigger guard and a single trigger
box((7.0, 4.2, 8.2), (9.0, 5.0, 12.6), "blued")
box((7.05, 4.8, 7.6), (8.95, 7.6, 8.4), "blued")
box((7.0, 4.4, 7.8), (9.0, 5.4, 9.0), "blued", rot=("x", 45, (8, 5.0, 8.4)))
box((7.0, 4.4, 12.0), (9.0, 5.4, 13.2), "blued", rot=("x", -45, (8, 5.0, 12.6)))
box((7.5, 5.2, 10.0), (8.5, 7.6, 10.8), "polished", rot=("x", 22.5, (8, 7.2, 10.4)))  # single trigger
# sawed off: the stock is cut away just behind the pistol grip, leaving a short checkered wrist
box((6.2, 7.0, 14.0), (9.8, 11.3, 18.2), "checkered")                  # wrist
box((6.4, 7.4, 18.2), (9.6, 10.9, 18.6), "walnut")                     # sawn end
PG = ("x", -22.5, (8, 7.2, 17.0))
box((6.4, 1.6, 15.4), (9.6, 7.4, 18.8), "checkered", rot=PG)           # pistol grip
box((6.2, 1.0, 15.2), (9.8, 1.6, 19.0), "dark", rot=PG)                # grip cap
SHOTGUN = elements

# ---------------- geometry: pala-pistol ----------------
# A retro energy pistol: dark red body, a glowing yellow core in an open cage, coil rings, hoses arching over the
# top, a copper capacitor and a needle emitter with prongs. Barrel toward north (-z) like the other guns.
def tex_banded(base, every=3, f=0.75, vertical=False):
    """Windings / ribs: darker lines every few pixels."""
    im = tex_metal(base, 0, edge=False); px = im.load()
    for y in range(16):
        for x in range(16):
            if ((y if vertical else x) % every) == 0: px[x, y] = shade(base, f)
    return im
def tex_glow():
    im = Image.new("RGBA", (16, 16)); px = im.load()
    for y in range(16):
        for x in range(16):
            c = 1.0 - 0.12 * abs(y - 7.5) / 7.5
            px[x, y] = (255, clamp(236 * c + 10), clamp(90 * c), 255)
    return im
def tex_grip():
    im = tex_metal((44, 40, 42), 0, edge=False); px = im.load()
    for y in range(2, 14, 3):
        for x in range(16): px[x, y] = shade((44, 40, 42), 0.7)
    return im
PALA_TEX = {"body": tex_metal((122, 24, 30)), "body_dark": tex_metal((86, 16, 22), 0, edge=False),
            "glow": tex_glow(), "coil": tex_banded((64, 66, 72), 2, 0.7), "copper": tex_banded((178, 98, 52), 3, 0.8),
            "hose": tex_banded((36, 36, 38), 2, 0.75), "metal": tex_metal((156, 160, 168)), "grip": tex_grip(),
            "dark": flat((22, 22, 26)), "gold": tex_metal((226, 180, 64))}
for k, im in PALA_TEX.items(): im.save(path("assets", NS, "textures", "item", "pala_pistol", k + ".png"))

elements = []
# rear housing, rounded on top and at the back, with a glowing indicator light on each side
box((5.6, 8.0, 3.0), (10.4, 13.4, 12.0), "body")
box((6.0, 13.4, 4.0), (10.0, 14.3, 11.0), "body")
box((6.0, 8.6, 12.0), (10.0, 12.8, 13.0), "body")
box((5.35, 9.4, 7.6), (5.62, 11.8, 10.0), "glow")                     # indicator light (left)
box((10.38, 9.4, 7.6), (10.65, 11.8, 10.0), "glow")                   # indicator light (right)
box((5.45, 9.0, 7.2), (5.6, 12.2, 10.4), "dark")                     # light bezels
box((10.4, 9.0, 7.2), (10.55, 12.2, 10.4), "dark")
# maker's mark: a small raised gold ankh on the left of the housing, in front of the indicator light
AX0, AX1 = 5.45, 5.62
box((AX0, 8.7, 4.95), (AX1, 11.0, 5.45), "gold")                     # stem
box((AX0, 11.0, 4.25), (AX1, 11.5, 6.15), "gold")                    # crossbar
box((AX0, 11.5, 4.6), (AX1 - 0.01, 12.7, 5.0), "gold")               # loop: front side
box((AX0, 11.5, 5.4), (AX1 - 0.01, 12.7, 5.8), "gold")               # loop: back side
box((AX0, 12.7, 4.85), (AX1 - 0.02, 13.1, 5.55), "gold")             # loop: top
# the glowing core inside an open cage
round_prism(8, 10.8, 2.8, -8.0, 3.2, "glow")
for x0, y0 in ((5.9, 12.7), (9.5, 12.7), (5.9, 8.3), (9.5, 8.3)):    # cage bars
    box((x0, y0, -8.0), (x0 + 0.6, y0 + 0.6, 3.0), "body_dark")
box((7.0, 7.3, -8.0), (9.0, 8.3, 3.0), "body")                       # spine under the cage
# coil rings round the back of the core, and a ring holding the front of the cage
for z in (1.2, -0.4, -2.0):
    round_prism(8, 10.8, 6.0, z, z + 0.8, "coil")
round_prism(8, 10.8, 6.0, -8.8, -7.8, "body")
# two hoses arching over the top, from the housing to the front ring
for hx in (6.6, 8.6):
    box((hx, 13.4, 3.1), (hx + 0.8, 15.9, 3.9), "hose")
    box((hx, 15.1, -5.6), (hx + 0.8, 15.9, 3.1), "hose")
    box((hx, 13.4, -6.4), (hx + 0.8, 15.9, -5.6), "hose")
# copper capacitor, front cap and the needle emitter with four prongs
round_prism(8, 10.8, 4.6, -12.0, -8.8, "copper")
round_prism(8, 10.8, 3.2, -13.0, -12.0, "body")
box((7.6, 10.4, -16.0), (8.4, 11.2, -13.0), "metal")                 # needle
box((7.75, 10.55, -16.4), (8.25, 11.05, -16.0), "glow")              # glowing tip
for dx, dy in ((-2.0, 0), (2.0, 0), (0, -2.0), (0, 2.0)):           # prongs
    box((8 + dx - 0.2, 10.8 + dy - 0.2, -15.0), (8 + dx + 0.2, 10.8 + dy + 0.2, -12.0), "metal")
# trigger and a raked-back grip with finger grooves
box((7.5, 5.8, 3.8), (8.5, 8.0, 4.6), "metal", rot=("x", 22.5, (8, 7.6, 4.2)))
PG = ("x", -22.5, (8, 8.0, 9.0))
box((6.2, 0.4, 6.6), (9.8, 8.1, 11.0), "grip", rot=PG)
box((5.9, 0.8, 7.1), (10.1, 7.6, 10.5), "grip", rot=PG)              # rounded sides
for y in (5.8, 4.0, 2.2):                                            # finger ridges
    box((6.5, y, 6.1), (9.5, y + 0.8, 6.6), "grip", rot=PG)
box((5.8, -0.4, 6.4), (10.2, 0.4, 11.2), "body", rot=PG)             # flared base
for e in elements:   # the yellow parts glow in the dark
    if any(f["texture"] == "#glow" for f in e["faces"].values()): e["light_emission"] = 15
PALA = elements

# ---------------- geometry: goo cannon ----------------
# Worn nozzle and steel tube up front with a vertical grip, a valve box on top, a navy rear section with a pistol
# grip and bar trigger, a pressure gauge facing the user, and a tilted canister of clear glass full of goo. The goo uses Minecraft's own honey block
# texture (pointed at directly, so nothing is copied); "fluid" below is only a stand-in for preview.png.
def tex_glass():
    im = Image.new("RGBA", (16, 16)); px = im.load()
    for y in range(16):
        for x in range(16):
            a = 70
            if x in (0, 15) or y in (0, 15): a = 150                 # rim
            if x in (3, 4): a = 125                                  # highlight streak
            px[x, y] = (226, 240, 248, a)
    return im
def tex_ribbed(base):
    im = tex_metal(base, 0, edge=False); px = im.load()
    for y in range(0, 16, 3):
        for x in range(16): px[x, y] = shade(base, 0.7)
    return im
def tex_honey_standin():
    im = Image.new("RGBA", (16, 16)); px = im.load()
    for y in range(16):
        for x in range(16):
            px[x, y] = (236, 168, 40, 255) if (x * 7 + y * 3) % 11 else (250, 206, 92, 255)
    return im
def tex_gauge():
    """Decorative pressure gauge, drawn big and scaled to 64x64 (four times the usual detail): chrome rim with
    screws, cream dial with a green / yellow / red pressure band, ticks, a PSI label, a red needle well into the
    yellow (pressure building), a hub and a glint on the glass. Outside the rim is see-through."""
    from PIL import ImageFont
    S = 256; c = S / 2
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    def pt(deg, r):   # deg 0 = straight up, clockwise
        a = math.radians(deg - 90); return (c + math.cos(a) * r, c + math.sin(a) * r)
    d.ellipse((2, 2, S - 3, S - 3), fill=(120, 124, 132, 255))                    # chrome rim
    d.ellipse((8, 8, S - 9, S - 9), fill=(196, 200, 208, 255))
    d.ellipse((18, 18, S - 19, S - 19), fill=(60, 62, 68, 255))
    for deg in (45, 135, 225, 315):                                               # rim screws
        x, y = pt(deg, S / 2 - 12); d.ellipse((x - 5, y - 5, x + 5, y + 5), fill=(88, 90, 96, 255))
        d.line((x - 3, y - 3, x + 3, y + 3), fill=(40, 40, 44, 255), width=2)
    d.ellipse((24, 24, S - 25, S - 25), fill=(244, 238, 222, 255))                # dial face
    START, SWEEP = -135, 270                                                      # 0..100 % runs over 270 degrees
    def arc(p0, p1, col):
        box_ = (40, 40, S - 41, S - 41)
        d.arc(box_, START + SWEEP * p0 - 90, START + SWEEP * p1 - 90, fill=col, width=14)
    arc(0.0, 0.6, (70, 170, 80, 255)); arc(0.6, 0.85, (236, 196, 40, 255)); arc(0.85, 1.0, (214, 46, 40, 255))
    for i in range(51):                                                           # ticks: major every 10 %
        deg = START + SWEEP * i / 50
        major = i % 5 == 0
        d.line((*pt(deg, 64 if major else 72), *pt(deg, 84)), fill=(34, 34, 38, 255), width=5 if major else 2)
    try: font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 30)
    except Exception: font = ImageFont.load_default()
    d.text((c, c + 52), "PSI", fill=(34, 34, 38, 255), font=font, anchor="mm")
    needle = START + SWEEP * 0.78                                                 # pressure building
    tip, tail = pt(needle, 80), pt(needle + 180, 18)
    left, right = pt(needle - 90, 11), pt(needle + 90, 11)
    d.polygon([tip, left, tail, right], fill=(206, 28, 28, 255))
    d.ellipse((c - 14, c - 14, c + 14, c + 14), fill=(40, 40, 44, 255))          # hub
    d.ellipse((c - 6, c - 6, c + 6, c + 6), fill=(150, 154, 162, 255))
    glare = Image.new("RGBA", (S, S), (0, 0, 0, 0)); g = ImageDraw.Draw(glare)    # glint on the glass
    g.arc((40, 40, S - 41, S - 41), 200, 250, fill=(255, 255, 255, 110), width=18)
    im = Image.alpha_composite(im, glare)
    return im.resize((64, 64), Image.LANCZOS)
GOO_TEX = {"steel": tex_metal((178, 182, 190)), "gauge": tex_gauge(), "nozzle": tex_metal((176, 168, 132)), "navy": tex_metal((38, 46, 70)),
           "rubber": tex_ribbed((34, 34, 38)), "glass": tex_glass(), "bore": tex_bore(), "dark": flat((22, 22, 26))}
for k, im in GOO_TEX.items(): im.save(path("assets", NS, "textures", "item", "goo_cannon", k + ".png"))
GOO_PREVIEW_TEX = dict(GOO_TEX, fluid=tex_honey_standin())
FULL_UV.add("gauge")
GOO_TEX_PATHS = {"fluid": "minecraft:block/honey_block_side"}

elements = []
# nozzle, collar with a knob, steel front tube
round_prism(8, 11.0, 4.6, -15.0, -12.0, "nozzle")
box((6.6, 9.6, -15.32), (9.4, 12.4, -15.22), "bore")                  # outlet
round_prism(8, 11.0, 4.0, -12.0, -9.6, "steel")
box((7.4, 12.9, -11.2), (8.6, 14.4, -10.2), "steel")                  # knob
box((7.2, 14.4, -11.4), (8.8, 14.9, -10.0), "dark")
round_prism(8, 11.0, 3.4, -9.6, 1.0, "steel")
# valve box on top, then a steel ring and the navy rear section with a rounded end
box((6.2, 12.4, -1.4), (9.8, 16.6, 2.6), "steel")                     # one solid valve box
# pressure gauge on the back of the valve box, facing the user: a steel bezel with the dial in front of it
round_prism(8, 14.66, 3.8, 2.6, 3.2, "steel")
box((6.2, 12.9, 3.3), (9.8, 16.5, 3.4), "dark", {"south": "gauge"})
round_prism(8, 11.0, 4.8, 0.6, 1.4, "steel")
round_prism(8, 11.0, 4.4, 1.0, 13.4, "navy")
round_prism(8, 11.0, 3.6, 13.4, 14.2, "navy")
# front vertical grip hanging from the collar
box((7.6, 4.6, -11.2), (8.4, 9.2, -10.4), "steel")                    # rod
box((5.8, 4.0, -12.6), (10.2, 4.6, -9.0), "rubber")                   # guard flange
box((6.8, -3.0, -12.0), (9.2, 4.0, -9.6), "rubber")                   # handle
box((6.0, -3.6, -12.6), (10.0, -3.0, -9.0), "rubber")                 # end flange
# the canister: tilted back, clear glass, goo inside (filled most of the way), steel caps and two straps
box((7.2, 5.6, -0.6), (8.8, 9.4, 1.0), "steel", rot=("x", -22.5, (8, 9.0, 0.2)))   # neck
CAN = ("x", -22.5, (8, 6.0, 0.4))
box((5.0, 5.4, -2.6), (11.0, 6.4, 3.4), "steel", rot=CAN)             # top cap
box((5.6, -5.5, -1.0), (10.4, 2.8, 1.8), "fluid", rot=CAN)            # goo
box((6.6, -5.46, -2.0), (9.4, 2.84, 2.8), "fluid", rot=CAN)
box((5.2, -5.6, -2.4), (10.8, 5.4, 3.2), "glass", rot=CAN)            # glass
box((5.0, -6.6, -2.6), (11.0, -5.6, 3.4), "steel", rot=CAN)           # bottom cap
for y0 in (0.6, -3.4):                                                # straps round the glass
    box((5.05, y0, -2.4), (5.2, y0 + 0.6, 3.2), "dark", rot=CAN)
    box((10.8, y0, -2.4), (10.95, y0 + 0.6, 3.2), "dark", rot=CAN)
    box((5.05, y0, -2.55), (10.95, y0 + 0.6, -2.4), "dark", rot=CAN)
    box((5.05, y0, 3.2), (10.95, y0 + 0.6, 3.35), "dark", rot=CAN)
# bar trigger, a looping guard and the pistol grip
box((6.8, 7.8, 3.8), (9.2, 8.8, 5.6), "rubber")                       # trigger mount
box((7.6, 3.6, 4.4), (8.4, 7.8, 5.0), "steel")                        # trigger bar
box((7.4, 3.0, 4.2), (8.6, 3.6, 6.6), "steel")                        # trigger foot
box((7.3, 2.2, 2.2), (8.7, 8.8, 2.8), "rubber", rot=("x", -22.5, (8, 8.8, 2.5)))  # guard, sloping back
box((7.3, 1.6, 4.6), (8.7, 2.2, 8.6), "rubber")                       # guard bottom
PG = ("x", -22.5, (8, 8.6, 9.0))
box((6.4, 1.0, 7.2), (9.6, 8.8, 10.8), "rubber", rot=PG)
box((6.1, 1.4, 7.7), (9.9, 8.4, 10.3), "rubber", rot=PG)
box((6.0, 0.4, 7.0), (10.0, 1.0, 11.0), "rubber", rot=PG)
GOO = elements

# ---------------- geometry: corruption cannon (files keep the old name, umbral_lance) ----------------
# An ominous darkness weapon: a long tapering spike of glowing red crystal, shards bursting out of it, set in a
# black, thorned receiver with a
# red gem each side and a tall fin carrying a red rune, a long stock rising to a flared tail, a tall blade-like
# front grip with a red inlay and a raked rear grip. Barrel toward north (-z) like the other guns.
def tex_crystal():
    im = Image.new("RGBA", (16, 16)); px = im.load()
    for y in range(16):
        for x in range(16):
            k = (x + y) % 8
            c = (236, 70, 82) if k == 0 else (214, 40, 54) if k in (1, 7) else (170, 18, 34) if k < 5 else (124, 10, 24)
            px[x, y] = c + (255,)
    return im
def tex_rune():
    """Black plate with an original red sigil: a downward triangle with an eye-ring and a spike through it."""
    S = 64; im = Image.new("RGBA", (S, S), (26, 24, 30, 255)); d = ImageDraw.Draw(im)
    red = (220, 34, 48, 255)
    d.polygon([(10, 12), (54, 12), (32, 54)], outline=red, width=3)
    d.ellipse((24, 18, 40, 34), outline=red, width=3)
    d.ellipse((30, 24, 34, 28), fill=red)
    d.line((32, 4, 32, 60), fill=red, width=2)
    return im
UMB_TEX = {"black": tex_metal((26, 24, 30)), "black_soft": tex_metal((44, 40, 50), 0, edge=False),
           "crystal": tex_crystal(), "rune": tex_rune()}
for k, im in UMB_TEX.items(): im.save(path("assets", NS, "textures", "item", "umbral_lance", k + ".png"))
FULL_UV.add("rune")

elements = []
# the crystal spike: stepped round sections tapering to a point, and a black collar where it meets the receiver
for z0, z1, dia in ((-16.0, -13.5, 0.8), (-13.5, -11.0, 1.4), (-11.0, -8.0, 2.0), (-8.0, -5.0, 2.6), (-5.0, -2.0, 3.2), (-2.0, 0.6, 3.8)):
    round_prism(8, 11.0, dia, z0, z1, "crystal")
round_prism(8, 11.0, 4.7, 0.3, 1.5, "black")
# crystal shards bursting outward along the spike: a thick base and a thinner tip, raked toward the muzzle
def spike_radius(z):
    for z0, z1, dia in ((-16.0, -13.5, 0.8), (-13.5, -11.0, 1.4), (-11.0, -8.0, 2.0), (-8.0, -5.0, 2.6), (-5.0, -2.0, 3.2), (-2.0, 0.6, 3.8)):
        if z0 <= z < z1: return dia / 2
    return 1.9
def shard(z, way, length):
    # each shard starts a little inside the crystal so it looks embedded
    for w_, l_, a_ in ((0.34, 0.65, 0.0), (0.17, 1.0, 0.05)):   # base then tip (tip nudged so faces never coincide)
        r = spike_radius(z) - 0.3 + a_
        L = length * l_; c0, c1 = z - w_ + a_, z + w_ + a_
        if way in ("up", "ur", "ul"):
            frm, to = (8 - w_ + a_, 11 + r, c0), (8 + w_ + a_, 11 + r + L, c1)
        elif way in ("down", "dr", "dl"):
            frm, to = (8 - w_ + a_, 11 - r - L, c0), (8 + w_ + a_, 11 - r, c1)
        elif way == "left":
            frm, to = (8 - r - L, 11 - w_ + a_, c0), (8 - r, 11 + w_ + a_, c1)
        else:   # right
            frm, to = (8 + r, 11 - w_ + a_, c0), (8 + r + L, 11 + w_ + a_, c1)
        rot = {"up": ("x", -22.5, (8, 11, z)), "down": ("x", 22.5, (8, 11, z)),
               "left": ("y", -22.5, (8, 11, z)), "right": ("y", 22.5, (8, 11, z)),
               "ur": ("z", -45, (8, 11, z)), "ul": ("z", 45, (8, 11, z)),
               "dr": ("z", 45, (8, 11, z)), "dl": ("z", -45, (8, 11, z))}[way]
        box(frm, to, "crystal", rot=rot)
for z, way, length in ((-12.2, "up", 1.6), (-10.6, "left", 2.0), (-9.6, "down", 2.2), (-8.7, "right", 2.4),
                       (-7.4, "up", 2.8), (-6.6, "ul", 2.2), (-6.0, "ur", 2.0), (-5.5, "left", 2.8),
                       (-4.6, "down", 2.6), (-3.7, "dr", 2.4), (-3.0, "right", 3.0), (-2.3, "dl", 2.2),
                       (-1.4, "up", 2.4)):
    shard(z, way, length * 1.5)
# receiver, with thorns jutting forward and outward, and a red gem on each side
box((5.8, 8.6, 1.0), (10.2, 13.6, 9.0), "black")
for y0 in (12.2, 9.2):
    box((5.0, y0, -2.0), (5.6, y0 + 0.6, 2.4), "black", rot=("y", 22.5, (5.3, y0 + 0.3, 2.4)))      # left thorns
    box((10.4, y0, -2.0), (11.0, y0 + 0.6, 2.4), "black", rot=("y", -22.5, (10.7, y0 + 0.3, 2.4)))  # right thorns
for x0 in (6.8, 8.6):
    box((x0, 13.4, -2.0), (x0 + 0.6, 14.0, 2.4), "black", rot=("x", 22.5, (x0 + 0.3, 13.7, 2.4)))   # top thorns
box((5.3, 10.2, 4.4), (5.85, 11.4, 5.6), "crystal")                    # gems
box((10.15, 10.2, 4.4), (10.7, 11.4, 5.6), "crystal")
# tall fin with the rune on both faces, capped with a point
box((7.6, 13.6, 5.0), (8.4, 18.8, 8.6), "black", {"east": "rune", "west": "rune"})
box((7.62, 18.0, 5.9), (8.38, 19.8, 7.7), "black", rot=("x", 45, (8, 18.9, 6.8)))
# long stock: a flat body, then a section rising to a flared tail, with a lower plate
box((6.0, 10.6, 9.0), (10.0, 14.2, 20.0), "black")
RISE = ("x", -22.5, (8, 13.0, 19.0))
box((6.2, 11.4, 19.0), (9.8, 14.4, 28.0), "black", rot=RISE)
box((5.4, 13.6, 25.6), (10.6, 15.2, 29.0), "black", rot=RISE)          # flared tail
box((6.4, 9.6, 9.1), (9.6, 10.8, 18.0), "black_soft")                  # lower plate
# tall blade-like front grip with a red inlay down each side
box((6.8, -9.0, 4.6), (9.2, 8.8, 7.4), "black")
box((6.7, -7.0, 5.0), (9.3, 6.0, 5.3), "crystal")
# trigger and the raked rear grip, with a red knob at its top
box((7.6, 7.8, 13.4), (8.4, 9.6, 14.0), "black_soft")
GR = ("x", -22.5, (8, 10.0, 17.3))
box((6.6, 1.0, 16.0), (9.4, 10.0, 18.6), "black", rot=GR)
box((6.4, 0.2, 15.6), (9.6, 1.0, 19.0), "black_soft", rot=GR)
box((7.4, 9.0, 14.6), (8.6, 10.0, 15.6), "crystal")
for e in elements:   # the crystal glows faintly in the dark
    if any(f["texture"] == "#crystal" for f in e["faces"].values()): e["light_emission"] = 10
UMBRAL = elements

# ---------------- geometry: radiant ankh (sword) ----------------
# A sword whose handle and hilt are an ankh: the stem is the grip, the crossbar is the guard, and the loop holds a
# pane of light; the blade rises from the top of the loop. Its edges carry radiant light. Two textures are animated
# (a strip of frames plus a .mcmeta file): the edge light dims and brightens and a gleam sweeps along the steel.
def frames_strip(draw_frame, n):
    strip = Image.new("RGBA", (16, 16 * n))
    for i in range(n): strip.paste(draw_frame(i, n), (0, 16 * i))
    return strip
def radiance_frame(i, n):
    """The edge light breathing: the whole strip dims and brightens together over the loop of frames."""
    level = 0.5 + 0.5 * math.sin(2 * math.pi * i / n)          # 0 = dimmest, 1 = brightest
    im = Image.new("RGBA", (16, 16)); px = im.load()
    for y in range(16):
        for x in range(16):
            core = 1 - abs(x - 7.5) / 8
            v = 0.45 + 0.45 * level + 0.1 * core
            px[x, y] = (clamp(200 + 55 * v), clamp(150 + 95 * v), clamp(40 + 200 * v * level), 255)
    return im
def blade_frame(i, n):
    im = Image.new("RGBA", (16, 16)); px = im.load()
    for y in range(16):
        for x in range(16):
            c = (206, 212, 222)
            if x in (7, 8): c = (168, 174, 188)                            # fuller down the middle
            g = (x + (15 - y)) - (i * 32 / n) + 8                          # diagonal gleam sweeping across
            if abs(g) < 2.2: c = tuple(min(255, v + 40) for v in c)
            px[x, y] = c + (255,)
    return im
def tex_ruby():
    """Cut ruby: deep red facets with lighter bevels and a bright glint."""
    im = Image.new("RGBA", (16, 16)); px = im.load()
    for y in range(16):
        for x in range(16):
            d = max(abs(x - 7.5), abs(y - 7.5))
            c = (120, 6, 22) if d > 6 else (186, 14, 38) if d > 3.5 else (214, 26, 52)
            if (x + y) % 6 == 0 and d <= 6: c = tuple(min(255, v + 30) for v in c)    # facet lines
            px[x, y] = c + (255,)
    for x, y in ((4, 4), (5, 4), (4, 5)): px[x, y] = (255, 180, 190, 255)          # glint
    return im
SWORD_TEX = {"gold": tex_metal((230, 186, 70)), "ruby": tex_ruby(), "grip": tex_banded((92, 54, 32), 3, 0.7, vertical=True),
             "blade": frames_strip(blade_frame, 16), "radiance": frames_strip(radiance_frame, 16)}
ANIMATED = {"blade": {"frametime": 3, "interpolate": True}, "radiance": {"frametime": 3, "interpolate": True}}
for k, im in SWORD_TEX.items():
    im.save(path("assets", NS, "textures", "item", "radiant_ankh", k + ".png"))
    if k in ANIMATED: wjson(path("assets", NS, "textures", "item", "radiant_ankh", k + ".png.mcmeta"), {"animation": ANIMATED[k]})
FULL_UV.update({"radiance"})

elements = []
H = -6.0   # the hilt sits this far down, leaving room for a longer blade (models can't go above y = 32)
def hb(frm, to, tex, faces_tex=None):   # a hilt box, lowered by H
    box((frm[0], frm[1] + H, frm[2]), (to[0], to[1] + H, to[2]), tex, faces_tex)
# the ankh: stem as the grip with a pommel, crossbar as the guard with flared ends
hb((7.0, -8.0, 7.2), (9.0, 1.0, 8.8), "grip")
hb((6.6, -9.0, 6.8), (9.4, -8.0, 9.2), "gold")                       # pommel
hb((3.0, 1.0, 7.0), (13.0, 2.6, 9.0), "gold")                        # crossbar
hb((2.4, 0.6, 6.9), (3.0, 3.0, 9.1), "gold")                         # flared ends
hb((13.0, 0.6, 6.9), (13.6, 3.0, 9.1), "gold")
# the loop, narrow where it meets the crossbar and round at the top
hb((6.6, 2.6, 7.1), (7.4, 3.6, 8.9), "gold")
hb((8.6, 2.6, 7.1), (9.4, 3.6, 8.9), "gold")
hb((5.8, 3.6, 7.1), (6.8, 5.4, 8.9), "gold")
hb((9.2, 3.6, 7.1), (10.2, 5.4, 8.9), "gold")
hb((5.2, 5.4, 7.1), (6.4, 8.2, 8.9), "gold")
hb((9.6, 5.4, 7.1), (10.8, 8.2, 8.9), "gold")
hb((5.8, 8.2, 7.1), (7.0, 9.2, 8.9), "gold")
hb((9.0, 8.2, 7.1), (10.2, 9.2, 8.9), "gold")
hb((6.6, 9.2, 7.1), (9.4, 10.0, 8.9), "gold")                        # top of the loop
hb((6.5, 3.65, 7.55), (9.5, 9.15, 8.45), "ruby")                     # a ruby set in the loop
hb((7.1, 4.6, 7.35), (8.9, 8.2, 8.65), "ruby")                       # its raised, cut table
# the blade: steel rising from the loop, tapering to a point
BASE = 10.0 + H
box((6.4, BASE, 7.6), (9.6, 26.0, 8.4), "blade")
box((6.9, 26.0, 7.62), (9.1, 28.5, 8.38), "blade")
box((7.4, 28.5, 7.64), (8.6, 30.4, 8.36), "blade")
box((7.8, 30.4, 7.66), (8.2, 31.4, 8.34), "blade")
# a thin line of radiant light down both edges and over the tip
box((6.05, BASE + 0.2, 7.55), (6.45, 26.03, 8.45), "radiance")
box((9.55, BASE + 0.2, 7.55), (9.95, 26.03, 8.45), "radiance")
box((6.55, 26.03, 7.57), (6.95, 28.53, 8.43), "radiance")
box((9.05, 26.03, 7.57), (9.45, 28.53, 8.43), "radiance")
box((7.05, 28.53, 7.59), (7.45, 30.43, 8.41), "radiance")
box((8.55, 28.53, 7.59), (8.95, 30.43, 8.41), "radiance")
box((7.45, 30.43, 7.61), (7.85, 31.43, 8.39), "radiance")
box((8.15, 30.43, 7.61), (8.55, 31.43, 8.39), "radiance")
box((7.7, 31.33, 7.63), (8.3, 32.0, 8.37), "radiance")                 # glowing point
for e in elements:
    if any(f["texture"] == "#radiance" for f in e["faces"].values()): e["light_emission"] = 15
SWORD = elements

# ---------------- geometry: stun grenade ----------------
# A flashbang: dark red body between two big nuts, a yellow stripe, rows of holes with brass showing through, a
# black fuse on top with a dark red spoon running down one side, and a steel pull ring. Stands upright, centred on
# x = z = 8 (like the bat).
def tex_hole():
    im = Image.new("RGBA", (16, 16), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    d.ellipse((0, 0, 15, 15), fill=(40, 20, 20, 255))
    d.ellipse((2, 2, 13, 13), fill=(150, 120, 60, 255))
    d.ellipse((4, 3, 12, 11), fill=(176, 146, 78, 255))
    return im
GRENADE_TEX = {"red": tex_metal((112, 24, 28)), "yellow": tex_metal((236, 192, 44), 0, edge=False),
               "black": tex_metal((30, 30, 34)), "steel": tex_metal((172, 176, 184)), "hole": tex_hole()}
for k, im in GRENADE_TEX.items(): im.save(path("assets", NS, "textures", "item", "stun_grenade", k + ".png"))
FULL_UV.add("hole")

elements = []
ENDS = {"up": "red", "down": "red"}
round_rod(8, 8, 7.0, 0.0, 3.2, "red")                               # bottom nut
round_rod(8, 8, 5.6, 3.2, 6.8, "red")                               # body
round_rod(8, 8, 5.72, 6.8, 8.8, "yellow")                           # yellow stripe (a hair proud of the body)
round_rod(8, 8, 5.6, 8.8, 12.4, "red")
round_rod(8, 8, 7.0, 12.4, 15.6, "red")                             # top nut
# rows of holes on four sides; the middle row sits on the stripe
for yc in (5.0, 7.8, 10.6):
    for side in ("north", "south", "east", "west"):
        if side == "south":   frm, to = (7.25, yc - 0.75, 10.82), (8.75, yc + 0.75, 10.9)
        elif side == "north": frm, to = (7.25, yc - 0.75, 5.1), (8.75, yc + 0.75, 5.18)
        elif side == "east":  frm, to = (10.82, yc - 0.75, 7.25), (10.9, yc + 0.75, 8.75)
        else:                 frm, to = (5.1, yc - 0.75, 7.25), (5.18, yc + 0.75, 8.75)
        box(frm, to, "black", {side: "hole"})
# fuse head, the spoon over the top and down the side, the pin and the pull ring
box((6.0, 15.6, 6.4), (10.0, 19.0, 9.6), "black")
box((6.8, 19.0, 5.0), (9.2, 19.6, 12.6), "red")                     # spoon across the top
box((6.8, 17.8, 4.4), (9.2, 19.6, 5.0), "red")                      # curled front of the spoon
box((6.8, 5.0, 12.0), (9.2, 19.0, 12.6), "red")                     # spoon down the side
box((6.8, 4.4, 11.4), (9.2, 5.0, 12.6), "red")                      # its foot
# the pin runs out through the side of the fuse head, and a closed ring hangs from its end
box((9.9, 17.75, 7.75), (11.2, 18.25, 8.25), "steel")               # pin
RX0, RX1 = 10.9, 11.3
box((RX0, 17.8, 7.5), (RX1, 18.2, 8.5), "steel")                    # ring: top, where the pin goes through
box((RX0, 15.7, 7.5), (RX1, 16.1, 8.5), "steel")                    # bottom
box((RX0, 16.5, 6.5), (RX1, 17.4, 6.9), "steel")                    # front
box((RX0, 16.5, 9.1), (RX1, 17.4, 9.5), "steel")                    # back
for yc, zc, ang in ((17.7, 8.9, 45), (17.7, 7.1, -45), (16.2, 8.9, -45), (16.2, 7.1, 45)):   # corners that join them up
    box((RX0 + 0.01, yc - 0.2, zc - 0.55), (RX1 - 0.01, yc + 0.2, zc + 0.55), "steel", rot=("x", ang, (8.0 + 3.1, yc, zc)))
GRENADE = elements

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
    "gui":                   centred(SHOTGUN, (0, 90, 0), 0.43),
    "ground":                centred(SHOTGUN, (0, 90, 0), 0.32),
    "fixed":                 centred(SHOTGUN, (0, 90, 0), 0.46),
    "head":                  centred(SHOTGUN, (0, 0, 0), 0.4, (0, 8, 0)),
    "firstperson_righthand": centred(SHOTGUN, (0, 0, 0), 0.5, (3, -1, -4)),
    "firstperson_lefthand":  centred(SHOTGUN, (0, 0, 0), 0.5, (3, -1, -4)),
    "thirdperson_righthand": centred(SHOTGUN, (0, 0, 0), 0.5, (0, 3, -1)),
    "thirdperson_lefthand":  centred(SHOTGUN, (0, 0, 0), 0.5, (0, 3, -1)),
}
PALA_DISPLAY = {
    "gui":                   centred(PALA, (0, 90, 0), 0.5),
    "ground":                centred(PALA, (0, 90, 0), 0.36),
    "fixed":                 centred(PALA, (0, 90, 0), 0.54),
    "head":                  centred(PALA, (0, 0, 0), 0.5, (0, 8, 0)),
    "firstperson_righthand": centred(PALA, (0, 0, 0), 0.55, (4, -1, -5)),
    "firstperson_lefthand":  centred(PALA, (0, 0, 0), 0.55, (4, -1, -5)),
    "thirdperson_righthand": centred(PALA, (0, 0, 0), 0.55, (0, 3, -2)),
    "thirdperson_lefthand":  centred(PALA, (0, 0, 0), 0.55, (0, 3, -2)),
}
GOO_DISPLAY = {
    "gui":                   centred(GOO, (0, 90, 0), 0.46),
    "ground":                centred(GOO, (0, 90, 0), 0.34),
    "fixed":                 centred(GOO, (0, 90, 0), 0.5),
    "head":                  centred(GOO, (0, 0, 0), 0.45, (0, 8, 0)),
    "firstperson_righthand": centred(GOO, (0, 0, 0), 0.5, (4, -1, -5)),
    "firstperson_lefthand":  centred(GOO, (0, 0, 0), 0.5, (4, -1, -5)),
    "thirdperson_righthand": centred(GOO, (0, 0, 0), 0.5, (0, 3, -2)),
    "thirdperson_lefthand":  centred(GOO, (0, 0, 0), 0.5, (0, 3, -2)),
}
UMBRAL_DISPLAY = {
    "gui":                   centred(UMBRAL, (0, 90, 0), 0.34),
    "ground":                centred(UMBRAL, (0, 90, 0), 0.26),
    "fixed":                 centred(UMBRAL, (0, 90, 0), 0.36),
    "head":                  centred(UMBRAL, (0, 0, 0), 0.4, (0, 8, 0)),
    "firstperson_righthand": centred(UMBRAL, (0, 0, 0), 0.5, (3, -1, -4)),
    "firstperson_lefthand":  centred(UMBRAL, (0, 0, 0), 0.5, (3, -1, -4)),
    "thirdperson_righthand": centred(UMBRAL, (0, 0, 0), 0.5, (0, 3, -1)),
    "thirdperson_lefthand":  centred(UMBRAL, (0, 0, 0), 0.5, (0, 3, -1)),
}
# Held like a sword, the same way as the bat below (the model stands upright where a sword sprite runs corner to corner)
SWORD_DISPLAY = {
    "gui":                   centred(SWORD, (0, 0, -45), 0.46),
    "ground":                centred(SWORD, (0, 0, 0), 0.32),
    "fixed":                 centred(SWORD, (0, 0, -45), 0.5),
    "head":                  centred(SWORD, (0, 180, 0), 0.55, (0, 10, 0)),
    "thirdperson_righthand": {"rotation": [0, -90, 10], "translation": [0, 12.6, 0.5], "scale": [0.6] * 3},
    "thirdperson_lefthand":  {"rotation": [0, 90, -10], "translation": [0, 12.6, 0.5], "scale": [0.6] * 3},
    "firstperson_righthand": {"rotation": [0, -90, -20], "translation": [1.13, 9.5, 1.13], "scale": [0.5] * 3},
    "firstperson_lefthand":  {"rotation": [0, 90, 20], "translation": [1.13, 9.5, 1.13], "scale": [0.5] * 3},
}
GRENADE_DISPLAY = {
    "gui":                   centred(GRENADE, (15, -30, 0), 0.72),
    "ground":                centred(GRENADE, (0, 0, 0), 0.5),
    "fixed":                 centred(GRENADE, (0, 0, 0), 0.72),
    "head":                  centred(GRENADE, (0, 0, 0), 0.6, (0, 8, 0)),
    "thirdperson_righthand": centred(GRENADE, (0, -90, 10), 0.5, (0, 2.5, 1.0)),
    "thirdperson_lefthand":  centred(GRENADE, (0, 90, -10), 0.5, (0, 2.5, 1.0)),
    "firstperson_righthand": centred(GRENADE, (0, -90, 0), 0.55, (2, 2, 0)),
    "firstperson_lefthand":  centred(GRENADE, (0, 90, 0), 0.55, (2, 2, 0)),
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

def write_item(name, els, tex, display, particle, paths=None):
    """paths: texture keys pointed somewhere other than this item's own folder (e.g. a vanilla texture)."""
    paths = paths or {}
    model = {"textures": {**{k: paths.get(k, f"{NS}:item/{name}/{k}") for k in tex}, **paths,
                          "particle": f"{NS}:item/{name}/{particle}"},
             "gui_light": "side", "elements": els, "display": display}
    wjson(path("assets", NS, "models", "item", name + ".json"), model)
    wjson(path("assets", NS, "items", name + ".json"), {"model": {"type": "minecraft:model", "model": f"{NS}:item/{name}"}})
write_item("hand_cannon", GUN, TEX, GUN_DISPLAY, "frame")
write_item("nail_bat", BAT, BAT_TEX, BAT_DISPLAY, "wood")
write_item("tommy_gun", TOMMY, TOMMY_TEX, TOMMY_DISPLAY, "steel")
write_item("shotgun", SHOTGUN, SG_TEX, SHOTGUN_DISPLAY, "blued")
write_item("pala_pistol", PALA, PALA_TEX, PALA_DISPLAY, "body")
write_item("goo_cannon", GOO, GOO_TEX, GOO_DISPLAY, "steel", GOO_TEX_PATHS)
write_item("umbral_lance", UMBRAL, UMB_TEX, UMBRAL_DISPLAY, "black")
write_item("radiant_ankh", SWORD, SWORD_TEX, SWORD_DISPLAY, "gold")
write_item("stun_grenade", GRENADE, GRENADE_TEX, GRENADE_DISPLAY, "red")
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
                    px_ = im[tx, ty]
                    a_ = px_[3] if len(px_) > 3 else 255
                    if a_ == 0: continue
                    quads.append((depth, cell, tuple(clamp(c * sh * 1.1) for c in px_[:3]), a_))
    xs = [p[0] for q in quads for p in q[1]]; ys = [p[1] for q in quads for p in q[1]]
    s = (size - 2 * pad) / max(max(xs) - min(xs), max(ys) - min(ys))
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    im = Image.new("RGBA", (size, size), (38, 40, 46, 255)); d = ImageDraw.Draw(im)
    glass = Image.new("RGBA", (size, size), (0, 0, 0, 0)); g = ImageDraw.Draw(glass)
    for _, v, col, a in sorted(quads, key=lambda q: q[0]):
        pts = [(size / 2 + (p[0] - cx) * s, size / 2 - (p[1] - cy) * s) for p in v]
        if a >= 250: d.polygon(pts, fill=col + (255,), outline=col + (255,))
        else: g.polygon(pts, fill=col + (a,))          # translucent: blended on top afterwards
    return Image.alpha_composite(im, glass)
rows = [[render(GUN, TEX, -90, 0), render(GUN, TEX, -130, 18), render(GUN, TEX, 180, 8), render(GUN, TEX, 0, 0)],
        [render(TOMMY, TOMMY_TEX, -90, 0), render(TOMMY, TOMMY_TEX, -130, 18), render(TOMMY, TOMMY_TEX, 180, 8), render(TOMMY, TOMMY_TEX, -60, -15)],
        [render(SHOTGUN, SG_TEX, -90, 0), render(SHOTGUN, SG_TEX, -130, 18), render(SHOTGUN, SG_TEX, 180, 8), render(SHOTGUN, SG_TEX, -60, -15)],
        [render(PALA, PALA_TEX, -90, 0), render(PALA, PALA_TEX, -130, 18), render(PALA, PALA_TEX, 180, 8), render(PALA, PALA_TEX, -60, -15)],
        [render(GOO, GOO_PREVIEW_TEX, -90, 0), render(GOO, GOO_PREVIEW_TEX, -130, 18), render(GOO, GOO_PREVIEW_TEX, 180, 8), render(GOO, GOO_PREVIEW_TEX, -60, -15)],
        [render(UMBRAL, UMB_TEX, -90, 0), render(UMBRAL, UMB_TEX, -130, 18), render(UMBRAL, UMB_TEX, 180, 8), render(UMBRAL, UMB_TEX, -60, -15)],
        [render(SWORD, SWORD_TEX, 0, 0, -90), render(SWORD, SWORD_TEX, 30, 20, -90), render(SWORD, SWORD_TEX, 0, 0, 0), render(SWORD, SWORD_TEX, 0, 0, -45)],
        [render(GRENADE, GRENADE_TEX, 0, 0, 0), render(GRENADE, GRENADE_TEX, 35, 15, 0), render(GRENADE, GRENADE_TEX, -90, 0, 0), render(GRENADE, GRENADE_TEX, 120, 15, 0)],
        [render(BAT, BAT_TEX, 0, 0, -90), render(BAT, BAT_TEX, 30, 20, -90), render(BAT, BAT_TEX, 0, 90), render(BAT, BAT_TEX, 0, 0, -45)]]
pv = Image.new("RGBA", (420 * 4, 420 * len(rows)))
for r, row in enumerate(rows):
    for i, v in enumerate(row): pv.paste(v, (420 * i, 420 * r))
pv.save("preview.png"); print("preview.png written")
