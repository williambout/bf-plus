#!/usr/bin/env python3
"""Read-only BF 1.04 phase-data diagnostic. Does not enable AF or install code.

This is research telemetry, not a calibrated focus-guide input. In particular,
the host clock and RAM hashes are NOT sensor acquisition timestamps/sequences.
See docs/FOCUS-GUIDE.md for field provenance and unresolved requirements.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import time

from bfplus_cli import preflight
from bfplus_ptp import PTP, BASE

RING = 0x4d7028698
CONTEXTS = 0x4d72aa130
CONTEXT_SIZE = 0x2f8
CELLS = 45 * 27
FLAGS_OFFSET = 0x4272
MANUAL_LENSES = 0x4d72aa4e8
SETTINGS = 0x4d7301b98
MANUAL_TABLE_SIZE = 0x79
MANUAL_SELECTION_OFFSET = 0xb4


def _read(p, address, size):
    data = p.read(address, size)
    if len(data) != size:
        raise ValueError(f'Short phase-data read at {address:#x}: {len(data)}/{size}')
    return data


def _pointer(address, size, *, alignment=8, minimum=0x400d20c00):
    if address % alignment or not minimum <= address <= 0x4fff00000 - size:
        raise ValueError(f'Invalid phase-data pointer: {address:#x}')
    return address


def decode_manual_lenses(table, selection):
    """Decode BF 1.04 Lens+ profiles, not electronic/PDAF calibration.

    Native getters: 0x4d31a2d00 (eight data bytes, ten-byte stride),
    0x4d3318480 (selection), 0x4d32fdf00 (mm, F/T, tenths, suffix).
    Entries are linked, not densely packed; deleted slots retain old data.
    The registered aperture is a label, not a live aperture measurement.
    """
    if len(table) != MANUAL_TABLE_SIZE or table[:16] != b'_ManualLensInfo_':
        raise ValueError('Unexpected BF 1.04 manual-lens table')
    if selection is not None and (type(selection) is not int or not 0 <= selection <= 0xffffffff):
        raise ValueError('Invalid manual-lens selection')
    count, head, tail = table[0x74:0x77]
    if count > 10:
        raise ValueError('Invalid manual-lens profile count')
    profiles = []
    seen = set()
    slot, previous = head, 0xff
    for _ in range(count):
        if slot >= 10 or slot in seen:
            raise ValueError('Invalid manual-lens profile links')
        offset = 0x10 + slot * 10
        focal, aperture, suffix, t_stop, shading, reserved, before, after = \
            struct.unpack_from('<HH6B', table, offset)
        if before != previous:
            raise ValueError('Inconsistent manual-lens profile links')
        # F/T is selected by zero/nonzero in the native label formatter.
        suffix_text = chr(suffix) if ord('A') <= suffix <= ord('Z') else ''
        aperture_type = 'T' if t_stop else 'F'
        value = str(aperture // 10)
        if aperture % 10:
            value += f'.{aperture % 10}'
        label = f'{focal}mm {aperture_type}{value}'
        if suffix_text:
            label += f' {suffix_text}'
        profiles.append({'slot': slot, 'focal_length_mm': focal,
                         'registered_aperture_tenths': aperture,
                         'aperture_type': aperture_type, 'suffix': suffix_text,
                         'color_shading_registered': bool(shading), 'label': label})
        seen.add(slot)
        previous, slot = slot, after
    if slot != 0xff or tail != previous:
        raise ValueError('Inconsistent manual-lens profile endpoints')
    selected = next((profile for profile in profiles if profile['slot'] == selection), None)
    return {'selection': selection, 'registered_count': count,
            'profiles': profiles, 'selected_profile': selected}


def read_manual_lenses(p):
    """Bounded read-only snapshot. Never follow an unchecked slot or retry.

    A selected profile is only reported when both pointers, the table and the
    selection match on reread. Matching reads are not an atomicity guarantee.
    Lens+ does not establish the current physical lens or its aperture.
    """
    table_pointer = _read(p, MANUAL_LENSES, 8)
    settings_pointer = _read(p, SETTINGS, 8)
    table_address, = struct.unpack('<Q', table_pointer)
    settings_address, = struct.unpack('<Q', settings_pointer)
    if not table_address or not settings_address:
        return {'status': 'uninitialized', 'selected_profile': None}
    _pointer(table_address, MANUAL_TABLE_SIZE)
    # Native 0x4d33148b8..c0 stores allocation+4, so this object has word,
    # not qword, alignment. The live settings allocation is at 0x400d00c00.
    _pointer(settings_address, MANUAL_SELECTION_OFFSET + 4,
             alignment=4, minimum=0x400d00000)
    table = _read(p, table_address, MANUAL_TABLE_SIZE)
    selection_address = settings_address + MANUAL_SELECTION_OFFSET
    # The native settings object can be below the vendor PTP read window.
    # Do not wrap its unsigned offset or claim an inferred selected slot.
    selection_readable = BASE <= selection_address <= BASE + 0x100000000 - 4
    selection = _read(p, selection_address, 4) if selection_readable else None
    unchanged = (_read(p, table_address, MANUAL_TABLE_SIZE) == table and
                 (not selection_readable or _read(p, selection_address, 4) == selection) and
                 _read(p, MANUAL_LENSES, 8) == table_pointer and
                 _read(p, SETTINGS, 8) == settings_pointer)
    if not unchanged:
        return {'status': 'changed_during_read', 'selected_profile': None}
    return {'status': 'matching_reads',
            'selection_status': 'read' if selection_readable else 'outside_ptp_window',
            **decode_manual_lenses(table, struct.unpack('<I', selection)[0] if selection else None)}


def read_snapshot(p):
    """Inspect one candidate publication without writing or retrying.

    Matching before/after headers are only a consistency observation: the
    allocator advances the ring index before filling the slot, and ABA reuse
    is possible. Nothing returned here is accepted by the guide as fresh.
    """
    ring = _read(p, RING, 16)
    index, capacity, count, stride = struct.unpack('<4I', ring)
    if capacity != 16 or index >= capacity or count > capacity or stride != CONTEXT_SIZE:
        raise ValueError(f'Unexpected BF 1.04 phase ring: {(index,capacity,count,stride)}')
    if not count:
        return {'ring_index': index, 'published_slots': 0}
    slot = CONTEXTS + 8 * index
    context = _pointer(struct.unpack('<Q', _read(p, slot, 8))[0], CONTEXT_SIZE)
    header = _read(p, context, CONTEXT_SIZE)
    grid = _pointer(struct.unpack_from('<Q', header, 0x78)[0], FLAGS_OFFSET + CELLS * 2)
    values = _read(p, grid, CELLS * 4)
    flag_bytes = _read(p, grid + FLAGS_OFFSET, CELLS * 2)
    unchanged = (_read(p, context, CONTEXT_SIZE) == header and
                 _read(p, slot, 8) == struct.pack('<Q',context) and
                 _read(p, RING, 16) == ring)
    flags = struct.unpack(f'<{CELLS}H', flag_bytes)
    # The center cell here assumes the still 45x27 grid. The native movie
    # consumer also uses 45x23; no live-coordinate adapter is implied.
    center = CELLS // 2
    return {
        'ring_index': index, 'published_slots': count,
        'context': hex(context), 'grid': hex(grid),
        'headers_unchanged_during_read': unchanged,
        'context_sha256': hashlib.sha256(header).hexdigest(),
        'phase_sha256': hashlib.sha256(values + flag_bytes).hexdigest(),
        'sampled_cells': CELLS,
        'flag_bit0_cells': sum(bool(flag & 1) for flag in flags),
        'flag_mask_0x71_eq_1_cells': sum((flag & 0x71) == 1 for flag in flags),
        'center_raw_signed': struct.unpack_from('<i', values, center * 4)[0],
        'center_flags': hex(flags[center]),
    }


def capture(p, samples, interval, emit):
    preflight(p)
    start = time.monotonic()
    for index in range(samples):
        snapshot = read_snapshot(p)
        snapshot['manual_lens'] = read_manual_lenses(p)
        emit({'sample': index, 'host_elapsed_ms': round((time.monotonic()-start)*1000),
              **snapshot})
        if index + 1 < samples:
            time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=int, default=5)
    parser.add_argument('--interval', type=float, default=0.2, help='seconds between reads')
    parser.add_argument('--output', type=Path, help='new JSONL file; existing files are never overwritten')
    args = parser.parse_args()
    if not 1 <= args.samples <= 300 or not 0.05 <= args.interval <= 5:
        parser.error('samples must be 1..300 and interval must be 0.05..5 seconds')
    # Buffer a bounded capture before creating the output. A busy transport or
    # failed read must not truncate a previous capture or leave an empty one.
    snapshots = []
    with PTP() as p:
        capture(p,args.samples,args.interval,snapshots.append)
    data = ''.join(json.dumps(row,sort_keys=True)+'\n' for row in snapshots)
    if args.output:
        with args.output.open('x') as stream:
            stream.write(data)
    else:
        print(data,end='')


if __name__ == '__main__': main()
