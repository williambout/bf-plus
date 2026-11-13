#!/usr/bin/env python3
"""Package the optional Doom engine and a user-supplied IWAD for BF+."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import struct
import zlib

HEADER = struct.Struct('<8s14I64s')
MAGIC = b'BFPDOOM1'
MAX_MODULE = 4 * 1024 * 1024
MAX_WAD = 64 * 1024 * 1024
DEFAULT_HEAP = 24 * 1024 * 1024


def mtp_send_chunks(send, raw, deadline):
    """One PTP container, bounded USB writes; no retry after a short write.

    Intermediate chunks are a multiple of the USB packet size, including the
    first chunk's PTP header. Only the final USB write can be a short packet.
    The caller keeps the same transaction and deadline for the whole stream.
    """
    for offset in range(0, len(raw), 4096):
        send(raw[offset:offset+4096], deadline)


def save_receipt(path, record):
    temporary = path.with_suffix('.tmp')
    with temporary.open('w') as stream:
        json.dump(record, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read_module(path):
    """Extract only a bounded, self-contained little-endian AArch64 PIE.

    The external loader accepts relative data relocations only. It cannot
    resolve imports or patch instructions. All offsets are module-relative.
    """
    raw = Path(path).read_bytes()
    require(len(raw) >= 64 and raw[:7] == b'\x7fELF\x02\x01\x01', 'Expected ELF64 little endian')
    fields = struct.unpack_from('<HHIQQQIHHHHHH', raw, 16)
    kind, machine, version, entry, phoff, shoff, flags, ehsize, phsize, phnum, shsize, shnum, _ = fields
    require(kind == 3 and machine == 183 and version == 1 and ehsize == 64,
            'Expected an AArch64 position-independent executable')
    require(phsize == 56 and 0 < phnum <= 32 and phoff + phsize * phnum <= len(raw),
            'Invalid ELF segments')
    require(shsize == 64 and 0 < shnum <= 512 and shoff + shsize * shnum <= len(raw),
            'Invalid ELF sections')
    segments = []
    for i in range(phnum):
        typ, perms, off, va, _, filesz, memsz, align = struct.unpack_from('<II6Q', raw, phoff + 56 * i)
        if typ != 1:
            continue
        require(filesz <= memsz and off + filesz <= len(raw) and va + memsz <= MAX_MODULE,
                'Module segment is out of bounds')
        require(not (perms & 2 and perms & 1), 'Writable executable segment')
        segments.append((va, filesz, memsz, off, perms))
    segments.sort()
    require(segments and segments[0][0] == 0, 'Module must be linked at zero')
    for a, b in zip(segments, segments[1:]):
        require(a[0] + a[2] <= b[0], 'Overlapping module segments')
    image_size = (max(v + f for v, f, _, _, _ in segments) + 63) & ~63
    memory_size = (max(v + m for v, _, m, _, _ in segments) + 63) & ~63
    require(image_size <= memory_size <= MAX_MODULE, 'Module exceeds 4 MiB')
    require(any(v <= entry < v + f and p & 1 for v, f, _, _, p in segments), 'Entry is outside code')
    writable = [(v, v + f) for v, f, _, _, p in segments if p & 2 and f]
    require(writable, 'Module has no initialized writable segment')
    data_start, data_end = min(a for a, _ in writable), max(b for _, b in writable)
    image = bytearray(image_size)
    for va, filesz, _, off, _ in segments:
        image[va:va + filesz] = raw[off:off + filesz]
    relocs = []
    for i in range(shnum):
        _, typ, sflags, va, off, size, link, info, align, entsize = struct.unpack_from('<II4QII2Q', raw, shoff + 64 * i)
        if typ == 9 and size:
            raise ValueError('ELF REL relocations are unsupported')
        if typ != 4 or not size:
            continue
        require(entsize == 24 and size % 24 == 0 and off + size <= len(raw), 'Invalid RELA section')
        for j in range(off, off + size, 24):
            target, what, addend = struct.unpack_from('<QQq', raw, j)
            require(what == 1027, 'Module has an import or nonrelative relocation')
            require(target % 8 == 0 and any(a <= target <= b - 8 for a, b in writable),
                    'Relocation writes outside initialized data')
            require(0 <= addend < memory_size, 'Relocation points outside module')
            relocs.append((target, addend))
    relocs.sort()
    require(len(relocs) <= 16384 and len({r[0] for r in relocs}) == len(relocs),
            'Too many or duplicate relocations')
    require(entry % 4 == 0 and entry < data_start, 'Invalid module entry')
    return bytes(image), memory_size, entry, data_start, data_end, relocs


def validate_wad(wad):
    require(12 <= len(wad) <= MAX_WAD and wad[:4] == b'IWAD', 'Supply a complete Doom-compatible IWAD')
    count, directory = struct.unpack_from('<II', wad, 4)
    require(0 < count <= 65536 and directory >= 12 and directory + count * 16 <= len(wad),
            'Invalid WAD directory')
    names = set()
    for offset in range(directory, directory + count * 16, 16):
        start, size, name = struct.unpack_from('<II8s', wad, offset)
        require(start <= len(wad) and size <= len(wad) - start, 'WAD lump is out of bounds')
        names.add(name.rstrip(b'\0'))
    require({b'PLAYPAL', b'COLORMAP'}.issubset(names) and
            (b'E1M1' in names or b'MAP01' in names), 'IWAD lacks Doom maps or palette')


def package(module, wad_path, output):
    image, memory_size, entry, data_start, data_end, relocs = read_module(module)
    wad = Path(wad_path).read_bytes()
    validate_wad(wad)
    relocation_data = b''.join(struct.pack('<QQ', *r) for r in relocs)
    reloc_offset = 128 + len(image)
    wad_offset = reloc_offset + len(relocation_data)
    header = HEADER.pack(MAGIC, 1, 128, wad_offset + len(wad), len(image), memory_size,
                         entry, reloc_offset, len(relocs), wad_offset, len(wad),
                         DEFAULT_HEAP, data_start, data_end, 0, bytes(64))
    result = bytearray(header + image + relocation_data + wad)
    struct.pack_into('<I', result, 60, zlib.crc32(result))
    verify(result)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as f:
        f.write(result)
    report = {'package': str(path), 'bytes': len(result), 'sha256': hashlib.sha256(result).hexdigest(),
              'module_bytes': len(image), 'module_memory': memory_size, 'relocations': len(relocs),
              'wad_sha256': hashlib.sha256(wad).hexdigest(), 'heap_bytes': DEFAULT_HEAP}
    return report


def verify(raw):
    require(len(raw) >= 128, 'Truncated package')
    magic, abi, hdr, total, image, memory, entry, reloc, count, wad_at, wad_len, heap, first, last, crc, reserved = HEADER.unpack_from(raw)
    require(magic == MAGIC and abi == 1 and hdr == 128 and not any(reserved), 'Unsupported package header')
    require(4 <= image <= memory <= MAX_MODULE and memory % 64 == 0 and
            entry % 4 == 0 and entry < first <= last <= image and first >= 4,
            'Invalid module extent')
    require(reloc == 128 + image and reloc % 8 == 0 and count <= 16384 and
            wad_at == reloc + count * 16 and total == wad_at + wad_len == len(raw) and
            8 * 1024 * 1024 <= heap <= 32 * 1024 * 1024 and heap % 64 == 0,
            'Invalid package layout')
    checksum = zlib.crc32(raw[:60])
    checksum = zlib.crc32(bytes(4), checksum)
    checksum = zlib.crc32(raw[64:], checksum)
    require(checksum == crc, 'Package checksum mismatch')
    previous = -1
    for i in range(count):
        target, addend = struct.unpack_from('<QQ', raw, reloc + 16 * i)
        require(target % 8 == 0 and first <= target <= last - 8 and target > previous and addend < memory,
                'Invalid module relocation')
        previous = target
    validate_wad(raw[wad_at:])
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'wad_bytes': wad_len}


def upload(path):
    """Experimental MTP path; SendObject times out on the tested BF 1.04.

    Use Mass Storage to copy DOOM.BFP. This path remains for investigation.

    Existing objects are preserved. A failed/uncertain transfer is never
    retried, deleted, resumed, or converted to a vendor memory write.
    """
    from bfplus_camera_files import CameraFiles, DataBound
    from bfplus_ptp import RESPONSE, ProtocolError

    class PackageFiles(CameraFiles):
        response_parameters = ()

        def _send(self, raw, deadline):
            return mtp_send_chunks(super()._send, raw, deadline)

        def _receive(self, operation, tid, expected_data, deadline):
            result = super()._receive(operation, tid, expected_data, deadline)
            kind, _, data = result
            if kind == RESPONSE:
                self.response_parameters = struct.unpack(f'<{len(data)//4}I', data)
            return result

        def send_file_data(self, operation, params, raw):
            self._require_open()
            self._stamp_write()
            try:
                self._exchange(operation, params, outgoing=raw)
                return self.response_parameters
            finally:
                self._stamp_write()

    raw = Path(path).read_bytes()
    report = verify(raw)
    with PackageFiles(timeout_ms=30000) as p:
        for handle in p.handles():
            if p.info(handle)['filename'].upper() == 'DOOM.BFP':
                raise FileExistsError('DOOM.BFP already exists; preserved. Remove/replace it manually before another upload.')
        _, storage = p._exchange(0x1004, expected_data=DataBound(4,132))
        count = struct.unpack_from('<I', storage)[0]
        require(count == 1 and len(storage) == 8, 'Expected exactly one camera storage')
        storage_id = struct.unpack_from('<I', storage, 4)[0]
        info = bytearray(52)
        struct.pack_into('<I', info, 0, storage_id)
        struct.pack_into('<H', info, 4, 0x3000)  # Undefined file, not a photograph.
        struct.pack_into('<I', info, 8, len(raw))
        name = 'DOOM.BFP\0'.encode('utf-16-le')
        info += bytes([len(name)//2]) + name + bytes(3)
        receipt = Path(path).with_name(f'.DOOM-transfer-{secrets.token_hex(8)}.json')
        record = {**report, 'filename': 'DOOM.BFP', 'storage_id': storage_id, 'phase': 'creating'}
        save_receipt(receipt, record)
        # Respect outstanding calibration work before starting the ordinary
        # MTP transaction pair. SendObject immediately follows SendObjectInfo:
        # inserting the vendor-write cooldown between these can time it out.
        p._wait_for_write()
        try:
            response = p.send_file_data(0x100c, (storage_id, 0xffffffff), bytes(info))
            if len(response) != 3 or response[0] != storage_id or not response[2]:
                raise ProtocolError('Unexpected SendObjectInfo response; no retry made')
            handle = response[2]
            record.update(handle=handle, phase='sending')
            save_receipt(receipt, record)
            p.send_file_data(0x100d, (), raw)
            record['phase'] = 'verifying'
            save_receipt(receipt, record)
            saved = p.info(handle)
            require(saved['bytes'] == len(raw) and saved['filename'] == 'DOOM.BFP',
                    'Uploaded object metadata mismatch; no retry made')
            _, readback = p._exchange(0x1009, (handle,), expected_data=len(raw))
            require(readback == raw, 'Uploaded game package readback mismatch; no retry made')
            record['phase'] = 'verified'
            save_receipt(receipt, record)
        except BaseException as error:
            record.update(phase='uncertain', error=str(error))
            try:
                save_receipt(receipt, record)
            except OSError as failure:
                error.add_note(f'Could not save transfer outcome: {failure}')
            raise
    return {**report, 'handle': handle, 'filename': 'DOOM.BFP', 'readback_verified': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('package', help='Combine a built engine and your IWAD; no camera access')
    p.add_argument('--module', type=Path, required=True)
    p.add_argument('--wad', type=Path, required=True)
    p.add_argument('--output', type=Path, default=Path('.touch-focus/doom/DOOM.BFP'))
    p = commands.add_parser('check', help='Validate a package without running it')
    p.add_argument('package', type=Path)
    p = commands.add_parser('upload', help='Experimental MTP transfer; use Mass Storage on BF 1.04 (see docs/DOOM.md)')
    p.add_argument('package', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'package':
            result = package(args.module, args.wad, args.output)
        elif args.command == 'upload':
            result = upload(args.package)
        else:
            result = verify(args.package.read_bytes())
    except (ValueError, OSError) as error:
        parser.exit(1, f'{error}\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
