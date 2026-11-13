#!/usr/bin/env python3
"""Compatibility alias for bfplus_ptp; prefer bfplus_ptp.py."""
import sys
import bfplus_ptp as _implementation

sys.modules[__name__] = _implementation
