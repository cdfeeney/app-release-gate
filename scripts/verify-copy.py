#!/usr/bin/env python3
"""The app's copy of Tour.swift must be byte-identical to the kit's. Exit 1 otherwise.

    python3 verify-copy.py <kit-root> <app-copy-of-Tour.swift>
"""
import hashlib
import sys
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


kit = Path(sys.argv[1]) / "tour" / "ios" / "Tour.swift"
app = Path(sys.argv[2])
if not app.exists():
    print(f"missing {app}: copy {kit} into the UI test target")
    sys.exit(1)
if digest(kit) != digest(app):
    print(f"{app} differs from the kit's Tour.swift; copy the kit version, never edit the copy")
    sys.exit(1)
print("Tour.swift copy matches the kit")
