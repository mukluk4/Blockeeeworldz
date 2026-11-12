# Build notes (history)

Toy-brick minifig versions of EverQuest player models for the RoF2 client. Local experiment, not part of
any repository or the patcher.

## Status (2026-11-09)

- All 28 player race models (14 races, male and female; not Froglok or Drakkin) are built in `output/races/` and
  installed in the client folder, each original saved beside it as
  `global<race>_chr.s3d.orig` (checked identical to the `_OG` copy). Only the male Dwarf has been seen in game so far.
- Every race is yellow except Dark Elves (dark blue-grey), Erudites (reddish brown) and Trolls (green), per the user. Races differ by
  hair, ears (elf, cat), tails (Iksar, Vah Shir), a lizard mask (Iksar), a belly (Ogres, Halflings) and clothing colors: see `RACES` in `minifig.py`.
- `output/races/all_races.png` is a contact sheet of every race (the quick previewer smears the face print; the real
  print is in each `_atlas.png`).
- The working male Dwarf build is kept as `output/globaldwm_chr_minifig_v1.s3d` (and the scripts that made it as
  the v1 scripts (not kept in the repo)). The new build has the same body, plus its eye meshes folded away.
- The client draws each race's classic model in the same spot as its Luclin model, so the classic Ogre and Troll
  bellies poked through the minifig. `hide_classic.py` folds away the classic meshes of all 26 classic player
  models (built as `output/global_chr.s3d` and `output/global4_chr.s3d`; originals saved as `.orig` in the client).
  Every `UseLuclin...` in eqclient.ini is TRUE; with one set to FALSE that race would be invisible.
- Originals are kept in `<client>\brick_orig\<file>.orig`, not beside the client files: with the `.orig`
  copies in the game folder the client seemed to draw the original models too (hair, Ogre/Troll bellies). Being
  tested 2026-11-09. Build from the copies in `brick_orig`.
- Found 2026-11-09 with Process Monitor: Luclin hair styles (IT1000-1812), beards/mustaches/sideburns
  (IT2000-2784) and robes/tunics/skirts/kilts/hoods (IT4000-4832) are attachment models in `lgequip.s3d` and
  `lgequip2.s3d`, drawn at the original head/body spot. They caused the Halfling bun, Dwarf face blob and Ogre/Troll
  "bellies". All 262 are folded away (`output/lgequip*.s3d`, originals in `brick_orig`). Confirmed in game. The
  classic-model hiding in `global_chr.s3d`/`global4_chr.s3d` was not the cause and is reverted (stock files back).
  Hair and beards (2026-11-09): `hairpieces.py` swaps each hair/beard model for a brick piece on the minifig head
  placed for the race whose original head it fits, through the attachment's own skeleton and the race's
  HAIR_POINT / BEARD_POINT bone (beard sets: Dwarf 2120, Halfling 2000 and 2780, Barbarian 2360/2480/2540). Kept simple on purpose (user's call): hair is short, long or
  bald (no-hair choice), each race's set has at least one short and one long; facial hair is mustache, beard or none (first choice of each set is the mustache; the client fixes the count),
  and every male Dwarf beard option is his triangle beard. The race bodies no longer carry built-in hair or the Dwarf
  beard (BAKED_HAIR=1 / BAKED_BEARD=1 bring them back for previews). Textures become flat grey so the client's
  hair-color tint still applies. Robes stay hidden. The male Dwarf no longer wears the horned helmet (user's call); he gets the hair choices too. Output `output/hair/lgequip*.s3d` (installed),
  style list in `output/hair/lgequip*_styles.json`, render check `output/hair/hair_check.png`. Untested in game.
- Launch with `eqgame.exe patchme`, not a server patcher: a patcher restores the original files.
- Next, agreed with the user: zone texture restyle (one classic zone first), then brick-built creatures (old .s3d
  ones first). Froglok (own skeleton) and Drakkin (.eqg) are not done.

## Tools (now in `lib/`, `characters/`, `zones/`; run with `python -I`)

| Script | What it does |
|---|---|
| `pfs.py` | Read and write .s3d (PFS) archives: `list`, `extract`. |
| `wld.py` | Read meshes, materials and the rest-pose skeleton from an old-format .wld. |
| `export.py` | Pose an archive's model on its skeleton and write a .glb plus a preview (`<s3d> <out.glb> <preview.png> [armor set]`). |
| `brickify.py` | First try: restyle textures only (plastic colors). Superseded by the minifig. |
| `minifig.py` | The minifig, designed on the Dwarf skeleton: parts, prints, per-race looks (`RACES`), `fit()` onto another race's skeleton, tails. Writes a .glb preview. |
| `make_s3d.py` | Builds a race's game archive: `make_s3d.py <original global<race>_chr.s3d> <out.s3d>` (race read from the skeleton). Also writes `_atlas.png` and `_preview.png`. |
| `hide_attachments.py` | Folds away every attachment mesh in an archive; used on `lgequip_amr.s3d` / `lgequip_amr2.s3d` (Luclin helmets and armor pieces, IT5000+), which poked out of the Erudite head. |
| (skin colors) | `make_s3d.py` gives races with `skin_colors` (Iksar: green, sand, rust, teal; Vah Shir: orange, grey, black, cream; Troll: green, olive, slate, mauve; Froglok: lime, forest, blue, orange) their skin parts on the head material `<P>HE0001_MDF`; each head texture (<race>he<set|sk><face><part>: the face digit) gets the atlas in one color. Sculpted heads (no face print): Iksar lizard, Drakkin dragon, Vah Shir cat, Troll, Froglok (`globalpcfroglok_chr.s3d`, both genders in one file). |
| `make_drakkin.py` | Brick Drakkin (`dkm.eqg` / `dkf.eqg`, EQG format via `eqgmod.py`): minifig with a dragon head, every triangle on the head material so the face choice sets the color (green, red, black, blue, repeating); hair, facial hair, horns, tattoos and armor pieces folded away. Untested in game. |
| `eqgmod.py` | Reads/writes EQG `.mod` models (round-trips every Drakkin model exactly). |
| `hairpieces.py` | Minifig hair/beard attachment pieces (`hairpieces.py <lgequip.s3d.orig> <out> <brick_orig folder>`). |
| `hide_classic.py` | Folds away the classic (pre-Luclin) body and head meshes of the listed races in `global_chr.s3d` / `global4_chr.s3d` (`hide_classic.py <original> <out> OGM OGF ...`). |

## What the client needs (each of these crashed eqgame in EQGraphicsDX9.dll)

- A replaced mesh (0x36) needs its vertex-texture runs (count, material) as well as its polygon-texture runs.
- Textures: keep every original texture name and put the atlas in each one as DXT1. An uncompressed (A8R8G8B8) atlas
  with every bitmap name pointed at it crashed.
- Vertices are stored in their bone's rest-pose space (`R^T (p - T)`), so the stock animations move the parts.
- Triangles are wound the opposite way to glTF.

## 2026-11-10: Faydwer, Odus, big races, faces, Frogloks
- Faydwer (15 zones) and Odus (9 zones) built from `zones/<continent>/zones.txt`; their creature types are in
  `characters/creatures.txt`. Some DXT1 textures carry extra bytes after the image; brickzone keeps them.
- Old two-letter models (KA, CL) parse as prefix + part; `texture_owner` keeps KA and KAF textures apart.
- Minifig NPC texture variants: the body uses a material whose texture has every variant (giants used to pick
  `giahe0019`, which has none). Each variant gets its own face print (`minifig.face_marks`); giants take their skin
  from their upper-arm texture (`'skin': 'upper'`).
- Dragons (DRA): the head and jaw bones' voxels are replaced by a sculpted head (`dragon_head`); kobolds have dog heads.
- 2026-11-11: the other dragons (DR2 BWD CCD PRI TRK DRU GDR), drakes (DRK), wurms (WUR) and wyverns (WYV) get the
  same sculpted head, fitted to their own head and jaw meshes (`head_fit`) and colored from their own bricks
  (`own_scheme`); the Velious dragons' heads are boosted 2.2x (DRU 1.6x) to read at their brick size. Rebuilding
  an archive can hand shared-name textures to another creature (wolf, BKN, SRG, SSN): merge only the rebuilt
  creature's pieces into the delivered file.
- 2026-11-11: rebuild the shrunk races with `make_s3d.py` (+ `racescale.py` for _chr2), never by splicing tracks
  or meshes into delivered files (`scripts/fix_track_scale.py` is retired: it lost the weapon grip and brought old
  UVs back, Ogre armor showed on the face).
- Helmets hang on HAIR_POINT, except Dwarf/Troll/Ogre/Halfling/Iksar/Vah Shir females on HEAD_POINT (`HEAD_FRAME`):
  on ten races the two frames are 120 degrees apart, and the wrong one lays the hat on its side. Erudite females
  stay on HAIR_POINT. The shape fit can't pick the frame (checked in game 2026-11-11).
- Barbarians shrink by 6/7, Trolls and Ogres to the Barbarians' height (`lib/racescale.py`, 2026-11-11; 6/8 and 6/9
  made them too small): every track offset and bone-space
  vertex times k, root frames lowered so the feet stay down. Their `global<race>_chr2.s3d` (extra animations) must
  be shrunk and shipped too, and their hair/beard/helmet pieces. Collision and camera stay full size.
- Track frames (0x12) are rotation w x y z, shift x y z, bone SCALE: the client reads the offset as shift / 256 and
  the last value / 256 as the bone's scale (shoulder bones 333, butt bone 6). Treating it as a divisor and raising it
  made the shrunk races' bones grow, compounding down the skeleton: giant heads in character select (fixed
  2026-11-11, `scripts/fix_track_scale.py` for built files). `wld.track_frame` still reads shift / value.
- Head parts use the head material (`<P>HE0001_MDF`); on the chest material a dyed breastplate tinted faces and
  eyes.
- Frogloks keep their own helmets, robes and shoulder/arm pieces in `frogequip.s3d` (IT4840-4876, IT5841-5873,
  IT78xx, IT88xx): all hidden, so Frogloks wear no hats.
- Hair/beard pieces are matched to races by head shape (voting), not by the helmet race order; the two disagree (position order tried 2026-11-11: giant hair on Ogres/Trolls/Barbarians, reverted)
  everywhere. Untested whether the shape matches are right for every race.

## Plane of Fear heads (2026-11-11)
- Samhain (SCA, scarecrow minifig): `head: 'pumpkin'` in brickcreature PEOPLE swaps the minifig head for a carved
  jack-o'-lantern (pumpkin_parts). Rebuilt all six archives holding SCA, merged with only `sca*` files + wld taken.
- Amygdalan (MYG, myg.eqg): eqgcreature HEADS = {'MYG': squid_head}; the drawn HE piece's box sizes a purple
  mantle, eyes and six tentacles (tentacles on JAW). Voxels on HEAD*/JAW/EAR bones are dropped.
- The Fear/Justice/Time Amygdalan knights and warriors are race 99, which the client draws with model DEN (a
  minifig here, `head: 'squid'`), not amy.eqg. squid_head now lives in brickcreature.py (eqgcreature uses it too).
