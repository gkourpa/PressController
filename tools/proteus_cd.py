"""Read Proteus' installation CD as data: unpack it, list the commands it sends.

Nothing on the CD is ever run. The installer's archive (InstallShield 5,
data1.hdr + data1.cab; format as documented by the unshield project) is read
with zlib, and proteus.exe is searched byte by byte.

Usage:
    python tools/proteus_cd.py unpack   data/proteus_cd  out/proteus_cd
    python tools/proteus_cd.py commands out/proteus_cd/_root/proteus.exe

`commands` finds every place the program passes a fixed code to its DigiMaxx
"send #B" / "send #D" methods (virtual-method slots 0x88 and 0x8C):
`mov edx, <string literal>` followed within a few instructions by
`call dword ptr [reg + 0x88 or 0x8C]`. Codes computed at run time (the ramp,
the stream interval, the machine number) are not fixed and are not listed.
"""

import argparse
import re
import struct
import sys
import zlib
from collections import Counter
from pathlib import Path

ISC_SIGNATURE = 0x28635349  # "ISc("
FLAG_COMPRESSED, FLAG_INVALID = 4, 8


def unpack(cd, out):
    h = (cd / "data1.hdr").read_bytes()
    cab = (cd / "data1.cab").read_bytes()
    sig, version, _, cd_off, _ = struct.unpack_from("<5I", h, 0)
    if sig != ISC_SIGNATURE or (version >> 12) & 0xF != 5:
        sys.exit(f"not an InstallShield 5 header: {sig:#x} {version:#x}")
    ft = cd_off + struct.unpack_from("<I", h, cd_off + 0x0C)[0]
    n_dirs = struct.unpack_from("<I", h, cd_off + 0x1C)[0]
    n_files = struct.unpack_from("<I", h, cd_off + 0x28)[0]
    offsets = struct.unpack_from(f"<{n_dirs + n_files}I", h, ft)

    def cstr(pos):
        return h[pos:h.index(b"\0", pos)].decode("latin-1")

    dirs = [cstr(ft + offsets[i]) for i in range(n_dirs)]
    for i in range(n_files):
        p = ft + offsets[n_dirs + i]
        name_off, dir_idx, flags, size, packed = struct.unpack_from("<IIHII", h, p)
        data_off = struct.unpack_from("<I", h, p + 18 + 0x14)[0]
        if flags & FLAG_INVALID:
            continue
        raw = cab[data_off:data_off + packed]
        if flags & FLAG_COMPRESSED:  # blocks of: u16 length, raw deflate
            data, q = bytearray(), 0
            while q < len(raw):
                n = struct.unpack_from("<H", raw, q)[0]
                data += zlib.decompressobj(-15).decompress(raw[q + 2:q + 2 + n])
                q += 2 + n
        else:
            data = raw
        if len(data) != size:
            print(f"size mismatch: {cstr(ft + name_off)}", file=sys.stderr)
        dest = out / (dirs[dir_idx].replace("\\", "_") or "_root") / cstr(ft + name_off)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    print(f"{n_files} files into {out}")


def _sections(b):
    pe = struct.unpack_from("<I", b, 0x3C)[0]
    count = struct.unpack_from("<H", b, pe + 6)[0]
    opt = struct.unpack_from("<H", b, pe + 20)[0]
    base = struct.unpack_from("<I", b, pe + 52)[0]
    for i in range(count):
        o = pe + 24 + opt + 40 * i
        vsize, rva, rsize, raw = struct.unpack_from("<4I", b, o + 8)
        yield b[o:o + 8].rstrip(b"\0").decode(), base + rva, raw, rsize


def commands(exe):
    b = exe.read_bytes()
    name, code_va, code_raw, code_size = next(_sections(b))
    delta = code_va - code_raw

    def literal(va):  # a Delphi string constant: length in the 4 bytes before it
        o = va - delta
        if not code_raw <= o < code_raw + code_size:
            return None
        n = struct.unpack_from("<I", b, o - 4)[0]
        s = b[o:o + n]
        return s.decode() if 0 < n < 8 and s.isdigit() else None

    found = Counter()
    send = re.compile(rb"\xff[\x90-\x97](\x88|\x8c)\x00\x00\x00")
    for m in re.finditer(rb"\xba(....)", b[code_raw:code_raw + code_size], re.S):
        code = literal(struct.unpack("<I", m.group(1))[0])
        if code is None:
            continue
        start = code_raw + m.end()
        call = send.search(b, start, start + 12)
        if call:
            found[("#B" if call.group(1) == b"\x88" else "#D") + code] += 1
    for cmd, n in sorted(found.items()):
        print(f"{cmd:6} x{n}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="what", required=True)
    u = sub.add_parser("unpack")
    u.add_argument("cd", type=Path)
    u.add_argument("out", type=Path)
    c = sub.add_parser("commands")
    c.add_argument("exe", type=Path)
    args = ap.parse_args()
    if args.what == "unpack":
        unpack(args.cd, args.out)
    else:
        commands(args.exe)


if __name__ == "__main__":
    main()
