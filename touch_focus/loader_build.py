"""Compatibility alias for bfplus.loader_build."""
import importlib
import runpy
import sys

if __name__ == "__main__":
    runpy.run_module("bfplus.loader_build", run_name="__main__")
else:
    sys.modules[__name__] = importlib.import_module("bfplus.loader_build")
