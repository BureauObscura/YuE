#!/usr/bin/env python3
"""Wrap the project PNG in a Windows ICO container without third-party modules."""
from pathlib import Path
import struct
import sys


def main() -> int:
    source, destination = map(Path, sys.argv[1:3])
    png = source.read_bytes()
    if png[:8] != b"\x89PNG\r\n\x1a\n" or png[12:16] != b"IHDR":
        raise ValueError("Icon source must be a PNG")
    width, height = struct.unpack(">II", png[16:24])
    if not (0 < width <= 256 and 0 < height <= 256):
        raise ValueError("ICO PNG must be between 1 and 256 pixels in each dimension")
    encoded_width = width if 0 < width < 256 else 0
    encoded_height = height if 0 < height < 256 else 0
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", encoded_width, encoded_height, 0, 0, 1, 32, len(png), 22)
    destination.write_bytes(header + entry + png)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
