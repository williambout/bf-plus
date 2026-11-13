#!/usr/bin/env python3
"""Verify BF container reconstruction offline, without emitting a firmware image.

Decrypts and re-encodes every segment, regenerates the table checksums, and
preserves all other bytes. Optional independently decoded files are compared
by SHA-256. This establishes container reproducibility, not installability,
signature validity, or boot compatibility. No camera transport is used.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import mmap
from pathlib import Path
import struct
import sys

if __package__:
    from .decode_bf import ENTRY, MAGIC, TABLE_OFF, extend_stream, recover_prefix, vendor_prefix
else:
    from decode_bf import ENTRY, MAGIC, TABLE_OFF, extend_stream, recover_prefix, vendor_prefix


@dataclass(frozen=True)
class Segment:
    index: int
    kind: int
    offset: int
    size: int
    checksum: int


def layout(data: memoryview) -> list[Segment]:
    """Validate the outer table and ciphertext checksums, without copying segments."""
    if len(data) < 0x300 or data[:12] != MAGIC:
        raise ValueError("Missing or truncated SIGMA BF header")
    count = struct.unpack_from("<H", data, 0x18)[0]
    if not 1 <= count <= 64:
        raise ValueError("Invalid segment count")
    table_end = TABLE_OFF + count * ENTRY.size
    if table_end > len(data):
        raise ValueError("Truncated segment table")
    last = max(0x300, table_end)
    result = []
    for i in range(count):
        index, kind, offset, size, trailer = ENTRY.unpack_from(data, TABLE_OFF + i * ENTRY.size)
        if index != i or size == 0 or offset < last or offset + size > len(data):
            raise ValueError(f"Invalid segment {i} index, extent, or overlap")
        if trailer & 0xFFFFFF:
            raise ValueError(f"Segment {i} has unknown trailer bits")
        checksum = (-sum(data[offset:offset + size])) & 0xFF
        if checksum != trailer >> 24:
            raise ValueError(f"Segment {i} checksum mismatch")
        result.append(Segment(index, kind, offset, size, checksum))
        last = offset + size
    return result


def check_roundtrip(data, decoded_dir: Path | None = None, *, chunk_size: int = 1 << 20) -> dict:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    with memoryview(data) as view:
        segments = layout(view)
        seg2 = next((s for s in segments if s.index == 2), None)
        if seg2 is None or seg2.size < 32:
            raise ValueError("Segment 2 is needed for the independent stream-prefix check")
        seed = struct.unpack_from("<I", view, 12)[0]
        prefix = vendor_prefix(seed)
        if recover_prefix(view[seg2.offset:seg2.offset + 32]) != prefix:
            raise ValueError("Header seed and known-plaintext stream prefixes disagree")
        key = extend_stream(prefix, max(32, max(s.size for s in segments)))
        original_digest = hashlib.sha256(view).hexdigest()

        # Regenerate the table checksums, retaining every other header/gap byte.
        header = bytearray(view[:segments[0].offset])
        for s in segments:
            struct.pack_into("<I", header, TABLE_OFF + s.index * ENTRY.size + 12, s.checksum << 24)
        if header != view[:len(header)]:
            raise ValueError("Regenerated table differs")
        rebuilt = hashlib.sha256(header)
        cursor = len(header)
        rows = []
        for s in segments:
            rebuilt.update(view[cursor:s.offset])
            plain_digest = hashlib.sha256()
            cipher_digest = hashlib.sha256()
            for start in range(0, s.size, chunk_size):
                end = min(start + chunk_size, s.size)
                cipher = view[s.offset + start:s.offset + end].tobytes()
                stream = key[start:end]
                plain = bytes((c - k) & 255 for c, k in zip(cipher, stream))
                encoded = bytes((p + k) & 255 for p, k in zip(plain, stream))
                if encoded != cipher:
                    raise ValueError(f"Segment {s.index} re-encoding differs at chunk {start}")
                rebuilt.update(encoded)
                plain_digest.update(plain)
                cipher_digest.update(cipher)
            row = {
                "index": s.index, "kind": f"0x{s.kind:04x}",
                "offset": s.offset, "size": s.size,
                "checksum_byte": s.checksum,
                "cipher_sha256": cipher_digest.hexdigest(),
                "plain_sha256": plain_digest.hexdigest(),
            }
            if decoded_dir is not None:
                reference = decoded_dir / f"{s.index:02d}_{s.kind:04x}.bin"
                with reference.open("rb") as f:
                    reference_digest = hashlib.file_digest(f, "sha256").hexdigest()
                if reference.stat().st_size != s.size or reference_digest != plain_digest.hexdigest():
                    raise ValueError(f"Segment {s.index} differs from {reference}")
                row["decoded_reference_matches"] = True
            rows.append(row)
            cursor = s.offset + s.size
        rebuilt.update(view[cursor:])
        rebuilt_digest = rebuilt.hexdigest()
        if rebuilt_digest != original_digest:
            raise ValueError("Reconstructed package digest differs")
        return {
            "evidence_type": "offline container roundtrip; no camera execution",
            "package_bytes": len(view), "package_sha256": original_digest,
            "reconstructed_sha256": rebuilt_digest, "byte_identical": True,
            "header_seed": f"0x{seed:08x}", "stream_prefix_crosscheck": True,
            "segment_count": len(segments), "segments": rows,
            "padding_bytes_preserved": len(view) - 0x300 - sum(s.size for s in segments),
            "firmware_image_written": False,
            "not_established": ["modified-image acceptance", "secure boot", "flash recovery"],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("firmware", type=Path)
    parser.add_argument("--decoded-dir", type=Path, help="Compare every decoded segment with existing files")
    parser.add_argument("--report", type=Path, help="Create a NEW JSON report (never a firmware image)")
    args = parser.parse_args()
    try:
        if args.report is not None and args.report.exists():
            raise ValueError("Report already exists; choose a new path")
        with args.firmware.open("rb") as f:
            if f.seek(0, 2) == 0:
                raise ValueError("Empty firmware file")
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
                report = check_roundtrip(data, args.decoded_dir)
        report["input_path"] = str(args.firmware.resolve())
        report["checker_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        report["stream_helper_sha256"] = hashlib.sha256(Path(__file__).with_name("decode_bf.py").read_bytes()).hexdigest()
        encoded = json.dumps(report, indent=2) + "\n"
        if args.report is not None:
            with args.report.open("x") as f:
                f.write(encoded)
            print(f"Verified {report['segment_count']} segments; byte-identical SHA-256 {report['package_sha256']}")
            print(f"Report: {args.report}")
        else:
            print(encoded, end="")
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
