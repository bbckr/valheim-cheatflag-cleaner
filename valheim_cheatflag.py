#!/usr/bin/env python3
"""
valheim_cheatflag.py - clear the "used cheats" flag from a Valheim character (.fch).

Valheim 1.0 permanently marks a character as a cheater when it detects dev command
use, and shows "Achievement progress is permanently disabled for this character due
to dev command usage". This tool resets that mark in the character save file:

  * the character's persistent "used cheats" flag   -> false
  * the "Cheats" entry in the character statistics  -> 0
  * the file's SHA-512 checksum                       -> recalculated

Nothing else in the file is touched. A backup is written before any change.

Usage:
    python valheim_cheatflag.py list                 # list characters in the usual save folders
    python valheim_cheatflag.py scan  <file|name>    # read-only report
    python valheim_cheatflag.py clean <file|name>    # clear the flag (makes a backup first)

<file|name> may be a path to a .fch file or just the character's file name
(e.g. "moonkej"), which is looked up in the default save folders.

Requires Python 3.8+ and nothing else.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import struct
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

__version__ = "1.0.0"

# Valheim Early Access launch (2021-02-02). Character creation dates before this are impossible.
_MIN_CREATED = 1612137600
_HASH_LEN = 64  # SHA-512
_STATS_OFFSET = 16  # stats array starts here inside the file (after length, version, count, unknown int)
_STAT_CHEATS_INDEX = 4  # PlayerStatType: Deaths, CraftsOrUpgrades, Builds, Jumps, Cheats, ...


class FchError(Exception):
    """Raised when a file does not look like a Valheim character save we understand."""


@dataclass
class FchInfo:
    path: Path
    raw: bytearray
    data_len: int
    version: int
    stats_count: int
    name: str
    player_id: int
    created_unix: int
    flag_offset: int
    cheats_stat_offset: Optional[int]
    checksum_ok: bool

    @property
    def used_cheats(self) -> bool:
        return self.raw[self.flag_offset] == 1

    @property
    def cheats_stat(self) -> Optional[float]:
        if self.cheats_stat_offset is None:
            return None
        return struct.unpack_from("<f", self.raw, self.cheats_stat_offset)[0]

    @property
    def is_clean(self) -> bool:
        stat = self.cheats_stat
        return not self.used_cheats and (stat is None or stat == 0.0)


# --------------------------------------------------------------------------- parsing

def _checksum(raw: bytes, data_len: int) -> bytes:
    return hashlib.sha512(raw[4 : 4 + data_len]).digest()


def _find_profile_header(raw: bytes, end: int) -> List[tuple]:
    """
    Locate the profile header written as:
        string name | int64 playerID | string startSeed | bool usedCheats | int64 dateCreated
    (strings are .NET BinaryWriter strings: 1-byte length for < 128 chars, then UTF-8).

    The header sits after the per-world map data, whose position varies, so we scan for
    the one place where all five fields line up and the creation date is plausible.
    """
    now = int(time.time())
    hits = []
    for p in range(20, end - 9):
        if raw[p] not in (0, 1):
            continue
        created = struct.unpack_from("<q", raw, p + 1)[0]
        if not (_MIN_CREATED <= created <= now + 365 * 86400):
            continue
        for seed_len in range(0, 64):
            q = p - seed_len - 1  # seed length byte
            if q < 13 or raw[q] != seed_len:
                continue
            id_start = q - 8
            for name_len in range(1, 64):
                ls = id_start - name_len - 1
                if ls < 4:
                    break
                if raw[ls] != name_len:
                    continue
                try:
                    name = bytes(raw[ls + 1 : id_start]).decode("utf-8")
                except UnicodeDecodeError:
                    continue
                if name.strip() and name.isprintable():
                    pid = struct.unpack_from("<q", raw, id_start)[0]
                    hits.append((p, name, pid, created))
    return hits


def _stats_look_valid(raw: bytes, count: int, end: int) -> bool:
    """The stats array is followed by the known-worlds dictionary (int count, then string/float pairs)."""
    after = _STATS_OFFSET + count * 4
    if not (0 < count < 2000) or after + 4 > end:
        return False
    worlds = struct.unpack_from("<i", raw, after)[0]
    if not (0 <= worlds < 10000):
        return False
    if worlds == 0:
        return True
    ln = raw[after + 4]
    if ln == 0 or ln >= 128:
        return False
    try:
        bytes(raw[after + 5 : after + 5 + ln]).decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def load(path: Path, expected_name: Optional[str] = None) -> FchInfo:
    raw = bytearray(path.read_bytes())
    if len(raw) < 4 + 16 + 4 + _HASH_LEN:
        raise FchError("File is too small to be a Valheim character.")

    data_len = struct.unpack_from("<I", raw, 0)[0]
    end = 4 + data_len
    if end + 4 + _HASH_LEN > len(raw):
        raise FchError("Length header doesn't match the file size - not a .fch, or truncated.")
    if struct.unpack_from("<I", raw, end)[0] != _HASH_LEN:
        raise FchError("Checksum block not found where expected - unsupported file layout.")

    checksum_ok = raw[end + 4 : end + 4 + _HASH_LEN] == _checksum(raw, data_len)
    version = struct.unpack_from("<I", raw, 4)[0]
    stats_count = struct.unpack_from("<I", raw, 8)[0]

    hits = _find_profile_header(raw, end)
    if expected_name and len(hits) > 1:
        narrowed = [h for h in hits if h[1].lower() == expected_name.lower()]
        hits = narrowed or hits
    if not hits:
        raise FchError("Couldn't find the character header (name / ID / cheat flag). "
                       "The save format may have changed - nothing was modified.")
    if len(hits) > 1:
        raise FchError(f"Found {len(hits)} possible cheat-flag locations, refusing to guess. "
                       "Nothing was modified.")
    flag_offset, name, pid, created = hits[0]

    cheats_off = None
    if _stats_look_valid(raw, stats_count, end) and stats_count > _STAT_CHEATS_INDEX:
        cheats_off = _STATS_OFFSET + _STAT_CHEATS_INDEX * 4

    return FchInfo(path, raw, data_len, version, stats_count, name, pid, created,
                   flag_offset, cheats_off, checksum_ok)


def clean(info: FchInfo, reset_stat: bool = True) -> bytearray:
    out = bytearray(info.raw)
    out[info.flag_offset] = 0
    if reset_stat and info.cheats_stat_offset is not None:
        struct.pack_into("<f", out, info.cheats_stat_offset, 0.0)
    end = 4 + info.data_len
    out[end + 4 : end + 4 + _HASH_LEN] = _checksum(out, info.data_len)
    return out


# --------------------------------------------------------------------------- file locations

def default_save_dirs() -> List[Path]:
    home = Path.home()
    dirs = []
    rel = Path("IronGate") / "Valheim"
    # Windows
    if os.name == "nt":
        base = Path(os.environ.get("USERPROFILE", home)) / "AppData" / "LocalLow" / rel
        dirs += [base / "characters_local", base / "characters"]
    # Linux / Steam Deck (native)
    base = home / ".config" / "unity3d" / rel
    dirs += [base / "characters_local", base / "characters"]
    # macOS
    base = home / "Library" / "Application Support" / rel
    dirs += [base / "characters_local", base / "characters"]
    # WSL: Windows saves under /mnt/c/Users/*
    users = Path("/mnt/c/Users")
    if users.is_dir():
        for u in users.iterdir():
            base = u / "AppData" / "LocalLow" / rel
            dirs += [base / "characters_local", base / "characters"]
    return [d for d in dirs if d.is_dir()]


def resolve(target: str) -> Path:
    p = Path(target).expanduser()
    if p.is_file():
        return p
    name = target if target.lower().endswith(".fch") else target + ".fch"
    matches = [d / name for d in default_save_dirs() if (d / name).is_file()]
    if not matches:
        raise FchError(f"'{target}' not found. Pass the full path to the .fch file, "
                       f"or run 'list' to see the characters I can find.")
    if len(matches) > 1:
        listing = "\n  ".join(str(m) for m in matches)
        raise FchError(f"'{target}' exists in more than one folder - pass the full path:\n  {listing}")
    return matches[0]


# --------------------------------------------------------------------------- CLI

def _report(info: FchInfo) -> None:
    created = time.strftime("%Y-%m-%d", time.localtime(info.created_unix))
    stat = info.cheats_stat
    rows = [
        ("File", str(info.path)),
        ("Character", f"{info.name}   (created {created}, save version {info.version})"),
        ("Used-cheats flag", "ON" if info.used_cheats else "off"),
        ("Cheats stat", "unknown" if stat is None else f"{stat:g}"),
        ("Checksum", "valid" if info.checksum_ok else "INVALID (will be fixed on clean)"),
    ]
    for label, value in rows:
        print(f"{label + ':':<18}{value}")


def cmd_list(_args) -> int:
    dirs = default_save_dirs()
    if not dirs:
        print("No Valheim character folders found. Pass the .fch path directly.")
        return 1
    for d in dirs:
        files = sorted(d.glob("*.fch"))
        print(f"{d}:")
        for f in files:
            try:
                i = load(f, f.stem)
                state = "FLAGGED" if not i.is_clean else "clean"
                print(f"  {f.stem:<24} {i.name:<20} {state}")
            except FchError as e:
                print(f"  {f.stem:<24} (couldn't read: {e})")
        if not files:
            print("  (empty)")
    return 0


def cmd_scan(args) -> int:
    path = resolve(args.target)
    _report(load(path, path.stem))
    return 0


def cmd_clean(args) -> int:
    path = resolve(args.target)
    info = load(path, path.stem)
    _report(info)
    if info.is_clean and info.checksum_ok:
        print("\nNothing to do - this character isn't flagged.")
        return 0
    if not args.yes:
        print("\nMake sure Valheim is closed. Steam Cloud users: see the README first.")
        if input("Clear the cheat flag? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Cancelled, nothing changed.")
            return 1
    if not args.no_backup:
        backup = path.with_name(path.name + f".precleanup-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(path, backup)
        print(f"{'Backup:':<18}{backup}")
    out = clean(info, reset_stat=not args.keep_stat)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(out)
    os.replace(tmp, path)
    after = load(path, path.stem)
    if after.used_cheats or (not args.keep_stat and not after.is_clean) or not after.checksum_ok:
        print("Verification failed - restore the backup.", file=sys.stderr)
        return 2
    print("Done. The cheat flag is cleared and the checksum is valid.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="valheim_cheatflag",
        description="Clear Valheim 1.0's permanent 'used cheats' flag from a character save.")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list characters in the default save folders").set_defaults(fn=cmd_list)
    s = sub.add_parser("scan", help="show a character's cheat status (read-only)")
    s.add_argument("target", help="path to a .fch file, or a character file name")
    s.set_defaults(fn=cmd_scan)
    c = sub.add_parser("clean", help="clear the cheat flag (backs up first)")
    c.add_argument("target", help="path to a .fch file, or a character file name")
    c.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
    c.add_argument("--no-backup", action="store_true", help="don't write a backup copy")
    c.add_argument("--keep-stat", action="store_true", help="leave the 'Cheats' statistic as is")
    c.set_defaults(fn=cmd_clean)
    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except FchError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
