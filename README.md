# HandCannon (Paper 26.2, Java 25)

A comically oversized snubnose revolver (right-click to fire), a cartoon M1-style Tommy gun with a huge drum magazine
(hold right-click for full auto), a chunky sawed-off side-by-side shotgun (right-click for a blast of pellets),
the Pala-Pistol (a slow bolt of light that stuns) and a nail-studded baseball bat (hold right-click to wind up a home run), all with 3D models. No ammo, no reloading.

![preview](preview.png)

## Build
No JDK 25 handy? Push this folder to a GitHub repo: `.github/workflows/build.yml` builds the jar and the resource pack
and attaches both to the run (Actions tab, artifacts `HandCannon-jar` and `HandCannon-resourcepack`).
    gradle build            # needs JDK 25; jar ends up in build/libs/
Drop the jar in `plugins/`.

## Resource pack
    python3 tools/make_pack.py handcannon-resourcepack   # needs Pillow; writes handcannon-resourcepack.zip, prints its sha1, writes preview.png
Host the zip at a public URL, then set `resource-pack.url` and `resource-pack.sha1` in `plugins/HandCannon/config.yml`
and run `/hc reload`. Players are asked to accept it on join (`/hc pack [player]` resends it).
Without the pack the gun shows as a missing-texture block.
Set `FINISH` at the top of the textures section to `stainless` (bright frame, dark cylinder), `blued` or `black`.

The model is built from boxes in `tools/make_pack.py` (barrel points north, grip at the back). How it sits in first
person, third person, the inventory and item frames is the `DISPLAY` table near the bottom of the geometry section:
change a rotation, nudge or scale, re-run the script and re-host the zip.

## Commands
    /hc give [gun|tommy|shotgun|pala|bat] [player]   give a Hand Cannon (default), Tommy Gun, Double Barrel, Pala-Pistol or Nail Bat (op)
    /hc reload              reload config.yml (op)
    /hc pack [player]       resend the resource pack (op)
Permission `handcannon.use` (everyone by default) is needed to fire.

## Shooting
Right-click (air, blocks or point-blank on a mob) fires a hitscan shot: big muzzle blast, smoke trail, block chips or
crits where it lands. Hits do `damage` (x `headshot-multiplier` at head height) and shove the target; the shooter gets
pushed back and their view kicks up. The cooldown shows as the sweep on the item. All of it is in `config.yml`.

## Tommy Gun
Hold right-click for full auto, about 10 bullets a second: 10 damage (five hearts) each, with a little spread. Its settings are under `tommy:` in `config.yml` and apply right away.

## Double Barrel
Right-click fires a blast of 8 pellets with a one-second wait between shots. Anything caught in the blast takes
10 damage (five hearts) however many pellets hit it, and gets shoved harder the more pellets land. Settings are
under `shotgun:` in `config.yml`.

## Pala-Pistol
Right-click fires a glowing bolt of yellow light that flies slowly (you can watch it go) in a straight line. Whatever
it hits takes 10 damage (five hearts) and is stunned for 3 seconds: it can't move, jump or attack, and yellow
sparks dance round its head. Misses fizzle out against blocks or after 48 blocks. Settings are under `pala:`.

## Nail Bat
Left-click is a normal hit: 10 damage (five hearts) at full strength, a bit under one swing a second.
Hold right-click to wind up (the bat goes up over your shoulder); after a second there's a ding, and letting go
swings a home run: 10 damage and whatever is in front of you goes flying with a cloud trail. Let go early and
nothing happens. Left-click damage and speed are stamped on each bat when it is given (`bat.damage`,
`bat.attack-speed`); the rest of `bat:` applies right away. The bat is a stick underneath, so it is kept out of
crafting grids and furnaces.
