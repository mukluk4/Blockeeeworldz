# Blockeeeworldz

Toy-brick restyle of the RoF2 client: brick minifig players and creatures, brick-built zones. Personal project.

This repo holds the build scripts only. No game files are included: you need your own copy of the RoF2 client. The
scripts read its stock archives and write new ones; nothing is uploaded or shared. Run everything with `python -I`
(Python 3 with numpy and Pillow).

Back up before you build: the scripts read each original from `<client>/brick_orig/<file>.orig` when it exists, else
from the client folder. Only the creature builders (`brick_all_copies.py`, `eqgcreature.py`) make that backup
themselves; for everything else, copy the files there first.

## Layout

```
lib/          shared readers/writers
  pfs.py        .s3d (PFS) archives
  wld.py        old-format .wld meshes, materials, skeletons
  eqgmod.py     EQG .mod models (Drakkin, creatures)
  eqgmds.py     EQG .mds models (mounts, creatures)
  racescale.py  shrinks Ogre/Troll/Barbarian to about Human height (also: their global<race>_chr2.s3d)
  export.py     pose a model and write a .glb + preview

characters/   players, their gear, creatures, mounts
  minifig.py          the minifig (parts, prints, per-race looks, fit onto any skeleton)
  make_s3d.py         a player race's global<race>_chr.s3d (body, armor atlases, weapon grip)
  make_armor_sets.py  global17-23_amr.s3d: armor sets 17-23 for every race
  hairpieces.py       hair and beards (lgequip.s3d, lgequip2.s3d)
  robes.py            robe skirts (on top of the hair build of lgequip*.s3d)
  eqgcreature.py      creatures in newer .eqg models (.mod/.mds), from each zone's <zone>_chr.txt
  helmets.py          toy hats (lgequip_amr.s3d, lgequip_amr2.s3d)
  make_drakkin.py     Drakkin (dkm.eqg, dkf.eqg)
  brickcreature.py    brick-built creatures and minifig NPCs in any _chr archive
  brick_all_copies.py rebuild every copy of some creatures across all archives
  creatures.txt       every creature type bricked so far (brick_all_copies.py <client> <out> @characters/creatures.txt)
  make_vehicles.py    brick vehicles in place of three mounts
  hide_attachments.py / hide_classic.py   fold away meshes that poke through
  brickify.py         first try (texture recolor only); superseded

zones/        brick zones, one folder per continent
  brickzone.py        one zone archive: ground (plates, brick walls, water) or objects
  build_continent.py  every zone listed in zones/<continent>/zones.txt
  antonica/zones.txt  done: 49 zones
  faydwer/zones.txt   15 zones, Butcherblock outward (incl. Ocean of Tears)
  odus/zones.txt      9 zones, Erudin outward
  kunark/zones.txt    28 zones, Field of Bone outward
  velious/zones.txt   19 zones, Iceclad outward
  luclin/zones.txt    28 zones, the Nexus outward
  pop/zones.txt       24 zones, the Plane of Knowledge outward
  custom/zones.txt     custom zones not in a continent list (incl. .eqg zones)
  thule/zones.txt      12 House of Thule zones (.eqg)
  eqg/zones.txt        every other newer .eqg zone, by expansion (Gates of Discord to Rain of Fear)
  eqgzone.py          brickzone for .eqg zones (DXT1/3/5, uncompressed, mips; normal maps left alone)

scripts/
  make_update.py      copy only changed files into transfer batches
  snapshot.py         snapshot tester: render every model in built archives, diff against accepted renders
  review.py           mob review: brick every creature, draw stock/brick/mid-animation, flag likely problems
  review_render.py    review.py's drawing and checks
  fix_flattened.py    finish hiding meshes an older build only half hid (stretched triangles)
  fix_track_scale.py  retired (see its docstring); kept for the record
```

## Building

Originals are read from `<client>/brick_orig/<file>.orig` (untouched copies), else from the client folder.

```
python -I zones/build_continent.py <client> antonica <out>
python -I characters/make_s3d.py <original global<race>_chr.s3d> <out.s3d>
python -I characters/make_armor_sets.py <client> <races out dir> <out>
python -I characters/helmets.py <lgequip_amr.s3d.orig> <out> <client>/brick_orig
python -I characters/hairpieces.py <lgequip.s3d.orig> <out> <client>/brick_orig
python -I characters/robes.py <hair-built lgequip.s3d> <out> <client>/brick_orig
python -I characters/brick_all_copies.py <client> <out> @characters/creatures.txt --read-only -j 4
```

`brick_all_copies.py --read-only` builds every creature copy from an untouched stock client without writing a
`brick_orig` backup into it; `-j` runs several archives at once.

## What the client needs (each of these crashed eqgame in EQGraphicsDX9.dll)

- A replaced mesh (0x36) needs its vertex-texture runs (count, material) as well as its polygon-texture runs.
- Textures: keep every original texture name and put the atlas in each one as DXT1. An uncompressed (A8R8G8B8) atlas
  with every bitmap name pointed at it crashed.
- Vertices are stored in their bone's rest-pose space (`R^T (p - T)`), so the stock animations move the parts.
- Triangles are wound the opposite way to glTF.

Build history and findings: [docs/notes.md](docs/notes.md).

## License

MIT: see [LICENSE](LICENSE). This covers the scripts only. EverQuest and its game files belong to their owners
and are not part of this project.

## Snapshot tester

`scripts/snapshot.py` renders each model in built `.s3d` archives (front, three-quarter, side) and compares the
renders with the last accepted ones, so a model tweak shows exactly what it changed and nothing else.

```
python -I scripts/snapshot.py accept output/creatures            # take the current renders as the baseline
python -I scripts/snapshot.py check  output/creatures            # after a tweak: list changed / new / missing
python -I scripts/snapshot.py show   output/creatures --only SHA # just render, for a quick preview
```

`check` writes an accepted / new / changed-pixels sheet per changed model and a `report.png` of all of them under
`output/snapshots/report`, and exits 1 when anything differs. Each baseline keeps its camera framing, so a part that
grows does not re-zoom the whole render. Old-format `.s3d` models only; `.eqg` models are not drawn yet.

## Mob review

`scripts/review.py` goes through every creature in `characters/creatures.txt` to find the ones that need a tweak:

```
python -I scripts/review.py all <client folder>        # index, build, render (build is slow, and resumes)
python -I scripts/review.py render <client folder> --only SHA,BEA   # redraw a few after a change
```

It reads the stock client (never writes it), bricks each creature once from its own archive into
`output/review/brick`, and draws one picture per creature in `output/review/img`: stock, brick, and the brick model
mid-animation (walk, swim or attack), all from one camera so sizes compare. `output/review/review.json` lists each
creature's flags: `not built`, `apart in motion` (a limb's bricks pull away from its parent's while animating),
`detached`, `empty limb`, `stretched` (sliver triangles), `size`, `sunk`, `few bricks`, `few colors`. The flags only
point at likely problems; the pictures are for judging the look. `build --only` rebuilds every creature in the
archives it touches, so shared archives stay whole.

Creatures in newer `.eqg` models have their own run, with the same pictures and flags (`output/review_eqg`):

```
python -I scripts/review_eqg.py all <client folder> -j 4   # every .eqg creature of the bricked zones and the global list
```

It bricks each with `eqgcreature.py --archive` (each such creature has its own archive, so the built archives are
also the full set for a client), and draws it from its own bones and `.ani` walk. `eqgcreature.py` now anchors limbs
like `brickcreature.py`, gives each head the best eye pair its texture shows (or the pick under `eqg:<code>` in
`creature_eyes.json`), and puts the same bricks in the distance models (`<code>_lod1.mod`...).

### Eyes

Small painted eyes get lost when a head becomes a few bricks, so brick creatures get built eyes: a disc in the stock
eye's color with a pupil and a glint, on the head bricks where the stock eye is. Which spots are eyes is picked by
hand, once, and kept in `characters/creature_eyes.json`:

```
python -I scripts/eyes.py sheet <client folder>         # numbered eye candidates on every stock head
python -I scripts/eyes.py pick RAT=1 SNA=3 BEA=0         # candidate pair per creature, 0 = no eyes
python -I scripts/eyes.py pick KOP=front MAM=side PUS=front:red   # eyes placed by the head's shape instead
python -I scripts/eyes.py sheet <client folder> --none  # the heads with no candidates, to check
```

Candidates are mirrored pairs of small patches that stand out from the skin around them, high on the head; a creature
not in the file gets no eyes. Shaped eyes (`front`, `side`, optional color) are for heads whose eyes don't stand out
in the texture. Creatures without a head bone get none.

### Hunched minifigs

Minifigs sit their hips and shoulders a little below the skeleton's joints, which suits upright figures. Creatures in
`JOINT_FIT` (`brickcreature.py`: those with deep crouching walks) are fitted with the hips and shoulders on their
joints and the body over their spine instead, so their limbs stay on when they move. Brick creatures get a similar
pass: a stray clump of bricks that doesn't touch any of its limb's ancestors moves with the limb it does touch, and a
limb's main clump that floats gets a short bridge of bricks to the nearest ancestor brick.
