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
    im = Image.new("RGBA", (16, 16)); px = im.load()
    for y in range(16):
        for x in range(16):
            n = rng.randint(-noise, noise) + (5 if y < 4 else 0) - (5 if y > 12 else 0)
            px[x, y] = tuple(clamp(c + n) for c in base) + (255,)
    if edge:
        for x in range(16): px[x, 1] = shade(base, 1.25)
    return im
def tex_flutes(base, vertical):
    """Long flutes that stop short of both ends of the cylinder. Rows on the side faces, columns on top/bottom."""
    im = tex_metal(base, 6, edge=False); px = im.load()
    for lane in (3, 9):
        for t in range(2, 14):
            for k, f in ((0, 0.55), (1, 0.45), (2, 0.6), (3, 1.3)):
                x, y = (lane + k, t) if vertical else (t, lane + k)
                px[x, y] = shade(base, f)
    return im
def tex_knurl(base):
    im = tex_metal(base, 4, edge=False); px = im.load()
    for y in range(16):
        for x in range(16):
            if (x + y) % 2 == 0: px[x, y] = shade(base, 0.6)
    return im
def tex_wood(base, streak):
    """Smooth polished hardwood, grain running along the grip."""
    im = Image.new("RGBA", (16, 16)); px = im.load()
    lines = [rng.uniform(0, 16) for _ in range(5)]
    for y in range(16):
        for x in range(16):
            g = math.sin(x * 1.7 + math.sin(y * 0.4) * 1.5) * 9 + rng.randint(-4, 4)
            c = [base[0] + g, base[1] + g * 0.6, base[2] + g * 0.35]
            if any(abs(x - (l + math.sin(y * 0.5 + l) * 0.8)) < 0.55 for l in lines): c = [v * streak for v in c]
            if x in (4, 5): c = [v * 1.18 for v in c]          # polish highlight
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

# ---------------- geometry ----------------
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
    """A roundish prism along z: two crossed slabs, plus the same pair turned 45 degrees (looks octagonal end-on)."""
    r, w = diameter / 2, diameter * 0.46 / 2
    origin = (cx, cy, (z0 + z1) / 2)
    for rot in (None, ("z", 45, origin)):
        box((cx - r, cy - w, z0), (cx + r, cy + w, z1), tex, faces_tex, rot)
        box((cx - w, cy - r, z0), (cx + w, cy + r, z1), tex, faces_tex, rot)

# barrel: short, fat and round (snubnose) with a flat sighting rib on top
round_prism(8, 13.0, 4.6, -6.0, 2.7, "frame", {"north": "bore"})
box((7.0, 14.9, -6.0), (9.0, 15.8, 2.7), "frame")                    # top rib
box((7.4, 15.6, -5.9), (8.6, 17.2, -4.0), "frame")                   # ramped front sight
box((7.35, 16.3, -5.7), (8.65, 17.0, -5.0), "orange")                # sight insert
# full-length underlug with the ejector rod showing through a slot
box((6.6, 8.6, -5.8), (9.4, 11.4, 2.7), "frame")
box((6.5, 9.4, -3.6), (9.5, 10.6, 1.6), "dark")                      # slot
box((6.45, 9.75, -3.4), (9.55, 10.25, 1.6), "polished")              # ejector rod
box((6.4, 9.5, -3.5), (9.6, 10.5, -2.4), "knurl")                    # knurled rod tip
# cylinder: fat and long, long flutes, bevelled front
FLUTES = {"east": "cyl_h", "west": "cyl_h", "up": "cyl_v", "down": "cyl_v"}
round_prism(8, 10.5, 9.6, 3.0, 12.0, "cylinder", FLUTES)
round_prism(8, 10.5, 8.6, 2.4, 3.0, "cylinder")                      # bevel
box((7.2, 9.7, 2.0), (8.8, 11.3, 2.4), "polished")                   # centre pin / ejector star
# frame
box((6.0, 4.0, 1.6), (10.0, 13.6, 2.6), "frame")                     # yoke
box((6.0, 4.0, 2.0), (10.0, 6.0, 12.0), "frame")                     # under the cylinder
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
box((6.1, -7.6, 13.1), (9.9, 4.8, 19.4), "wood", rot=GRIP_ROT)       # front and back bulge out
box((4.9, -5.2, 15.0), (11.1, 1.8, 18.4), "wood", rot=GRIP_ROT)      # palm swell
for y in (1.6, -1.6, -4.8):                                          # finger ridges on the front strap
    box((6.6, y, 12.8), (9.4, y + 1.2, 13.4), "wood", rot=GRIP_ROT)
box((6.2, 3.0, 16.0), (9.8, 6.6, 19.6), "wood", rot=("x", -45, (8, 5, 16.6)))   # backstrap curve up behind the hammer
box((5.0, -9.6, 12.8), (11.0, -7.8, 20.0), "wood_dark", rot=GRIP_ROT)  # flared base
box((5.6, -10.2, 13.4), (10.4, -9.6, 19.4), "wood_dark", rot=GRIP_ROT)
box((6.5, 4.0, 12.8), (9.5, 6.0, 16.0), "frame")                     # grip frame under the hammer

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
allp = [p for e in elements for p in elem_corners(e)]
lo = [min(p[i] for p in allp) for i in range(3)]; hi = [max(p[i] for p in allp) for i in range(3)]
centre = [(lo[i] + hi[i]) / 2 for i in range(3)]
print("model bounds", [round(v, 2) for v in lo], [round(v, 2) for v in hi])

def display_rotate(v, rot):   # display rotations: x, then y, then z, about the model centre (8,8,8)
    for ax, d in zip("xyz", rot): v = rot_axis(v, ax, d, (0, 0, 0))
    return v
def centred(rot, scale, nudge=(0, 0, 0)):
    """Display entry that puts the model's middle on the slot's middle, then nudges it (model units)."""
    off = display_rotate(tuple(centre[i] - 8 for i in range(3)), rot)
    return {"rotation": list(rot), "translation": [round(-scale * off[i] + nudge[i], 3) for i in range(3)],
            "scale": [scale] * 3}

# How it sits. Big on purpose: the gun is meant to look comically oversized.
DISPLAY = {
    "gui":                   centred((0, 90, 0), 0.52),
    "ground":                centred((0, 90, 0), 0.34),
    "fixed":                 centred((0, 90, 0), 0.55),          # item frames
    "head":                  centred((0, 0, 0), 0.6, (0, 8, 0)),
    "firstperson_righthand": centred((0, 0, 0), 0.62, (4, -1, -6)),
    "firstperson_lefthand":  centred((0, 0, 0), 0.62, (4, -1, -6)),
    "thirdperson_righthand": centred((0, 0, 0), 0.62, (0, 3, -3)),
    "thirdperson_lefthand":  centred((0, 0, 0), 0.62, (0, 3, -3)),
}

model = {"textures": {**{k: f"{NS}:item/hand_cannon/{k}" for k in TEX}, "particle": f"{NS}:item/hand_cannon/frame"},
         "gui_light": "side", "elements": elements, "display": DISPLAY}
wjson(path("assets", NS, "models", "item", "hand_cannon.json"), model)
wjson(path("assets", NS, "items", "hand_cannon.json"),
      {"model": {"type": "minecraft:model", "model": f"{NS}:item/hand_cannon"}})
# pack.mcmeta: resource pack format 88 = Minecraft 26.2
wjson(path("pack.mcmeta"), {"pack": {"description": "HandCannon revolver model", "min_format": [88, 0], "max_format": [99, 0]}})

zpath = OUT.rstrip("/") + ".zip"
with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
    for root, _, files in os.walk(OUT):
        for f in files:
            full = os.path.join(root, f); z.write(full, os.path.relpath(full, OUT))
print("zip:", zpath, "sha1:", hashlib.sha1(open(zpath, "rb").read()).hexdigest())

# ---------------- preview.png: flat-shaded orthographic renders ----------------
# corners in texture order (top-left, top-right, bottom-right, bottom-left) as Minecraft maps face UVs
FACE_IDX = {"north": (5, 4, 0, 1), "south": (6, 7, 3, 2), "east": (7, 5, 1, 3), "west": (4, 6, 2, 0),
            "up": (4, 5, 7, 6), "down": (2, 3, 1, 0)}
def face_quads(e):
    f, t = e["from"], e["to"]
    c = [(x, y, z) for y in (f[1], t[1]) for z in (f[2], t[2]) for x in (f[0], t[0])]
    # index: bit0 x, bit1 z, bit2 y
    if "rotation" in e:
        r = e["rotation"]; c = [rot_axis(p, r["axis"], r["angle"], r["origin"]) for p in c]
    for name, idx in FACE_IDX.items():
        yield name, [c[i] for i in idx], e["faces"][name]["texture"][1:], e["faces"][name]["uv"]
def render(yaw, pitch, size=420, pad=30):
    def view(p):
        p = rot_axis(p, "y", yaw, centre); p = rot_axis(p, "x", pitch, centre); return p
    quads = []
    light = (0.35, 0.8, 0.5); ln = math.sqrt(sum(v * v for v in light)); light = tuple(v / ln for v in light)
    N = 6
    def lerp(a, b, t): return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))
    for e in elements:
        for name, pts, tex, uv in face_quads(e):
            v = [view(p) for p in pts]
            a = [v[1][i] - v[0][i] for i in range(3)]; b = [v[2][i] - v[0][i] for i in range(3)]
            n = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
            nl = math.sqrt(sum(x * x for x in n)) or 1; n = tuple(-x / nl for x in n)   # outward normal
            if n[2] <= 0: continue   # facing away (camera looks down -z from +z)
            sh = 0.5 + 0.5 * max(0, sum(n[i] * light[i] for i in range(3)))
            im = TEX[tex].load()
            depth = sum(p[2] for p in v) / 4
            for i in range(N):
                for j in range(N):
                    def at(u, w): return lerp(lerp(v[0], v[1], u), lerp(v[3], v[2], u), w)
                    cell = [at(i / N, j / N), at((i + 1) / N, j / N), at((i + 1) / N, (j + 1) / N), at(i / N, (j + 1) / N)]
                    tx = int(uv[0] + (uv[2] - uv[0]) * (i + 0.5) / N) % 16; ty = int(uv[1] + (uv[3] - uv[1]) * (j + 0.5) / N) % 16
                    col = tuple(clamp(c * sh * 1.1) for c in im[tx, ty][:3])
                    quads.append((depth, cell, col))
    xs = [p[0] for q in quads for p in q[1]]; ys = [p[1] for q in quads for p in q[1]]
    s = (size - 2 * pad) / max(max(xs) - min(xs), max(ys) - min(ys))
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    im = Image.new("RGBA", (size, size), (38, 40, 46, 255)); d = ImageDraw.Draw(im)
    for _, v, col in sorted(quads, key=lambda q: q[0]):
        d.polygon([(size / 2 + (p[0] - cx) * s, size / 2 - (p[1] - cy) * s) for p in v], fill=col + (255,), outline=col + (255,))
    return im
views = [render(-90, 0), render(-130, 18), render(180, 8), render(0, 0)]
pv = Image.new("RGBA", (420 * len(views), 420))
for i, v in enumerate(views): pv.paste(v, (420 * i, 0))
pv.save("preview.png"); print("preview.png written")
