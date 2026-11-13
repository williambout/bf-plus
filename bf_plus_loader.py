#!/usr/bin/env python3
"""Compatibility alias for bfplus_loader; prefer bfplus_loader.py."""
import sys
import bfplus_loader as _implementation

sys.modules[__name__] = _implementation
