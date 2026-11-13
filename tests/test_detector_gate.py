"""Exercise relocated code hooks, caller isolation and exact restoration offline."""
import unittest
from pathlib import Path

from unicorn import arm64_const as r
from bfplus_cli import CODE_PATCHES, PATCHES
from tests.test_touch_payload import Machine, STAGE, RESIDENT, STOP, FW, LIVE_LITERAL, LIVE
from bfplus.build import build

CALL, ISLAND = 0x4d326dcd4, 0x4d3321270


class GateMachine(Machine):
    def __init__(self, blob, symbols):
        super().__init__(blob,symbols)
        self.stock_mode=0
        self.raw_mode=3

    def hook(self,u,pc,size,opaque):
        if pc==CALL+4:
            u.reg_write(r.UC_ARM64_REG_PC,STOP)
            return
        if pc in (0x4d33211c0,0x4d3318500):
            self.calls.append(('setting',pc))
            u.reg_write(r.UC_ARM64_REG_X0,self.stock_mode if pc==0x4d33211c0 else self.raw_mode)
            u.reg_write(r.UC_ARM64_REG_PC,u.reg_read(r.UC_ARM64_REG_LR))
            return
        return super().hook(u,pc,size,opaque)

    def config(self,enabled=1,mode=1,lens=0):
        self.put(RESIDENT+self.symbols['focus_target'],enabled,4)
        self.put(RESIDENT+self.symbols['state']+12,mode,4)
        self.lens=lens


class DetectorGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.blob,cls.syms=build()

    def test_only_enabled_manual_detector_caller_gets_override(self):
        m=GateMachine(self.blob,self.syms); m.install()
        for enabled,mode,lens,stock,expected in (
                (1,1,0,0,3),(0,1,0,0,0),(1,0,0,0,0),(1,2,0,0,0),
                (1,1,1,0,0),(1,1,2,0,0),(1,1,0,2,2),(1,1,0,3,3)):
            with self.subTest(enabled=enabled,mode=mode,lens=lens,stock=stock):
                m.config(enabled,mode,lens); m.stock_mode=stock
                self.assertEqual(m.run(CALL),expected)
                self.assertEqual(m.get(RESIDENT+self.syms['detector_gate']+12,4),expected)
        self.assertEqual(m.get(RESIDENT+self.syms['detector_gate'],4),8)
        self.assertEqual(m.get(RESIDENT+self.syms['detector_gate']+4,4),1)

    def test_uses_native_detection_mode_and_explicit_on_enables_automatic_if_off(self):
        m=GateMachine(self.blob,self.syms); m.install(); m.config()
        for mode in range(4):
            m.raw_mode=mode
            self.assertEqual(m.run(CALL),mode or 1)

    def test_normal_raw_setting_veneer_callers_are_unchanged(self):
        m=GateMachine(self.blob,self.syms); m.install(); m.config()
        for value in range(4):
            m.raw_mode=value
            self.assertEqual(m.run(ISLAND),value)
        self.assertEqual(m.get(RESIDENT+self.syms['detector_gate'],4),0)
        self.assertEqual(m.calls,[('setting',0x4d3318500)]*4)

    def test_installs_and_removes_exact_code_and_pointer_hooks(self):
        m=GateMachine(self.blob,self.syms); m.install()
        for address,_,replacement,size in CODE_PATCHES:
            self.assertEqual(m.get(address,size),replacement)
        self.assertEqual(m.get(ISLAND+8),RESIDENT+self.syms['detector_gate_wrapper'])
        ctl=STAGE+self.syms['control']; m.put(ctl+64,1,4)
        m.run(STAGE,1,2,3)
        self.assertEqual(m.get(ctl+16),0)
        for address,original,_,size in CODE_PATCHES:
            self.assertEqual(m.get(address,size),original)
        for address,original,_ in PATCHES:
            self.assertEqual(m.get(address),original)
        # A retained stale callback forwards to the stock effective setting.
        m.config(mode=2)
        self.assertEqual(m.run(RESIDENT+self.syms['detector_gate_wrapper']),m.raw_mode)

    def test_unrecognized_code_aborts_before_any_hook_write(self):
        for address,_,_,size in CODE_PATCHES:
            m=GateMachine(self.blob,self.syms)
            m.put(address,0xdeadbeef,size)
            m.run(STAGE,1,2,3)
            self.assertEqual(m.get(STAGE+self.syms['control']+16),6)
            self.assertEqual(m.get(LIVE_LITERAL),LIVE)
            self.assertEqual(m.get(ISLAND+8),0)

    @unittest.skipUnless((Path(__file__).resolve().parents[1]/'decoded-V104/rtos-alt.bin').is_file(),
                         'requires supplied decoded segment05')
    def test_reconstructed_original_branches_match_supplied_firmware(self):
        data=(Path(__file__).resolve().parents[1]/'decoded-V104/rtos-alt.bin').read_bytes()
        for address,original,_,size in CODE_PATCHES:
            self.assertEqual(int.from_bytes(data[address-FW:address-FW+size],'little'),original)
        self.assertEqual(data[ISLAND+8-FW:ISLAND+16-FW],bytes(8))


if __name__=='__main__': unittest.main()
