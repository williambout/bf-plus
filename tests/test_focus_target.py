"""Compiled targeting flow, with optional original firmware ABI/geometry checks.

No USB access. Synthetic detections cannot prove the detector runs with a
no-contact lens; that requires a live camera observation.
"""
from pathlib import Path
import struct
import unittest

from unicorn import arm64_const as r
from tests.test_touch_payload import Machine, FW, RESIDENT, STACK, STOP
from bfplus.build import build

DETECTOR = 0x4d72f40d8
SNAPSHOT = 0x4d3270e50
POSITION = 0x4d7034688
GET_POSITION, RAW_POSITION, SET_POSITION = 0x4d3319b00, 0x4d3319b30, 0x4d331d040
FIRMWARE = Path(__file__).resolve().parents[1] / 'decoded-V104/rtos-alt.bin'


def rectangle(x=100, y=120, width=80, height=60, valid=1, selected=0):
    return struct.pack('<BB4H', valid, selected, x, y, width, height)


class TargetMachine(Machine):
    def __init__(self, blob, symbols):
        super().__init__(blob, symbols)
        self.snapshots = [bytes(40)]
        self.snapshot_calls = 0
        self.zoom_fails = False
        self.position = (512, 341)

    @property
    def position(self):
        return struct.unpack('<2H', self.uc.mem_read(POSITION, 4))

    @position.setter
    def position(self, point):
        self.uc.mem_write(POSITION, struct.pack('<2H', *point))

    def target(self, offset=0):
        return self.get(RESIDENT+self.symbols['focus_target']+offset, 4)

    def enable(self):
        self.install()
        self.put(RESIDENT+self.symbols['focus_target'], 1, 4)

    def detection(self, primary=None, candidate1=None, candidate2=None, tracker=None):
        self.snapshots = [b''.join(part or bytes(10) for part in (primary,candidate1,candidate2,tracker))]

    def hook(self, u, pc, size, opaque):
        x0, x1 = u.reg_read(r.UC_ARM64_REG_X0), u.reg_read(r.UC_ARM64_REG_X1)
        if pc == SNAPSHOT:
            data = self.snapshots[min(self.snapshot_calls,len(self.snapshots)-1)]
            self.snapshot_calls += 1
            u.mem_write(x0, data)
        elif pc == GET_POSITION:
            u.mem_write(x0, struct.pack('<2H', *self.position))
        elif pc == RAW_POSITION:
            self.position = struct.unpack('<2H', u.mem_read(x0, 4))
            self.calls.append(('restore_position', self.position))
        elif pc == SET_POSITION:
            self.position = (x0, x1)
            self.calls.append(('target_position', self.position, self.mag))
        elif pc == 0x4d33a1e70 and self.zoom_fails:
            self.calls.append(('zoom_failed',))
            u.reg_write(r.UC_ARM64_REG_X0, 1)
        else:
            return super().hook(u, pc, size, opaque)
        u.reg_write(r.UC_ARM64_REG_PC, u.reg_read(r.UC_ARM64_REG_LR))


class TargetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.blob, cls.syms = build()

    def setUp(self):
        self.m = TargetMachine(self.blob, self.syms)
        self.m.enable()

    def test_native_selected_primary_wins_over_auxiliary_candidate_markers(self):
        m = self.m
        m.detection(primary=rectangle(500,300,24,24), candidate1=rectangle(300,210,70,70),
                    candidate2=rectangle(400,220,80,80,selected=1))
        m.zoom()
        self.assertEqual(m.position, (512,312))
        self.assertEqual(m.target(8), 1)
        self.assertEqual(m.snapshot_calls, 2)
        self.assertEqual(m.calls[:2], [('target_position',(512,312),2),('zoom',4,1)])

    def test_auxiliary_candidates_without_native_selected_target_do_not_retarget(self):
        for index in (1,2):
            for selected in (0,1):
                m = TargetMachine(self.blob,self.syms); m.enable()
                candidates = [None,None]
                candidates[index-1] = rectangle(400,200,70,70,selected=selected)
                m.detection(candidate1=candidates[0],candidate2=candidates[1])
                m.zoom()
                self.assertEqual(m.position,(512,341))
                self.assertEqual(m.target(8),0)

    def test_native_selected_target_stays_fixed_during_hold(self):
        m = self.m
        m.detection(primary=rectangle(300,210,20,10),candidate1=rectangle(400,220,70,70))
        m.zoom()
        self.assertEqual(m.position,(310,215))
        m.detection(primary=rectangle(600,300,10,10))
        m.event('mag_update',key=False)
        self.assertEqual(m.position,(310,215))
        self.assertEqual(m.snapshot_calls,2)

    def test_invalid_primary_does_not_fall_back_to_other_candidates(self):
        invalid = (rectangle(width=0),rectangle(height=0),rectangle(valid=0),
                   rectangle(valid=2),rectangle(x=1000,width=30),
                   rectangle(y=670,height=20),rectangle(x=65535,width=1))
        for primary in invalid:
            with self.subTest(primary=primary):
                m = TargetMachine(self.blob,self.syms); m.enable()
                m.detection(primary=primary,candidate1=rectangle(500,300,100,80))
                m.zoom()
                self.assertEqual(m.position,(512,341))
                self.assertEqual(m.target(8),0)

    def test_no_valid_detection_keeps_current_position_and_still_zooms(self):
        m = self.m; m.position=(330,310)
        m.detection(primary=rectangle(valid=0),candidate1=rectangle(width=0),tracker=rectangle())
        m.zoom()
        self.assertEqual(m.position,(330,310))
        self.assertEqual(m.calls,[('zoom',4,1)])
        self.assertEqual((m.target(4),m.target(8),m.target(24)),(0,0,1))

    def test_tracker_substituted_for_face_is_rejected(self):
        m = self.m
        m.put(DETECTOR+1,8,1); m.put(DETECTOR+0x40,2,4)
        m.detection(primary=rectangle(),tracker=rectangle())
        m.zoom()
        self.assertEqual(m.position,(512,341))
        self.assertEqual(m.target(24),1)

    def test_snapshot_changed_during_copy_is_rejected_without_retry(self):
        m = self.m
        m.snapshots=[rectangle()+bytes(30),rectangle(x=200)+bytes(30)]
        m.zoom()
        self.assertEqual(m.position,(512,341))
        self.assertEqual(m.snapshot_calls,2)
        self.assertEqual(m.target(28),1)
        self.assertEqual(m.target(4),0)

    def test_disabled_targeting_and_ineligible_touch_do_not_read_detector(self):
        for case in ('target_off','touch_off','electronic_lens','press','no_touch'):
            with self.subTest(case=case):
                m = TargetMachine(self.blob,self.syms); m.enable()
                m.detection(candidate1=rectangle())
                if case=='target_off': m.put(RESIDENT+self.syms['focus_target'],0,4)
                if case=='touch_off': m.put(RESIDENT+self.syms['state']+12,0,4)
                if case=='electronic_lens': m.lens=2
                m.put(0x4d72c2468,0x401 if case=='press' else 1,4)
                m.event('live',1,case!='no_touch',int(case=='press'))
                self.assertEqual(m.snapshot_calls,0)
                self.assertEqual(m.position,(512,341))

    def test_owned_exit_restores_original_point_and_magnification(self):
        for exit_kind in ('release','timer','press','stock_transition','live_return'):
            with self.subTest(exit_kind=exit_kind):
                m = TargetMachine(self.blob,self.syms); m.enable()
                m.position=(350,290); m.mag=1
                m.detection(primary=rectangle(400,200,20,10))
                m.zoom()
                self.assertEqual(m.calls[0],('target_position',(410,205),2))
                if exit_kind in ('release','timer'):
                    m.put(0x4d72c2468,0,4)
                    m.event('mag_update' if exit_kind=='timer' else 'mag',1,0)
                elif exit_kind=='press':
                    m.put(0x4d72c2468,0x401,4); m.event('mag',1,1,1)
                elif exit_kind=='stock_transition':
                    m.put(0x4d70346a4,4,4); m.event('mag',key=False)
                else:
                    m.event('live_update',key=False)
                self.assertEqual(m.position,(350,290))
                self.assertEqual(m.mag,1)
                self.assertEqual(m.target(4),0)
                self.assertEqual(m.calls.count(('restore_position',(350,290))),1)

    def test_failed_zoom_entry_restores_immediately_and_forwards_event(self):
        m = self.m; m.zoom_fails=True; m.mag=1
        m.detection(primary=rectangle())
        m.put(0x4d72c2468,1,4)
        self.assertEqual(m.event('live',1,1),0x42)
        self.assertEqual(m.position,(512,341))
        self.assertEqual(m.mag,1)
        self.assertEqual(m.target(4),0)
        self.assertEqual(m.get(RESIDENT+self.syms['state']+32,4),0)

    def test_movie_live_uses_same_targeting_and_stock_zoom_is_untouched(self):
        m = self.m
        m.detection(primary=rectangle(500,300,100,80))
        m.event('mag_update',key=False)
        self.assertEqual(m.snapshot_calls,0)
        m.put(0x4d72c2468,1,4); m.event('cine',1,1)
        self.assertEqual(m.position,(550,340))


class NativeTargetMachine(TargetMachine):
    def __init__(self, blob, symbols):
        super().__init__(blob,symbols)
        self.uc.mem_write(FW,FIRMWARE.read_bytes())
        self.uc.reg_write(r.UC_ARM64_REG_CPACR_EL1,3<<20)
        self.aspect=2

    def hook(self,u,pc,size,opaque):
        if pc==getattr(self,'stop_address',None):
            u.reg_write(r.UC_ARM64_REG_PC,STOP)
            return
        if pc in (SNAPSHOT,GET_POSITION,RAW_POSITION,SET_POSITION): return
        if pc==0x4d3007fc0:
            dst,src,n=(u.reg_read(reg) for reg in
                       (r.UC_ARM64_REG_X0,r.UC_ARM64_REG_X1,r.UC_ARM64_REG_X2))
            u.mem_write(dst,bytes(u.mem_read(src,n)))
            result=dst
        elif pc in (0x4d330f6f0,0x4d3319c60,0x4d330f3f0,0x4d3315350): result=0
        elif pc==0x4d3317670: result=self.aspect
        else: return super().hook(u,pc,size,opaque)
        u.reg_write(r.UC_ARM64_REG_X0,result)
        u.reg_write(r.UC_ARM64_REG_PC,u.reg_read(r.UC_ARM64_REG_LR))


@unittest.skipUnless(FIRMWARE.is_file(),'requires supplied decoded segment05')
class NativeTargetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.blob,cls.syms=build()

    def test_manual_zoom_matches_original_af_primary_selection(self):
        for primary in (rectangle(600,300,24,24),rectangle(0,0,20,20),bytes(10)):
            snapshot=primary+rectangle(300,200,90,90,selected=1)+bytes(20)
            native=NativeTargetMachine(self.blob,self.syms)
            native.uc.mem_write(STACK+0xf000+0x68,snapshot)
            native.stop_address=0x4d3398f18
            native.run(0x4d3398ef0)  # original AF subject-center block
            manual=NativeTargetMachine(self.blob,self.syms)
            manual.uc.mem_write(RESIDENT,self.blob)
            manual.put(RESIDENT+self.syms['state']+12,1,4)
            manual.put(RESIDENT+self.syms['focus_target'],1,4)
            manual.uc.mem_write(DETECTOR+0x90,snapshot)
            manual.zoom()
            self.assertEqual(manual.position,native.position)

    def test_original_setter_clamps_visible_window_and_raw_restore_is_exact(self):
        m=NativeTargetMachine(self.blob,self.syms)
        # Execute resident code directly; firmware loading replaces installer fixtures.
        m.uc.mem_write(RESIDENT,self.blob)
        m.put(RESIDENT+self.syms['state']+12,1,4)
        m.put(RESIDENT+self.syms['focus_target'],1,4)
        m.put(0x4d70346a0,2,4); m.put(0x4d70346a4,12,4)
        for mag,aspect,expected in ((2,2,(256,170)),(3,2,(128,85)),(2,1,(256,224))):
            with self.subTest(mag=mag,aspect=aspect):
                m.mag=mag; m.aspect=aspect
                m.run(SET_POSITION,0,0)
                self.assertEqual(m.position,expected)
                m.run(SET_POSITION,1023,681)
                self.assertEqual(m.position,(1023-expected[0],681-expected[1]))
        m.mag=1; m.aspect=2; m.position=(333,277)
        m.uc.mem_write(DETECTOR+0x90,rectangle(0,0,10,10)+bytes(30))
        m.zoom()
        self.assertEqual(m.position,(256,170))
        m.put(0x4d72c2468,0,4); m.event('mag_update',key=False)
        self.assertEqual(m.position,(333,277))

    def test_original_producer_marks_auxiliary_candidate_and_separates_tracker(self):
        m=NativeTargetMachine(self.blob,self.syms)
        raw,tracker,out=STACK+0x3000,STACK+0x3300,STACK+0x3400
        m.uc.mem_write(raw,bytes(0x228)); m.uc.mem_write(tracker,bytes(0x48))
        m.put(raw+0xc,1,4)
        m.uc.mem_write(raw+0x1c0,struct.pack('<4h',9216,6144,4096,4096))
        m.put(raw+0x1e8,1,4); m.put(raw+0x1ec,1,4)
        m.uc.mem_write(raw+0x200,struct.pack('<8h',8000,5000,512,512,10000,5000,512,512))
        m.put(raw+0x214,1,4)
        m.uc.mem_write(raw+0x218,struct.pack('<4h',11000,5200,256,256))
        for side,index in ((1,1),(0,2)):
            with self.subTest(side=side):
                m.put(raw+0x210,side,1)
                m.run(0x4d326c4c0,0,0,raw,tracker,out)
                records=[struct.unpack('<BB4H',m.uc.mem_read(out+i*10,10)) for i in range(4)]
                self.assertEqual([rec[0] for rec in records],[1,1,1,0])
                self.assertEqual([rec[1] for rec in records[1:3]], [int(index==1),int(index==2)])
                # Producer output: top-left/size in 1024x682 logical space.
                self.assertEqual(records[0][2:],(398,227,228,228))
                self.assertEqual(records[index][2:],(604,282,14,14))
        # Tracking takeover may also substitute record zero; target_apply guards it.
        m.put(DETECTOR+1,8,1); m.put(DETECTOR+0x40,2,4)
        m.put(raw+3,2,1); m.put(tracker+1,1,1)
        m.uc.mem_write(tracker+0x30,struct.pack('<4H',6000,4000,2000,2000))
        m.run(0x4d326c4c0,0,1,raw,tracker,out)
        self.assertEqual(bytes(m.uc.mem_read(out+2,8)),bytes(m.uc.mem_read(out+32,8)))


if __name__=='__main__': unittest.main()
