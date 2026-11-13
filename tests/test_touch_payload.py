"""Execute the actual compiled hook at relocated addresses with stock calls stubbed.

Privileged cache/TLB operations are checked in source/disassembly, skipped in
Unicorn; these tests cannot validate real hardware coherency or UI rendering.
"""
import struct
import unittest

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_READ
from unicorn import arm64_const as r
from bfplus.build import build
from bfplus_cli import PATCHES, CODE_PATCHES

STAGE = 0x447581000
ALLOC = 0x447701123
RESIDENT = 0x447702000
STACK = 0x448000000
STOP = STACK + 0x100
FW = 0x4d3000000
CALLBACK = 0x4d729bd00
ORIGINAL = 0x4d31254f0
LIVE_LITERAL = 0x4d3398860
MAG_LITERAL = 0x4d33a1388
LIVE = 0x4d3398940
MAG = 0x4d33a1670
LIVE_SLOT = 0x4d7303098
L2 = 0x4d71484c8
L2_RO = 0x4d3200781
NONCE = 0x123456789abcdef0

class Machine:
    def __init__(self, blob, symbols):
        self.symbols = symbols
        self.blob = blob
        self.uc = u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        u.mem_map(STAGE, 0x10000)
        u.mem_map(ALLOC & ~4095, 0x20000)
        u.mem_map(STACK, 0x10000)
        u.mem_map(FW, 0x4400000)
        u.mem_write(STAGE, blob)
        self.put(STAGE+symbols['control'], NONCE)
        for a,v in ((CALLBACK,STAGE),(LIVE_LITERAL,LIVE),(MAG_LITERAL,MAG),
                    (LIVE_SLOT,LIVE),(L2,L2_RO),(0x4d71484c0,0x4d3000781),(0x4d3398868,0x4d3396120),
                    (0x4d33a1390,0x4d33a1420),(LIVE_SLOT+8,0x4d3396120)):
            self.put(a,v)
        for a,original,_ in PATCHES: self.put(a,original)
        for a,original,_,size in CODE_PATCHES: self.put(a,original,size)
        self.put(0x4d70346a0,2,4)
        self.put(0x4d70346a4,12,4)
        self.put(0x4d703469c,12,4)
        u.mem_write(0x4d7301c00,struct.pack('<4Q',0x4d3398930,0x4d33988b0,0x4d3393730,0x4d33936a0))
        self.el = 4
        self.alloc_ok = True
        self.lens = 0
        self.mag = 2
        self.mag_restricted = False
        self.queue_ok = True
        self.image_size = 0
        self.storage_rc = 0x1234
        self.calls = []
        self.system = {}
        for ins in Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN).disasm(blob,0):
            if ins.mnemonic in ('mrs','msr','dc','ic','tlbi','dsb','dmb','isb'):
                self.system[ins.address]=(ins.mnemonic,ins.op_str)
        self.code_hook = u.hook_add(UC_HOOK_CODE,self.hook)

    def put(self,a,v,n=8): self.uc.mem_write(a,int(v).to_bytes(n,'little'))
    def get(self,a,n=8): return int.from_bytes(self.uc.mem_read(a,n),'little')
    def hook(self,u,pc,size,_):
        offset = pc-STAGE if STAGE <= pc < STAGE+len(self.blob) else pc-RESIDENT
        if offset in self.system:
            op,args=self.system[offset]
            if op=='mrs':
                dst,src=args.split(', ')
                value={'currentel':self.el,'ctr_el0':0x8444c004,'mair_el1':0xff,
                       'tcr_el1':0,'daif':0}.get(src.lower())
                if value is None: raise AssertionError(src)
                u.reg_write(getattr(r,'UC_ARM64_REG_'+dst.upper()),value)
            u.reg_write(r.UC_ARM64_REG_PC,pc+4)
            return
        if pc == 0x4d330c850:
            self.calls.append(('allocate',u.reg_read(r.UC_ARM64_REG_X0)))
            self.put(u.reg_read(r.UC_ARM64_REG_X4),ALLOC if self.alloc_ok else 0)
            u.reg_write(r.UC_ARM64_REG_X0,int(self.alloc_ok))
        elif pc==ORIGINAL:
            assert self.get(CALLBACK)==ORIGINAL
            self.calls.append(('storage',*[u.reg_read(x) for x in
                               (r.UC_ARM64_REG_X0,r.UC_ARM64_REG_X1,r.UC_ARM64_REG_X2)]))
            u.reg_write(r.UC_ARM64_REG_X0,self.storage_rc)
        elif pc==0x4d31d48c0:
            u.reg_write(r.UC_ARM64_REG_X0,self.lens)
        elif pc==0x4d33226f0:
            u.reg_write(r.UC_ARM64_REG_X0,self.image_size)
        elif pc == 0x4d33224d0:
            u.reg_write(r.UC_ARM64_REG_X0,1 if self.mag_restricted else self.mag)
        elif pc == 0x4d3319880:
            u.reg_write(r.UC_ARM64_REG_X0,self.mag)
        elif pc == 0x4d3322500:
            self.mag=u.reg_read(r.UC_ARM64_REG_X0)
        elif pc == 0x4d33a1e70:
            self.calls.append(('zoom',u.reg_read(r.UC_ARM64_REG_X0),u.reg_read(r.UC_ARM64_REG_X1)))
            self.put(0x4d70346a4,3,4)
            u.reg_write(r.UC_ARM64_REG_X0,0)
        elif pc == 0x4d3324250:
            self.calls.append(('pop',))
            self.put(0x4d70346a4,2,4)
            u.reg_write(r.UC_ARM64_REG_X0,0)
        elif pc == 0x4d3033a00:
            packet=bytes(u.mem_read(u.reg_read(r.UC_ARM64_REG_X1),u.reg_read(r.UC_ARM64_REG_X2)))
            self.calls.append(('queue',packet))
            u.reg_write(r.UC_ARM64_REG_X0,0 if self.queue_ok else 0xffffffff)
        elif pc in (LIVE,MAG,0x4d3396120,0x4d33a1420,0x4d3392c40,0x4d338ef10):
            self.calls.append(('handler',pc,u.reg_read(r.UC_ARM64_REG_X0)))
            u.reg_write(r.UC_ARM64_REG_X0,0x42)
        else: return
        u.reg_write(r.UC_ARM64_REG_PC,u.reg_read(r.UC_ARM64_REG_LR))

    def run(self,pc,*args):
        for i,arg in enumerate(args): self.uc.reg_write(getattr(r,f'UC_ARM64_REG_X{i}'),arg)
        self.uc.reg_write(r.UC_ARM64_REG_SP,STACK+0xf000)
        self.uc.reg_write(r.UC_ARM64_REG_LR,STOP)
        # The resident may now approach 64 KiB; copying/zeroing its bounded
        # extent needs more instructions than the old 16 KiB bootstrap.
        self.uc.emu_start(pc,STOP,count=1000000)
        assert self.uc.reg_read(r.UC_ARM64_REG_PC)==STOP, 'instruction budget exhausted'
        return self.uc.reg_read(r.UC_ARM64_REG_X0)

    def install(self,mode=1):
        self.put(STAGE+self.symbols['control']+68,mode,4)
        self.run(STAGE,1,2,3)
        self.calls=[]

    def event(self,kind,changed=0,touch=0,press=0,repeat=0,key=True):
        event,payload=STACK+0x2000,STACK+0x2101
        self.uc.mem_write(event,b'\0'*40)
        if key:
            self.put(event,payload)
            self.uc.mem_write(payload,struct.pack('<4H2B',changed,touch,press,repeat,0,0))
        return self.run(RESIDENT+self.symbols[kind+'_wrapper'],event)

    def zoom(self):
        self.put(0x4d72c2468,1,4)
        self.event('live',1,1)
        self.put(0x4d70346a0,3,4)
        self.put(0x4d70346a4,12,4)

class PayloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.blob, cls.syms = build()
    def setUp(self): self.m=Machine(self.blob,self.syms)
    def test_installs_relocated_owned_wrappers_and_publishes_completion(self):
        m=self.m
        self.assertEqual(m.run(STAGE,7,8,STACK+0x1000),0x1234)
        ctl=STAGE+self.syms['control']
        self.assertEqual(m.get(ctl+8),NONCE)
        self.assertEqual(m.get(ctl+16),0)
        self.assertEqual(m.get(ctl+24),RESIDENT)
        self.assertEqual(m.get(ctl+72,4),0x1234)
        self.assertEqual(m.get(LIVE_LITERAL),RESIDENT+self.syms['live_wrapper'])
        self.assertEqual(m.get(MAG_LITERAL),RESIDENT+self.syms['mag_wrapper'])
        self.assertEqual(m.get(L2),L2_RO)
        self.assertEqual(m.calls[-1],('storage',7,8,STACK+0x1000))
    def test_wrong_original_does_not_patch(self):
        self.m.put(LIVE_LITERAL,99)
        self.m.run(STAGE,1,2,3)
        self.assertEqual(self.m.get(LIVE_LITERAL),99)
        self.assertEqual(self.m.get(STAGE+self.syms['control']+16),3)
        self.assertEqual(len(self.m.calls),1)

    def test_storage_failure_is_exposed_alongside_hook_result(self):
        m=self.m; m.storage_rc=0xffffffff
        self.assertEqual(m.run(STAGE,1,2,3),0xffffffff)
        ctl=STAGE+self.syms['control']
        self.assertEqual(m.get(ctl+72,4),0xffffffff)
        self.assertEqual(m.get(ctl+8),NONCE)
    def test_failed_allocation_does_not_patch(self):
        self.m.alloc_ok=False
        self.m.run(STAGE,1,2,3)
        self.assertEqual(self.m.get(LIVE_LITERAL),LIVE)
        self.assertEqual(self.m.get(STAGE+self.syms['control']+16),4)
    def test_observer_forwards_unaligned_key_and_exact_return(self):
        m=self.m; m.run(STAGE,1,2,3)
        event,key=STACK+0x2000,STACK+0x2101
        m.put(event,key)
        keys=struct.pack('<4H2B',1,1,0,0,0,0)
        m.uc.mem_write(key,keys)
        self.assertEqual(m.run(RESIDENT+self.syms['live_wrapper'],event),0x42)
        state=RESIDENT+self.syms['state']
        self.assertEqual(m.get(state+48,4),1)
        self.assertEqual(bytes(m.uc.mem_read(state+64+16,10)),keys)
    def test_uninstall_restores_originals_and_keeps_allocation(self):
        m=self.m; m.run(STAGE,1,2,3)
        ctl=STAGE+self.syms['control']
        m.put(ctl+64,1,4)
        m.run(STAGE,4,5,6)
        self.assertEqual(m.get(LIVE_LITERAL),LIVE)
        self.assertEqual(m.get(MAG_LITERAL),MAG)
        self.assertEqual(m.get(LIVE_SLOT),LIVE)
        self.assertEqual(m.get(RESIDENT+self.syms['state']+12,4),2)
        self.assertEqual(m.get(L2),L2_RO)

    def test_bootstrap_zeroes_resident_tail_without_reading_beyond_upload(self):
        m=self.m
        image_end, memory_end=self.syms['__image_end'],self.syms['__end']
        self.assertEqual(len(self.blob),image_end)
        self.assertLessEqual(image_end,0x10000)
        self.assertGreater(memory_end,image_end)
        self.assertGreaterEqual(self.syms['state'],image_end)
        # Simulate arbitrary old staging/heap contents. The allocated tail
        # must be initialized locally, never copied from outside the upload.
        m.uc.mem_write(STAGE+image_end,b'\xa5'*(memory_end-image_end))
        m.uc.mem_write(RESIDENT-64,b'\xcc'*(memory_end+128))
        reads=[]
        def read(u,access,address,size,value,opaque):
            if address < STAGE+memory_end and address+size > STAGE+image_end:
                reads.append((address,size))
        hook=m.uc.hook_add(UC_HOOK_MEM_READ,read)
        # This is host-supplied configuration and must survive the split.
        m.put(STAGE+self.syms['focus_target'],1,4)
        m.put(STAGE+self.syms['control']+68,1,4)
        m.run(STAGE,1,2,3)
        state=RESIDENT+self.syms['state']
        self.assertEqual(m.get(state),0x314843554f544642)
        self.assertEqual(m.get(state+8,4),1)
        self.assertEqual(m.get(state+16),NONCE)
        self.assertEqual(m.get(state+24),ALLOC)
        self.assertEqual(bytes(m.uc.mem_read(state+64,128*32)),bytes(128*32))
        self.assertEqual(m.get(RESIDENT+self.syms['focus_target'],4),1)
        self.assertEqual(bytes(m.uc.mem_read(RESIDENT-64,64)),b'\xcc'*64)
        self.assertEqual(bytes(m.uc.mem_read(RESIDENT+memory_end,64)),b'\xcc'*64)
        self.assertIn(('allocate',memory_end+4095+self.syms['__scratch_size']),m.calls)
        # Removal is executed from the original uploaded prefix and must not
        # depend on a staging copy of the resident BSS either.
        m.put(STAGE+self.syms['control']+64,1,4)
        m.run(STAGE,4,5,6)
        m.uc.hook_del(hook)
        self.assertFalse(reads)
        self.assertEqual(m.get(LIVE_LITERAL),LIVE)
        self.assertEqual(m.get(L2),L2_RO)

    def test_deferred_focus_guide_is_not_linked_into_production(self):
        self.assertFalse(any(name.startswith("focus_guide") for name in self.syms))

    def test_touch_holds_until_physical_release(self):
        m=self.m; m.install(); m.zoom()
        self.assertEqual(m.calls,[('zoom',4,1)])
        m.event('mag',key=False)
        self.assertNotIn(('pop',),m.calls)
        m.put(0x4d72c2468,0,4)
        m.event('mag',1,0)
        self.assertEqual(m.calls.count(('pop',)),1)
        self.assertEqual(m.get(RESIDENT+self.syms['state']+32,4),0)

    def test_attached_electronic_lens_and_press_do_not_enter(self):
        m=self.m; m.install(); m.lens=2
        m.put(0x4d72c2468,1,4); m.event('live',1,1)
        self.assertEqual(m.calls[0][0],'handler')
        m.lens=0; m.event('live',1,0)
        m.put(0x4d72c2468,0x401,4); m.event('live',1,1,1)
        self.assertFalse(any(c[0]=='zoom' for c in m.calls))

    def test_pressure_during_zoom_pops_and_queues_normal_press(self):
        m=self.m; m.install(); m.zoom()
        m.put(0x4d72c2468,0x401,4); m.event('mag',1,1,1)
        self.assertIn(('pop',),m.calls)
        packet=[c[1] for c in m.calls if c[0]=='queue'][0]
        self.assertEqual(packet[16:21],bytes([10,0,0,0,0]))
        self.assertEqual(struct.unpack('<4H2B',packet[21:]),(1,1,1,0,0,0))
        m.put(0x4d70346a0,2,4); m.put(0x4d70346a4,12,4)
        m.event('live',1,1,1)
        self.assertEqual(m.calls[-1][0],'handler')
        m.put(0x4d72c2468,1,4); m.event('live',1,1)
        self.assertEqual(sum(c[0]=='zoom' for c in m.calls),1)

    def test_timer_catches_release_and_restores_one_x(self):
        m=self.m; m.install(); m.mag=1; m.zoom()
        self.assertEqual(m.mag,2)
        m.put(0x4d72c2468,0,4); m.event('mag_update',key=False)
        self.assertEqual(m.mag,1)
        self.assertEqual(m.calls[-1],('pop',))

    def test_existing_stock_zoom_is_not_owned(self):
        m=self.m; m.install(); m.event('mag',1,0)
        self.assertEqual(m.calls[0][0],'handler')
        self.assertFalse(any(c[0]=='pop' for c in m.calls))

    def test_recording_restriction_preserves_saved_magnification(self):
        m=self.m; m.install(); m.mag=3; m.mag_restricted=True
        m.put(0x4d72c2468,1,4); m.event('live',1,1)
        self.assertEqual(m.mag,3)
        self.assertFalse(any(c[0]=='zoom' for c in m.calls))

    def test_menu_transition_is_not_popped(self):
        m=self.m; m.install(); m.zoom()
        m.put(0x4d70346a4,4,4)
        m.put(0x4d72c2468,0,4); m.event('mag',1,0)
        self.assertNotIn(('pop',),m.calls)

    def test_full_replay_queue_does_not_wait(self):
        m=self.m; m.install(); m.zoom(); m.queue_ok=False
        m.put(0x4d72c2468,0x401,4); m.event('mag',1,1,1)
        self.assertEqual(m.get(RESIDENT+self.syms['state']+56,4),1)

if __name__=='__main__': unittest.main()
