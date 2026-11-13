"""Bounded read-only PAS captures must not follow unknown banks or hide races."""
import struct
import unittest
from unittest.mock import patch

import bfplus_focus_raw_probe as raw


class RawReader:
    # No write/call operation: the diagnostic must work with reads alone.
    def __init__(self, pair=2):
        self.metadata = bytearray(raw.METADATA_SIZE)
        struct.pack_into('<4Q', self.metadata, 0x138, *raw.BANKS[0], *raw.BANKS[1])
        self.mode = struct.pack('<I', 2)
        self.scene = (2, 12)
        self.stack = raw.IDLE_SCENE
        descriptor = bytearray(0x58)
        struct.pack_into('<I', descriptor, 8, 3)
        for start, width, stride in ((0x30, 1514, 1536), (0x40, 504, 512)):
            struct.pack_into('<3H', descriptor, start, width, 334, stride)
            descriptor[start+8:start+10] = bytes((14, 8))
        self.writer = {raw.WRITER_DESCRIPTOR: bytes(descriptor),
                       raw.WRITER_MODE: struct.pack('<I', 3),
                       raw.WRITER_CHANNELS: b'\x04',
                       raw.WRITER_OFFSETS: struct.pack('<QQ', 1536, 512)}
        self.calls = []
        self.header_reads = 0
        self.mutate = None
        self.short = None
        self.pair = pair
        _, offset, stride = raw.CROPS[pair]
        size = (raw.HEIGHT - 1)*stride + raw.WIDTH
        self.planes = {p+offset: bytes([i+1])*size
                       for i, p in enumerate(raw.BANKS[pair-1])}

    def read(self, address, size):
        self.calls.append((address, size))
        assert size <= raw.MAX_READ
        if address == raw.BANK_TABLE:
            data = b''.join(struct.pack('<QQ', *b) for b in raw.BANKS)
        elif address == raw.METADATA:
            self.header_reads += 1
            data = bytes(self.metadata)
            if self.header_reads > 1 and self.mutate == 'metadata':
                data = data[:16] + bytes([data[16] ^ 1]) + data[17:]
            if self.header_reads > 1 and self.mutate == 'pointer':
                data = bytearray(data)
                struct.pack_into('<QQ', data, raw.CROPS[self.pair][0], *raw.BANKS[3])
        elif address == raw.SENSOR_MODE:
            data = self.mode
            if self.header_reads > 1 and self.mutate == 'mode':
                data = struct.pack('<I', 3)
        elif address == raw.SCENE_DEPTH:
            data = struct.pack('<II', *self.scene)
            if self.header_reads > 1 and self.mutate == 'scene':
                data = struct.pack('<II', 3, 12)
        elif address == raw.SCENE_STACK:
            data = struct.pack('<4Q', *self.stack)
        elif address in self.writer:
            data = self.writer[address]
            if self.header_reads > 1 and self.mutate == 'writer' and address == raw.WRITER_DESCRIPTOR:
                data = bytes([data[0] ^ 1]) + data[1:]
        else:
            for base, plane in self.planes.items():
                if base <= address and address+size <= base+len(plane):
                    data = plane[address-base:address-base+size]
                    if self.header_reads > 1 and self.mutate == 'plane':
                        data = bytes([data[0] ^ 1]) + data[1:]
                    break
            else:
                raise AssertionError(f'Unexpected memory read {address:#x}+{size:#x}')
        data = bytes(data[:size])
        return data[:-1] if address == self.short else data


class RawProbeTests(unittest.TestCase):
    def test_pair_crops_and_bounded_reads_do_not_claim_freshness(self):
        for pair in (1, 2):
            r = RawReader(pair)
            result, planes = raw.read_raw_snapshot(r, pair)
            self.assertEqual(result['status'], 'matching_reads')
            self.assertFalse(result['acquisition_freshness_proven'])
            self.assertFalse(result['direction_calibrated'])
            self.assertEqual(result['a']['mean'], 1)
            self.assertEqual(result['b']['mean'], 2)
            self.assertNotIn('captured_ms', result)
            self.assertEqual(planes['a'], planes['a-repeat'])
            self.assertTrue(all(0 < size <= raw.MAX_READ for _, size in r.calls))

    def test_rejects_unrecognized_modes_and_pointer_pairs_before_crops(self):
        for kind in ('pas', 'mode13', 'mode16', 'null', 'reversed', 'mixed', 'unknown'):
            with self.subTest(kind=kind):
                r = RawReader()
                if kind == 'pas':
                    struct.pack_into('<I', r.metadata, 8, 1)
                elif kind.startswith('mode'):
                    r.mode = struct.pack('<I', int(kind[4:]))
                else:
                    pair = {'null': (0, 0), 'reversed': raw.BANKS[1][::-1],
                            'mixed': (raw.BANKS[0][0], raw.BANKS[1][1]),
                            'unknown': (0x419c52b08, 0x419ccff00)}[kind]
                    struct.pack_into('<QQ', r.metadata, 0x148, *pair)
                with self.assertRaises(ValueError): raw.read_raw_snapshot(r)
                self.assertTrue(all(a in (raw.METADATA, raw.SENSOR_MODE) for a, _ in r.calls))

    def test_changes_discard_consistency_and_do_not_follow_rotated_pointer(self):
        for mutation in ('metadata', 'pointer', 'mode', 'plane', 'writer'):
            with self.subTest(mutation=mutation):
                r = RawReader(); r.mutate = mutation
                result, _ = raw.read_raw_snapshot(r)
                self.assertEqual(result['status'], 'changed_during_read')
                self.assertEqual(r.header_reads, 3)
                self.assertEqual(sum(a == raw.SCENE_DEPTH for a, _ in r.calls), 3)

    def test_writer_modes_coverage_packing_and_crop_bounds_are_validated(self):
        bad = ((raw.WRITER_MODE, 0, 2), (raw.WRITER_CHANNELS, 0, 8),
               (raw.WRITER_OFFSETS, 1, 2), (raw.WRITER_DESCRIPTOR, 8, 0),
               (raw.WRITER_DESCRIPTOR, 0x39, 10), (raw.WRITER_DESCRIPTOR, 0x48, 0),
               (raw.WRITER_DESCRIPTOR, 0x41, 0), (raw.WRITER_DESCRIPTOR, 0x43, 0))
        for address, offset, value in bad:
            with self.subTest(address=address, offset=offset):
                r = RawReader()
                data = bytearray(r.writer[address]); data[offset] = value
                r.writer[address] = bytes(data)
                with self.assertRaises(ValueError): raw.read_raw_snapshot(r)
                self.assertFalse(any(a in r.planes for a, _ in r.calls))

    def test_pending_skip_is_never_labelled_matching_measurement(self):
        r = RawReader(); r.metadata[0] = 1
        result, _ = raw.read_raw_snapshot(r)
        self.assertEqual(result['status'], 'pending_skip')
        self.assertTrue(result['pending_skip_observed'])

    def test_matching_frozen_pixels_in_magnification_are_not_idle_still_data(self):
        for kind in ('magnified', 'pending', 'different_stack', 'transition'):
            with self.subTest(kind=kind):
                r = RawReader()
                if kind == 'magnified': r.scene = (3, 12)
                elif kind == 'pending': r.scene = (2, 1)
                elif kind == 'different_stack': r.stack = (0, 0, 0, 0)
                else: r.mutate = 'scene'
                result, _ = raw.read_raw_snapshot(r)
                self.assertEqual(result['status'], 'unsupported_scene')
                self.assertFalse(result['idle_still_scene'])
                self.assertFalse(result['acquisition_freshness_proven'])

    def test_repeated_timing_across_samples_is_reported_without_claiming_freshness(self):
        r = RawReader(); results = []
        struct.pack_into('<3Q', r.metadata, 0x10, 100, 110, 90)
        with patch.object(raw, 'preflight'), patch.object(raw.time, 'sleep'):
            raw.capture(r, 3, .25, 2, lambda result, _: results.append(result))
        self.assertEqual([x['repeated_timing_from_previous_sample'] for x in results], [False, True, True])
        self.assertTrue(all(not x['acquisition_freshness_proven'] for x in results))

    def test_short_read_stops_without_retry(self):
        r = RawReader()
        addresses = (raw.METADATA, raw.SENSOR_MODE, *r.planes)
        for address in addresses:
            with self.subTest(address=address):
                r = RawReader(); r.short = address
                with self.assertRaisesRegex(ValueError, 'Short phase-data read'):
                    raw.read_raw_snapshot(r)
                self.assertEqual(sum(a == address for a, _ in r.calls), 1)

    def test_padding_changes_are_not_misreported_as_sensor_texture(self):
        stride = raw.CROPS[2][2]
        data = bytearray((raw.HEIGHT-1)*stride+raw.WIDTH)
        data[raw.WIDTH+10] = 42
        stats = raw.plane_statistics(data, stride)
        self.assertEqual(stats['max'], 0)
        self.assertEqual(stats['distinct_values'], 1)
        self.assertEqual(stats['zero_fraction'], 1)
        self.assertNotEqual(stats['file_sha256'], stats['roi_sha256'])

    def test_capture_checks_firmware_bank_table_before_following_pointers(self):
        r = RawReader(); r.short = raw.BANK_TABLE
        with patch.object(raw, 'preflight') as check:
            with self.assertRaises(ValueError): raw.capture(r, 1, .25, 2, lambda *args: None)
            check.assert_called_once_with(r)
        self.assertEqual(r.calls, [(raw.BANK_TABLE, 64)])
        for count in (0, 31, True):
            r = RawReader()
            with self.assertRaises(ValueError): raw.capture(r, count, .25, 2, lambda *args: None)
            self.assertEqual(r.calls, [])


if __name__ == '__main__':
    unittest.main()
