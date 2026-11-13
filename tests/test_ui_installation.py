"""Standalone loader calling the actual BF+ resident entry, entirely offline.

Native allocation/storage and privileged cache/TLB instructions are stubbed;
C loader, image CRC, BSS setup, resident initialization and exact hook install/
restore execute. The reduced resident keeps native display/input paths and
has no compositor scratch or display-drain state.
"""
from dataclasses import replace
import unittest

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from unicorn import UC_HOOK_CODE
from unicorn import arm64_const as r

import bf_plus_loader as loader
from bf_touch_focus import PATCHES, CODE_PATCHES, UI_L2_SLOT, UI_L2_RO
from tests.test_segmented_loader import Machine, BASE, OWNER
from tests.test_touch_menu import build_menu_fixture


class ResidentMachine(Machine):
    def __init__(self, blob, symbols):
        super().__init__()
        self.symbols = symbols
        self.package = loader.ResidentImage(blob, symbols['__end'],
                                            symbols['resident_entry'], symbols['__scratch_size'])
        for address, original, _ in PATCHES:
            self.put(address, original)
        for address, original, _, size in CODE_PATCHES:
            self.put(address, original, size)
        self.put(UI_L2_SLOT, UI_L2_RO)
        self.put(0x4d7303098, 0x4d3398940)
        self.put(0x4d73030a0, 0x4d3396120)
        self.put(0x4d7303030, 0x4d3392c40)
        self.put(0x4d7303038, 0x4d338ef10)
        decoder = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
        decoder.skipdata = True
        for ins in decoder.disasm(blob, BASE):
            if ins.mnemonic not in ('mrs', 'msr', 'dc', 'ic', 'dsb', 'dmb', 'isb', 'tlbi'):
                continue
            def system(u, pc, size, opaque, op=ins.mnemonic, args=ins.op_str):
                if op == 'mrs':
                    dst, src = args.split(', ')
                    value = dict(currentel=4, ctr_el0=self.ctr, mair_el1=0xff,
                                 tcr_el1=0, daif=0)[src.lower()]
                    u.reg_write(getattr(r, 'UC_ARM64_REG_'+dst.upper()), value)
                u.reg_write(r.UC_ARM64_REG_PC, pc+4)
            self.uc.hook_add(UC_HOOK_CODE, system, begin=ins.address, end=ins.address)

    def installed(self):
        request = self.prepare(self.package)
        for offset in range(0, len(self.package.image), loader.WRITE_MAX):
            self.uc.mem_write(BASE+offset, self.package.image[offset:offset+loader.WRITE_MAX])
        return self.commit(request)

    def remove_request(self, result):
        return replace(result, command=loader.REMOVE, request_nonce=103, done=0)


class ProductionUiInstallationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.blob, cls.symbols = build_menu_fixture()

    def machine(self):
        return ResidentMachine(self.blob, self.symbols)

    def assert_hooks(self, m, installed):
        for address, original, name in PATCHES:
            self.assertEqual(m.get(address), BASE+self.symbols[name] if installed else original,
                             f'pointer {address:#x}')
        for address, original, replacement, size in CODE_PATCHES:
            self.assertEqual(m.get(address, size), replacement if installed else original,
                             f'code {address:#x}')
        self.assertEqual(m.get(loader.L2_SLOT), loader.L2_RO)
        self.assertEqual(m.get(UI_L2_SLOT), UI_L2_RO)
        self.assertEqual(m.get(loader.CALLBACK), loader.ORIGINAL)

    def test_real_resident_install_and_exact_removal_without_ui_drain(self):
        m = self.machine()
        self.assertGreater(len(self.blob), loader.WRITE_MAX)
        self.assertEqual(self.symbols['__scratch_size'],0)
        self.assertNotIn('ui',self.symbols)
        self.assertNotIn('menu_orientation',self.symbols)
        c = m.installed()
        self.assertEqual((c.result, c.entry_result, c.phase), (0, 0, loader.COMMITTED))
        self.assert_hooks(m, True)
        self.assertEqual(m.get(BASE+self.symbols['state']+16), c.identity_nonce)
        self.assertEqual(m.get(BASE+self.symbols['state']+24), OWNER)
        self.assertEqual(m.get(BASE+self.symbols['aspect_extra_enabled'],4),0)
        c = m.run(m.remove_request(c))
        self.assertEqual((c.result, c.entry_result, c.phase), (0, 0, loader.REMOVED))
        self.assert_hooks(m, False)
        self.assertEqual(m.get(BASE+self.symbols['state']+12, 4), 2)
        self.assertEqual(sum(e[0]=='allocate' for e in m.events), 1)
        self.assertEqual(sum(e[0]=='writer' for e in m.events), 3)
        self.assertEqual(m.get(BASE+self.symbols['state']+24), OWNER)

    def test_owned_center_touch_blocks_removal_without_ui_state(self):
        m=self.machine();c=m.installed()
        m.put(BASE+self.symbols['state']+32,1,4)
        c=m.run(m.remove_request(c))
        self.assertEqual((c.result,c.entry_result,c.phase),(11,9,loader.FAILED))
        self.assert_hooks(m,True)
        self.assertEqual(m.get(BASE+self.symbols['state']+12,4),0)
        self.assertEqual(m.get(BASE+self.symbols['aspect_ratio']+12,4)&4,0)

    def test_failed_restore_keeps_mode_and_unseals_aspect_admission(self):
        m=self.machine();c=m.installed()
        address,_,replacement,size=CODE_PATCHES[0]
        m.put(address,replacement^1,size)
        c=m.run(m.remove_request(c))
        self.assertEqual((c.result,c.entry_result,c.phase),(11,6,loader.FAILED))
        self.assertEqual(m.get(BASE+self.symbols['state']+12,4),0)
        self.assertEqual(m.get(BASE+self.symbols['aspect_ratio']+12,4)&4,0)
        for a,_,name in PATCHES:self.assertEqual(m.get(a),BASE+self.symbols[name])
        for a,_,v,n in CODE_PATCHES:self.assertEqual(m.get(a,n),v^int(a==address))

    def test_native_ui_sites_are_untouched_during_install_and_removal(self):
        m=self.machine();sites=(0x4d31ad3f4,0x4d33232f8,0x4d3351e98)
        for i,address in enumerate(sites):m.put(address,0x12345670+i,4)
        c=m.installed();self.assertEqual(c.result,0)
        self.assert_hooks(m,True)
        c=m.run(m.remove_request(c));self.assertEqual(c.result,0)
        self.assert_hooks(m,False)
        for i,address in enumerate(sites):self.assertEqual(m.get(address,4),0x12345670+i)

    def test_hook_mismatch_refuses_all_other_hook_changes(self):
        m = self.machine()
        changed,original,_,n=CODE_PATCHES[0]
        m.put(changed, original ^ 1, n)
        c = m.installed()
        self.assertEqual((c.result, c.entry_result, c.phase), (11, 6, loader.FAILED))
        for address, expected, _ in PATCHES:
            self.assertEqual(m.get(address), expected)
        for address, expected, _, size in CODE_PATCHES:
            self.assertEqual(m.get(address, size), expected ^ int(address==changed))
        self.assertEqual(m.get(loader.L2_SLOT), loader.L2_RO)
        self.assertEqual(m.get(UI_L2_SLOT), UI_L2_RO)
