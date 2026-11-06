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
rng = random.Random(7)
def clamp(v): return max(0, min(255, int(v)))
def tex_metal(base=(58, 62, 72), noise=10):
    im = Image.new("RGBA", (16, 16)); px = im.load()
    for y in range(16):
        for x in range(16):
            n = rng.randint(-noise, noise) + (6 if y < 3 else 0) - (6 if y > 12 else 0)
            px[x, y] = tuple(clamp(c + n) for c in base) + (255,)
    for x in range(16): px[x, 1] = tuple(clamp(c + 38) for c in base) + (255,)   # polished edge highlight
    return im
def tex_cylinder():
    im = tex_metal((66, 70, 80)); px = im.load()
    for x in (2, 7, 12):   # flutes: dark grooves with a light lip
        for y in range(2, 14):
            px[x, y] = (32, 34, 40, 255); px[x + 1, y] = (40, 42, 50, 255); px[x + 2, y] = (96, 100, 112, 255)
    return im
def tex_wood():
    im = Image.new("RGBA", (16, 16)); px = im.load()
    for y in range(16):
        for x in range(16):
            g = math.sin((x + y * 0.35) * 1.3) * 10 + rng.randint(-6, 6)
            px[x, y] = (clamp(112 + g), clamp(62 + g * 0.6), clamp(32 + g * 0.3), 255)
    for y in range(3, 13):   # checkering panel
        for x in range(3, 13):
            if (x + y) % 3 == 0 or (x - y) % 3 == 0:
                r, g, b, a = px[x, y]; px[x, y] = (clamp(r * 0.62), clamp(g * 0.62), clamp(b * 0.62), 255)
    for x in range(16): px[x, 0] = (70, 38, 20, 255); px[x, 15] = (70, 38, 20, 255)
    return im
def tex_bore():
    im = tex_metal((58, 62, 72)); d = ImageDraw.Draw(im)
    d.ellipse((2, 2, 13, 13), fill=(20, 20, 24, 255), outline=(110, 114, 124, 255))
    d.ellipse((5, 5, 10, 10), fill=(4, 4, 6, 255))
    return im
def tex_dark(): return tex_metal((30, 32, 38), 5)
def tex_brass():
    im = tex_metal((176, 132, 52), 14); d = ImageDraw.Draw(im)
    return im

TEX = {"metal": tex_metal(), "cylinder": tex_cylinder(), "wood": tex_wood(), "bore": tex_bore(),
       "dark": tex_dark(), "brass": tex_brass()}
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
        uv = [0, 0, 16, 16] if t == "bore" else [0, 0, round(min(16, w), 2), round(min(16, h), 2)]
        faces[f] = {"uv": uv, "texture": "#" + t}
    e = {"from": [round(v, 3) for v in frm], "to": [round(v, 3) for v in to], "faces": faces}
    if rot: e["rotation"] = {"axis": rot[0], "angle": rot[1], "origin": list(rot[2])}
    elements.append(e)

def round_prism(cx, cy, diameter, z0, z1, tex, end_tex=None):
    """A roundish prism along z: two crossed slabs, plus the same pair turned 45 degrees (looks octagonal end-on)."""
    r, w = diameter / 2, diameter * 0.46 / 2
    ft = {"north": end_tex, "south": end_tex} if end_tex else None
    origin = (cx, cy, (z0 + z1) / 2)
    for rot in (None, ("z", 45, origin)):
        box((cx - r, cy - w, z0), (cx + r, cy + w, z1), tex, ft, rot)
        box((cx - w, cy - r, z0), (cx + w, cy + r, z1), tex, ft, rot)

# barrel: short and fat (snubnose), lined up with the top chamber
round_prism(8, 13.0, 4.6, -4.0, 4.6, "metal", end_tex="bore")
box((6.6, 8.8, -3.6), (9.4, 11.2, 4.6), "metal")                 # full underlug
box((7.4, 15.0, -3.4), (8.6, 16.8, -1.2), "metal")               # front sight blade
# cylinder: fat and fluted
round_prism(8, 10.5, 9.6, 4.6, 11.6, "cylinder")
box((7.0, 9.5, 4.2), (9.0, 11.5, 4.7), "brass")                  # cylinder pin / ejector star
# frame
box((6.0, 4.0, 3.6), (10.0, 13.0, 4.7), "metal")                 # front of frame (yoke)
box((6.0, 4.0, 4.0), (10.0, 6.0, 12.0), "metal")                 # under the cylinder
box((6.2, 15.0, 4.6), (9.8, 16.0, 15.6), "metal")                # top strap
box((5.5, 4.0, 11.5), (10.5, 16.0, 16.5), "metal")               # recoil shield / rear frame
box((7.2, 16.0, 14.4), (8.8, 16.6, 15.6), "dark")                # rear sight notch block
# hammer with a spur
box((7.0, 15.0, 15.6), (9.0, 17.6, 17.0), "dark")
box((7.0, 16.6, 17.0), (9.0, 17.6, 19.0), "dark")
# trigger guard and trigger
box((7.0, 1.4, 7.4), (9.0, 2.4, 14.2), "metal")
box((7.0, 1.4, 7.4), (9.0, 5.6, 8.4), "metal")
box((7.5, 2.0, 10.4), (8.5, 5.4, 11.4), "dark", rot=("x", -22.5, (8, 5, 11)))
# grip, raked back, with a steel butt cap
GRIP_ROT = ("x", -22.5, (8, 6, 16))
box((5.4, -8.0, 13.4), (10.6, 5.0, 19.0), "wood", rot=GRIP_ROT)
box((5.2, -9.0, 13.2), (10.8, -8.0, 19.2), "metal", rot=GRIP_ROT)
box((6.5, 4.0, 12.8), (9.5, 6.0, 16.0), "metal")                  # grip frame strap under the hammer

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

model = {"textures": {**{k: f"{NS}:item/hand_cannon/{k}" for k in TEX}, "particle": f"{NS}:item/hand_cannon/metal"},
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
avg = {k: im.convert("RGB").resize((1, 1), Image.BOX).getpixel((0, 0)) for k, im in TEX.items()}
FACE_IDX = {"down": (0, 1, 3, 2), "up": (4, 6, 7, 5), "north": (0, 4, 5, 1), "south": (2, 3, 7, 6),
            "west": (0, 2, 6, 4), "east": (1, 5, 7, 3)}
def face_quads(e):
    f, t = e["from"], e["to"]
    c = [(x, y, z) for y in (f[1], t[1]) for z in (f[2], t[2]) for x in (f[0], t[0])]
    # index: bit0 x, bit1 z, bit2 y
    if "rotation" in e:
        r = e["rotation"]; c = [rot_axis(p, r["axis"], r["angle"], r["origin"]) for p in c]
    for name, idx in FACE_IDX.items():
        yield name, [c[i] for i in idx], e["faces"][name]["texture"][1:]
def render(yaw, pitch, size=420, pad=30):
    def view(p):
        p = rot_axis(p, "y", yaw, centre); p = rot_axis(p, "x", pitch, centre); return p
    quads = []
    light = (0.35, 0.8, 0.5); ln = math.sqrt(sum(v * v for v in light)); light = tuple(v / ln for v in light)
    for e in elements:
        for name, pts, tex in face_quads(e):
            v = [view(p) for p in pts]
            a = [v[1][i] - v[0][i] for i in range(3)]; b = [v[2][i] - v[0][i] for i in range(3)]
            n = (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
            nl = math.sqrt(sum(x * x for x in n)) or 1; n = tuple(x / nl for x in n)
            if n[2] <= 0: continue   # facing away (camera looks down -z from +z)
            shade = 0.45 + 0.55 * max(0, sum(n[i] * light[i] for i in range(3)))
            col = tuple(clamp(c * shade * 1.15) for c in avg[tex])
            quads.append((sum(p[2] for p in v) / 4, v, col))
    xs = [p[0] for q in quads for p in q[1]]; ys = [p[1] for q in quads for p in q[1]]
    s = (size - 2 * pad) / max(max(xs) - min(xs), max(ys) - min(ys))
    cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    im = Image.new("RGBA", (size, size), (38, 40, 46, 255)); d = ImageDraw.Draw(im)
    for _, v, col in sorted(quads, key=lambda q: q[0]):
        d.polygon([(size / 2 + (p[0] - cx) * s, size / 2 - (p[1] - cy) * s) for p in v], fill=col + (255,), outline=(15, 15, 18, 255))
    return im
views = [render(-90, 0), render(-130, 18), render(180, 8), render(0, 0)]
pv = Image.new("RGBA", (420 * len(views), 420))
for i, v in enumerate(views): pv.paste(v, (420 * i, 0))
pv.save("preview.png"); print("preview.png written")
