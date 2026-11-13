#!/usr/bin/env python3
"""Compatibility alias for bfplus_camera_files; prefer bfplus_camera_files.py."""
import sys
import bfplus_camera_files as _implementation

if __name__ == "__main__":
    _implementation.main()
else:
    sys.modules[__name__] = _implementation
