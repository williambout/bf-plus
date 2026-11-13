"""Container reconstruction tests use entirely synthetic firmware-like data."""
import tempfile
import unittest
from pathlib import Path
import struct

from tools.check_bf_roundtrip import check_roundtrip
from tools.decode_bf import ENTRY, KNOWN_32, MAGIC, vendor_prefix


def synthetic_package(seed=0x6985374A):
    # Independent scalar xorshift encoding; nonzero gaps and a trailing footer
    # catch accidental layout normalization in the checker.
    plains = [b"synthetic metadata", bytes(range(73)), KNOWN_32 + bytes(range(256))]
    raw = bytearray(b"\xa5" * 0x900)
    raw[:12] = MAGIC
    struct.pack_into("<I", raw, 12, seed)
    struct.pack_into("<H", raw, 24, len(plains))
    for i, plain in enumerate(plains):
        offset = 0x300 + i * 0x200
        cipher = bytes((p + k) & 255 for p, k in zip(plain, vendor_prefix(seed, len(plain))))
        raw[offset:offset + len(cipher)] = cipher
        ENTRY.pack_into(raw, 0x100 + i * 16, i, i, offset, len(cipher), ((-sum(cipher)) & 255) << 24)
    return raw, plains


class RoundtripTests(unittest.TestCase):
    def test_all_bytes_and_independent_reference(self):
        raw, plains = synthetic_package()
        before = bytes(raw)
        with tempfile.TemporaryDirectory() as folder:
            for i, plain in enumerate(plains):
                (Path(folder) / f"{i:02d}_{i:04x}.bin").write_bytes(plain)
            result = check_roundtrip(raw, Path(folder), chunk_size=37)
        self.assertTrue(result["byte_identical"])
        self.assertEqual(result["package_sha256"], result["reconstructed_sha256"])
        self.assertEqual(bytes(raw), before)
        self.assertTrue(all(s["decoded_reference_matches"] for s in result["segments"]))

    def test_zero_seed_is_one_and_stream_resets_per_segment(self):
        for seed in (0, 1, 0xFFFFFFFF, 0x690AB9FB):
            with self.subTest(seed=seed):
                self.assertTrue(check_roundtrip(synthetic_package(seed)[0], chunk_size=13)["byte_identical"])

    def test_cipher_corruption_rejected(self):
        raw, _ = synthetic_package()
        raw[0x500] ^= 1
        with self.assertRaisesRegex(ValueError, "checksum"):
            check_roundtrip(raw)

    def test_repaired_checksum_is_not_authentication(self):
        raw, plains = synthetic_package()
        original = check_roundtrip(raw)["package_sha256"]
        raw[0x500] ^= 1
        checksum = (-sum(raw[0x500:0x500 + len(plains[1])])) & 255
        struct.pack_into("<I", raw, 0x110 + 12, checksum << 24)
        result = check_roundtrip(raw)
        self.assertTrue(result["byte_identical"])
        self.assertNotEqual(result["package_sha256"], original)
        self.assertIn("modified-image acceptance", result["not_established"])

    def test_wrong_seed_with_valid_cipher_checksums_rejected(self):
        raw, _ = synthetic_package()
        raw[12] ^= 1
        with self.assertRaisesRegex(ValueError, "prefixes disagree"):
            check_roundtrip(raw)

    def test_truncation_overlap_index_and_trailer_rejected(self):
        for field, value in (("offset", 0x301), ("size", 0x10000), ("index", 7), ("trailer", 1)):
            raw, _ = synthetic_package()
            offset, fmt = {"offset": (4, "<I"), "size": (8, "<I"), "index": (0, "<H"), "trailer": (12, "<I")}[field]
            struct.pack_into(fmt, raw, 0x110 + offset, value)
            with self.subTest(field=field), self.assertRaises(ValueError):
                check_roundtrip(raw)
        for size in (0, 20, 0x250, 0x800):
            with self.subTest(size=size), self.assertRaises(ValueError):
                check_roundtrip(synthetic_package()[0][:size])

    def test_reference_mismatch_rejected(self):
        raw, _ = synthetic_package()
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "00_0000.bin").write_bytes(b"different")
            with self.assertRaisesRegex(ValueError, "differs from"):
                check_roundtrip(raw, Path(folder))


if __name__ == "__main__":
    unittest.main()
