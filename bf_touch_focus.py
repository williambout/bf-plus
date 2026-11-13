#!/usr/bin/env python3
"""Compatibility alias for bfplus_cli; prefer bfplus_cli.py."""
import sys
import bfplus_cli as _implementation

if __name__ == "__main__":
    _implementation.main()
else:
    sys.modules[__name__] = _implementation
