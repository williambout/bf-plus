"""Run the supplied native producer and renderer with the relocated frame hook."""
import struct
import unittest

from unicorn import arm64_const as r
from bfplus_cli import PATCHES, CODE_PATCHES
from tests.test_focus_target import TargetMachine, FIRMWARE, rectangle
from tests.test_touch_payload import FW, RESIDENT, STACK, STOP
from bfplus.build import build

FRAME = 0x4d72aa598
STOCK_FRAME = 0x4d7034670
PRODUCER, RENDERER = 0x4d31a7470, 0x4d31a7240
ISLAND = 0x4d331ce50


class FrameMachine(TargetMachine):
    def __init__(self, blob, symbols):
        super().__init__(blob, symbols)
        self.uc.mem_write(FW, FIRMWARE.read_bytes())
        self.uc.mem_write(RESIDENT, blob)
        for address, _, name in PATCHES:
            self.put(address, RESIDENT+symbols[name])
        for address, _, value, size in CODE_PATCHES:
            self.put(address, value, size)
        self.put(RESIDENT+symbols['state']+12, 1, 4)
        self.put(RESIDENT+symbols['focus_target'], 1, 4)
        self.put(STOCK_FRAME-8, 100)
        self.focus_mode = 2
        self.af_mode = 7
        self.af_time = 50
        self.draws = []
        self.uc.reg_write(r.UC_ARM64_REG_CPACR_EL1, 3 << 20)

    def hook(self, u, pc, size, opaque):
        x0, x1, x2 = [u.reg_read(getattr(r, f'UC_ARM64_REG_X{i}')) for i in range(3)]
        if pc == 0x4d3007fc0:
            u.mem_write(x0, bytes(u.mem_read(x1, x2)))
        elif pc == 0x4d3159120:
            data = bytearray(0x68)
            struct.pack_into('<I', data, 4, self.af_mode)
            u.mem_write(x0, bytes(data)); self.put(x1, self.af_time)
        elif pc == 0x4d331d9e0:
            u.reg_write(r.UC_ARM64_REG_X0, self.focus_mode)
        elif pc == 0x4d31a5c00:  # hardware clock used by stock AF frame writeback
            u.reg_write(r.UC_ARM64_REG_X0, 100)
        elif pc in (0x4d3320850, 0x4d33211c0, 0x4d331eb10):
            u.reg_write(r.UC_ARM64_REG_X0, 0)
        elif pc == 0x4d320b990:
            self.draws.append(struct.unpack('<6HI', bytes(u.mem_read(x1, 16))))
        elif pc == 0x4d320bad0:
            self.draws = []
        elif pc in (0x4d320ba90, 0x4d320bef0, 0x4d320bb10):
            pass
        else:
            return super().hook(u, pc, size, opaque)
        u.reg_write(r.UC_ARM64_REG_PC, u.reg_read(r.UC_ARM64_REG_LR))

    def update(self):
        self.run(PRODUCER, 0, 0, 0, 0, STACK+0x4000)
        self.run(RENDERER)

    def frame(self):
        return struct.unpack('<3I4H', self.uc.mem_read(FRAME, 20))


@unittest.skipUnless(FIRMWARE.is_file(), 'requires supplied decoded segment05')
class SubjectFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.blob, cls.syms = build()

    def test_native_renderer_draws_native_primary_in_detection_gray(self):
        m = FrameMachine(self.blob, self.syms)
        m.detection(primary=rectangle(), candidate1=rectangle(300,200,20,20),
                    candidate2=rectangle(600,300,20,20,selected=1))
        m.update()
        self.assertEqual(m.frame(), (1,15,0,100,120,80,60))
        self.assertEqual(len(m.draws), 2)  # native outline + gray stroke
        self.assertEqual(m.draws[-1][-1], 0x888888)
        self.assertEqual(m.draws[-1][4], 2)  # same thin stroke as AF detection
        self.assertEqual(m.target(12), 0)  # rendering does not count as a zoom
        self.assertEqual(bytes(m.uc.mem_read(STOCK_FRAME,20)), bytes(20))
        self.assertEqual(m.get(STOCK_FRAME-8), 100)

    def test_native_target_moves_and_clears_when_subject_is_lost(self):
        m = FrameMachine(self.blob, self.syms)
        for x in (100,300,700):
            m.detection(primary=rectangle(x,220,80,60)); m.update()
            self.assertEqual(m.frame(), (1,15,0,x,220,80,60))
            self.assertEqual(m.draws[-1][-1], 0x888888)
        m.detection(); m.update()
        self.assertEqual(m.frame()[:3], (0,0,0))
        self.assertEqual(m.draws, [])

    def test_override_supersedes_newer_and_older_af_status(self):
        for af_mode in (0,1,2,4,5,6,7,8,9,10,11,12,13):
            for af_time in (0,50,200):
                with self.subTest(af_mode=af_mode,af_time=af_time):
                    m = FrameMachine(self.blob, self.syms)
                    m.af_mode=af_mode; m.af_time=af_time
                    m.detection(primary=rectangle(400,300,20,20)); m.update()
                    self.assertEqual(m.frame(), (1,15,0,400,300,20,20))

    def test_disabled_option_other_lenses_and_nonlive_scenes_keep_stock_data(self):
        for change in ('option','touch','removed','lens1','lens2','menu','zoom','pending'):
            with self.subTest(change=change):
                m = FrameMachine(self.blob, self.syms)
                m.detection(primary=rectangle()); m.update()
                if change=='option': m.put(RESIDENT+self.syms['focus_target'],0,4)
                if change in ('touch','removed'):
                    m.put(RESIDENT+self.syms['state']+12,0 if change=='touch' else 2,4)
                if change.startswith('lens'): m.lens=int(change[-1])
                if change in ('menu','zoom'): m.put(0x4d70346a0,3,4)
                if change=='zoom': m.put(RESIDENT+self.syms['state']+32,1,4)
                if change=='pending': m.put(0x4d70346a4,3,4)
                m.update()
                self.assertEqual(m.frame()[:3], (0,0,0))
                self.assertEqual(m.draws, [])

    def test_tracker_and_unstable_snapshot_do_not_draw(self):
        for kind in ('tracker','takeover','unstable','invalid'):
            m = FrameMachine(self.blob,self.syms)
            if kind=='tracker': m.detection(tracker=rectangle())
            if kind=='takeover':
                m.detection(primary=rectangle()); m.put(0x4d72f40d9,8,1); m.put(0x4d72f4118,2,4)
            if kind=='unstable': m.snapshots=[rectangle()+bytes(30),bytes(40),rectangle()+bytes(30)]
            if kind=='invalid': m.detection(candidate1=rectangle(width=0))
            m.update()
            self.assertEqual(m.draws, [])

    def test_manual_box_matches_unmodified_native_af_display(self):
        for primary in (rectangle(100,120,80,60),rectangle(600,300,24,24)):
            manual=FrameMachine(self.blob,self.syms)
            af=FrameMachine(self.blob,self.syms)
            af.lens=2; af.focus_mode=0; af.af_mode=0
            af.put(STOCK_FRAME+4,1,4)  # native AF idle frame state
            for m in (manual,af):
                m.detection(primary=primary,candidate1=rectangle(300,200,90,90,selected=1),
                            candidate2=rectangle(700,400,60,60))
                m.update()
            self.assertEqual(manual.frame(),af.frame())
            self.assertEqual(manual.draws,af.draws)

    def test_unrelated_snapshot_callers_receive_exact_original(self):
        m = FrameMachine(self.blob,self.syms)
        m.detection(primary=rectangle())
        original=struct.pack('<3I4H',1,15,7,20,40,60,80)
        m.uc.mem_write(STOCK_FRAME,original)
        out,stamp=STACK+0x3000,STACK+0x3100
        m.run(ISLAND,out,stamp)
        self.assertEqual(bytes(m.uc.mem_read(out,20)),original)
        self.assertEqual(m.get(stamp),100)


if __name__ == '__main__': unittest.main()
