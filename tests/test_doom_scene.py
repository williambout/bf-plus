"""Execute the compiled BF+ Doom menu/scene with native services stubbed.

No USB. Engine internals, real file I/O and scanout have separate checks.
"""
import struct
import unittest
from unicorn import arm64_const as r
from tests.test_touch_menu import MenuMachine, build_menu_fixture, DEPTH, PENDING, EVENT, PARAMS, SURFACE
from tests.test_touch_payload import RESIDENT, STACK, STOP


class DoomMachine(MenuMachine):
    def __init__(self, blob, symbols):
        super().__init__(blob, symbols)
        self.clock = 1000
        self.timed_results = []
        self.receive_caller = False

    @property
    def game(self):
        return RESIDENT + self.symbols['doom_game']

    def hook(self, u, pc, size, opaque):
        x0, x1 = (u.reg_read(reg) for reg in (r.UC_ARM64_REG_X0, r.UC_ARM64_REG_X1))
        if self.receive_caller and pc == RESIDENT+self.symbols['doom_receive_wrapper']:
            u.reg_write(r.UC_ARM64_REG_LR, 0x4d3323ac4)
            return
        if self.receive_caller and pc == 0x4d3323ac4:
            u.reg_write(r.UC_ARM64_REG_PC, STOP)
            return
        if pc == 0x4d31a5c00:
            value = self.clock * 24000
        elif pc == 0x4d313b9e0:
            self.calls.append(('open', self.text(x0), x1))
            value = 0
        elif pc == 0x4d3328180:
            self.calls.append(('text', self.text(self.get(x1+8))))
            value = 0
        elif pc == 0x4d3033a50:
            self.calls.append(('blocking_receive', x0, x1))
            value = 37
        elif pc == 0x4d3033ab0:
            self.calls.append(('timed_receive', u.reg_read(r.UC_ARM64_REG_X2)))
            assert self.timed_results, 'unbounded timeout loop'
            value = self.timed_results.pop(0)
            self.clock += 28
        elif pc == 0x4d3317610:  # Updated if a different setter island is chosen.
            self.calls.append(('original_setter', x0, x1))
            value = 123
        else:
            return super().hook(u, pc, size, opaque)
        u.reg_write(r.UC_ARM64_REG_X0, value & ((1<<64)-1))
        u.reg_write(r.UC_ARM64_REG_PC, u.reg_read(r.UC_ARM64_REG_LR))

    def enter_doom(self):
        self.enter_submenu()
        for _ in range(3):
            self.send(submenu=True, changed=8, press=8)
        self.send(submenu=True, changed=1, press=1)
        self.run(RESIDENT+self.symbols['menu_submenu_leave'])
        self.run(RESIDENT+self.symbols['doom_enter'], STACK+0x5000, STACK+0x5100, 0)
        self.put(DEPTH,6,4); self.put(PENDING,12,4)
        self.put(PARAMS,self.get(self.game+4,4),4)
        self.calls.clear()

    def input(self, press=0,touch=0,changed=0,key=True,dial=None):
        at=STACK+0x2101
        self.uc.mem_write(at,struct.pack('<4H2B',changed,touch,press,0,0,0))
        self.uc.mem_write(STACK+0x2123,struct.pack('<hh',dial or 0,0))
        self.uc.mem_write(EVENT,struct.pack('<5Q',at if key else 0,STACK+0x2123 if dial is not None else 0,0,0,0))
        return self.run(RESIDENT+self.symbols['doom_input'],EVENT)


class DoomSceneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.blob,cls.symbols=build_menu_fixture()

    def setUp(self):
        self.m=DoomMachine(self.blob,self.symbols)
        self.m.initialize()

    def test_doom_menu_opens_owned_scene_and_publishes_only_owned_handler(self):
        m=self.m
        m.enter_doom()
        self.assertEqual(m.get(m.game,4),1)
        self.assertEqual(m.get(m.game+8,4),6)
        self.assertEqual(m.read(STACK+0x5100,16),struct.pack('<QQ',RESIDENT+self.symbols['doom_input'],0))
        expected=('doom_enter','doom_resume','doom_leave','doom_leave')
        self.assertEqual(m.read(RESIDENT+self.symbols['doom_scene'],32),
                         struct.pack('<4Q',*(RESIDENT+self.symbols[x] for x in expected)))

    def test_loading_message_precedes_file_io_and_missing_package_stays_exitable(self):
        m=self.m; m.enter_doom()
        callback=RESIDENT+self.symbols['doom_foreground']
        m.run(callback,SURFACE,PARAMS,4)
        self.assertNotIn('open',[c[0] for c in m.calls])
        self.assertIn(('text',b'Loading Doom...'),m.calls)
        m.calls.clear(); m.run(callback,SURFACE,PARAMS,4)
        self.assertIn(('open',b'J:\\DOOM.BFP',0),m.calls)
        self.assertEqual(m.get(m.game+12,4),3)
        self.assertIn(('text',b'Copy DOOM.BFP To Camera Storage'),m.calls)
        m.calls.clear();m.input(press=64,changed=64)
        self.assertIn(('pop',),m.calls)
        self.assertEqual(m.get(m.game,4),0)

    def test_inputs_never_reach_photography_and_null_key_preserves_hold(self):
        m=self.m;m.enter_doom()
        m.input(press=17,changed=17)
        self.assertEqual(m.get(m.game+16,4),1|16|64)  # forward, fire, Enter
        m.input(key=False,dial=1)
        self.assertEqual(m.get(m.game+16,4),1|16|64)
        self.assertEqual(m.get(m.game+20,4),2)
        m.input(press=0,touch=1,changed=1)
        self.assertEqual(m.get(m.game+16,4),32)  # door/use, never focus zoom
        m.input(press=32,changed=32)
        self.assertEqual(m.get(m.game+16,4),128)  # game menu
        self.assertEqual(m.calls,[])

    def test_stale_generation_callbacks_and_removed_scene_are_inert(self):
        m=self.m;m.enter_doom()
        m.run(RESIDENT+self.symbols['doom_leave'])
        for name in ('doom_foreground','doom_background'):
            m.run(RESIDENT+self.symbols[name],SURFACE,PARAMS,4)
        m.input(press=1,changed=1)
        self.assertEqual(m.calls,[])
        m.mode=2
        m.run(RESIDENT+self.symbols['doom_enter'],STACK+0x5000,STACK+0x5100,0)
        self.assertEqual(m.read(STACK+0x5100,16),bytes(16))

    def test_timeout_queues_frames_only_while_active_and_passes_real_results(self):
        m=self.m;m.enter_doom();m.receive_caller=True
        m.timed_results=[-50,25]
        result=m.run(RESIDENT+self.symbols['doom_receive_wrapper'],123,STACK+0x6000)
        self.assertEqual(result,25)
        self.assertEqual([c for c in m.calls if c[0]=='timed_receive'],[('timed_receive',28)]*2)
        self.assertTrue(any(c[0]=='draw_queue' for c in m.calls))
        m.run(RESIDENT+self.symbols['doom_leave']);m.calls.clear()
        self.assertEqual(m.run(RESIDENT+self.symbols['doom_receive_wrapper'],123,STACK+0x6000),37)
        self.assertEqual(m.calls,[('blocking_receive',123,STACK+0x6000)])

    def test_engine_uses_its_own_stack_and_restores_native_stack(self):
        m=self.m
        entry=STACK+0x7000
        # sub sp,sp,#256; mov x0,#42; add sp,sp,#256; ret
        m.uc.mem_write(entry,struct.pack('<4I',0xd10403ff,0xd2800540,0x910403ff,0xd65f03c0))
        m.uc.reg_write(r.UC_ARM64_REG_X19,0x12345678)
        result=m.run(RESIDENT+self.symbols['doom_engine_call'],entry,0,0,STACK+0xa000)
        self.assertEqual(result,42)
        self.assertEqual(m.uc.reg_read(r.UC_ARM64_REG_SP),STACK+0xf000)
        self.assertEqual(m.uc.reg_read(r.UC_ARM64_REG_X19),0x12345678)


if __name__=='__main__':
    unittest.main()
