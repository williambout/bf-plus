"""Compatibility alias for bfplus.build."""
import importlib
import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("bfplus.build", run_name="__main__")
else:
    sys.modules[__name__] = importlib.import_module("bfplus.build")
