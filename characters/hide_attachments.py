"""Fold away every attachment mesh in an archive (Luclin helmets and armor pieces in lgequip_amr*.s3d).

The minifigs show no armor, and these pieces (tinted with the armor color) poke out of the head, like the purple
cap on the Erudite in character creation. Each mesh keeps its layout but draws nothing.

    python -I hide_attachments.py <original .s3d> <out .s3d> [eye atlas .png]

With an atlas, every chr_eye*.dds in the archive gets it (frogequip.s3d holds the Froglok's eye-color textures, and
the Froglok's head pieces sit on the eye material: make_s3d.py EYE_HEAD).
"""
import os, sys

_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(_root, d) for d in ('lib', 'characters', 'zones')]
import make_s3d, pfs, wld


def main():
    src, dst = sys.argv[1:3]
    files = pfs.read(src)
    wld_name, wld_data = next((n, b) for n, b in files if n.endswith('.wld'))
    w = wld.Wld(wld_data)
    frags = [(t, make_s3d.flatten_mesh(raw) if t == 0x36 else raw) for t, _n, raw in w.frags[1:]]
    eye = None
    if len(sys.argv) > 3:
        from PIL import Image
        eye = make_s3d.dds_dxt1(Image.open(sys.argv[3]).convert('RGB'))
    new_wld = make_s3d.write_wld(wld_data, frags)
    pfs.write(dst, [(n, new_wld if n == wld_name else eye if eye and n.startswith('chr_eye') else b) for n, b in files])
    print(f'hid {sum(1 for t, _ in frags if t == 0x36)} meshes -> {dst}')


if __name__ == '__main__':
    main()
