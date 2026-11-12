"""Read and write EverQuest PFS archives (.s3d / .eqg / .pak)."""
import os, struct, sys, zlib

NAMES_CRC = 0x61580AC9


def _crc_table():
    table = []
    for i in range(256):
        c = i << 24
        for _ in range(8):
            c = ((c << 1) ^ 0x04C11DB7) if c & 0x80000000 else (c << 1)
        table.append(c & 0xFFFFFFFF)
    return table


_TABLE = _crc_table()


def name_crc(name):
    # EQ's filename CRC: CRC-32 (non-reflected) over the lower-case name plus its terminating null
    crc = 0
    for b in name.lower().encode('latin-1') + b'\0':
        crc = ((crc << 8) ^ _TABLE[((crc >> 24) ^ b) & 0xFF]) & 0xFFFFFFFF
    return crc


def _inflate(data, offset, size):
    out = bytearray()
    while len(out) < size:
        deflen, inflen = struct.unpack_from('<II', data, offset)
        offset += 8
        out += zlib.decompress(data[offset:offset + deflen])
        offset += deflen
    return bytes(out)


def read(path):
    """Returns [(name, bytes)] in archive order."""
    data = open(path, 'rb').read()
    dir_off, magic, _ver = struct.unpack_from('<I4sI', data, 0)
    if magic != b'PFS ':
        sys.exit(f'{path}: not a PFS archive')
    count, = struct.unpack_from('<I', data, dir_off)
    entries = [struct.unpack_from('<III', data, dir_off + 4 + 12 * i) for i in range(count)]
    files, names = [], []
    for crc, off, size in entries:
        blob = _inflate(data, off, size)
        if crc == NAMES_CRC:
            n, = struct.unpack_from('<I', blob, 0)
            p = 4
            for _ in range(n):
                ln, = struct.unpack_from('<I', blob, p)
                names.append(blob[p + 4:p + 4 + ln].rstrip(b'\0').decode('latin-1'))
                p += 4 + ln
        else:
            files.append((off, crc, blob))
    files.sort()  # names are listed in data order
    by_crc = {name_crc(n): n for n in names}
    return [(by_crc.get(crc, names[i] if i < len(names) else f'unknown_{crc:08x}'), blob)
            for i, (off, crc, blob) in enumerate(files)]


def write(path, files, footer=b'STEVE' + bytes(4)):
    out = bytearray(struct.pack('<I4sI', 0, b'PFS ', 0x20000))
    entries = []

    def put(blob):
        off = len(out)
        for i in range(0, len(blob), 8192) or [0]:
            chunk = blob[i:i + 8192]
            z = zlib.compress(chunk, 9)
            out.extend(struct.pack('<II', len(z), len(chunk)) + z)
        return off

    for name, blob in files:
        entries.append((name_crc(name), put(blob), len(blob)))
    names = bytearray(struct.pack('<I', len(files)))
    for name, _ in files:
        b = name.lower().encode('latin-1') + b'\0'
        names += struct.pack('<I', len(b)) + b
    entries.append((NAMES_CRC, put(bytes(names)), len(names)))
    entries.sort()  # the client looks entries up by CRC
    struct.pack_into('<I', out, 0, len(out))
    out += struct.pack('<I', len(entries))
    for e in entries:
        out += struct.pack('<III', *e)
    out += footer  # usually 'STEVE' and a date; some zone archives have none
    open(path, 'wb').write(out)


if __name__ == '__main__':
    cmd, arc = sys.argv[1], sys.argv[2]
    if cmd == 'list':
        for n, b in read(arc):
            print(f'{len(b):9d}  {n}')
    elif cmd == 'extract':
        dest = sys.argv[3]
        os.makedirs(dest, exist_ok=True)
        for n, b in read(arc):
            open(os.path.join(dest, n), 'wb').write(b)
