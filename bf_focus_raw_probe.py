#!/usr/bin/env python3
"""Read-only BF 1.04 PAS paired-plane diagnostic for no-contact focus research.

Reads a bounded central byte crop. Matching repeated reads are NOT proof of
DMA ownership, acquisition freshness, optical zero, or physical focus direction.
No native code is invoked and no camera memory is written.
"""
import argparse
import hashlib
import json
from pathlib import Path
from statistics import mean, pstdev
import struct
import time

from bf_focus_guide_probe import _read
from bf_touch_focus import preflight
from bf_touch_ptp import PTP, PTPError, MAX_READ

METADATA = 0x4d72faf50
METADATA_SIZE = 0x158
SENSOR_MODE = 0x4d703459c
BANK_TABLE = 0x4d3df2110
WRITER_DESCRIPTOR = 0x4d72fb0a8
WRITER_MODE = 0x4d70342e4
WRITER_CHANNELS = 0x4d72fba22
WRITER_OFFSETS = 0x4d72fba28
SCENE_DEPTH = 0x4d70346a0
SCENE_STACK = 0x4d7301c00
IDLE_SCENE = (0x4d3398930, 0x4d33988b0, 0x4d3393730, 0x4d33936a0)
BANKS = ((0x419b58300, 0x419bd5700), (0x419c52b00, 0x419ccff00),
         (0x419d4d300, 0x419dca700), (0x419e47b00, 0x419ec4f00))
# PBLM descriptors selected by 0x4d31920d0, consumed at 0x4d32c84d4 and
# 0x4d32c8838. PAS writer setup: 0x4d32cae10. The metadata selector at +8
# is NOT the writer layout mode. Keep row padding in saved bytes.
CROPS = {1: (0x138, 0x38675, 1536), 2: (0x148, 0x12c7c, 512)}
WIDTH, HEIGHT = 256, 32


def read_writer(p):
    descriptor = _read(p, WRITER_DESCRIPTOR, 0x58)
    mode = _read(p, WRITER_MODE, 4)
    channels = _read(p, WRITER_CHANNELS, 1)
    offsets = _read(p, WRITER_OFFSETS, 16)
    # Only the measured direct four-channel, eight-bit layout is supported.
    # Modes 0/1/2 have different channel coverage/interleaving and may leave
    # pair 2 untouched. Consumer geometry alone does not prove writer coverage.
    if struct.unpack_from('<I', descriptor, 8)[0] != 3 or mode != struct.pack('<I', 3) or \
            channels != b'\x04' or struct.unpack('<QQ', offsets) != (1536, 512):
        raise ValueError('Unsupported PAS writer mode, channels or row offsets')
    for start, stride, right in ((0x30, 1536, 885), (0x40, 512, 380)):
        width, height, row_bytes = struct.unpack_from('<3H', descriptor, start)
        fmt, depth = descriptor[start+8:start+10]
        if not right <= width <= stride or not 182 <= height <= 512 or \
                row_bytes != stride or fmt != 14 or depth != 8:
            raise ValueError('Unsupported PAS writer dimensions or packing')
    return descriptor, mode, channels, offsets


def read_header(p, pair):
    if pair not in CROPS:
        raise ValueError('pair must be 1 or 2')
    metadata = _read(p, METADATA, METADATA_SIZE)
    mode = _read(p, SENSOR_MODE, 4)
    if struct.unpack_from('<I', metadata, 8)[0] != 0 or \
            struct.unpack('<I', mode)[0] in (13, 16):
        raise ValueError('Unsupported PAS/sensor mode for this diagnostic crop')
    pointers = struct.unpack_from('<QQ', metadata, CROPS[pair][0])
    if pointers not in BANKS:
        raise ValueError('PAS plane pair is not a supported BF 1.04 bank')
    writer = read_writer(p)
    scene = (_read(p, SCENE_DEPTH, 8), _read(p, SCENE_STACK, 32))
    return metadata, mode, pointers, writer, scene


def read_plane(p, address, size):
    # Pair 1 spans three bounded PTP reads. Never retry a failed transaction.
    return b''.join(_read(p, address + offset, min(MAX_READ, size - offset))
                    for offset in range(0, size, MAX_READ))


def plane_statistics(data, stride):
    expected = (HEIGHT - 1) * stride + WIDTH
    if len(data) != expected:
        raise ValueError('Unexpected PAS crop length')
    pixels = b''.join(data[row*stride:row*stride+WIDTH] for row in range(HEIGHT))
    return {'file_sha256': hashlib.sha256(data).hexdigest(),
            'roi_sha256': hashlib.sha256(pixels).hexdigest(),
            'min': min(pixels), 'max': max(pixels), 'mean': mean(pixels),
            'stddev': pstdev(pixels), 'distinct_values': len(set(pixels)),
            'zero_fraction': pixels.count(0) / len(pixels),
            'ff_fraction': pixels.count(255) / len(pixels)}


def read_raw_snapshot(p, pair=2):
    before = read_header(p, pair)
    _, offset, stride = CROPS[pair]
    size = (HEIGHT - 1) * stride + WIDTH
    a, b = (read_plane(p, pointer + offset, size) for pointer in before[2])
    middle = read_header(p, pair)
    # Always repeat the original addresses. A rotating pointer does not cause
    # us to follow a different frame and compare unrelated buffers as one pair.
    ar, br = (read_plane(p, pointer + offset, size) for pointer in before[2])
    after = read_header(p, pair)
    headers_equal = before == middle == after
    crops_equal = (a, b) == (ar, br)
    skipped = any(h[0][0] for h in (before, middle, after))
    scenes = [dict(zip(('depth', 'pending'), struct.unpack('<II', h[4][0])),
                   stack=[hex(v) for v in struct.unpack('<4Q', h[4][1])])
              for h in (before, middle, after)]
    idle = all(h[4] == (struct.pack('<II', 2, 12), struct.pack('<4Q', *IDLE_SCENE))
               for h in (before, middle, after))
    return {
        'pair': pair, 'width': WIDTH, 'height': HEIGHT, 'stride': stride,
        'crop_offset': hex(offset), 'pointers': [hex(v) for v in before[2]],
        'metadata_unchanged': headers_equal, 'repeated_crops_equal': crops_equal,
        'status': ('unsupported_scene' if not idle else
                   'changed_during_read' if not headers_equal or not crops_equal else
                   'pending_skip' if skipped else 'matching_reads'),
        'idle_still_scene': idle, 'scenes': scenes,
        'pending_skip_observed': skipped,
        'acquisition_freshness_proven': False, 'direction_calibrated': False,
        # 0x4d32be0b4 samples DD_TIMESTAMP in an SSG interrupt callback.
        # The other two fields are arithmetic predictions, not DMA completion.
        'timing_ticks': [dict(zip(('ssg_callback', 'derived_end', 'derived_start'),
                                  (hex(v) for v in struct.unpack_from('<3Q', h[0], 0x10))))
                         for h in (before, middle, after)],
        'counter_hz_nominal': 24000000,
        'metadata_hex': [h[0].hex() for h in (before, middle, after)],
        'sensor_mode_hex': [h[1].hex() for h in (before, middle, after)],
        'writer_hex': [[field.hex() for field in h[3]] for h in (before, middle, after)],
        'a': plane_statistics(a, stride), 'b': plane_statistics(b, stride),
    }, {'a': a, 'b': b, 'a-repeat': ar, 'b-repeat': br}


def capture(p, samples, interval, pair, emit):
    if type(samples) is not int or not 1 <= samples <= 30 or \
            not 0.05 <= interval <= 5 or pair not in CROPS:
        raise ValueError('Require 1..30 samples, 0.05..5 second interval, pair 1 or 2')
    preflight(p)
    expected = b''.join(struct.pack('<QQ', *bank) for bank in BANKS)
    if _read(p, BANK_TABLE, len(expected)) != expected:
        raise ValueError('BF 1.04 PAS bank table mismatch')
    start = time.monotonic()
    previous_timing = None
    for index in range(samples):
        result, planes = read_raw_snapshot(p, pair)
        # Magnification can leave perfectly matching old pixels and metadata.
        # This is an observation across host reads, never a sensor sequence.
        timing = result['timing_ticks'][0]
        result['repeated_timing_from_previous_sample'] = timing == previous_timing
        previous_timing = timing
        result.update(sample=index, host_elapsed_ms=round((time.monotonic()-start)*1000))
        emit(result, planes)
        if index + 1 < samples:
            time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='new capture directory')
    parser.add_argument('--samples', type=int, default=3)
    parser.add_argument('--interval', type=float, default=0.25)
    parser.add_argument('--pair', type=int, choices=(1, 2), default=2)
    args = parser.parse_args()
    if not 1 <= args.samples <= 30 or not 0.05 <= args.interval <= 5:
        parser.error('samples must be 1..30 and interval must be 0.05..5 seconds')
    if args.output.exists():
        parser.error('output directory already exists; choose a new path')
    # Bounded buffering allows failed USB sessions to leave no partial capture.
    # Correlation is deliberately separate: unchanging zeros or padding hashes
    # must never be accepted as a calibrated in-focus measurement.
    snapshots = []
    try:
        with PTP() as p:
            capture(p, args.samples, args.interval, args.pair,
                    lambda result, planes: snapshots.append((result, planes)))
        args.output.mkdir()
        for result, planes in snapshots:
            for name, data in planes.items():
                with (args.output/f'{result["sample"]}-{name}.bin').open('xb') as stream:
                    stream.write(data)
        with (args.output/'capture.json').open('x') as stream:
            json.dump([r for r, _ in snapshots], stream, indent=2)
            stream.write('\n')
    except (PTPError, OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f'{error}\n')
    print(f'Saved {len(snapshots)} read-only snapshots to {args.output}')


if __name__ == '__main__':
    main()
