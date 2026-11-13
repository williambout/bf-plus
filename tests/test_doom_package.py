"""Offline Doom package tests: real host C validators and synthetic ELF/IWAD.

No engine build, firmware, USB, or .touch-focus fixtures are required. The C
validator deliberately treats the WAD as opaque; Python checks its directory.
"""
import ctypes as C
import hashlib
import json
from pathlib import Path
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

import bfplus_doom as doom


ROOT = Path(__file__).resolve().parents[1]
FIELDS = dict(zip(('abi', 'header', 'total', 'image', 'memory', 'entry',
                   'reloc', 'count', 'wad_at', 'wad_len', 'heap', 'first',
                   'last', 'crc'), range(8, 64, 4)))


def checksum(raw):
    raw = bytearray(raw)
    struct.pack_into('<I', raw, 60, 0)
    struct.pack_into('<I', raw, 60, zlib.crc32(raw))
    return bytes(raw)


def change_header(raw, **fields):
    raw = bytearray(raw)
    for name, value in fields.items():
        struct.pack_into('<I', raw, FIELDS[name], value)
    return checksum(raw)


def minimal_iwad(map_name=b'E1M1'):
    # Three real directory entries, including a zero-length map marker at EOF.
    payload = bytes(range(32))
    directory = 12 + len(payload)
    end = directory + 3 * 16
    return (struct.pack('<4sII', b'IWAD', 3, directory) + payload +
            struct.pack('<II8s', 12, 16, b'PLAYPAL') +
            struct.pack('<II8s', 28, 16, b'COLORMAP') +
            struct.pack('<II8s', end, 0, map_name))


def synthetic_package(image_size=128, memory=192, relocs=None,
                      heap=24 * 1024 * 1024, map_name=b'E1M1'):
    first = image_size // 2
    if relocs is None:
        relocs = [(first, 0), (first + 8, image_size), (image_size - 8, memory - 1)]
    image = bytes((i * 37 + 11) & 255 for i in range(image_size))
    relocation_data = b''.join(struct.pack('<QQ', *r) for r in relocs)
    wad = minimal_iwad(map_name)
    reloc_at = 128 + image_size
    wad_at = reloc_at + len(relocation_data)
    header = struct.pack('<8s14I64s', b'BFPDOOM1', 1, 128, wad_at + len(wad),
                         image_size, memory, 4, reloc_at, len(relocs), wad_at,
                         len(wad), heap, first, image_size, 0, bytes(64))
    return checksum(header + image + relocation_data + wad)


def synthetic_elf():
    """A bounded ELF64 AArch64 PIE with RX, RW+BSS, and unsorted RELA."""
    raw = bytearray(0x480)
    raw[:16] = b'\x7fELF\x02\x01\x01' + bytes(9)
    struct.pack_into('<HHIQQQIHHHHHH', raw, 16,
                     3, 183, 1, 4, 64, 0x400, 0, 64, 56, 2, 64, 2, 0)
    struct.pack_into('<II6Q', raw, 64, 1, 5, 0x200, 0, 0, 64, 64, 64)
    struct.pack_into('<II6Q', raw, 120, 1, 6, 0x280, 128, 128, 64, 128, 64)
    raw[0x200:0x240] = bytes(range(64))
    raw[0x280:0x2c0] = bytes(range(64, 128))
    struct.pack_into('<QQqQQq', raw, 0x300, 184, 1027, 255, 128, 1027, 0)
    struct.pack_into('<II4QII2Q', raw, 0x440,
                     0, 4, 2, 0, 0x300, 48, 0, 0, 8, 24)
    return bytes(raw)


PACKAGE_C = r'''
#include "bfplus/doom_package.h"
int package_verify(const void *p, size_t n) { return doom_package_verify(p,n); }
int package_header(const void *p) { return doom_package_header(p); }
size_t package_allocation(const void *p) { return doom_package_allocation(p); }
uint32_t package_crc(uint32_t crc,const void *p,size_t n) {
    return doom_crc32(crc,p,n);
}
#ifdef GUARDED_MAIN
#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <unistd.h>
int main(int argc,char **argv) {
    if (argc!=3) return 2;
    FILE *f=fopen(argv[1],"rb");
    if (!f || fseek(f,0,SEEK_END)) return 3;
    long length=ftell(f);
    if (length<0 || fseek(f,0,SEEK_SET)) return 4;
    size_t n=(size_t)length, page=(size_t)sysconf(_SC_PAGESIZE);
    size_t padded=(n+7)&~(size_t)7, span=(padded+page-1)/page*page;
    if (!span) span=page;
    uint8_t *map=mmap(NULL,span+2*page,PROT_NONE,MAP_PRIVATE|MAP_ANON,-1,0);
    if (map==MAP_FAILED || mprotect(map+page,span,PROT_READ|PROT_WRITE)) return 5;
    uint8_t *file=map+page+span-padded;
    if (fread(file,1,n,f)!=n) return 6;
    fclose(f);
    if (mprotect(map+page,span,PROT_READ)) return 7;
    /* A write, or an over-read beyond the rounded file extent, faults here. */
    int accepted=doom_package_verify(file,n);
    munmap(map,span+2*page);
    return accepted==atoi(argv[2]) ? 0 : 8;
}
#endif
'''


class DoomPackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc = shutil.which('cc') or shutil.which('clang')
        if not cc:
            raise unittest.SkipTest('host C compiler required')
        cls.directory = tempfile.TemporaryDirectory(prefix='bf-doom-package-')
        cls.addClassCleanup(cls.directory.cleanup)
        cls.work = Path(cls.directory.name)
        source = cls.work / 'package.c'
        source.write_text(PACKAGE_C)
        library = cls.work / 'package.so'
        flags = [cc, '-std=c11', '-D_DEFAULT_SOURCE', '-O2', '-Wall', '-Wextra',
                 '-Werror', '-I', str(ROOT), str(source)]
        subprocess.run([*flags, '-dynamiclib' if sys.platform == 'darwin' else '-shared',
                        '-fPIC', '-o', str(library)], check=True, capture_output=True)
        cls.guarded = cls.work / 'guarded'
        subprocess.run([*flags, '-DGUARDED_MAIN', '-o', str(cls.guarded)],
                       check=True, capture_output=True)
        cls.lib = C.CDLL(str(library))
        for name, args, result in (
                ('package_verify', [C.c_void_p, C.c_size_t], C.c_int),
                ('package_header', [C.c_void_p], C.c_int),
                ('package_allocation', [C.c_void_p], C.c_size_t),
                ('package_crc', [C.c_uint32, C.c_void_p, C.c_size_t], C.c_uint32)):
            function = getattr(cls.lib, name)
            function.argtypes, function.restype = args, result

    def c_check(self, raw, expected, header=None):
        # Aligned backing storage, with canaries before and after the file.
        backing = (C.c_uint64 * ((len(raw) + 135) // 8))()
        C.memset(backing, 0xa5, C.sizeof(backing))
        address = C.addressof(backing) + 64
        C.memmove(address, raw, len(raw))
        before = bytes(backing)
        self.assertEqual(self.lib.package_verify(address, len(raw)), expected)
        if header is not None:
            self.assertEqual(self.lib.package_header(address), header)
        self.assertEqual(bytes(backing), before, 'validator modified package or canaries')
        return self.lib.package_allocation(address) if len(raw) >= 128 else 0

    def reject(self, raw, header=None):
        self.c_check(raw, 0, header)
        with self.assertRaises(ValueError):
            doom.verify(raw)

    def test_generated_valid_packages_agree_and_allocation_is_bounded(self):
        rng = random.Random(0xD00D)
        for i in range(24):
            image = rng.randrange(1, 17) * 64
            memory = image + rng.randrange(5) * 64
            targets = sorted(rng.sample(range(image // 2, image, 8), i % 5))
            relocs = [(t, rng.randrange(memory)) for t in targets]
            heap = (8, 24, 32)[i % 3] * 1024 * 1024
            raw = synthetic_package(image, memory, relocs, heap,
                                    (b'E1M1', b'MAP01')[i % 2])
            with self.subTest(image=image, memory=memory, relocs=relocs):
                report = doom.verify(raw)
                self.assertEqual(report, {'bytes': len(raw),
                                          'sha256': hashlib.sha256(raw).hexdigest(),
                                          'wad_bytes': len(minimal_iwad())})
                expected = 4095 + memory + ((len(raw) + 63) & ~63) + heap + 256 * 1024
                self.assertEqual(self.c_check(raw, 1, 1), expected)

    def test_maximum_memory_and_relocation_count_are_accepted(self):
        image = 262144
        relocs = [(image // 2 + 8 * i, doom.MAX_MODULE - 1) for i in range(16384)]
        raw = synthetic_package(image, doom.MAX_MODULE, relocs, 32 * 1024 * 1024)
        doom.verify(raw)
        self.c_check(raw, 1, 1)

    def test_crc_matches_standard_vector_and_streaming_zlib(self):
        data = b'123456789'
        state = self.lib.package_crc(0xffffffff, data, len(data))
        self.assertEqual(state ^ 0xffffffff, 0xcbf43926)
        state = 0xffffffff
        raw = synthetic_package()
        for start in range(0, len(raw), 17):
            chunk = raw[start:start + 17]
            state = self.lib.package_crc(state, chunk, len(chunk))
        self.assertEqual(state ^ 0xffffffff, zlib.crc32(raw))

    def test_every_header_and_payload_byte_is_integrity_protected(self):
        raw = synthetic_package()
        for offset in range(len(raw)):
            with self.subTest(offset=offset):
                changed = bytearray(raw)
                changed[offset] ^= 1
                self.reject(bytes(changed))
        # These edits remain structurally valid, so the header itself must be
        # checksummed, not merely checked for magic/version and valid bounds.
        for field, value in (('entry', 8), ('memory', 256), ('heap', 8 * 1024 * 1024)):
            changed = bytearray(raw)
            struct.pack_into('<I', changed, FIELDS[field], value)
            self.reject(bytes(changed), header=1)

    def test_rechecksummed_malformed_and_extreme_extents_are_rejected(self):
        raw = synthetic_package()
        cases = {
            'abi': (0, 2, 0xffffffff), 'header': (0, 127, 129, 0xffffffff),
            'total': (0, len(raw) - 1, len(raw) + 1, 0xffffffff),
            'image': (0, 3, 127, doom.MAX_MODULE + 1, 0xffffffff),
            'memory': (0, 64, 191, doom.MAX_MODULE + 64, 0xffffffff),
            'entry': (1, 64, 128, 0xffffffff), 'first': (0, 3, 129, 0xffffffff),
            'last': (0, 63, 129, 0xffffffff), 'reloc': (0, 255, 264, 0xffffffff),
            'count': (16385, 0xffffffff), 'wad_at': (0, 303, 320, 0xffffffff),
            'wad_len': (0, 11, doom.MAX_WAD + 1, 0xffffffff),
            'heap': (0, 8 * 1024 * 1024 - 64, 8 * 1024 * 1024 + 1,
                     32 * 1024 * 1024 + 64, 0xffffffff),
        }
        for field, values in cases.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    bad = change_header(raw, **{field: value})
                    self.assertEqual(self.c_check(bad, 0, 0), 0)
                    with self.assertRaises(ValueError):
                        doom.verify(bad)
        for offset in (0, *range(64, 128)):
            with self.subTest(reserved_or_magic=offset):
                bad = bytearray(raw)
                bad[offset] ^= 1
                self.reject(checksum(bad), header=0)

    def test_truncation_trailing_bytes_null_and_unaligned_input(self):
        raw = synthetic_package()
        for length in (0, 1, 63, 127, 128, 255, 256, 303, len(raw) - 1):
            with self.subTest(length=length):
                self.reject(raw[:length])
        self.reject(raw + b'\0')
        self.assertEqual(self.lib.package_verify(None, len(raw)), 0)
        self.assertEqual(self.lib.package_header(None), 0)
        self.assertEqual(self.lib.package_allocation(None), 0)
        backing = C.create_string_buffer(len(raw) + 8)
        for alignment in range(1, 8):
            C.memmove(C.addressof(backing) + alignment, raw, len(raw))
            before = bytes(backing)
            self.assertEqual(self.lib.package_verify(C.addressof(backing) + alignment, len(raw)), 0)
            self.assertEqual(bytes(backing), before)

    def test_bad_final_relocations_fail_without_any_write(self):
        raw = synthetic_package()
        # Earlier records are valid: an implementation applying relocations as
        # it validates would write before discovering the last invalid record.
        cases = ((72, 0), (64, 0), (80 + 1, 0), (0, 0), (56, 0),
                 (121, 0), (128, 0), (2**64 - 8, 0), (120, 192),
                 (120, 2**64 - 1))
        path = self.work / 'readonly.bfp'
        for target, addend in cases:
            with self.subTest(target=target, addend=addend):
                bad = bytearray(raw)
                struct.pack_into('<QQ', bad, 256 + 32, target, addend)
                bad = checksum(bad)
                self.reject(bad, header=1)
                path.write_bytes(bad)
                result = subprocess.run([str(self.guarded), str(path), '0'],
                                        capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
        path.write_bytes(raw)
        result = subprocess.run([str(self.guarded), str(path), '1'],
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_python_rejects_malformed_iwad_directories_and_lumps(self):
        wad = minimal_iwad()
        cases = [b'', wad[:11], b'PWAD' + wad[4:]]
        for offset, value in ((4, 0), (4, 65537), (4, 0xffffffff),
                              (8, 0), (8, 11), (8, len(wad)), (8, 0xffffffff),
                              (44, len(wad) + 1), (48, len(wad)), (48, 0xffffffff)):
            bad = bytearray(wad)
            struct.pack_into('<I', bad, offset, value)
            cases.append(bytes(bad))
        for name in (b'PLAYPAL', b'COLORMAP', b'E1M1'):
            cases.append(wad.replace(name, b'X' * len(name)))
        for bad in cases:
            with self.subTest(wad=bad):
                with self.assertRaises(ValueError):
                    doom.validate_wad(bad)
        for map_name in (b'E1M1', b'MAP01'):
            doom.validate_wad(minimal_iwad(map_name))

    def test_synthetic_pie_extracts_segments_bss_and_sorted_relative_relocations(self):
        module = self.work / 'engine.elf'
        module.write_bytes(synthetic_elf())
        image, memory, entry, first, last, relocs = doom.read_module(module)
        self.assertEqual(image, bytes(range(64)) + bytes(64) + bytes(range(64, 128)))
        self.assertEqual((memory, entry, first, last), (256, 4, 128, 192))
        self.assertEqual(relocs, [(128, 0), (184, 255)])

    def test_elf_rejects_unbounded_non_pie_imports_and_unsafe_relocations(self):
        original = synthetic_elf()
        # Offsets are ELF64 ABI fields, not mocks of the parser.
        cases = [('B', 0, 0), ('B', 4, 1), ('B', 5, 2),
                 ('H', 16, 2), ('H', 18, 62), ('I', 20, 2), ('H', 52, 63),
                 ('Q', 32, 2**64 - 1), ('H', 54, 55), ('H', 56, 0), ('H', 56, 33),
                 ('Q', 40, 2**64 - 1), ('H', 58, 63), ('H', 60, 0), ('H', 60, 513),
                 ('I', 68, 7), ('Q', 72, 2**64 - 1), ('Q', 80, 64),
                 ('Q', 96, 65), ('Q', 104, doom.MAX_MODULE + 1),
                 ('Q', 136, 32), ('I', 124, 4), ('Q', 24, 128), ('Q', 24, 1),
                 ('I', 0x444, 9), ('Q', 0x458, 2**64 - 1),
                 ('Q', 0x460, 47), ('Q', 0x478, 16),
                 ('Q', 0x308, 257), ('Q', 0x308, (1 << 32) | 1027),
                 ('Q', 0x300, 129), ('Q', 0x300, 0), ('Q', 0x300, 192),
                 ('Q', 0x300, 128), ('q', 0x310, -1), ('q', 0x310, 256)]
        module = self.work / 'bad.elf'
        for fmt, offset, value in cases:
            with self.subTest(offset=hex(offset), value=value):
                raw = bytearray(original)
                struct.pack_into('<' + fmt, raw, offset, value)
                module.write_bytes(raw)
                with self.assertRaises(ValueError):
                    doom.read_module(module)
        for length in (0, 7, 63, 64, len(original) - 1):
            module.write_bytes(original[:length])
            with self.subTest(truncated=length), self.assertRaises(ValueError):
                doom.read_module(module)

    def test_package_and_cli_round_trip_preserve_existing_output(self):
        with tempfile.TemporaryDirectory(prefix='bf-doom-roundtrip-') as directory:
            directory = Path(directory)
            module, wad = directory / 'engine.elf', directory / 'doom.wad'
            output = directory / 'nested' / 'DOOM.BFP'
            module.write_bytes(synthetic_elf())
            wad.write_bytes(minimal_iwad())
            report = doom.package(module, wad, output)
            raw = output.read_bytes()
            self.c_check(raw, 1, 1)
            self.assertEqual(report['module_bytes'], 192)
            self.assertEqual(report['module_memory'], 256)
            self.assertEqual(report['relocations'], 2)
            self.assertEqual(report['bytes'], len(raw))
            self.assertEqual(report['sha256'], hashlib.sha256(raw).hexdigest())
            self.assertEqual(report['wad_sha256'], hashlib.sha256(wad.read_bytes()).hexdigest())
            result = subprocess.run([sys.executable, str(ROOT / 'bfplus_doom.py'),
                                     'check', str(output)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), doom.verify(raw))
            with self.assertRaises(FileExistsError):
                doom.package(module, wad, output)
            self.assertEqual(output.read_bytes(), raw)
            wad.write_bytes(b'not an IWAD')
            absent = directory / 'invalid.bfp'
            with self.assertRaises(ValueError):
                doom.package(module, wad, absent)
            self.assertFalse(absent.exists())


class DoomUploadTests(unittest.TestCase):
    """Mock the camera boundary, retaining upload's send/receive/readback logic."""

    def setUp(self):
        import bfplus_camera_files as camera_files
        from bfplus_ptp import RESPONSE, ProtocolError

        self.ProtocolError = ProtocolError
        directory = tempfile.TemporaryDirectory(prefix='bf-doom-upload-')
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'DOOM.BFP'
        self.raw = synthetic_package()
        self.path.write_bytes(self.raw)
        self.existing = {}
        self.storage_id, self.handle = 0x10001, 42
        self.storage = struct.pack('<II', 1, self.storage_id)
        self.info_response = (self.storage_id, 0xffffffff, self.handle)
        self.saved = {'filename': 'DOOM.BFP', 'bytes': len(self.raw)}
        self.readback = self.raw
        self.exchanges, self.info_calls, self.events = [], [], []
        self.fail_operation = None
        self.failure = ProtocolError('injected uncertain transfer')
        self.opened = self.closed = 0
        owner = self

        class FakeCameraFiles:
            def __init__(self, *, timeout_ms):
                owner.assertEqual(timeout_ms, 30000)

            def __enter__(self):
                owner.opened += 1
                return self

            def __exit__(self, *args):
                owner.closed += 1

            def handles(self):
                owner.events.append('handles')
                return list(owner.existing)

            def info(self, handle):
                owner.info_calls.append(handle)
                return owner.existing.get(handle, owner.saved)

            def _require_open(self):
                owner.assertEqual((owner.opened, owner.closed), (1, 0))

            def _wait_for_write(self):
                owner.events.append('wait')

            def _stamp_write(self):
                owner.events.append('stamp')

            def _receive(self, operation, tid, expected_data, deadline):
                parameters = owner.info_response if operation == 0x100c else ()
                return RESPONSE, 0x2001, struct.pack(f'<{len(parameters)}I', *parameters)

            def _exchange(self, operation, params=(), *, outgoing=None, expected_data=None):
                # Any vendor command, delete, or unexpected operation is a test
                # failure, including attempts made on a failure/cleanup path.
                owner.assertIn(operation, (0x1004, 0x100c, 0x100d, 0x1009))
                owner.exchanges.append((operation, params, outgoing, expected_data))
                if operation == owner.fail_operation:
                    raise owner.failure
                if operation == 0x1004:
                    return 0x2001, owner.storage
                if operation == 0x1009:
                    return 0x2001, owner.readback
                # Dispatch through the real PackageFiles._receive override,
                # which must capture SendObjectInfo's returned object handle.
                self._receive(operation, 1, None, 0)
                return 0x2001, None

        patcher = patch.object(camera_files, 'CameraFiles', FakeCameraFiles)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch('bfplus_ptp.usb.core.find',
                        side_effect=AssertionError('physical USB access forbidden'))
        self.find = patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.find.assert_not_called()

    def operations(self):
        return [operation for operation, *_ in self.exchanges]

    def test_existing_package_is_preserved_before_any_send(self):
        for filename in ('DOOM.BFP', 'doom.bfp', 'Doom.Bfp'):
            with self.subTest(filename=filename):
                self.existing = {17: {'filename': 'photo.jpg', 'bytes': 1},
                                 23: {'filename': filename, 'bytes': 999}}
                with self.assertRaisesRegex(FileExistsError, 'preserved'):
                    doom.upload(self.path)
                self.assertEqual(self.exchanges, [])
                self.assertNotIn('wait', self.events)
                self.assertNotIn('stamp', self.events)
                self.assertEqual(self.path.read_bytes(), self.raw)
                self.assertEqual(self.existing[23], {'filename': filename, 'bytes': 999})
                self.assertEqual(self.opened, self.closed)

    def test_standard_mtp_upload_checks_metadata_and_complete_readback(self):
        report = doom.upload(self.path)
        self.assertEqual(self.operations(), [0x1004, 0x100c, 0x100d, 0x1009])
        _, params, metadata, bound = self.exchanges[1]
        self.assertEqual(params, (self.storage_id, 0xffffffff))
        self.assertIsNone(bound)
        self.assertEqual(struct.unpack_from('<I', metadata)[0], self.storage_id)
        self.assertEqual(struct.unpack_from('<H', metadata, 4)[0], 0x3000)
        self.assertEqual(struct.unpack_from('<I', metadata, 8)[0], len(self.raw))
        self.assertEqual(metadata[52], 9)
        self.assertEqual(metadata[53:71].decode('utf-16-le'), 'DOOM.BFP\0')
        self.assertEqual(metadata[71:], bytes(3))
        self.assertEqual(self.exchanges[2], (0x100d, (), self.raw, None))
        self.assertEqual(self.exchanges[3], (0x1009, (self.handle,), None, len(self.raw)))
        self.assertEqual(self.info_calls, [self.handle])
        self.assertEqual(report, {**doom.verify(self.raw), 'handle': self.handle,
                                  'filename': 'DOOM.BFP', 'readback_verified': True})
        self.assertEqual(self.events.count('wait'), 1)
        self.assertEqual(self.events.count('stamp'), 4)
        self.assertEqual((self.opened, self.closed), (1, 1))

    def test_invalid_local_package_never_opens_a_camera_session(self):
        self.path.write_bytes(self.raw[:-1])
        with self.assertRaises(ValueError):
            doom.upload(self.path)
        self.assertEqual((self.opened, self.closed, self.exchanges), (0, 0, []))

    def test_failed_metadata_or_payload_send_is_not_retried_or_deleted(self):
        for operation, expected in ((0x100c, [0x1004, 0x100c]),
                                    (0x100d, [0x1004, 0x100c, 0x100d])):
            with self.subTest(operation=hex(operation)):
                self.exchanges.clear()
                self.events.clear()
                self.opened = self.closed = 0
                self.fail_operation = operation
                with self.assertRaises(self.ProtocolError) as caught:
                    doom.upload(self.path)
                self.assertIs(caught.exception, self.failure)
                self.assertEqual(self.operations(), expected)
                self.assertEqual(self.events[-1], 'stamp')
                self.assertEqual((self.opened, self.closed), (1, 1))

    def test_bad_send_object_info_response_never_sends_payload(self):
        for response in ((), (self.storage_id,), (self.storage_id, 0, 0),
                         (self.storage_id + 1, 0, self.handle)):
            with self.subTest(response=response):
                self.info_response = response
                self.exchanges.clear()
                self.opened = self.closed = 0
                with self.assertRaises(self.ProtocolError):
                    doom.upload(self.path)
                self.assertEqual(self.operations(), [0x1004, 0x100c])
                self.assertEqual((self.opened, self.closed), (1, 1))

    def test_saved_metadata_mismatch_stops_without_retry_or_delete(self):
        for saved in ({'filename': 'DOOM.BFP', 'bytes': len(self.raw) - 1},
                      {'filename': 'WRONG.BFP', 'bytes': len(self.raw)}):
            with self.subTest(saved=saved):
                self.saved = saved
                self.exchanges.clear()
                self.opened = self.closed = 0
                with self.assertRaisesRegex(ValueError, 'metadata mismatch'):
                    doom.upload(self.path)
                self.assertEqual(self.operations(), [0x1004, 0x100c, 0x100d])
                self.assertEqual((self.opened, self.closed), (1, 1))

    def test_readback_checks_every_byte_and_length_without_retry_or_delete(self):
        for readback in (self.raw[:-1], self.raw + b'\0',
                         self.raw[:-1] + bytes([self.raw[-1] ^ 1]),
                         bytes([self.raw[0] ^ 1]) + self.raw[1:]):
            with self.subTest(length=len(readback), first=readback[:8]):
                self.readback = readback
                self.exchanges.clear()
                self.opened = self.closed = 0
                with self.assertRaisesRegex(ValueError, 'readback mismatch'):
                    doom.upload(self.path)
                self.assertEqual(self.operations(), [0x1004, 0x100c, 0x100d, 0x1009])
                self.assertEqual((self.opened, self.closed), (1, 1))

    def test_ambiguous_storage_is_rejected_before_any_send(self):
        for storage in (struct.pack('<I', 0), struct.pack('<III', 2, 1, 2),
                        struct.pack('<III', 1, self.storage_id, 99)):
            with self.subTest(storage=storage):
                self.storage = storage
                self.exchanges.clear()
                self.opened = self.closed = 0
                with self.assertRaisesRegex(ValueError, 'exactly one'):
                    doom.upload(self.path)
                self.assertEqual(self.operations(), [0x1004])


class DoomStreamingTests(unittest.TestCase):
    def test_one_container_is_streamed_in_packet_aligned_chunks(self):
        raw=bytes(range(256))*20700+b'end'
        writes=[]
        doom.mtp_send_chunks(lambda chunk,deadline:writes.append((chunk,deadline)),raw,123)
        self.assertEqual(b''.join(chunk for chunk,_ in writes),raw)
        self.assertTrue(all(len(chunk)==4096 for chunk,_ in writes[:-1]))
        self.assertTrue(all(deadline==123 for _,deadline in writes))
        self.assertLessEqual(len(writes[-1][0]),4096)

    def test_uncertain_chunk_stops_without_retry_or_resuming(self):
        writes=[]
        def send(chunk,deadline):
            writes.append(chunk)
            if len(writes)==2: raise RuntimeError('short USB write')
        with self.assertRaisesRegex(RuntimeError,'short USB write'):
            doom.mtp_send_chunks(send,bytes(20000),99)
        self.assertEqual([len(x) for x in writes],[4096,4096])


if __name__ == '__main__':
    unittest.main()
