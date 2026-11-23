"""Tests for valheim_cheatflag. Run with:  python -m unittest discover tests"""

import hashlib
import os
import struct
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import valheim_cheatflag as vc  # noqa: E402


def _str(s: str) -> bytes:
    b = s.encode("utf-8")
    return bytes([len(b)]) + b


def make_fch(name="Ragnar", used_cheats=True, cheats_stat=3.0, seed="", worlds=("Midgard",)) -> bytes:
    """Build a synthetic character file with the same layout as a Valheim 1.0 save (version 47)."""
    stats = [0.0] * 205
    stats[0] = 7.0                      # Deaths
    stats[vc._STAT_CHEATS_INDEX] = cheats_stat
    body = struct.pack("<III", 47, len(stats), 10)
    body += b"".join(struct.pack("<f", v) for v in stats)
    body += struct.pack("<i", len(worlds)) + b"".join(_str(w) + struct.pack("<f", 1.0) for w in worlds)
    body += os.urandom(4000).replace(b"\x00", b"\x7f").replace(b"\x01", b"\x7f")  # stand-in for map data
    body += _str(name) + struct.pack("<q", 123456789) + _str(seed)
    body += bytes([1 if used_cheats else 0]) + struct.pack("<q", int(time.time()) - 86400)
    body += b"\x01" + os.urandom(500)   # rest of the player data
    return (struct.pack("<I", len(body)) + body + struct.pack("<I", 64)
            + hashlib.sha512(body).digest())


class CheatFlagTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "ragnar.fch"

    def tearDown(self):
        self.dir.cleanup()

    def write(self, data: bytes) -> Path:
        self.path.write_bytes(data)
        return self.path

    def test_detects_flagged_character(self):
        info = vc.load(self.write(make_fch()))
        self.assertEqual(info.name, "Ragnar")
        self.assertTrue(info.used_cheats)
        self.assertEqual(info.cheats_stat, 3.0)
        self.assertTrue(info.checksum_ok)

    def test_clean_clears_flag_stat_and_fixes_checksum(self):
        original = make_fch()
        info = vc.load(self.write(original))
        out = vc.clean(info)
        after = vc.load(self.write(bytes(out)))
        self.assertFalse(after.used_cheats)
        self.assertEqual(after.cheats_stat, 0.0)
        self.assertTrue(after.checksum_ok)
        changed = [i for i in range(len(out)) if out[i] != original[i]]
        hash_start = len(out) - 64
        # Only the flag byte, the stat float and the checksum may change.
        self.assertTrue(all(i in (info.flag_offset,) or 16 <= i < 36 or i >= hash_start for i in changed))

    def test_keep_stat(self):
        info = vc.load(self.write(make_fch()))
        after = vc.load(self.write(bytes(vc.clean(info, reset_stat=False))))
        self.assertFalse(after.used_cheats)
        self.assertEqual(after.cheats_stat, 3.0)

    def test_seed_and_unicode_name(self):
        info = vc.load(self.write(make_fch(name="Bjørn Æsir", seed="abcDEF123")))
        self.assertEqual(info.name, "Bjørn Æsir")
        self.assertTrue(info.used_cheats)

    def test_clean_character(self):
        info = vc.load(self.write(make_fch(used_cheats=False, cheats_stat=0.0)))
        self.assertTrue(info.is_clean)

    def test_rejects_garbage(self):
        with self.assertRaises(vc.FchError):
            vc.load(self.write(os.urandom(2000)))

    def test_cli_clean_makes_backup(self):
        self.write(make_fch())
        rc = vc.main(["clean", "-y", str(self.path)])
        self.assertEqual(rc, 0)
        self.assertTrue(any(p.name.startswith("ragnar.fch.precleanup-") for p in self.path.parent.iterdir()))
        self.assertTrue(vc.load(self.path).is_clean)


if __name__ == "__main__":
    unittest.main()
