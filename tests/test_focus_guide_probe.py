"""Phase-data decoder bounds and consistency checks with a read-only transport."""
import struct
import unittest

from bfplus_focus_guide_probe import read_snapshot, RING, CONTEXTS, CONTEXT_SIZE, CELLS, FLAGS_OFFSET
from bfplus_focus_guide_probe import (decode_manual_lenses, read_manual_lenses,
                                 MANUAL_LENSES, SETTINGS, MANUAL_TABLE_SIZE,
                                 MANUAL_SELECTION_OFFSET)

CONTEXT, GRID = 0x41a111da0,0x41a087d00


class Reader:
    # Intentionally no write or command method.
    def __init__(self):
        self.blocks = {
            RING: struct.pack('<4I',12,16,16,CONTEXT_SIZE),
            CONTEXTS+12*8: struct.pack('<Q',CONTEXT),
            CONTEXT: bytearray(CONTEXT_SIZE),
            GRID: bytearray(CELLS*4),
            GRID+FLAGS_OFFSET: bytearray(CELLS*2),
        }
        struct.pack_into('<Q',self.blocks[CONTEXT],0x78,GRID)
        self.calls = []
        self.change = None

    def read(self,address,size):
        repeated = address in self.calls
        self.calls.append(address)
        data = self.blocks[address]
        if repeated and address==self.change:
            data = bytes([data[0]^1])+bytes(data[1:])
        return bytes(data[:size])


class PhaseProbeTests(unittest.TestCase):
    def test_zero_grid_is_not_misreported_as_in_focus(self):
        result = read_snapshot(Reader())
        self.assertEqual(result['center_raw_signed'],0)
        self.assertEqual(result['flag_bit0_cells'],0)
        self.assertEqual(result['flag_mask_0x71_eq_1_cells'],0)
        self.assertTrue(result['headers_unchanged_during_read'])
        self.assertNotIn('captured_ms',result)

    def test_decodes_signed_center_and_distinct_native_validity_checks(self):
        reader = Reader()
        struct.pack_into('<i',reader.blocks[GRID],(CELLS//2)*4,-12345)
        for index,flag in enumerate((1,0x11,0x21,0x41,0x81,0)):
            struct.pack_into('<H',reader.blocks[GRID+FLAGS_OFFSET],index*2,flag)
        result = read_snapshot(reader)
        self.assertEqual(result['center_raw_signed'],-12345)
        self.assertEqual(result['flag_bit0_cells'],5)
        self.assertEqual(result['flag_mask_0x71_eq_1_cells'],2)

    def test_detects_slot_pointer_header_and_ring_changes_without_retry(self):
        for address in (RING,CONTEXTS+12*8,CONTEXT):
            with self.subTest(address=address):
                reader = Reader(); reader.change = address
                result = read_snapshot(reader)
                self.assertFalse(result['headers_unchanged_during_read'])
                self.assertEqual(reader.calls.count(GRID),1)

    def test_empty_ring_does_not_follow_uninitialized_pointer(self):
        reader = Reader(); reader.blocks[RING] = struct.pack('<4I',0,16,0,CONTEXT_SIZE)
        self.assertEqual(read_snapshot(reader),{'ring_index':0,'published_slots':0})
        self.assertEqual(reader.calls,[RING])

    def test_rejects_unexpected_ring_layouts(self):
        for fields in ((16,16,16,760),(0,0,0,760),(0,32,1,760),(0,16,17,760),(0,16,1,8)):
            with self.subTest(fields=fields):
                reader = Reader(); reader.blocks[RING] = struct.pack('<4I',*fields)
                with self.assertRaises(ValueError): read_snapshot(reader)
                self.assertEqual(reader.calls,[RING])

    def test_rejects_unaligned_null_outside_and_overrunning_pointers(self):
        for pointer in (0,CONTEXT+1,0x10000000,0x4fff00000-8):
            for source in ('context','grid'):
                with self.subTest(pointer=pointer,source=source):
                    reader = Reader()
                    if source=='context': reader.blocks[CONTEXTS+12*8] = struct.pack('<Q',pointer)
                    else: struct.pack_into('<Q',reader.blocks[CONTEXT],0x78,pointer)
                    with self.assertRaises(ValueError): read_snapshot(reader)
                    self.assertNotIn(pointer,reader.calls)

    def test_short_reads_are_rejected(self):
        for address in (RING,CONTEXTS+12*8,CONTEXT,GRID,GRID+FLAGS_OFFSET):
            with self.subTest(address=address):
                reader = Reader(); reader.blocks[address] = reader.blocks[address][:-1]
                with self.assertRaisesRegex(ValueError,'Short phase-data read'):
                    read_snapshot(reader)


TABLE, CONFIG = 0x445152c80, 0x41a100004


def manual_table(slots=(4, 1)):
    table = bytearray(MANUAL_TABLE_SIZE)
    table[:16] = b'_ManualLensInfo_'
    table[0x74:0x77] = bytes((len(slots), slots[0] if slots else 0xff,
                            slots[-1] if slots else 0xff))
    for index, slot in enumerate(slots):
        struct.pack_into('<HH6B', table, 0x10 + slot * 10,
                         35 + index * 15, 14 + index * 6, ord('A') + index,
                         index % 2, index % 2, 0,
                         slots[index - 1] if index else 0xff,
                         slots[index + 1] if index + 1 < len(slots) else 0xff)
    return table


class ManualLensTests(unittest.TestCase):
    def reader(self):
        reader = Reader()
        reader.blocks = {MANUAL_LENSES: struct.pack('<Q', TABLE),
                         SETTINGS: struct.pack('<Q', CONFIG), TABLE: manual_table(),
                         CONFIG + MANUAL_SELECTION_OFFSET: struct.pack('<I', 1)}
        return reader

    def test_registered_profiles_are_sparse_and_follow_native_order(self):
        result = read_manual_lenses(self.reader())
        self.assertEqual(result['status'], 'matching_reads')
        self.assertEqual([p['slot'] for p in result['profiles']], [4, 1])
        self.assertEqual([p['label'] for p in result['profiles']], ['35mm F1.4 A', '50mm T2 B'])
        self.assertEqual(result['selected_profile']['focal_length_mm'], 50)
        self.assertTrue(result['selected_profile']['color_shading_registered'])
        self.assertNotIn('current_aperture', result['selected_profile'])
        self.assertNotIn('phase_calibrated', result['selected_profile'])

    def test_deleted_and_special_slots_are_not_reported_as_selected(self):
        table = manual_table()
        # A deleted slot can retain perfectly plausible old lens metadata.
        table[0x10:0x18] = table[0x38:0x40]
        for selection in (0, 9, 10, 11, 0xff, 0xffffffff):
            with self.subTest(selection=selection):
                self.assertIsNone(decode_manual_lenses(table, selection)['selected_profile'])
        self.assertEqual(decode_manual_lenses(manual_table(()), 0)['profiles'], [])

    def test_all_ten_slots_and_absent_suffix(self):
        table = manual_table(tuple(range(10)))
        table[0x14] = 0
        result = decode_manual_lenses(table, 0)
        self.assertEqual(result['registered_count'], 10)
        self.assertEqual(result['selected_profile']['label'], '35mm F1.4')

    def test_rejects_short_bad_magic_count_cycle_links_and_endpoints(self):
        corruptions = ((0, 0), (0x74, 11), (0x75, 10), (0x76, 4),
                       (0x10 + 4*10 + 8, 1), (0x10 + 4*10 + 9, 4),
                       (0x10 + 1*10 + 9, 9))
        for offset, value in corruptions:
            with self.subTest(offset=offset):
                table = manual_table(); table[offset] = value
                with self.assertRaises(ValueError): decode_manual_lenses(table, 1)
        with self.assertRaises(ValueError): decode_manual_lenses(manual_table()[:-1], 1)
        for selection in (-1, 2**32, '1', True):
            with self.assertRaises(ValueError): decode_manual_lenses(manual_table(), selection)

    def test_profile_or_selection_changes_discard_metadata_without_retry(self):
        for address in (MANUAL_LENSES, SETTINGS, TABLE, CONFIG + MANUAL_SELECTION_OFFSET):
            with self.subTest(address=address):
                reader = self.reader(); reader.change = address
                result = read_manual_lenses(reader)
                self.assertEqual(result['status'], 'changed_during_read')
                self.assertIsNone(result['selected_profile'])
                self.assertEqual(reader.calls.count(TABLE), 2)

    def test_uninitialized_table_is_not_followed(self):
        for address in (MANUAL_LENSES, SETTINGS):
            reader = self.reader(); reader.blocks[address] = bytes(8)
            self.assertEqual(read_manual_lenses(reader)['status'], 'uninitialized')
            self.assertNotIn(TABLE, reader.calls)

    def test_settings_below_ptp_window_report_profiles_without_guessing_selection(self):
        reader = self.reader()
        reader.blocks[SETTINGS] = struct.pack('<Q', 0x400d00c04)
        result = read_manual_lenses(reader)
        self.assertEqual(result['selection_status'], 'outside_ptp_window')
        self.assertEqual(result['registered_count'], 2)
        self.assertIsNone(result['selection'])
        self.assertIsNone(result['selected_profile'])
        self.assertNotIn(0x400d00c04 + MANUAL_SELECTION_OFFSET, reader.calls)

    def test_bad_pointers_and_short_reads(self):
        for address in (MANUAL_LENSES, SETTINGS):
            for pointer in (TABLE+1, 0x10000000, 0x4fff00000-8):
                reader = self.reader(); reader.blocks[address] = struct.pack('<Q', pointer)
                with self.assertRaises(ValueError): read_manual_lenses(reader)
                self.assertNotIn(pointer, reader.calls)
        for address in self.reader().blocks:
            reader = self.reader(); reader.blocks[address] = reader.blocks[address][:-1]
            with self.assertRaisesRegex(ValueError, 'Short phase-data read'):
                read_manual_lenses(reader)


if __name__ == '__main__': unittest.main()
