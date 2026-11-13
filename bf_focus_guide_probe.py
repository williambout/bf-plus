#!/usr/bin/env python3
"""Compatibility alias for bfplus_focus_guide_probe; prefer bfplus_focus_guide_probe.py."""
import sys
import bfplus_focus_guide_probe as _implementation

if __name__ == "__main__":
    _implementation.main()
else:
    sys.modules[__name__] = _implementation
