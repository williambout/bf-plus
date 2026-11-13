"""Execute original BF 1.04 native navigation with the extended choices.

No USB. Native step/get/set/arrow/sequence-render instructions run; display
transport and resource lookup are intercepted. Photos need hardware validation.
"""
import hashlib
import struct
import unittest
from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn import arm64_const as r
from tests.test_aspect_ratio import AspectMachine, FIRMWARE, IMAGE_HASH
from tests.test_touch_menu import build_menu_fixture
from tests.test_touch_payload import FW, RESIDENT, STACK, STOP

# Start at the getter; stop after the corresponding native setter/refresh.
PATHS = ((0x4d3394bf8,0x4d3394c28,20,None),
         (0x4d33a31ec,0x4d33a320c,19,None),
         (0x4d33a3630,0x4d33a3650,None,0),
         (0x4d33a3f9c,0x4d33a3fbc,None,-1),
         (0x4d33a4028,0x4d33a4048,21,None),
         (0x4d33a418c,0x4d33a41ac,None,1))
LABEL_CALLS = (0x4d335693c,0x4d33a2aa0,0x4d33a3700)

class NativeAspectMachine(AspectMachine):
    def __init__(self,*args):
        super().__init__(*args)
        self.glyphs=[]
        self.native_labels=[]
        self.uc.mem_write(0x4d7034730,struct.pack('<IIQIIQ',1,0,0x4d3e21ba8,256,0,0x4d3e21ba8))
        self.uc.mem_write(STACK+0x9000,b'native\0')

    def hook(self,u,pc,size,opaque):
        if pc==0x4d322e020:
            xy=u.reg_read(r.UC_ARM64_REG_X1)
            self.glyphs.append((u.reg_read(r.UC_ARM64_REG_X0),
                               struct.unpack('<2H2B',self.read(xy,6)),
                               u.reg_read(r.UC_ARM64_REG_X2)))
            u.reg_write(r.UC_ARM64_REG_X0,0)
            u.reg_write(r.UC_ARM64_REG_PC,u.reg_read(r.UC_ARM64_REG_LR))
        elif pc==0x4d33724b0:
            self.native_labels.append(u.reg_read(r.UC_ARM64_REG_X0))
            u.reg_write(r.UC_ARM64_REG_X0,STACK+0x9000)
            u.reg_write(r.UC_ARM64_REG_PC,u.reg_read(r.UC_ARM64_REG_LR))
        else:
            return super().hook(u,pc,size,opaque)

    def slice(self,start,end):
        self.uc.reg_write(r.UC_ARM64_REG_SP,STACK+0xf000)
        self.uc.emu_start(start,end,count=200000)
        assert self.uc.reg_read(r.UC_ARM64_REG_PC)==end
        return self.uc.reg_read(r.UC_ARM64_REG_X0)

    def step(self,path,delta=0):
        start,end,reg,fixed=path
        if reg: self.uc.reg_write(getattr(r,f'UC_ARM64_REG_X{reg}'),delta & 0xffff)
        self.slice(start,end)

    def enabled(self,value):
        self.run(RESIDENT+self.symbols['aspect_extra_select'],value)

    def position(self,value):
        self.enabled(1)
        self.run(0x4d33208a0,value if value<7 else 6)
        if value>=7: self.run(RESIDENT+self.symbols['aspect_select'],value-6)

    def current(self):
        return 6+self.aspect if self.aspect else self.get(self.settings+0x18,4)


@unittest.skipUnless(FIRMWARE.exists(),'local BF 1.04 image required')
class NativeAspectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.firmware=FIRMWARE.read_bytes()
        assert hashlib.sha256(cls.firmware).hexdigest()==IMAGE_HASH
        cls.blob,cls.symbols=build_menu_fixture()

    def setUp(self):
        self.m=NativeAspectMachine(self.blob,self.symbols,self.firmware)

    def test_all_six_native_paths_reach_each_choice_without_storing_private_enum(self):
        m=self.m; writes=[]
        def observe(u,access,address,size,value,opaque): writes.append(value)
        watch=m.uc.hook_add(UC_HOOK_MEM_WRITE,observe,begin=m.settings+0x18,end=m.settings+0x1b)
        try:
            for path in PATHS:
                for position in range(10):
                    for delta in ((-1,0,1) if path[3] is None else (path[3],)):
                        with self.subTest(path=hex(path[0]),position=position,delta=delta):
                            m.position(position); m.step(path,delta)
                            self.assertEqual(m.current(),max(0,min(9,position+delta)))
                            self.assertLess(m.run(0x4d3317670),7)
            self.assertTrue(writes)
            self.assertTrue(all(0<=v<=6 for v in writes))
        finally: m.uc.hook_del(watch)

    def test_off_is_default_and_stops_at_native_boundary_for_all_paths(self):
        m=self.m
        self.assertEqual(m.get(RESIDENT+self.symbols['aspect_extra_enabled'],4),0)
        for path in PATHS:
            for position in range(7):
                for delta in ((-1,0,1) if path[3] is None else (path[3],)):
                    m.run(0x4d33208a0,position); m.step(path,delta)
                    self.assertEqual(m.current(),max(0,min(6,position+delta)))

    def test_off_restores_retained_native_choice_and_keeps_queued_photo_crop(self):
        m=self.m
        for original in range(7):
            m.run(0x4d33208a0,original); m.enabled(1)
            m.run(RESIDENT+self.symbols['aspect_select'],2)
            encoded=m.call_from(0x4d3320850,0x4d324358c)
            m.enabled(0)
            self.assertEqual(m.current(),original)
            self.assertEqual(m.get(RESIDENT+self.symbols['aspect_extra_enabled'],4),0)
            metadata=m.prepare(0,encoded=encoded); m.encode_metadata(metadata)
            self.assertEqual((m.encodes[0][3],m.encodes[0][5]),(6016,2560))
            m.release()

    def test_seal_prevents_off_from_stranding_an_active_crop(self):
        m=self.m; m.position(8)
        m.put(m.aspect_address+12,6,4)
        m.enabled(0)
        self.assertEqual(m.aspect,2)
        self.assertEqual(m.get(RESIDENT+self.symbols['aspect_extra_enabled'],4),1)

    def test_restricted_modes_cannot_admit_private_choices(self):
        m=self.m; m.enabled(1)
        for field,value in (('restriction',1),('shooting_mode',0x10),('secondary_mode',5)):
            setattr(m,field,value)
            for path in PATHS:
                m.run(0x4d33208a0,6); m.step(path,1)
                self.assertLess(m.current(),7)
            setattr(m,field,0)

    def test_mode_change_between_step_and_commit_never_stores_private_enum(self):
        m=self.m; m.enabled(1)
        for caller in (0x4d3394c24,0x4d33a320c,0x4d33a3650,
                       0x4d33a3fbc,0x4d33a4048,0x4d33a41ac):
            for value in (7,8,9):
                m.run(0x4d33208a0,6)
                m.shooting_mode=0x10
                m.call_from(0x4d33208a0,caller,value)
                self.assertEqual(m.current(),6)
                m.shooting_mode=0

    def test_original_arrow_instructions_show_last_only_at_final_extra(self):
        m=self.m
        for enabled,maximum in ((0,6),(1,9)):
            for position in range(maximum+1):
                m.position(position); m.enabled(enabled)
                m.slice(0x4d33a3668,0x4d33a3680)
                self.assertEqual(m.uc.reg_read(r.UC_ARM64_REG_X5),
                                 0x123 if position==0 else 0x121 if position==maximum else 0x122)

    def test_main_and_editor_label_calls_show_custom_text_and_native_fallback(self):
        m=self.m
        for call in LABEL_CALLS:
            for position,text,identifier in ((7,b'65:24',0x100),(8,b'2.35:1',0x100),(9,b'5:4',0x103)):
                m.position(position)
                m.uc.reg_write(r.UC_ARM64_REG_X0,identifier)
                address=m.slice(call,call+4)
                self.assertEqual(m.text(address),text)
            m.enabled(0); m.uc.reg_write(r.UC_ARM64_REG_X0,0xff)
            self.assertEqual(m.text(m.slice(call,call+4)),b'native')
            self.assertEqual(m.native_labels[-1],0xff)

    def test_sub_lcd_runs_native_font_renderer_with_centered_bounded_glyphs(self):
        m=self.m; table=0x4d3e21ba8
        for position,ids in ((7,(30,26,53,14,22)),(8,(14,57,18,26,53,10)),(9,(26,53,22))):
            m.position(position); m.glyphs.clear(); m.run(0x4d336a100)
            self.assertEqual(len(m.glyphs),len(ids))
            width=sum(m.get(table+(i-1)*16,2) for i in ids)
            x=80-width//2
            for (pointer,(gx,gy,w,h),flags),identifier in zip(m.glyphs,ids):
                self.assertEqual(pointer,m.get(table+(identifier-1)*16+8))
                self.assertEqual((gx,gy,h,flags),(x,35,26,1))
                self.assertTrue(0<=gx and gx+w<=160)
                x+=w
            self.assertEqual(x,80+(width+1)//2)
        m.enabled(0); m.glyphs.clear(); m.run(0x4d336a100)
        self.assertEqual(len(m.glyphs),1)
        self.assertEqual(m.glyphs[0][0],m.get(table+(207-1)*16+8))

if __name__=='__main__': unittest.main()
