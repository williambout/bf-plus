#!/usr/bin/env python3
"""Compatibility alias for bfplus_focus_raw_probe; prefer bfplus_focus_raw_probe.py."""
import sys
import bfplus_focus_raw_probe as _implementation

if __name__ == "__main__":
    _implementation.main()
else:
    sys.modules[__name__] = _implementation
