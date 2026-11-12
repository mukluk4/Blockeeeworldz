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
  eqgzone.py          brickzone for .eqg zones (DXT1/3/5, uncompressed, mips; normal maps left alone)

scripts/
  make_update.py      copy only changed files into transfer batches
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
```

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
