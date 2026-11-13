"""Run BF+ crops through the supplied BF 1.04 descriptor/metadata routines.

No USB or encoder MMIO is used. Real JPEG bitstreams and editor behavior need
camera/file verification; these tests establish bounds, ABI and propagation.
"""
from pathlib import Path
import hashlib
import struct
import unittest

from unicorn import UC_HOOK_CODE
from unicorn import arm64_const as r

from bf_touch_focus import PATCHES, CODE_PATCHES, ASPECT_SNAPSHOT_SITES, ASPECT_FINGERPRINTS
from bf_plus_loader import Control
from tests.test_touch_menu import MenuMachine, build_menu_fixture, DEPTH, PENDING
from tests.test_touch_payload import FW, RESIDENT, STACK, STAGE, STOP

FIRMWARE = Path(__file__).resolve().parents[1] / 'decoded-V104/rtos-alt.bin'
IMAGE_HASH = 'f747c1350f00526b9c68c65aaef44d6e7b644b0169992342e12f059c42e150dc'
MAIN, HALF, SMALL, DNG, VIEW = (0x4d3daa870, 0x4d3daa720, 0x4d3daa6c8,
                               0x4d3cab100, 0x4d3cabc60)
CROP = struct.Struct('<IIHH')
EXPECTED = {
    1: ((80,186,5980,2208), (96,128,3770,1392)),
    2: ((64,10,6016,2560), (96,24,3760,1600)),
    3: ((64,14,4980,3984), (64,8,3180,2544)),
}
RATIOS = {1:(65,24), 2:(47,20), 3:(5,4)}


class AspectMachine(MenuMachine):
    def __init__(self, blob, symbols, firmware):
        super().__init__(blob, symbols)
        self.uc.mem_write(FW, firmware)
        self.uc.mem_map(0x400000000,0xc0000)
        self.uc.reg_write(r.UC_ARM64_REG_CPACR_EL1, 3 << 20)
        self.settings = STACK+0x3000
        self.put(0x4d7301b98, self.settings)
        self.put(self.settings+0x18, 2, 4)
        self.encodes = []
        self.restriction = self.shooting_mode = self.secondary_mode = 0
        self.receive_id, self.receive_result = 0, 2
        self.install()

    def hook(self, u, pc, size, opaque):
        if pc in (0x4d327a140, 0x4d327a150, 0x4d3269960, 0x4d3033700,
                  0x4d30336d0, 0x4d3008458):
            result = 0
        elif pc == 0x4d3033ab0:
            queue, pointer, timeout = (u.reg_read(getattr(r, f'UC_ARM64_REG_X{i}'))
                                       for i in range(3))
            self.calls.append(('id_received', queue, pointer, timeout))
            # The native receive clobbers x1 even when it succeeds. A bridge
            # that reads the ID through that clobbered register is incorrect.
            self.put(pointer, self.receive_id, 2)
            u.reg_write(r.UC_ARM64_REG_X1, 0xdeadbeef)
            result = self.receive_result
        elif pc == 0x4d30339d0:
            pointer=u.reg_read(r.UC_ARM64_REG_X1)
            if u.reg_read(r.UC_ARM64_REG_LR)==0x4d3268ff0:
                # An optimized tailcall can retain the native release LR.
                pass
            identifier=self.get(pointer,2)
            assert self.get(RESIDENT+self.symbols['aspect_jobs']+identifier,1)==0
            self.calls.append(('id_returned',identifier))
            result=0
        elif pc == 0x4d32ffea0:
            self.encodes.append(struct.unpack('<3Q3H', self.read(
                u.reg_read(r.UC_ARM64_REG_X0), 30)))
            result = 4096
        elif pc == 0x4d3319c60:
            result = self.restriction
        elif pc == 0x4d330f3f0:
            result = self.shooting_mode
        elif pc == 0x4d3315350:
            result = self.secondary_mode
        elif pc == 0x4d31e36b0:
            result = 0  # Orientation is independent of the crop backend.
        else:
            return super().hook(u, pc, size, opaque)
        u.reg_write(r.UC_ARM64_REG_X0, result)
        u.reg_write(r.UC_ARM64_REG_PC, u.reg_read(r.UC_ARM64_REG_LR))

    def choose(self, value):
        # BF+ enables extra native choices; ratio selection itself belongs to
        # the stock editor. Backend tests set the choice directly after using
        # the real boolean picker. Native editor paths have separate coverage.
        self.enter_picker(2)
        self.put(self.picker_address+3, 1, 1)
        self.send(picker=True, changed=1, press=1)
        self.run(RESIDENT+self.symbols['menu_picker_leave'])
        self.put(DEPTH, 2, 4)
        self.put(PENDING, 12, 4)
        self.run(RESIDENT+self.symbols['aspect_select'],value)

    def crop(self, symbol, selected, size):
        address = RESIDENT+self.symbols[symbol]+((selected-1)*2+size)*CROP.size
        return CROP.unpack(self.read(address, CROP.size))

    def call_from(self, pc, caller, *args):
        for i,arg in enumerate(args):
            self.uc.reg_write(getattr(r, f'UC_ARM64_REG_X{i}'), arg)
        self.uc.reg_write(r.UC_ARM64_REG_SP, STACK+0xf000)
        self.uc.reg_write(r.UC_ARM64_REG_LR, caller)
        self.uc.emu_start(pc, caller, count=200000)
        assert self.uc.reg_read(r.UC_ARM64_REG_PC) == caller
        return self.uc.reg_read(r.UC_ARM64_REG_X0)

    def prepare(self,size,slot=0,encoded=None):
        if encoded is None:
            encoded=self.call_from(0x4d3317670,ASPECT_SNAPSHOT_SITES[0])
        metadata=0x400000000+slot*4096
        self.put(metadata+0x58,size,4)
        self.put(STACK+0x6010,encoded,4)
        self.uc.reg_write(r.UC_ARM64_REG_X19,metadata)
        self.uc.reg_write(r.UC_ARM64_REG_X21,STACK+0x6000)
        self.uc.reg_write(r.UC_ARM64_REG_SP,STACK+0xf000)
        self.uc.emu_start(0x4d32fd9dc,0x4d32fd9e4,count=200000)
        assert self.uc.reg_read(r.UC_ARM64_REG_PC)==0x4d32fd9e4
        assert self.get(metadata+0x74,4)==encoded&255
        return metadata

    def encode_metadata(self,metadata):
        planes=STACK+0x6000
        self.uc.mem_write(planes, struct.pack('<8IQ',
            0x1000,0x1000000,0x2000,0x3000,0x4000,0x5000,0x6000,0x7000,
            0x450000000))
        self.encodes.clear()
        self.run(0x4d3300100, planes, 0x460000000, metadata)
        return metadata

    def encode(self,size,index):
        metadata=self.prepare(size)
        assert self.get(metadata+0x74,4)==index
        return self.encode_metadata(metadata)

    def release(self,slot=0):
        self.run(0x4d3268fb0,slot)

    def remove_resident(self):
        state=RESIDENT+self.symbols['state']
        # This fixture does not run display tasks. Model the loader host's
        # completed landscape drain before testing the independent crop gate.
        if 'ui' in self.symbols:
            ui=RESIDENT+self.symbols['ui']
            for name,value in (('removing',1),('ready',1),('displayed',0),('frame',0)):
                self.put(ui+self.symbols[f'__ui_{name}_offset'],value,4)
        request=Control(identity_nonce=self.get(state+16),owner=self.get(state+24),
                        resident=RESIDENT,image_size=len(self.blob),
                        memory_size=self.symbols['__end'],
                        scratch_size=self.symbols['__scratch_size'],mode=1)
        self.uc.mem_write(STACK+0x7000,request.pack())
        return self.run(RESIDENT+self.symbols['resident_entry'],1,STACK+0x7000,0x8444c004)

    def dng(self,metadata):
        destination=STACK+0x8000
        self.uc.reg_write(r.UC_ARM64_REG_X27,metadata)
        self.uc.reg_write(r.UC_ARM64_REG_X19,destination-0xc8)
        self.uc.reg_write(r.UC_ARM64_REG_SP,STACK+0xf000)
        self.uc.emu_start(0x4d3262190,0x4d32621c0,count=10000)
        assert self.uc.reg_read(r.UC_ARM64_REG_PC)==0x4d32621c0
        return struct.unpack('<8I',self.read(destination,32))


@unittest.skipUnless(FIRMWARE.exists(), 'local BF 1.04 image required')
class AspectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.firmware = FIRMWARE.read_bytes()
        if hashlib.sha256(cls.firmware).hexdigest() != IMAGE_HASH:
            raise RuntimeError('Aspect tests require the analyzed BF 1.04 segment')
        cls.blob, cls.symbols = build_menu_fixture()

    def setUp(self):
        self.m = AspectMachine(self.blob, self.symbols, self.firmware)

    def original(self, address, size):
        offset=address-FW if address<0x4d7000000 else address-0x4d7000000+0xebdfb0
        return self.firmware[offset:offset+size]

    def test_all_hook_originals_match_the_supplied_firmware(self):
        for address, original, _ in PATCHES:
            self.assertEqual(int.from_bytes(self.original(address,8),'little'),original)
        for address, original, _, size in CODE_PATCHES:
            self.assertEqual(int.from_bytes(self.original(address,size),'little'),original)

    def test_aspect_fingerprints_cover_untouched_native_regions(self):
        patched = [(address, 8) for address, _, _ in PATCHES]
        patched += [(address, size) for address, _, _, size in CODE_PATCHES]
        for (address, size), digest in ASPECT_FINGERPRINTS.items():
            with self.subTest(address=hex(address)):
                self.assertEqual(hashlib.sha256(self.original(address,size)).hexdigest(),digest)
                self.assertFalse(any(address < other+length and other < address+size
                                     for other,length in patched))

    def test_native_initialization_and_restoration_preserve_every_table(self):
        m=self.m
        frozen={name:m.read(RESIDENT+self.symbols[name],length) for name,length in
                (('aspect_main',72),('aspect_half',72),('aspect_small',72),('aspect_dng',192))}
        for selection in (0,1,2,3,0):
            m.choose(selection)
            for name,before in frozen.items():
                self.assertEqual(m.read(RESIDENT+self.symbols[name],len(before)),before)
            for literal,table in ((0x4d3295f08,MAIN),(0x4d3295f58,HALF),(0x4d3295f98,SMALL),(0x4d3264cb8,DNG)):
                self.assertEqual(m.get(literal),table)
            if not selection:
                self.assertEqual(m.read(RESIDENT+self.symbols['aspect_view'],28),self.original(VIEW,28))
        self.assertEqual(m.get(m.settings+0x18,4),2)

    def test_exact_main_ratios_and_preserved_native_allocations(self):
        m=self.m
        for selection, entries in EXPECTED.items():
            m.choose(selection)
            index=5 if selection==3 else 0
            for size,expected in enumerate(entries):
                with self.subTest(selection=selection,size=size):
                    row=size*7+index
                    actual=m.crop('aspect_main',selection,size)
                    self.assertEqual(actual,expected)
                    x,y,width,height=actual
                    ox,oy,ow,oh=CROP.unpack(self.original(MAIN+12*row,12))
                    self.assertGreaterEqual(x,ox); self.assertGreaterEqual(y,oy)
                    self.assertLessEqual(x+width,ox+ow); self.assertLessEqual(y+height,oy+oh)
                    a,b=RATIOS[selection]
                    self.assertEqual(width*b,height*a)
                    self.assertEqual(x%16,0)
            for literal,table in ((0x4d3295f00,0x4d3daaac0),
                                  (0x4d3295f50,0x4d3daa970),(0x4d3295f90,0x4d3daa918)):
                self.assertEqual(m.get(literal),table)
            self.assertEqual(m.read(MAIN,168),self.original(MAIN,168))

    def test_previews_remain_in_bounds_and_track_the_main_field_of_view(self):
        m=self.m
        for selection in EXPECTED:
            m.choose(selection); index=5 if selection==3 else 0
            for size in range(2):
                row=size*7+index
                x,y,w,h=m.crop('aspect_main',selection,size)
                ox,oy,ow,oh=CROP.unpack(self.original(MAIN+12*row,12))
                for name,table,table_row in (('aspect_half',HALF,row),('aspect_small',SMALL,index)):
                    with self.subTest(selection=selection,size=size,preview=name):
                        px,py,pw,ph=m.crop(name,selection,size)
                        nx,ny,nw,nh=CROP.unpack(self.original(table+12*table_row,12))
                        self.assertGreater(pw,0); self.assertGreater(ph,0)
                        self.assertGreaterEqual(px,nx); self.assertGreaterEqual(py,ny)
                        self.assertLessEqual(px+pw,nx+nw); self.assertLessEqual(py+ph,ny+nh)
                        self.assertEqual(px%16,0)
                        self.assertEqual(pw%2,0); self.assertEqual(ph%2,0)
                        self.assertLess(abs((px-nx)-(x-ox)*nw/ow),16)
                        self.assertLess(abs((py-ny)-(y-oy)*nh/oh),1)
                        self.assertLess(abs(pw-w*nw/ow),2)
                        self.assertLess(abs(ph-h*nh/oh),2)

    def test_original_encoder_builder_carries_all_dimensions_and_aligned_planes(self):
        m=self.m
        for selection in EXPECTED:
            m.choose(selection); index=5 if selection==3 else 0
            for size in range(2):
                with self.subTest(selection=selection,size=size):
                    metadata=m.encode(size,index)
                    self.assertEqual(len(m.encodes),4)
                    for ordinal,name,offset in ((0,'aspect_main',0x7bc),
                                                (1,'aspect_small',0x79c),
                                                (2,'aspect_half',0x7ac)):
                        _,_,width,height=m.crop(name,selection,size)
                        p0,p1,_,dw,stride,dh=m.encodes[ordinal]
                        self.assertEqual((dw,dh),(width,height))
                        self.assertEqual((p0%16,p1%16),(0,0))
                        self.assertGreaterEqual(stride,width)
                        self.assertEqual(struct.unpack('<2H',m.read(metadata+offset,4)),(width,height))
                    # Fixed native thumbnail has a separate content mapping.
                    self.assertEqual((m.encodes[3][3],m.encodes[3][5]),(160,120))
                    # The save coordinator supplies metadata+0x780 as x3;
                    # fileWriteJpeg keeps that in x20. Its native EXIF stores
                    # must use the same post-encode dimensions as the JPEG.
                    template=0x4d70305e0
                    m.uc.mem_write(template,self.original(template-0x3142050,0x300))
                    m.uc.reg_write(r.UC_ARM64_REG_X0,template)
                    m.uc.reg_write(r.UC_ARM64_REG_X20,metadata+0x780)
                    m.uc.emu_start(0x4d326697c,0x4d3266990,count=100)
                    self.assertEqual(m.uc.reg_read(r.UC_ARM64_REG_PC),0x4d3266990)
                    self.assertEqual(m.get(template+0x2ce,2),0xa002)
                    self.assertEqual(m.get(template+0x2da,2),0xa003)
                    self.assertEqual((m.get(template+0x2d6,4),m.get(template+0x2e2,4)),
                                     EXPECTED[selection][size][2:])
                    m.release()

    def test_original_dng_copy_matches_the_saved_jpeg_crop(self):
        m=self.m
        for selection in EXPECTED:
            m.choose(selection); index=5 if selection==3 else 0
            for size in range(2):
                with self.subTest(selection=selection,size=size):
                    metadata=m.prepare(size)
                    top,dy,left,dx,bottom,dy2,right,dx2=m.dng(metadata)
                    x,y,width,height=m.crop('aspect_main',selection,size)
                    original=struct.unpack('<8I',self.original(DNG+index*64+size*32,32))
                    ox,oy,_,_=CROP.unpack(self.original(MAIN+(size*7+index)*12,12))
                    self.assertEqual((top,left),(original[0]+y-oy,original[2]+x-ox))
                    self.assertEqual((bottom-top+1,right-left+1),(height,width))
                    self.assertEqual((dy,dx,dy2,dx2),(original[1],original[3],original[5],original[7]))
                    self.assertTrue(0<=top<=bottom<=dy and 0<=left<=right<=dx)
                    m.release()

    def test_native_setting_round_trip_and_movie_restrictions(self):
        m=self.m
        for selection in EXPECTED:
            m.choose(selection); index=5 if selection==3 else 0
            self.assertEqual(m.run(0x4d3317670),index)
            self.assertEqual(m.call_from(0x4d3317670,0x4d331f5d4),2)
            self.assertEqual(m.run(0x4d3320850),index)
            m.shooting_mode=0x10
            self.assertEqual(m.run(0x4d3320850),1)
            m.shooting_mode=0; m.restriction=1
            self.assertEqual(m.run(0x4d3320850),2)
            m.restriction=0
            self.assertEqual(m.get(m.settings+0x18,4),2)

    def test_stock_chooser_open_preserves_override_and_real_edit_restores_native(self):
        m=self.m; m.choose(1)
        m.call_from(0x4d33208a0,0x4d33a3650,0)
        self.assertEqual(m.aspect,1); self.assertEqual(m.get(m.settings+0x18,4),2)
        m.run(0x4d33208a0,4)
        self.assertEqual(m.aspect,0); self.assertEqual(m.get(m.settings+0x18,4),4)
        self.assertEqual(m.get(0x4d3295f08),MAIN)

    def test_view_geometry_recomputes_when_sensor_crop_changes(self):
        m=self.m
        for selection in EXPECTED:
            m.choose(selection); index=5 if selection==3 else 0
            for size in range(2):
                m.image_size=size; m.run(0x4d3317670)
                width,height=struct.unpack('<2H',m.read(RESIDENT+self.symbols['aspect_view']+index*4,4))
                _,_,cw,ch=m.crop('aspect_main',selection,size)
                _,_,fw,fh=CROP.unpack(self.original(MAIN+(size*7+2)*12,12))
                self.assertLessEqual(abs(width-cw*1024/fw),1)
                self.assertLessEqual(abs(height-ch*682/fh),1)

    def test_hud_override_is_limited_to_its_callsite(self):
        m=self.m
        for selection,text in ((1,b'65:24'),(2,b'2.35:1')):
            m.choose(selection)
            address=m.call_from(0x4d33208b0,0x4d3356940,0x100)
            self.assertEqual(m.text(address),text)
        # Native veneer reads the next property unchanged for ordinary callers.
        m.put(m.settings+0x1e0,6,4)
        self.assertEqual(m.run(0x4d33208b0),6)

    def test_queued_photos_keep_independent_crops_after_menu_changes(self):
        m=self.m
        for size in range(2):
            tags=[]
            for selection in (1,2,3):
                m.choose(selection)
                tags.append(m.call_from(0x4d3320850,ASPECT_SNAPSHOT_SITES[0]))
            self.assertEqual(m.get(m.aspect_address+12,4)>>8,3)
            m.choose(0)
            for slot,encoded in enumerate(tags):
                metadata=m.prepare(size,slot,encoded)
                m.encode_metadata(metadata)
                crop=m.dng(metadata)
                expected=EXPECTED[slot+1][size][2:]
                self.assertEqual((m.encodes[0][3],m.encodes[0][5]),expected)
                self.assertEqual((crop[6]-crop[2]+1,crop[4]-crop[0]+1),expected)
                m.release(slot)
            self.assertEqual(m.get(m.aspect_address+12,4)>>8,0)

    def test_seven_producer_sequences_mask_budget_without_losing_tags(self):
        m=self.m
        offsets=(0x38,0x78,0x80,0x80,0x80,0x30,0x48)
        for site,offset in zip(ASPECT_SNAPSHOT_SITES,offsets):
            for selection in (1,2,3):
                m.choose(selection); index=5 if selection==3 else 0
                for size in (0,1):
                    for format_value in (2,5,6):
                        with self.subTest(site=hex(site),choice=selection,size=size,format=format_value):
                            budget=m.run(0x4d3322ba0,format_value,size,index)
                            stack=STACK+0xf000
                            m.put(stack+offset+8,format_value,4)
                            m.put(stack+offset+12,size,4)
                            m.uc.reg_write(r.UC_ARM64_REG_SP,stack)
                            m.uc.emu_start(site-4,site+24,count=10000)
                            self.assertEqual(m.uc.reg_read(r.UC_ARM64_REG_PC),site+24)
                            self.assertEqual(m.get(stack+offset+16,4),0xbf000000|(selection<<8)|index)
                            self.assertEqual(m.get(stack+offset+20,4),budget)

    def test_only_still_snapshot_callers_admit_private_jobs(self):
        m=self.m; m.choose(3)
        for caller in (*ASPECT_SNAPSHOT_SITES,0x4d324344c,0x4d331451c,0x4d331f5d4,STOP):
            before=m.get(m.aspect_address+12,4)>>8
            value=m.call_from(0x4d3320850,caller)
            admitted=caller in ASPECT_SNAPSHOT_SITES
            self.assertEqual(m.get(m.aspect_address+12,4)>>8,before+admitted)
            self.assertEqual(value,0xbf000305 if admitted else
                             2 if caller in (0x4d324344c,0x4d331f5d4) else 5)
        for field,value in (('shooting_mode',0x10),('restriction',1),('secondary_mode',5)):
            setattr(m,field,value)
            before=m.get(m.aspect_address+12,4)>>8
            result=m.call_from(0x4d3320850,ASPECT_SNAPSHOT_SITES[0])
            self.assertIn(result,(1,2))
            self.assertEqual(m.get(m.aspect_address+12,4)>>8,before)
            setattr(m,field,0)

    def test_retirement_and_native_reuse_do_not_inherit_old_crop(self):
        m=self.m; m.choose(1)
        metadata=m.prepare(0,slot=191)
        self.assertEqual(m.get(RESIDENT+self.symbols['aspect_jobs']+191,1),1)
        m.release(191)
        self.assertIn(('id_returned',191),m.calls)
        self.assertEqual(m.get(RESIDENT+self.symbols['aspect_jobs']+191,1),0)
        # A native or auxiliary producer can reuse the same page directly.
        m.put(metadata+0x74,0,4)
        m.encode_metadata(metadata)
        self.assertEqual((m.encodes[0][3],m.encodes[0][5]),(6016,2580))
        self.assertEqual(m.dng(metadata),struct.unpack('<8I',self.original(DNG,32)))

    def test_reserve_clears_old_choice_before_unlock_and_publication(self):
        m=self.m
        jobs=RESIDENT+self.symbols['aspect_jobs']
        output=STACK+0x6800
        observed=[]
        def observe(u, pc, size, opaque):
            if pc in (0x4d3268eb4,0x4d3268ee8):
                observed.append(pc)
                self.assertEqual(m.get(jobs+m.receive_id,1),0)
                self.assertEqual(m.get(output,4),0xa5a5a5a5)
        hook=m.uc.hook_add(UC_HOOK_CODE,observe)
        try:
            for identifier in (0,191):
                with self.subTest(identifier=identifier):
                    observed.clear()
                    m.receive_id=identifier
                    m.put(jobs+identifier,2,1)
                    m.put(output,0xa5a5a5a5,4)
                    self.assertEqual(m.run(0x4d3268e70,output,1),0)
                    self.assertEqual(observed,[0x4d3268eb4,0x4d3268ee8])
                    self.assertEqual(m.get(output,4),identifier)
                    self.assertEqual(m.calls[-1][0],'id_received')
                    self.assertEqual(m.calls[-1][3],0)
                    # An alternate native producer reusing the page must not
                    # inherit a crop, even without calling our metadata bridge.
                    metadata=0x400000000+identifier*4096
                    m.put(metadata+0x58,0,4); m.put(metadata+0x74,0,4)
                    m.encode_metadata(metadata)
                    self.assertEqual((m.encodes[0][3],m.encodes[0][5]),(6016,2580))
                    self.assertEqual(m.dng(metadata),struct.unpack('<8I',self.original(DNG,32)))
        finally:
            m.uc.hook_del(hook)

    def test_reserve_wrapper_preserves_failure_results_and_bounds(self):
        m=self.m
        jobs=RESIDENT+self.symbols['aspect_jobs']
        pointer=STACK+0x6801
        for identifier in (0,191,192,65535):
            for result in (2,0,1,0xffffffff):
                with self.subTest(identifier=identifier,result=result):
                    before=b'\xa5'+bytes([3])*192+b'\x5a'
                    m.uc.mem_write(jobs-1,before)
                    m.receive_id, m.receive_result=identifier,result
                    actual=m.call_from(0x4d33208f0,0x4d3268eac,0x1234,pointer,77)
                    self.assertEqual(actual,result)
                    self.assertEqual(m.calls[-1],('id_received',0x1234,pointer,77))
                    expected=bytearray(before)
                    if result==2 and identifier<192: expected[identifier+1]=0
                    self.assertEqual(m.read(jobs-1,194),bytes(expected))

    def test_failed_native_reserve_preserves_choice_and_native_error(self):
        m=self.m
        jobs=RESIDENT+self.symbols['aspect_jobs']
        output=STACK+0x6800
        m.receive_id, m.receive_result=191,0xffffffff
        m.put(jobs+191,3,1)
        self.assertEqual(m.run(0x4d3268e70,output,1),0xffffffff)
        self.assertEqual(m.get(output,4),0xffffffff)
        self.assertEqual(m.get(jobs+191,1),3)

    def test_multiplexed_reserve_veneer_preserves_native_setting_getter(self):
        m=self.m
        m.put(m.settings+0x2dc,0x12345678,4)
        m.put(RESIDENT+self.symbols['aspect_jobs'],3,1)
        self.assertEqual(m.run(0x4d33208f0,12),0x12345678)
        self.assertEqual(m.get(RESIDENT+self.symbols['aspect_jobs'],1),3)
        self.assertFalse(any(call[0]=='id_received' for call in m.calls))

    def test_multiplexed_dng_and_release_veneers_preserve_native_properties(self):
        m=self.m
        jobs=RESIDENT+self.symbols['aspect_jobs']
        m.uc.mem_write(jobs,bytes([3])*192)
        before=m.read(m.settings,0x400)
        for index in (*range(13),0xffffffff):
            with self.subTest(index=index):
                # These islands also serve ordinary camera properties. Compare
                # their complete effects against the original native routines.
                m.uc.mem_write(m.settings,before)
                native_result=m.run(0x4d3317860,index,0x12345678)
                native_settings=m.read(m.settings,0x400)
                m.uc.mem_write(m.settings,before)
                self.assertEqual(m.run(0x4d33208e0,index,0x12345678),native_result)
                self.assertEqual(m.read(m.settings,0x400),native_settings)
                self.assertEqual(m.run(0x4d33208d0,index),m.run(0x4d33176f0,index))
                self.assertEqual(m.read(jobs,192),bytes([3])*192)
        self.assertFalse(any(call[0]=='id_returned' for call in m.calls))

    def test_admission_seal_rejects_pending_and_live_jobs_before_uninstall(self):
        m=self.m; m.choose(1)
        encoded=m.call_from(0x4d3317670,ASPECT_SNAPSHOT_SITES[0])
        control=STAGE+self.symbols['control']
        m.put(control+64,1,4)
        for phase in ('pending','materialized'):
            with self.subTest(phase=phase):
                if phase=='materialized': m.prepare(0,encoded=encoded)
                m.run(STAGE,1,2,3)
                self.assertEqual(m.get(control+16),12)
                self.assertEqual(m.mode,1)
                self.assertFalse(m.get(m.aspect_address+12,4)&4)
                for address,_,symbol in PATCHES:
                    self.assertEqual(m.get(address),RESIDENT+self.symbols[symbol])
        m.release()
        m.run(STAGE,1,2,3)
        self.assertEqual(m.get(control+16),0)
        self.assertEqual(m.mode,2)
        for address,original,_ in PATCHES:
            self.assertEqual(m.get(address),original)
        for address,original,_,length in CODE_PATCHES:
            self.assertEqual(m.get(address,length),original)

    def test_segmented_entry_seals_pending_and_live_photos_before_removal(self):
        m=self.m; m.choose(1)
        encoded=m.call_from(0x4d3317670,ASPECT_SNAPSHOT_SITES[0])
        for phase in ('pending','materialized'):
            with self.subTest(phase=phase):
                if phase=='materialized': m.prepare(0,encoded=encoded)
                self.assertEqual(m.remove_resident(),12)
                self.assertEqual(m.mode,1)
                self.assertFalse(m.get(m.aspect_address+12,4)&4)
                for address,_,symbol in PATCHES:
                    self.assertEqual(m.get(address),RESIDENT+self.symbols[symbol])
        m.release()
        self.assertEqual(m.remove_resident(),0)
        self.assertEqual(m.mode,2)
        self.assertEqual(m.calls[-1],('aspect_refresh',1))
        for address,original,_ in PATCHES:
            self.assertEqual(m.get(address),original)
        for address,original,_,length in CODE_PATCHES:
            self.assertEqual(m.get(address,length),original)

    def test_segmented_removal_failure_keeps_mode_and_reopens_admission(self):
        m=self.m; m.choose(1)
        address,_,symbol=PATCHES[0]
        m.put(address,0x1234)
        self.assertEqual(m.remove_resident(),6)
        self.assertEqual(m.mode,1)
        self.assertFalse(m.get(m.aspect_address+12,4)&4)
        m.put(address,RESIDENT+self.symbols[symbol])
        encoded=m.call_from(0x4d3317670,ASPECT_SNAPSHOT_SITES[0])
        self.assertEqual(encoded,0xbf000100)
        m.prepare(0,encoded=encoded); m.release()
        self.assertEqual(m.remove_resident(),0)
        self.assertEqual(m.mode,2)
        self.assertEqual(m.calls[-1],('aspect_refresh',1))

    def test_metadata_bridge_preserves_native_registers_and_input_snapshot(self):
        m=self.m; m.choose(2)
        encoded=m.call_from(0x4d3317670,ASPECT_SNAPSHOT_SITES[0])
        for number in range(19,30):
            m.uc.reg_write(getattr(r,f'UC_ARM64_REG_X{number}'),0xabcdef00+number)
        metadata=0x400000000
        m.put(STACK+0x6010,encoded,4)
        m.uc.reg_write(r.UC_ARM64_REG_X19,metadata)
        m.uc.reg_write(r.UC_ARM64_REG_X21,STACK+0x6000)
        before={number:m.uc.reg_read(getattr(r,f'UC_ARM64_REG_X{number}')) for number in range(19,30)}
        m.uc.reg_write(r.UC_ARM64_REG_SP,STACK+0xf000)
        m.uc.emu_start(0x4d32fd9dc,0x4d32fd9e4,count=10000)
        self.assertEqual(m.get(metadata+0x74,4),0)
        self.assertEqual(m.get(STACK+0x6010,4),encoded)
        self.assertEqual(m.uc.reg_read(r.UC_ARM64_REG_SP),STACK+0xf000)
        for number,value in before.items():
            self.assertEqual(m.uc.reg_read(getattr(r,f'UC_ARM64_REG_X{number}')),value)

    def test_multiplexed_metadata_veneer_preserves_ordinary_setting_writes(self):
        m=self.m
        m.run(0x4d33208c0,0x12345678)
        self.assertEqual(m.get(m.settings+0x1e0,4),0x12345678)
        self.assertEqual(m.get(m.aspect_address+12,4),0)


if __name__ == '__main__':
    unittest.main()
