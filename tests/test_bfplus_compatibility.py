"""Legacy entrypoints must share BF+ state and preserve command behavior."""
import importlib
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
ALIASES = {
    'bf_touch_focus': 'bfplus_cli',
    'bf_touch_ptp': 'bfplus_ptp',
    'bf_plus_loader': 'bfplus_loader',
    'bf_camera_files': 'bfplus_camera_files',
    'bf_focus_guide_probe': 'bfplus_focus_guide_probe',
    'bf_focus_raw_probe': 'bfplus_focus_raw_probe',
    'touch_focus.build': 'bfplus.build',
    'touch_focus.loader_build': 'bfplus.loader_build',
}


class CompatibilityTests(unittest.TestCase):
    def test_import_aliases_share_modules_including_mutable_transport_and_install_state(self):
        for old, new in ALIASES.items():
            with self.subTest(old=old):
                self.assertIs(importlib.import_module(old), importlib.import_module(new))

    def test_legacy_and_current_help_commands_match_without_camera_access(self):
        commands = [([old+'.py'], [ALIASES[old]+'.py']) for old in (
            'bf_touch_focus', 'bf_camera_files', 'bf_focus_guide_probe', 'bf_focus_raw_probe')]
        commands.append((['-m', 'touch_focus.loader_build'], ['-m', 'bfplus.loader_build']))
        for old, new in commands:
            with self.subTest(old=old):
                results = [subprocess.run([sys.executable, *args, '--help'], cwd=ROOT,
                                          capture_output=True, text=True, timeout=15,
                                          check=True) for args in (old, new)]
                for result in results:
                    self.assertEqual(result.stderr, '')
                # argparse wraps usage according to the executable name's
                # width; compare the same options/help independent of layout.
                legacy = results[0].stdout.replace(old[-1], new[-1]).split()
                self.assertEqual(legacy, results[1].stdout.split())


if __name__ == '__main__':
    unittest.main()
