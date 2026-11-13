"""Run compiled, relocated BF+ wrappers offline with stock services stubbed.

These tests cover the wrapper ABI and event/draw contracts, plus original
firmware scene transitions and glyph lookup when the decoded image is present.
They do not cover camera pixels, cache coherency or real UI queue scheduling.
No USB is opened.
"""
import importlib
import re
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn import arm64_const as r

from tests.test_touch_payload import FW, Machine, RESIDENT, STACK, STAGE
from bfplus_cli import PATCHES


def build_menu_fixture():
    """Snapshot the integrated source; never race the parent's build output.

    Compiler, linker and relocation checks are the production build's own.
    The emulator explicitly invokes menu_initialize; installer integration
    belongs to test_touch_payload.
    """
    builder = importlib.import_module('bfplus.build')
    with tempfile.TemporaryDirectory(prefix='bf-menu-test-') as directory:
        root = Path(directory)
        target = root / 'bfplus'
        target.mkdir()
        pending=['payload.c', 'payload.ld', 'launch.S']
        copied=set()
        while pending:
            name=pending.pop()
            if name in copied: continue
            copied.add(name)
            raw=(builder.ROOT/'bfplus'/name).read_bytes()
            (target/name).write_bytes(raw)
            if name.endswith(('.c','.h')):
                pending.extend(re.findall(r'^\s*#\s*include\s+"([^"]+)"',raw.decode(),re.M))
        with patch.object(builder, 'ROOT', root), patch.object(builder, 'BUILD', root / 'build'):
            return builder.build()

ROWS = 0x4d7042c18
ALTERNATE = 0x4d73025f4
CURRENT = 0x4d73025f6
PREVIOUS = 0x4d73025f7
REPAINT = 0x4d7042e98
HIGHLIGHT = 0x4d7042ea0
BACKING = 0x4d7042ec0
SCROLL = 0x4d7042ee0
INPUT = 0x4d3373200
DRAW = 0x4d33726d0
INITIAL = 0x4d33729c0
UPDATE = 0x4d3372a20
PAINT = 0x4d3363df0
FONT_HEIGHT = 0x4d3325940
FONT_FAMILY = 0x4d332df40
GLYPH_INDEX = 0x4d332df80
TEXT_DRAW = 0x4d3328180
TEXT_WIDTH = 0x4d3327e50
TEXT_HEIGHT = 0x4d3328000
GLYPH_FROM_DRAW = 0x4d3328650
QUEUE = 0x4d3322d90
RECT = 0x4d3325ca0
REPEAT = 0x4d3323400
PUSH = 0x4d3324110
POP = 0x4d3324250
PARENT_RESUME = 0x4d3372d90
DEPTH = 0x4d70346a0
PENDING = 0x4d70346a4
SCENES = 0x4d7301bc0
PENDING_SCENE = 0x4d7301d40
EVENT = STACK + 0x2000
SURFACE = STACK + 0x4000
PARAMS = STACK + 0x4100
ROW = struct.Struct('<HBBIQQII')
PICKER = struct.Struct('<H8B6x4Q')
PICKER_MEASURE = 0x4d33646d0
PICKER_BACKGROUND = 0x4d3364750
PICKER_FOREGROUND = 0x4d3364970
PICKER_DIM_BACKGROUND = 0x4d332b110
PICKER_DIM_FOREGROUND = 0x4d3327240
ASPECT_REFRESH = 0x4d33a03a0
KEY = struct.Struct('<4H2B')
OFF, ON = b'\x1b\x06OFF', b'\x1b\x06ON'
FIRMWARE = Path(__file__).resolve().parents[1] / 'decoded-V104/rtos-alt.bin'


class MenuMachine(Machine):
    def __init__(self, blob, symbols):
        super().__init__(blob, symbols)
        self.owned_rows = RESIDENT + symbols['menu_rows']
        self.owned_callbacks = RESIDENT + symbols['menu_callbacks']
        self.mode_address = RESIDENT + symbols['state'] + 12
        self.orientation = 0
        self.stock_result = 0x1234abcd
        self.draw_result = 0x89abcdef
        self.repeat_ready = True
        self.push_result = 0
        self.stock_pending = None
        self.stock_mode = None
        self.inputs = []
        self.row10_accesses = []
        self.aspect_address = RESIDENT+symbols['aspect_ratio']
        self.aspect_writes = []
        self.uc.hook_add(UC_HOOK_MEM_WRITE, self.observe_aspect_write,
                         begin=self.aspect_address, end=self.aspect_address+3)
        self.stock_rows = b''.join(
            ROW.pack(52 + 90*i, 2 | (i == 0), i, 0x100+i,
                     0x4d3001000+16*i, 0x4d3002000+16*i, 4, 0x200+i)
            for i in range(10)
        )
        self.uc.mem_write(ROWS, self.stock_rows + b'\xa5'*32)
        self.put(SCROLL, 52, 2)
        self.put(HIGHLIGHT, 52, 2)
        self.put(BACKING + 16, 0x11220800, 4)
        self.put(SURFACE + 16, 0x33440820, 4)
        self.uc.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE,
                         self.observe_row10, begin=self.owned_rows+320,
                         end=self.owned_rows+351)

    def observe_row10(self, u, access, address, size, value, _):
        self.row10_accesses.append((access, address, size))

    def observe_aspect_write(self, u, access, address, size, value, _):
        self.aspect_writes.append((address, size, value))

    @property
    def aspect(self):
        return self.get(self.aspect_address, 4)

    @aspect.setter
    def aspect(self, value):
        self.put(self.aspect_address, value, 4)

    @property
    def mode(self):
        return self.get(self.mode_address, 4)

    @mode.setter
    def mode(self, value):
        self.put(self.mode_address, value, 4)

    def initialize(self, mode=1):
        # Execute staging code against a separately relocated destination.
        self.uc.mem_write(RESIDENT, self.blob)
        self.uc.mem_write(RESIDENT+self.symbols["__image_end"],
                          bytes(self.symbols["__end"]-self.symbols["__image_end"]))
        self.mode = mode
        self.put(STAGE + self.symbols['state'] + 12, 1-mode, 4)
        self.run(STAGE + self.symbols['menu_initialize'], RESIDENT)
        self.calls.clear()
        self.row10_accesses.clear()
        self.aspect_writes.clear()

    def select(self, current, previous=None, scroll=52):
        self.put(CURRENT, current, 1)
        self.put(PREVIOUS, current if previous is None else previous, 1)
        self.put(SCROLL, scroll, 2)

    def read(self, address, length):
        return bytes(self.uc.mem_read(address, length))

    def text(self, address):
        return self.read(address, 64).split(b'\0', 1)[0]

    def send(self, *, changed=0, touch=0, press=0, repeat=0, count=0,
             pad=0, key=True, dial=None, lcd=None, one=None, five=None,
             submenu=False, picker=False):
        payloads = [KEY.pack(changed, touch, press, repeat, count, pad) if key else None,
                    struct.pack('<hh', *dial) if dial is not None else None,
                    lcd, one, five]
        # Deliberately unaligned serialized key and dial, independent NULLs.
        slots = [STACK+0x2101, STACK+0x2123, STACK+0x2141,
                 STACK+0x2161, STACK+0x2171]
        pointers = []
        for address, payload in zip(slots, payloads):
            pointers.append(address if payload is not None else 0)
            if payload is not None:
                self.uc.mem_write(address, payload)
        self.uc.mem_write(EVENT, struct.pack('<5Q', *pointers))
        self.original_parts = payloads
        self.original_pointers = pointers
        name = ('menu_picker_input_wrapper' if picker else
                'menu_submenu_input_wrapper' if submenu else 'menu_input_wrapper')
        return self.run(RESIDENT+self.symbols[name], EVENT)

    def enter_submenu(self):
        self.select(10, scroll=412)
        self.put(DEPTH, 4, 4)
        self.put(PENDING, 12, 4)
        self.send(changed=1, touch=1, press=1)
        self.run(RESIDENT+self.symbols['menu_submenu_enter'], STACK+0x5000, STACK+0x5100, 0)
        self.put(DEPTH, 5, 4)
        self.put(PENDING, 12, 4)
        self.calls.clear()
        self.aspect_writes.clear()

    def draw(self, initial=False):
        name = 'menu_initial_draw_wrapper' if initial else 'menu_draw_wrapper'
        return self.run(RESIDENT+self.symbols[name], SURFACE, PARAMS, 0x12345678)

    @property
    def picker_address(self):
        return RESIDENT+self.symbols['menu_picker']

    def picker_state(self):
        return PICKER.unpack(self.read(self.picker_address, PICKER.size))

    def enter_picker(self, row=0):
        self.enter_submenu()
        for _ in range(row):
            self.send(submenu=True, changed=8, press=8)
        self.send(submenu=True, changed=1, press=1)
        assert self.get(PENDING, 4) == 6
        self.run(RESIDENT+self.symbols['menu_submenu_leave'])
        self.run(RESIDENT+self.symbols['menu_picker_enter'], STACK+0x5000, STACK+0x5100, 0)
        self.put(DEPTH, 6, 4)
        self.put(PENDING, 12, 4)
        self.calls.clear()

    def hook(self, u, pc, size, opaque):
        args = [u.reg_read(reg) for reg in
                (r.UC_ARM64_REG_X0, r.UC_ARM64_REG_X1, r.UC_ARM64_REG_X2)]
        if pc == 0x4d31e36b0:
            result = self.orientation
        elif pc == 0x4d3372c30:
            self.calls.append(('parent_update',))
            result = self.stock_result
        elif pc == INPUT:
            if self.mode == 2:
                assert self.get(CURRENT, 1) <= 9
                assert self.get(PREVIOUS, 1) <= 9
            pointers = list(struct.unpack('<5Q', self.read(args[0], 40)))
            parts = [self.read(p, n) if p else None
                     for p, n in zip(pointers, (10, 4, 20, 1, 5))]
            # Capture stack copies NOW; they are invalid after the wrapper returns.
            self.inputs.append({'event': args[0], 'pointers': pointers, 'parts': parts,
                                'current': self.get(CURRENT, 1)})
            self.calls.append(('input',))
            if self.stock_pending is not None:
                self.put(PENDING, self.stock_pending, 4)
            if self.stock_mode is not None:
                self.mode = self.stock_mode
            result = self.stock_result
        elif pc == PUSH:
            assert args[0] != 0x4d3e89370, 'must not push stock setting picker'
            descriptor = struct.unpack('<4Q', self.read(args[0], 32))
            self.calls.append(('push', args[0], descriptor))
            if not self.push_result:
                self.uc.mem_write(PENDING_SCENE, self.read(args[0], 32))
                self.put(PENDING, self.get(DEPTH, 4)+1, 4)
            result = self.push_result & 0xffffffff
        elif pc == POP:
            self.calls.append(('pop',))
            self.put(PENDING, self.get(DEPTH, 4)-1, 4)
            result = 0
        elif pc == PARENT_RESUME:
            self.calls.append(('resume', *args))
            if not (args[2] & 255):
                if self.get(CURRENT, 1)>9:
                    self.select(0)
                self.put(args[1], RESIDENT+self.symbols['menu_input_wrapper'])
                self.put(args[1]+8, 0x4d3372c30)
            result = 0x76543210
        elif pc == REPEAT:
            self.calls.append(('repeat', KEY.unpack(self.read(args[0], 10)), args[1]))
            result = int(self.repeat_ready)
        elif pc == UPDATE:
            self.calls.append(('update', args[0], self.get(CURRENT, 1)))
            # Model only the stock updater's ten-row flag ownership.
            for i in range(10):
                address = self.owned_rows + 32*i + 2
                self.put(address, (self.get(address, 1) & ~1) |
                         (i == self.get(CURRENT, 1)), 1)
            result = 0
        elif pc == QUEUE:
            triple = struct.unpack('<3Q', self.read(args[0], 24))
            self.calls.append(('draw_queue', args[0], triple, args[1], args[2]))
            result = 0
        elif pc == PAINT:
            row = ROW.unpack(self.read(args[1], 32))
            self.calls.append(('paint', args[0], args[1], row, self.get(BACKING+16, 4)))
            result = 0
        elif pc in (DRAW, INITIAL):
            if self.mode == 2:
                assert self.get(CURRENT, 1) <= 9
                assert self.get(PREVIOUS, 1) <= 9
            self.calls.append(('draw', pc, *args))
            result = self.draw_result
        elif pc == RECT:
            rect = struct.unpack('<4H', self.read(args[1], 8))
            self.calls.append(('rect', args[0], rect, args[2]))
            result = 0xdddd  # Draw wrapper must preserve the STOCK draw result.
        elif pc in (0x4d3363ca0, 0x4d3363c60):
            self.calls.append(('title', pc, args[0], self.get(args[1], 2),
                               self.text(self.get(args[1]+8)), self.get(args[1]+16, 1)))
            result = 0
        elif pc == 0x4d3363d80:
            self.calls.append(('row_background', args[0], ROW.unpack(self.read(args[1], 32))))
            result = 0
        elif pc == 0x4d3328cc0:
            self.calls.append(('background', args[0], struct.unpack('<4H', self.read(args[1], 8)), args[2]))
            result = 0
        elif pc == 0x4d335d4b0:
            self.calls.append(('status', *args, u.reg_read(r.UC_ARM64_REG_X3)))
            result = 0
        elif pc == 0x4d335f000:
            self.calls.append(('status_update', args[0]))
            result = 0
        elif pc == ASPECT_REFRESH:
            # Execute the owned selection backend, but keep its stock display
            # refresh outside the UI fixture. Geometry has separate coverage.
            self.calls.append(('aspect_refresh', self.aspect))
            result = 0
        elif pc == PICKER_MEASURE:
            self.calls.append(('picker_measure', args[0]))
            result = 0  # OFF is wider than ON; original metrics tested below.
        elif pc == TEXT_WIDTH:
            result = 94  # Original font metrics execute in NativeTextMachine.
        elif pc in (PICKER_BACKGROUND, PICKER_FOREGROUND):
            self.calls.append(('picker_paint', pc, args[0], args[1],
                               PICKER.unpack(self.read(args[1], PICKER.size))))
            result = 0
        elif pc in (PICKER_DIM_BACKGROUND, PICKER_DIM_FOREGROUND):
            self.calls.append(('picker_dim', pc, args[0],
                               struct.unpack('<4H', self.read(args[1], 8)), args[2]))
            result = 0
        elif pc == 0x4d335d380:
            self.calls.append(('status_background', args[0]))
            result = 0
        elif pc in (0x4d33212d0, 0x4d33212e0, 0x4d3321f80, 0x4d3389130):
            raise AssertionError(f'fixed stock setting path called: {pc:#x}')
        else:
            return super().hook(u, pc, size, opaque)
        u.reg_write(r.UC_ARM64_REG_X0, result)
        u.reg_write(r.UC_ARM64_REG_PC, u.reg_read(r.UC_ARM64_REG_LR))


class NativeSceneMachine(MenuMachine):
    """Execute the supplied firmware's scene engine and settings resume.

    Renderers, device services and memory-library calls are intercepted. The
    engine's scene copies, callback ABI, unwind loop, dispatch-pair publication
    and hierarchy updates execute as the original instructions.
    """
    def __init__(self, blob, symbols):
        super().__init__(blob, symbols)
        firmware = FIRMWARE.read_bytes()
        for start, length in ((0x4d3323ca0, 0x680), (0x4d3372d90, 0x1c0),
                              (0x4d33725f0, 0x20)):
            offset = start-0x4d3000000
            self.uc.mem_write(start, firmware[offset:offset+length])
        self.put(0x4d703469c, 12, 4)
        self.put(BACKING+8, STACK+0x7000)
        self.put(BACKING+20, 1, 2)

    def initialize(self, mode=1):
        super().initialize(mode)
        # Apply the integrated pointer map inside Unicorn. Original resume
        # must see the owned rows/callbacks, just as the installer supplies.
        for address, original, symbol in PATCHES:
            self.put(address, RESIDENT+self.symbols[symbol])

    def hook(self, u, pc, size, opaque):
        if pc in (PUSH, POP, PARENT_RESUME):
            return  # Execute the original instructions, including literals.
        a = [u.reg_read(reg) for reg in
             (r.UC_ARM64_REG_X0, r.UC_ARM64_REG_X1, r.UC_ARM64_REG_X2)]
        if pc == 0x4d3008200:
            u.mem_write(a[0], bytes([a[1] & 255])*a[2])
            result = a[0]
        elif pc == 0x4d3007ec0:
            left, right = self.read(a[0], a[2]), self.read(a[1], a[2])
            result = 0 if left == right else 1
        elif pc in (0x4d3325830, 0x4d3158c70, 0x4d33222e0,
                    0x4d3210a80, 0x4d33257c0):
            self.calls.append(('service', pc))
            result = 0
        elif pc == QUEUE:
            self.calls.append(('native_draw_queue', a[0]))
            # Complete the foreground synchronously, as a tail call with the
            # stock queue caller's LR. Exercise restoration INSIDE stock resume.
            u.reg_write(r.UC_ARM64_REG_X0, SURFACE)
            u.reg_write(r.UC_ARM64_REG_X1, 0)
            u.reg_write(r.UC_ARM64_REG_X2, 0)
            u.reg_write(r.UC_ARM64_REG_PC, self.get(a[0]))
            return
        else:
            return super().hook(u, pc, size, opaque)
        u.reg_write(r.UC_ARM64_REG_X0, result)
        u.reg_write(r.UC_ARM64_REG_PC, u.reg_read(r.UC_ARM64_REG_LR))


class NativeGlyphMachine(MenuMachine):
    """Execute original font selection and glyph lookup against segment05.

    Only the lookup's memcpy dependency is stubbed. The menu draw services
    remain intercepted so tests can inspect the actual relocated strings
    submitted by the compiled wrappers without rasterizing camera surfaces.
    """
    def __init__(self, blob, symbols):
        super().__init__(blob, symbols)
        self.uc.mem_write(FW, FIRMWARE.read_bytes())

    def glyph(self, font, character):
        height = self.run(FONT_HEIGHT, font)
        return self.run(GLYPH_INDEX, height, ord(character), 0, 0) & 0xffffffff

    def hook(self, u, pc, size, opaque):
        if pc != 0x4d3007fc0:
            return super().hook(u, pc, size, opaque)
        destination, source, length = (u.reg_read(reg) for reg in
                                      (r.UC_ARM64_REG_X0, r.UC_ARM64_REG_X1,
                                       r.UC_ARM64_REG_X2))
        u.mem_write(destination, self.read(source, length))
        u.reg_write(r.UC_ARM64_REG_X0, destination)
        u.reg_write(r.UC_ARM64_REG_PC, u.reg_read(r.UC_ARM64_REG_LR))


class NativeTextMachine(NativeGlyphMachine):
    """Run original row/title painters, text parsers and glyph metrics.

    Bitmap assets live outside segment05. Only their three pixel conversion
    leaves are skipped; glyph lookup, width/height, escape parsing and text
    placement execute the firmware instructions. No pixel fidelity is claimed.
    """
    def __init__(self, blob, symbols):
        super().__init__(blob, symbols)
        data = FIRMWARE.read_bytes()
        # Stock initialized data supplies the palette and glyph service data.
        self.uc.mem_write(0x4d7000000, data[0xebdfb0:0xebdfb0+0x45ec0])
        self.uc.mem_map(0x402174000, 0x20000)  # Stock glyph scratch bitmap.
        self.uc.mem_map(0x200000, 0x300000)    # Includes main row10 at Y952.
        self.uc.reg_write(r.UC_ARM64_REG_CPACR_EL1, 3 << 20)
        self.uc.mem_write(SURFACE, struct.pack('<4HQ4HQ', 0, 682, 0, 0,
                                              0x200000, 2048, 0, 682, 0, 0))
        self.uc.mem_write(BACKING, self.read(SURFACE, 32))
        self.text_calls = []
        self.glyph_calls = []
        self.glyph_origin = None
        self.language = 0  # English native resource sprites (family10).
        self.pua_calls = []

    def hook(self, u, pc, size, opaque):
        a = [u.reg_read(reg) for reg in
             (r.UC_ARM64_REG_X0, r.UC_ARM64_REG_X1, r.UC_ARM64_REG_X2)]
        if pc in (PAINT, 0x4d3363ca0, PICKER_MEASURE, PICKER_BACKGROUND,
                  PICKER_FOREGROUND, TEXT_WIDTH):
            return  # Execute original row/title painters, not their stubs.
        if pc == TEXT_DRAW:
            self.text_calls.append({'font': self.get(a[1]+28, 4),
                                    'text': self.text(self.get(a[1]+8)),
                                    'glyphs': [], 'pua': []})
        elif pc == 0x4d320abf0:
            self.glyph_origin = u.reg_read(r.UC_ARM64_REG_LR)
        elif pc == GLYPH_INDEX:
            glyph = {'height': a[0], 'codepoint': a[1], 'style': a[2],
                     'flag': u.reg_read(r.UC_ARM64_REG_X3), 'index': None,
                     'origin': self.glyph_origin}
            self.glyph_calls.append(glyph)
            if self.text_calls:
                self.text_calls[-1]['glyphs'].append(glyph)
        elif pc == 0x4d320ac50:
            self.glyph_calls[-1]['index'] = a[0] & 0xffffffff
        elif pc == 0x4d332d420 and u.reg_read(r.UC_ARM64_REG_LR)==0x4d320ad90:
            self.pua_calls.append((a[0], a[1]))  # Actual PUA family/glyph mapping.
            if self.text_calls:
                self.text_calls[-1]['pua'].append((a[0], a[1]))
        if pc == 0x4d3008200:
            u.mem_write(a[0], bytes([a[1] & 255])*a[2])
            result = a[0]
        elif pc == 0x4d3321f70:
            result = self.language
        elif pc in (0x4d33278e0, 0x4d3327c80, 0x4d3327d90):
            result = 0  # Bitmap conversion only; metrics come from segment05.
        else:
            return super().hook(u, pc, size, opaque)
        u.reg_write(r.UC_ARM64_REG_X0, result)
        u.reg_write(r.UC_ARM64_REG_PC, u.reg_read(r.UC_ARM64_REG_LR))


class NativeExitMachine(NativeTextMachine):
    """Execute original main-input predicates/exit routing on filtered events.

    Only the final Menu/playback transition service is recorded, so this
    checks that masked navigation cannot hide exits or touch stock rows.
    """
    category = 0

    def hook(self, u, pc, size, opaque):
        if pc in (INPUT, REPEAT):
            return
        if pc in (0x4d33731e0, 0x4d31a3800, 0x4d31a38b0):
            self.calls.append(('native_exit', pc))
            self.put(PENDING, 2, 4)
            result = 0
        elif pc == 0x4d330f3f0:
            result = self.category
        else:
            return super().hook(u, pc, size, opaque)
        u.reg_write(r.UC_ARM64_REG_X0, result)
        u.reg_write(r.UC_ARM64_REG_PC, u.reg_read(r.UC_ARM64_REG_LR))


class MenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.blob, cls.syms = build_menu_fixture()

    def setUp(self):
        self.m = MenuMachine(self.blob, self.syms)
        self.m.initialize()

    def assert_input_unchanged(self):
        m = self.m
        self.assertEqual(m.read(EVENT, 40), struct.pack('<5Q', *m.original_pointers))
        for address, payload in zip(m.original_pointers, m.original_parts):
            if payload is not None:
                self.assertEqual(m.read(address, len(payload)), payload)

    def assert_queued_once(self):
        m = self.m
        queues = [c for c in m.calls if c[0] == 'draw_queue']
        self.assertEqual(queues, [('draw_queue', m.owned_callbacks,
                                  (RESIDENT+self.syms['menu_draw_wrapper'],
                                   0x4d3372680, 0), 0, 0)])

    def test_initialize_copies_ten_rows_and_relocates_owned_data(self):
        m = self.m
        self.assertEqual(m.read(m.owned_rows, 320), m.stock_rows)
        self.assertEqual(m.read(ROWS, 352), m.stock_rows + b'\xa5'*32)
        self.assertEqual(m.read(STAGE+self.syms['menu_rows'], 352), bytes(352))
        row = ROW.unpack(m.read(m.owned_rows+320, 32))
        self.assertEqual(row[:4], (952, 2, 0, 0))
        self.assertEqual(row[6:], (4, 0))
        for pointer in row[4:5]:
            self.assertTrue(RESIDENT <= pointer < RESIDENT+self.syms['__end'])
        self.assertEqual(m.text(row[4]), b'BF+')
        self.assertEqual(row[5], 0)  # Stock submenu arrow.
        self.assertEqual(struct.unpack('<6Q', m.read(m.owned_callbacks, 48)),
                         (RESIDENT+self.syms['menu_draw_wrapper'], 0x4d3372680, 0,
                          RESIDENT+self.syms['menu_initial_draw_wrapper'], 0x4d3372f50, 0))
        self.assertEqual(m.read(STAGE+self.syms['menu_callbacks'], 48), bytes(48))

    def test_initialize_uses_resident_mode_and_selection(self):
        m = self.m
        m.select(10)
        m.initialize(mode=0)
        row = ROW.unpack(m.read(m.owned_rows+320, 32))
        self.assertEqual(row[1], 3)
        self.assertEqual(row[5], 0)
        child = RESIDENT+self.syms['menu_submenu_rows']
        self.assertEqual(m.text(m.get(child+16)), OFF)

    def test_bootstrap_zeroing_reseeds_resident_rows_and_callbacks(self):
        m = self.m
        m.uc.mem_write(m.owned_rows, b'\xcc'*352)
        m.uc.mem_write(m.owned_callbacks, b'\xcc'*48)
        m.initialize(mode=0)
        self.assertEqual(m.read(m.owned_rows, 320), m.stock_rows)
        row = ROW.unpack(m.read(m.owned_rows+320, 32))
        self.assertEqual(m.text(row[4]), b'BF+')
        self.assertEqual(row[5], 0)
        self.assertEqual(m.get(m.owned_callbacks), RESIDENT+self.syms['menu_draw_wrapper'])

    def test_down_from_last_stock_row_selects_bf_plus(self):
        m = self.m
        m.select(9, scroll=322)
        self.assertEqual(m.send(changed=8, touch=8, press=8), m.stock_result)
        self.assertEqual((m.get(CURRENT, 1), m.get(PREVIOUS, 1)), (10, 9))
        self.assertEqual((m.get(SCROLL, 2), m.get(HIGHLIGHT, 2)), (412, 592))
        self.assertIn(('update', 0, 10), m.calls)
        self.assertTrue(all(m.get(m.owned_rows+32*i+2, 1) & 1 == 0 for i in range(10)))
        self.assertEqual(KEY.unpack(m.inputs[-1]['parts'][0]), (0, 8, 8, 0, 0, 0))
        self.assertEqual(m.mode, 1)
        self.assert_queued_once()
        self.assert_input_unchanged()

    def test_down_repeat_uses_stock_gate_and_acceleration_count(self):
        m = self.m
        for ready in (False, True):
            with self.subTest(ready=ready):
                m.calls.clear()
                m.select(9)
                m.repeat_ready = ready
                m.send(touch=8, press=8, repeat=8, count=12, pad=0xa5)
                self.assertIn(('repeat', (0, 8, 8, 8, 12, 0xa5), 3), m.calls)
                self.assertEqual(m.get(CURRENT, 1), 10 if ready else 9)
                self.assertEqual(KEY.unpack(m.inputs[-1]['parts'][0]), (0, 8, 8, 0, 12, 0xa5))
                self.assertEqual(sum(c[0] == 'draw_queue' for c in m.calls), int(ready))

    def test_dial_only_with_null_key_preserves_second_field(self):
        m = self.m
        m.select(9)
        m.send(key=False, dial=(7, -1234))
        self.assertEqual(m.get(CURRENT, 1), 10)
        self.assertIsNone(m.inputs[-1]['parts'][0])
        self.assertEqual(m.inputs[-1]['parts'][1], struct.pack('<hh', 0, -1234))
        self.assert_queued_once()
        self.assert_input_unchanged()

    def test_navigation_bundle_does_not_also_toggle_new_row(self):
        m = self.m
        m.select(9)
        m.send(changed=13, touch=13, press=13, repeat=4, dial=(1, 22))
        self.assertEqual(m.get(CURRENT, 1), 10)
        self.assertEqual(m.mode, 1)
        self.assertEqual(KEY.unpack(m.inputs[-1]['parts'][0]), (0, 13, 13, 0, 0, 0))
        self.assertEqual(m.inputs[-1]['parts'][1], struct.pack('<hh', 0, 22))
        self.assert_queued_once()
        self.assert_input_unchanged()

    def test_parent_press_opens_once_without_changing_mode(self):
        m = self.m
        m.select(10)
        for bits in (1, 4, 5):
            with self.subTest(bits=bits):
                m.calls.clear()
                m.put(PENDING, 12, 4)
                m.send(changed=bits, touch=bits, press=bits)
                self.assertEqual(m.mode, 1)
                self.assertEqual(m.get(m.owned_rows+320+16), 0)
                self.assertEqual(KEY.unpack(m.inputs[-1]['parts'][0]), (0, bits, bits, 0, 0, 0))
                self.assertEqual([c[0] for c in m.calls], ['input', 'push'])
                self.assertEqual(m.calls[-1][1], RESIDENT+self.syms['menu_submenu_scene'])

    def test_touch_release_and_center_right_repeat_do_not_toggle(self):
        m = self.m
        m.select(10)
        for changed, touch, press, repeat in ((1, 1, 0, 0), (1, 1, 0, 0),
                                              (1, 0, 0, 0), (0, 5, 5, 5)):
            with self.subTest(changed=changed, touch=touch, repeat=repeat):
                m.calls.clear()
                m.send(changed=changed, touch=touch, press=press, repeat=repeat)
                self.assertEqual(m.mode, 1)
                self.assertFalse(any(c[0] == 'draw_queue' for c in m.calls))
                if not repeat:
                    self.assertEqual(m.inputs[-1]['event'], EVENT)
                    self.assertEqual(m.inputs[-1]['parts'], m.original_parts)

    def test_bottom_down_and_positive_dial_are_consumed(self):
        m = self.m
        m.select(10, previous=9, scroll=412)
        m.send(changed=8, touch=8, press=8, repeat=8, dial=(32767, -2))
        self.assertEqual(m.get(CURRENT, 1), 10)
        self.assertEqual(m.calls, [('input',)])
        self.assertEqual(KEY.unpack(m.inputs[-1]['parts'][0]), (0, 8, 8, 0, 0, 0))
        self.assertEqual(m.inputs[-1]['parts'][1], struct.pack('<hh', 0, -2))
        self.assert_input_unchanged()

    def test_up_negative_and_zero_dial_are_forwarded_unchanged(self):
        m = self.m
        m.select(10)
        for args in ({'changed': 16, 'touch': 16, 'press': 16},
                     {'key': False, 'dial': (-32768, 7)},
                     {'key': False, 'dial': (0, 7)}):
            with self.subTest(args=args):
                m.calls.clear()
                m.send(**args)
                self.assertEqual(m.calls, [('input',)])
                self.assertEqual(m.inputs[-1]['event'], EVENT)
                self.assertEqual(m.inputs[-1]['parts'], m.original_parts)
                self.assertEqual(m.inputs[-1]['current'], 10)

    def test_mixed_exit_and_optional_parts_prevent_submenu_push(self):
        m = self.m
        m.select(10)
        m.stock_pending = 2  # Stock Menu/playback exit beats entering BF+.
        bits = 1 | 8 | 32 | 64  # Center, down, playback, menu/exit.
        m.send(changed=bits, touch=bits, press=bits, repeat=8, count=17, pad=0xad,
               dial=(3, -9), lcd=bytes(range(20)), one=b'\x71', five=b'hello')
        parts = m.inputs[-1]['parts']
        self.assertEqual(KEY.unpack(parts[0]), (96, bits, bits, 0, 17, 0xad))
        self.assertEqual(parts[1], struct.pack('<hh', 0, -9))
        self.assertEqual(parts[2:], m.original_parts[2:])
        self.assertEqual(m.inputs[-1]['pointers'][2:], m.original_pointers[2:])
        self.assertEqual(m.mode, 1)
        self.assertFalse(any(c[0] in ('push', 'draw_queue') for c in m.calls))
        self.assert_input_unchanged()

    def test_mixed_navigation_preserves_other_key_actions(self):
        m = self.m
        m.select(9)
        m.send(changed=8 | 16 | 64, touch=88, press=88, repeat=16, dial=(-1, 2))
        self.assertEqual(KEY.unpack(m.inputs[-1]['parts'][0]), (80, 88, 88, 16, 0, 0))
        self.assertEqual(m.inputs[-1]['pointers'][1], m.original_pointers[1])
        self.assertEqual(m.inputs[-1]['parts'][1], m.original_parts[1])
        self.assertEqual(m.inputs[-1]['current'], 10)
        self.assert_input_unchanged()

    def test_repeated_right_does_not_hide_mixed_exit(self):
        m = self.m
        m.select(10)
        m.send(changed=64, touch=68, press=68, repeat=4)
        self.assertEqual(KEY.unpack(m.inputs[-1]['parts'][0]), (64, 68, 68, 0, 0, 0))
        self.assertEqual(m.mode, 1)

    def test_existing_rows_forward_original_event_and_return(self):
        m = self.m
        for current in (0, 8, 9):
            with self.subTest(current=current):
                m.calls.clear()
                m.select(current)
                self.assertEqual(m.send(changed=1, touch=1, press=1), m.stock_result)
                self.assertEqual(m.calls, [('input',)])
                self.assertEqual(m.inputs[-1]['event'], EVENT)
                self.assertEqual(m.inputs[-1]['parts'], m.original_parts)
                self.assertEqual(m.get(CURRENT, 1), current)

    def test_draw_paints_owned_row_before_stock_then_corrects_scrollbar(self):
        m = self.m
        for mode, selected in ((1, 10), (0, 9)):
            with self.subTest(mode=mode, selected=selected):
                m.calls.clear()
                m.mode = mode
                m.select(selected, scroll=412)
                self.assertEqual(m.draw(), m.draw_result)
                self.assertEqual([c[0] for c in m.calls], ['paint', 'draw', 'rect', 'rect'])
                paint = m.calls[0]
                self.assertEqual(paint[1:3], (BACKING, m.owned_rows+320))
                row = paint[3]
                self.assertEqual((row[0], row[1], row[6]), (952, 2 | (selected == 10), 4))
                self.assertEqual(m.text(row[4]), b'BF+')
                self.assertEqual(row[5], 0)
                self.assertEqual(m.calls[1], ('draw', DRAW, SURFACE, PARAMS, 0x12345678))
                self.assertEqual(m.calls[2:], [('rect', SURFACE, (1018, 52, 6, 630), 0),
                                              ('rect', SURFACE, (1018, 282, 6, 400), 0xffff)])
                self.assertEqual(m.read(m.owned_rows, 320), m.stock_rows)

    def test_initial_draw_copies_pitch_before_prepainting(self):
        m = self.m
        self.assertEqual(m.draw(initial=True), m.draw_result)
        self.assertEqual(m.calls[0][4], 0x33440820)
        self.assertEqual(m.get(BACKING+16, 4), m.get(SURFACE+16, 4))
        self.assertEqual(m.calls[1], ('draw', INITIAL, SURFACE, PARAMS, 0x12345678))

    def test_normal_draw_does_not_overwrite_backing_pitch(self):
        self.m.draw()
        self.assertEqual(self.m.calls[0][4], 0x11220800)

    def test_scrollbar_proportions_and_clamping(self):
        m = self.m
        for scroll, expected_y in ((0, 52), (52, 52), (232, 167), (412, 282), (65535, 282)):
            with self.subTest(scroll=scroll):
                m.calls.clear()
                m.put(SCROLL, scroll, 2)
                m.draw()
                self.assertEqual(m.calls[-1], ('rect', SURFACE, (1018, expected_y, 6, 400), 0xffff))

    def test_alternate_menu_forwards_without_custom_access_or_pitch_changes(self):
        m = self.m
        m.put(ALTERNATE, 1, 1)
        m.select(9)
        m.send(changed=8, touch=8, press=8, dial=(1, 0))
        self.assertEqual(m.inputs[-1]['event'], EVENT)
        self.assertEqual(m.inputs[-1]['parts'], m.original_parts)
        self.assertEqual(m.get(CURRENT, 1), 9)
        m.draw()
        m.draw(initial=True)
        self.assertEqual([c[0] for c in m.calls], ['input', 'draw', 'draw'])
        self.assertEqual(m.get(BACKING+16, 4), 0x11220800)
        self.assertEqual(m.row10_accesses, [])

    def test_removed_stale_wrappers_forward_with_safe_stock_indices(self):
        m = self.m
        m.mode = 2
        for action in ('input', 'draw', 'initial'):
            with self.subTest(action=action):
                m.calls.clear()
                m.row10_accesses.clear()
                m.select(10, previous=10, scroll=412)
                m.put(REPAINT, 0, 1)
                if action == 'input':
                    self.assertEqual(m.send(changed=1, touch=1, press=1), m.stock_result)
                    self.assertEqual(m.inputs[-1]['event'], EVENT)
                    self.assertEqual(m.inputs[-1]['parts'], m.original_parts)
                else:
                    self.assertEqual(m.draw(initial=action == 'initial'), m.draw_result)
                self.assertEqual((m.get(CURRENT, 1), m.get(PREVIOUS, 1)), (9, 9))
                self.assertEqual((m.get(SCROLL, 2), m.get(HIGHLIGHT, 2)), (322, 592))
                self.assertEqual(m.get(REPAINT, 1), 1)
                self.assertEqual(m.mode, 2)
                self.assertEqual(len(m.calls), 1)
                self.assertEqual(m.row10_accesses, [])

    def test_removed_valid_stock_selection_is_not_changed(self):
        m = self.m
        m.mode = 2
        m.select(5, previous=4, scroll=142)
        before = (m.read(CURRENT, 2), m.read(SCROLL, 2), m.read(HIGHLIGHT, 2))
        m.send(key=False)
        m.draw(initial=True)
        self.assertEqual((m.read(CURRENT, 2), m.read(SCROLL, 2), m.read(HIGHLIGHT, 2)), before)
        self.assertEqual(m.get(BACKING+16, 4), 0x11220800)
        self.assertEqual(m.row10_accesses, [])

    def test_removed_stale_selection_keeps_highlight_in_view(self):
        m = self.m
        m.mode = 2
        for current, previous, scroll, expected_scroll, expected_y in (
                (0, 10, 412, 52, 52), (10, 9, 52, 322, 592),
                (255, 255, 65535, 322, 592), (0, 0, 0, 52, 52)):
            with self.subTest(current=current, previous=previous, scroll=scroll):
                m.select(current, previous=previous, scroll=scroll)
                m.draw()
                self.assertEqual(m.get(SCROLL, 2), expected_scroll)
                self.assertEqual(m.get(HIGHLIGHT, 2), expected_y)
                self.assertEqual(m.row10_accesses, [])

    def test_owned_scene_and_draw_descriptors_are_relocated(self):
        m = self.m
        def address(name):
            return RESIDENT+self.syms[name]
        self.assertEqual(struct.unpack('<4Q', m.read(address('menu_parent_scene'), 32)),
                         (0x4d3372ff0, address('menu_parent_resume_wrapper'),
                          0x4d33725f0, 0x4d3372610))
        self.assertEqual(struct.unpack('<4Q', m.read(address('menu_submenu_scene'), 32)),
                         (address('menu_submenu_enter'), address('menu_submenu_resume'),
                          address('menu_submenu_leave'), address('menu_submenu_leave')))
        self.assertEqual(struct.unpack('<3Q', m.read(address('menu_submenu_callbacks'), 24)),
                         (address('menu_submenu_draw_wrapper'),
                          address('menu_submenu_background_wrapper'), 0))
        row = ROW.unpack(m.read(address('menu_submenu_rows'), 32))
        self.assertEqual((row[0], row[1], row[6]), (142, 3, 6))
        self.assertEqual(m.text(row[4]), b'\x1b\x06Touch Focus Zoom')
        self.assertEqual(m.text(row[5]), ON)
        for pointer in row[4:6]:
            self.assertTrue(RESIDENT <= pointer < RESIDENT+self.syms['__end'])
        subject = ROW.unpack(m.read(address('menu_submenu_rows')+32, 32))
        self.assertEqual((subject[0], subject[1], subject[6]), (232, 2, 6))
        self.assertEqual(m.text(subject[4]), b'\x1b\x06MF Subject Detection')
        self.assertEqual(m.text(subject[5]), OFF)
        aspect = ROW.unpack(m.read(address('menu_submenu_rows')+64, 32))
        self.assertEqual((aspect[0], aspect[1], aspect[6]), (322, 2, 6))
        self.assertEqual(m.text(aspect[4]), b'\x1b\x06Extra Aspect Ratios')
        self.assertEqual(m.text(aspect[5]), OFF)
        version = ROW.unpack(m.read(address('menu_submenu_rows')+96, 32))
        self.assertEqual((version[0], version[1], version[6]), (412, 0x12, 6))
        self.assertEqual(m.text(version[4]), b'\x1b\x06Version')
        self.assertEqual(m.text(version[5]), b'1.0')

    def test_failed_push_or_busy_hierarchy_does_not_arm_return(self):
        m = self.m
        m.select(10)
        m.push_result = -1
        m.send(changed=1, press=1)
        view = RESIDENT+self.syms['menu_view']
        self.assertEqual(m.get(view+8, 4), 0)
        for depth, pending in ((4, 3), (0, 12), (11, 12)):
            with self.subTest(depth=depth, pending=pending):
                m.calls.clear()
                m.put(DEPTH, depth, 4)
                m.put(PENDING, pending, 4)
                m.send(changed=1, press=1)
                self.assertEqual(m.calls, [('input',)])

    def test_child_init_installs_handler_pair_without_chaining_scene(self):
        m = self.m
        next_scene, handlers = STACK+0x5000, STACK+0x5100
        m.uc.mem_write(next_scene, bytes(32))
        m.uc.mem_write(handlers, b'\xaa'*16)
        self.assertEqual(m.run(RESIDENT+self.syms['menu_submenu_enter'], next_scene, handlers, 0), 0)
        self.assertEqual(m.read(next_scene, 32), bytes(32))
        self.assertEqual(struct.unpack('<2Q', m.read(handlers, 16)),
                         (RESIDENT+self.syms['menu_submenu_input_wrapper'], 0))
        self.assertEqual([c[0] for c in m.calls], ['status_update', 'draw_queue'])
        self.assertEqual(m.calls[-1][1], RESIDENT+self.syms['menu_submenu_callbacks'])
        m.calls.clear()
        m.run(RESIDENT+self.syms['menu_submenu_enter'], next_scene, handlers, 1)
        self.assertEqual(m.calls, [])

    def test_submenu_press_opens_picker_without_changing_mode(self):
        m = self.m
        for bits in (1, 4, 5):
            with self.subTest(bits=bits):
                m.enter_submenu()
                m.send(submenu=True, changed=bits, touch=bits, press=bits)
                self.assertEqual(m.mode, 1)
                self.assertEqual([c[0] for c in m.calls], ['input', 'push'])
                self.assertEqual(m.calls[-1][1], RESIDENT+self.syms['menu_picker_scene'])
                self.assertEqual(m.get(PENDING, 4), 6)
                m.calls.clear()
                m.send(submenu=True, changed=bits, press=bits)
                self.assertEqual(m.calls, [])  # Pending push cannot repeat.
                self.assert_input_unchanged()

    def test_submenu_touch_and_activation_repeats_do_not_toggle(self):
        m = self.m
        m.enter_submenu()
        for args in ({'changed': 1, 'touch': 1}, {'changed': 1},
                     {'press': 5, 'touch': 5, 'repeat': 5}):
            with self.subTest(args=args):
                m.calls.clear()
                m.send(submenu=True, **args)
                self.assertEqual(m.mode, 1)
                self.assertEqual(m.calls, [('input',)])
                if 'dial' in args:
                    self.assertEqual(m.inputs[-1]['parts'][1], struct.pack('<hh', 0, args['dial'][1]))
                if not args.get('key', True):
                    self.assertIsNone(m.inputs[-1]['parts'][0])
                self.assert_input_unchanged()

    def test_submenu_left_pops_and_parent_resume_retains_bf_selection(self):
        m = self.m
        m.enter_submenu()
        m.send(submenu=True, changed=7, touch=7, press=7)
        self.assertEqual(m.mode, 1)  # Back takes priority over simultaneous toggle.
        self.assertEqual(m.calls, [('input',), ('pop',)])
        self.assertEqual(m.get(PENDING, 4), 4)
        m.run(RESIDENT+self.syms['menu_submenu_leave'])
        result = m.run(RESIDENT+self.syms['menu_parent_resume_wrapper'], STACK+0x5000, STACK+0x5100, 0)
        self.assertEqual(result, 0x76543210)
        self.assertEqual((m.get(CURRENT, 1), m.get(PREVIOUS, 1)), (10, 10))
        self.assertEqual((m.get(SCROLL, 2), m.get(HIGHLIGHT, 2)), (412, 592))
        self.assertEqual(m.get(STACK+0x5100), RESIDENT+self.syms['menu_input_wrapper'])
        self.assertIn(('update', 1, 10), m.calls)

    def test_submenu_stock_exit_beats_toggle_and_preserves_optional_payloads(self):
        m = self.m
        m.enter_submenu()
        m.stock_pending = 2
        m.send(submenu=True, changed=95, touch=95, press=95, repeat=31,
               dial=(3, -9), lcd=bytes(range(20)), one=b'\x71', five=b'hello')
        parts = m.inputs[-1]['parts']
        self.assertEqual(KEY.unpack(parts[0]), (64, 95, 95, 0, 0, 0))
        self.assertEqual(parts[1], struct.pack('<hh', 0, -9))
        self.assertEqual(parts[2:], m.original_parts[2:])
        self.assertEqual([c[0] for c in m.calls], ['repeat', 'input'])
        self.assertEqual(m.mode, 1)
        m.calls.clear()
        m.run(RESIDENT+self.syms['menu_submenu_leave'])
        m.run(RESIDENT+self.syms['menu_parent_resume_wrapper'], STACK+0x5000, STACK+0x5100, 1)
        self.assertEqual(m.calls, [('resume', STACK+0x5000, STACK+0x5100, 1)])
        self.assertEqual(m.get(RESIDENT+self.syms['menu_view']+8, 4), 0)
        self.assert_input_unchanged()

    def test_submenu_draws_native_title_option_highlight_and_status(self):
        m = self.m
        m.enter_submenu()
        m.run(RESIDENT+self.syms['menu_submenu_background_wrapper'], SURFACE, PARAMS, 0)
        self.assertEqual([c[0] for c in m.calls], ['background', 'title'] + ['row_background']*4)
        self.assertEqual(m.calls[0], ('background', SURFACE, (0, 52, 1024, 630), 0x228080ff))
        self.assertEqual(m.calls[1], ('title', 0x4d3363c60, SURFACE, 52, b'BF+', 1))
        self.assertEqual(m.calls[2][2][1], 3)
        for mode in (0, 1):
            with self.subTest(mode=mode):
                m.calls.clear()
                m.mode = mode
                m.run(RESIDENT+self.syms['menu_submenu_draw_wrapper'], SURFACE, PARAMS, 0)
                self.assertEqual([c[0] for c in m.calls], ['rect', 'title']+['paint']*4+['status'])
                self.assertEqual(m.calls[1], ('title', 0x4d3363ca0, SURFACE, 52, b'BF+', 1))
                row = m.calls[2][3]
                self.assertEqual(m.text(row[4]), b'\x1b\x06Touch Focus Zoom')
                self.assertEqual(m.text(row[5]), ON if mode else OFF)
                subject = m.calls[3][3]
                self.assertEqual(m.text(subject[4]), b'\x1b\x06MF Subject Detection')
                self.assertEqual(m.text(subject[5]), OFF)
                aspect = m.calls[4][3]
                self.assertEqual(m.text(aspect[4]), b'\x1b\x06Extra Aspect Ratios')
                self.assertEqual(m.text(aspect[5]), OFF)
                version = m.calls[5][3]
                self.assertEqual(m.text(version[4]), b'\x1b\x06Version')
                self.assertEqual(m.text(version[5]), b'1.0')
                self.assertEqual(m.calls[-1], ('status', SURFACE, 47, 0, 0))

    def test_stale_submenu_callbacks_are_inert_after_exit_or_removal(self):
        m = self.m
        for removed in (False, True):
            with self.subTest(removed=removed):
                m.mode = 1
                m.enter_submenu()
                if removed:
                    m.mode = 2
                else:
                    m.run(RESIDENT+self.syms['menu_submenu_leave'])
                m.row10_accesses.clear()
                m.send(submenu=True, changed=7, press=7)
                m.run(RESIDENT+self.syms['menu_submenu_draw_wrapper'], SURFACE, PARAMS, 0)
                m.run(RESIDENT+self.syms['menu_submenu_background_wrapper'], SURFACE, PARAMS, 0)
                self.assertEqual(m.calls, [])
                self.assertEqual(m.row10_accesses, [])

    def test_removed_parent_resume_forwards_without_restoring_owned_selection(self):
        m = self.m
        m.enter_submenu()
        m.mode = 2
        m.row10_accesses.clear()
        result = m.run(RESIDENT+self.syms['menu_parent_resume_wrapper'], STACK+0x5000, STACK+0x5100, 0)
        self.assertEqual(result, 0x76543210)
        self.assertEqual(m.calls, [('resume', STACK+0x5000, STACK+0x5100, 0)])
        self.assertLessEqual(m.get(CURRENT, 1), 9)
        self.assertEqual(m.row10_accesses, [])

    def test_submenu_navigation_and_read_only_version(self):
        m = self.m
        m.enter_submenu()
        rows = RESIDENT+self.syms['menu_submenu_rows']
        view = RESIDENT+self.syms['menu_view']
        for args, expected in (({'changed': 8, 'press': 8}, 1),
                               ({'changed': 8, 'press': 8}, 2),
                               ({'changed': 8, 'press': 8}, 3),
                               ({'changed': 8, 'press': 8}, 3),
                               ({'changed': 8, 'press': 8}, 3),
                               ({'changed': 5, 'press': 5}, 3),
                               ({'key': False, 'dial': (-3, 21)}, 2),
                               ({'key': False, 'dial': (-3, 21)}, 1),
                               ({'key': False, 'dial': (-3, 21)}, 0),
                               ({'key': False, 'dial': (8, -21)}, 1),
                               ({'changed': 16, 'press': 16}, 0)):
            with self.subTest(args=args):
                m.calls.clear()
                m.send(submenu=True, **args)
                self.assertEqual(m.get(view+16, 4), expected)
                self.assertEqual(m.mode, 1)
                self.assertEqual(m.get(rows+2, 1), 2 | (expected == 0))
                self.assertEqual(m.get(rows+34, 1), 2 | (expected == 1))
                self.assertEqual(m.get(rows+66, 1), 2 | (expected == 2))
                self.assertEqual(m.get(rows+98, 1), 0x12 | (expected == 3))
                self.assertEqual(m.text(m.get(rows+112)), b'1.0')
                self.assertNotIn('push', [c[0] for c in m.calls])
                if 'dial' in args:
                    self.assertIsNone(m.inputs[-1]['parts'][0])
                    self.assertEqual(m.inputs[-1]['parts'][1], struct.pack('<hh', 0, args['dial'][1]))
                self.assert_input_unchanged()

    def test_submenu_navigation_uses_stock_repeat_gate_and_beats_toggle(self):
        m = self.m
        m.enter_submenu()
        view = RESIDENT+self.syms['menu_view']
        m.repeat_ready = False
        m.send(submenu=True, touch=8, press=8, repeat=8, count=12)
        self.assertEqual(m.get(view+16, 4), 0)
        m.repeat_ready = True
        m.send(submenu=True, touch=8, press=8, repeat=8, count=12)
        self.assertEqual(m.get(view+16, 4), 1)
        m.send(submenu=True, changed=17, press=17)
        self.assertEqual(m.get(view+16, 4), 0)
        self.assertEqual(m.mode, 1)

    def test_picker_image_size_and_all_owned_pointers_are_relocated(self):
        m = self.m
        self.assertLessEqual(len(self.blob), 0x10000)
        self.assertEqual((self.syms['launch'], self.syms['bootstrap']), (0, 0x100))
        p = m.picker_state()
        self.assertEqual(p[:9], (142, 2, 1, 255, 1, 0, 0, 2, 0))
        labels, secondary, disabled, language = p[9:]
        self.assertEqual((secondary, language), (0, 0))
        self.assertEqual(m.read(disabled, 2), bytes(2))
        pointers = struct.unpack('<2Q', m.read(labels, 16))
        self.assertEqual([m.text(a) for a in pointers], [OFF, ON])
        for pointer in (labels, disabled, *pointers):
            self.assertTrue(RESIDENT <= pointer < RESIDENT+self.syms['__end'])
        scene = RESIDENT+self.syms['menu_picker_scene']
        self.assertEqual(struct.unpack('<4Q', m.read(scene, 32)), tuple(
            RESIDENT+self.syms[name] for name in ('menu_picker_enter', 'menu_picker_enter',
                                                'menu_picker_leave', 'menu_picker_leave')))
        callbacks = RESIDENT+self.syms['menu_picker_callbacks']
        self.assertEqual(struct.unpack('<6Q', m.read(callbacks, 48)), tuple(
            RESIDENT+self.syms[name] if name else 0 for name in (
                'menu_picker_draw_wrapper', 'menu_picker_background_wrapper', None,
                'menu_picker_initial_draw_wrapper', 'menu_picker_initial_background_wrapper', None)))
        for name, length in (('menu_picker', 48), ('menu_picker_scene', 32),
                             ('menu_picker_callbacks', 48), ('menu_picker_labels', 16)):
            self.assertEqual(m.read(STAGE+self.syms[name], length), bytes(length))

    def test_picker_enter_snapshots_current_and_queues_initial_callbacks(self):
        m = self.m
        for mode in (0, 1):
            m.mode = mode
            m.enter_picker()
            m.put(m.picker_address+3, 1-mode, 1)
            m.run(RESIDENT+self.syms['menu_picker_enter'], STACK+0x5000, STACK+0x5100, 0)
            self.assertEqual(m.mode, mode)
            self.assertEqual(m.picker_state()[2:5], (mode, 255, mode))
            self.assertEqual(struct.unpack('<2Q', m.read(STACK+0x5100, 16)),
                             (RESIDENT+self.syms['menu_picker_input_wrapper'], 0))
            self.assertEqual([c[0] for c in m.calls],
                             ['picker_measure', 'status_update', 'draw_queue'])
            self.assertEqual(m.calls[-1][1], RESIDENT+self.syms['menu_picker_callbacks']+24)
            m.calls.clear()
            before = m.read(m.picker_address, 48)
            m.run(RESIDENT+self.syms['menu_picker_enter'], STACK+0x5000, STACK+0x5100, 1)
            self.assertEqual(m.calls, [])
            self.assertEqual(m.read(m.picker_address, 48), before)

    def test_picker_navigation_is_tentative_clamped_and_uses_partial_redraw(self):
        m = self.m
        for mode in (0, 1):
            for event, expected in (({'changed':8, 'press':8},1),
                                    ({'changed':16, 'press':16},0),
                                    ({'key':False, 'dial':(32767,-9)},1),
                                    ({'key':False, 'dial':(-32768,12)},0)):
                with self.subTest(mode=mode, event=event):
                    m.mode = mode
                    m.enter_picker()
                    m.send(picker=True, **event)
                    self.assertEqual(m.mode, mode)
                    self.assertEqual(m.picker_state()[2:5], (expected, mode, mode))
                    self.assertEqual(m.get(PENDING, 4), 12)
                    queues = [c for c in m.calls if c[0]=='draw_queue']
                    self.assertEqual(len(queues), int(mode!=expected))
                    if queues:
                        self.assertEqual(queues[0][1], RESIDENT+self.syms['menu_picker_callbacks'])
                    if not event.get('key', True):
                        self.assertIsNone(m.inputs[-1]['parts'][0])
                        self.assertEqual(m.inputs[-1]['parts'][1],
                                         struct.pack('<hh', 0, event['dial'][1]))
                    self.assert_input_unchanged()

    def test_picker_repeat_gate_touch_release_and_activation_repeat(self):
        m = self.m
        m.enter_picker()
        m.repeat_ready = False
        m.send(picker=True, repeat=16, count=12)
        self.assertEqual(m.picker_state()[2], 1)
        m.repeat_ready = True
        m.send(picker=True, repeat=16, count=12)
        self.assertEqual(m.picker_state()[2], 0)
        for event in ({'changed':1, 'touch':1}, {'changed':1},
                      {'repeat':5, 'press':5}, {'key':False, 'dial':(0,7)}):
            m.calls.clear()
            m.send(picker=True, **event)
            self.assertEqual(m.calls, [('input',)])
            self.assertEqual(m.mode, 1)
            self.assertEqual(m.picker_state()[2:5], (0, 1, 1))
            self.assert_input_unchanged()

    def test_picker_center_and_right_commit_only_private_mode_once(self):
        m = self.m
        for initial in (0, 1):
            for bits in (1, 4, 5):
                with self.subTest(initial=initial, bits=bits):
                    m.mode = initial
                    m.enter_picker()
                    m.send(picker=True, key=False, dial=(-1 if initial else 1, 0))
                    m.calls.clear()
                    m.send(picker=True, changed=bits, press=bits)
                    self.assertEqual(m.mode, 1-initial)
                    self.assertEqual(m.picker_state()[4], initial)
                    self.assertEqual(m.calls, [('input',), ('pop',)])
                    self.assertEqual(m.get(PENDING, 4), 5)
                    m.calls.clear()
                    m.send(picker=True, changed=bits, press=bits)
                    self.assertEqual(m.calls, [])
                    self.assert_input_unchanged()

    def test_picker_left_cancels_tentative_and_beats_simultaneous_confirm_dial(self):
        m = self.m
        m.enter_picker()
        m.send(picker=True, key=False, dial=(-1,0))
        m.calls.clear()
        m.send(picker=True, changed=7, press=7, dial=(1,3))
        self.assertEqual(m.mode, 1)
        self.assertEqual(m.picker_state()[2], 0)
        self.assertEqual(m.calls, [('input',), ('pop',)])
        self.assert_input_unchanged()

    def test_picker_menu_playback_cancel_and_preserve_filtered_optional_events(self):
        m = self.m
        for exit_bit in (32, 64):
            for pending in (None, 2):
                with self.subTest(exit_bit=exit_bit, pending=pending):
                    m.stock_pending = None
                    m.enter_picker()
                    m.send(picker=True, key=False, dial=(-1,0))
                    m.calls.clear()
                    m.stock_pending = pending
                    m.send(picker=True, changed=exit_bit|5, press=exit_bit|5,
                           repeat=5, dial=(1,-9), lcd=bytes(range(20)),
                           one=b'a', five=b'hello')
                    self.assertEqual(m.mode, 1)
                    self.assertEqual(m.picker_state()[2], 0)
                    self.assertEqual(m.calls, [('input',)])
                    self.assertEqual(KEY.unpack(m.inputs[-1]['parts'][0]),
                                     (exit_bit,0,exit_bit|5,0,0,0))
                    self.assertEqual(m.inputs[-1]['parts'][1], struct.pack('<hh',0,-9))
                    self.assertEqual(m.inputs[-1]['parts'][2:], m.original_parts[2:])
                    self.assert_input_unchanged()

    def test_picker_initial_dim_and_partial_paint_use_native_routines(self):
        m = self.m
        m.enter_picker()
        for background in (True, False):
            suffix = 'background_wrapper' if background else 'draw_wrapper'
            m.calls.clear()
            m.run(RESIDENT+self.syms['menu_picker_initial_'+suffix], SURFACE, PARAMS, 7)
            self.assertEqual(m.calls[0], ('picker_dim',
                PICKER_DIM_BACKGROUND if background else PICKER_DIM_FOREGROUND,
                SURFACE, (0,52,1024,630), 0x00808085 if background else 8))
            self.assertEqual(m.calls[1][:4], ('picker_paint',
                PICKER_BACKGROUND if background else PICKER_FOREGROUND,
                SURFACE, m.picker_address))
            self.assertEqual(m.calls[-1][0], 'status_background' if background else 'status')
            m.calls.clear()
            m.run(RESIDENT+self.syms['menu_picker_'+suffix], SURFACE, PARAMS, 7)
            self.assertEqual([c[0] for c in m.calls], ['picker_paint'])

    def test_picker_stale_callbacks_inert_after_exit_pending_or_removal(self):
        m = self.m
        draws = ('draw_wrapper','background_wrapper','initial_draw_wrapper','initial_background_wrapper')
        for removed in (False, True):
            m.mode = 1
            m.enter_picker()
            if removed:
                m.mode = 2
            else:
                m.run(RESIDENT+self.syms['menu_picker_leave'])
            m.row10_accesses.clear()
            m.send(picker=True, changed=5, press=5)
            for suffix in draws:
                m.run(RESIDENT+self.syms['menu_picker_'+suffix], SURFACE, PARAMS, 0)
            self.assertEqual(m.calls, [])
            self.assertEqual(m.row10_accesses, [])
            self.assertEqual(m.mode, 2 if removed else 1)
        m.run(RESIDENT+self.syms['menu_picker_enter'], STACK+0x5000, STACK+0x5100, 0)
        self.assertEqual(m.read(STACK+0x5100, 16), bytes(16))
        self.assertEqual(m.calls, [])
        m.mode = 1
        m.enter_picker()
        for depth, pending in ((5,12),(6,5),(7,12)):
            m.put(DEPTH, depth, 4)
            m.put(PENDING, pending, 4)
            m.send(picker=True, changed=5, press=5)
            self.assertEqual(m.calls, [])

    def test_picker_removal_during_stock_remainder_cannot_reenable_mode(self):
        m = self.m
        m.enter_picker()
        m.stock_mode = 2
        m.send(picker=True, changed=1, press=1)
        self.assertEqual(m.mode, 2)
        self.assertEqual(m.calls, [('input',)])

    def test_picker_failed_push_and_max_depth_leave_bf_plus_usable(self):
        m = self.m
        m.enter_submenu()
        m.push_result = -1
        m.send(submenu=True, changed=1, press=1)
        self.assertEqual(m.get(PENDING,4),12)
        self.assertEqual(m.get(RESIDENT+self.syms['menu_picker_active'],4),0)
        self.assertEqual(m.mode,1)
        m.calls.clear()
        m.send(submenu=True, changed=8, press=8)
        self.assertEqual(m.get(RESIDENT+self.syms['menu_view']+16,4),1)
        m.put(RESIDENT+self.syms['menu_view']+16,0,4)
        m.put(RESIDENT+self.syms['menu_view'],10,4)
        m.put(DEPTH,11,4)
        m.calls.clear()
        m.send(submenu=True, changed=1, press=1)
        self.assertEqual(m.calls,[('input',)])

    @unittest.skipUnless(FIRMWARE.is_file(), 'requires supplied decoded segment05')
    def test_original_picker_renders_owned_off_on_with_separate_current_marker(self):
        m = NativeTextMachine(self.blob, self.syms)
        m.initialize(mode=1)
        m.enter_picker()
        self.assertEqual(m.picker_state()[5],0)  # Actual widest-label result.
        m.send(picker=True, key=False, dial=(-1,0))
        stock_before = m.read(0x4d7043890,48)
        m.calls.clear()
        m.run(RESIDENT+self.syms['menu_picker_background_wrapper'], SURFACE, PARAMS, 0)
        rectangles = [c[2] for c in m.calls if c[0]=='background']
        self.assertEqual(rectangles,[(790,142,234,90),(790,232,234,90),(797,239,10,76)])
        m.run(RESIDENT+self.syms['menu_picker_draw_wrapper'], SURFACE, PARAMS, 0)
        self.assertEqual([(c['text'],c['font']) for c in m.text_calls],
                         [(OFF,5),(ON,5)])
        self.assertEqual(m.pua_calls, [])
        for call in m.text_calls:
            drawn = [g for g in call['glyphs'] if g['origin']==GLYPH_FROM_DRAW]
            self.assertEqual([g['codepoint'] for g in drawn],list(call['text'][2:]))
            self.assertTrue(all(g['height']==60 and g['index'] not in (None,0xffffffff)
                                for g in call['glyphs']))
        labels = m.picker_state()[9]
        for index, width in ((0,94),(1,74)):
            self.assertEqual(m.run(TEXT_WIDTH,5,labels+8*index,0),width)
            self.assertEqual(m.run(TEXT_HEIGHT,5,labels+8*index),60)
        self.assertEqual(m.picker_state()[2:5],(0,1,1))
        self.assertEqual(m.mode,1)
        self.assertEqual(m.read(0x4d7043890,48),stock_before)

    @unittest.skipUnless(FIRMWARE.is_file(), 'requires supplied decoded segment05')
    def test_picker_font6_controls_preserve_uppercase_values_in_all_languages(self):
        m = NativeTextMachine(self.blob, self.syms)
        m.initialize()
        labels = m.picker_state()[9]
        for language in range(17):
            m.language = language
            for index, text, width in ((0,OFF,94),(1,ON,74)):
                with self.subTest(language=language, text=text):
                    m.glyph_calls.clear()
                    self.assertEqual(m.text(m.get(labels+8*index)),text)
                    self.assertEqual(m.run(TEXT_WIDTH,5,labels+8*index,0),width)
                    self.assertEqual(m.run(TEXT_HEIGHT,5,labels+8*index),60)
                    self.assertEqual(set(g['codepoint'] for g in m.glyph_calls),set(text[2:]))
                    self.assertTrue(all(g['height']==60 and g['index'] not in (None,0xffffffff)
                                        for g in m.glyph_calls))
        self.assertEqual(m.pua_calls, [])

    @unittest.skipUnless(FIRMWARE.is_file(), 'requires supplied decoded segment05')
    def test_original_stock_menu_playback_exit_routes_cancel_picker(self):
        m = NativeExitMachine(self.blob, self.syms)
        m.initialize(mode=1)
        for bits, category, target in ((64,0,0x4d33731e0),
                                      (32,0,0x4d31a3800),(32,3,0x4d31a38b0)):
            with self.subTest(bits=bits, category=category):
                m.category = category
                m.enter_picker()
                m.send(picker=True, key=False, dial=(-1,0))
                m.calls.clear()
                m.row10_accesses.clear()
                m.send(picker=True, changed=bits|31, press=bits|31,
                       repeat=31, dial=(1,0))
                self.assertEqual(m.calls,[('native_exit',target)])
                self.assertEqual(m.mode,1)
                self.assertEqual(m.picker_state()[2],0)
                self.assertEqual(m.get(PENDING,4),2)
                self.assertEqual(m.row10_accesses,[])

    @unittest.skipUnless(FIRMWARE.is_file(), 'requires supplied decoded segment05')
    def test_original_firmware_has_glyphs_for_every_displayed_string(self):
        m = NativeTextMachine(self.blob, self.syms)
        m.initialize()
        m.select(10, scroll=412)
        m.draw()
        self.assertEqual([(c['font'], c['text']) for c in m.text_calls], [(5, b'BF+')])
        m.enter_submenu()
        for mode in (0, 1):
            m.mode = mode
            m.run(RESIDENT+self.syms['menu_submenu_draw_wrapper'], SURFACE, PARAMS, 0)
        expected = {(5, b'BF+'): (54, b'BF+'), (3, b'BF+'): (41, b'BF+'),
                    (5, b'\x1b\x06Touch Focus Zoom'): (60, b'Touch Focus Zoom'),
                    (5, b'\x1b\x06MF Subject Detection'): (60, b'MF Subject Detection'),
                    (5, b'\x1b\x06Extra Aspect Ratios'): (60, b'Extra Aspect Ratios'),
                    (5, b'\x1b\x06Version'): (60, b'Version'),
                    (6, ON): (60, b'ON'), (6, OFF): (60, b'OFF'),
                    (6, b'1.0'): (60, b'1.0')}
        self.assertEqual({(c['font'], c['text']) for c in m.text_calls}, set(expected))
        for font, height, family in ((6, 60, 5), (5, 54, 4), (4, 52, 3), (3, 41, 2)):
            self.assertEqual(m.run(FONT_HEIGHT, font), height)
            self.assertEqual(m.run(FONT_FAMILY, height), family)
        for call in m.text_calls:
            height, visible = expected[(call['font'], call['text'])]
            self.assertEqual(call['pua'],[])
            with self.subTest(font=call['font'], text=call['text']):
                # Exact draw sequence proves neither control byte is emitted.
                drawn = [g['codepoint'] for g in call['glyphs']
                         if g['origin'] == GLYPH_FROM_DRAW]
                self.assertEqual(drawn, list(visible))
                for glyph in call['glyphs']:  # Includes alignment measurement.
                    self.assertEqual(glyph['height'], height)
                    self.assertNotIn(glyph['index'], (None, 0xffffffff))

    @unittest.skipUnless(FIRMWARE.is_file(), 'requires supplied decoded segment05')
    def test_original_row_values_use_uppercase_font6_and_full_size_version(self):
        m = NativeTextMachine(self.blob, self.syms)
        m.initialize()
        m.enter_submenu()
        rows = RESIDENT+self.syms['menu_submenu_rows']
        target = RESIDENT+self.syms['focus_target']
        for mode, subject in ((0,0),(0,1),(1,0),(1,1)):
            with self.subTest(mode=mode, subject=subject):
                m.mode=mode; m.put(target,subject,4)
                m.text_calls.clear()
                m.run(RESIDENT+self.syms['menu_submenu_draw_wrapper'],SURFACE,PARAMS,0)
                values = [c for c in m.text_calls if c['font']==6]
                expected = [ON if mode else OFF, ON if subject else OFF, OFF, b'1.0']
                self.assertEqual([c['text'] for c in values],expected)
                # Match each value's actual draw path independently, including
                # uppercase coverage and skipping the inline font control.
                for call in values[:3]:
                    self.assertEqual(call['pua'],[])
                    drawn = [g for g in call['glyphs'] if g['origin']==GLYPH_FROM_DRAW]
                    self.assertEqual([g['codepoint'] for g in drawn],list(call['text'][2:]))
                    self.assertTrue(all(g['height']==60 and g['index'] not in (None,0xffffffff)
                                        for g in call['glyphs']))
                version = values[3]
                self.assertEqual(version['pua'],[])
                drawn = [g for g in version['glyphs'] if g['origin']==GLYPH_FROM_DRAW]
                self.assertEqual([(g['codepoint'],g['height'],g['index']) for g in drawn],
                                 [(ord('1'),60,1),(ord('.'),60,18),(ord('0'),60,0)])
                self.assertEqual(m.run(FONT_FAMILY,60),5)
                for i, text in enumerate(expected):
                    self.assertEqual(m.get(rows+32*i+24,4),6)
                    pointer_slot = rows+32*i+16
                    width = m.run(TEXT_WIDTH,6,pointer_slot,0)
                    height = m.run(TEXT_HEIGHT,6,pointer_slot)
                    self.assertEqual(height,60)
                    self.assertEqual(width,57 if i==3 else 94 if text==OFF else 74)
                self.assertEqual((m.mode,m.get(target,4)),(mode,subject))

    @unittest.skipUnless(FIRMWARE.is_file(), 'requires supplied decoded segment05')
    def test_original_measurement_and_rendering_honor_inline_font(self):
        m = NativeTextMachine(self.blob, self.syms)
        for label, width, small_width in ((b'Touch Focus Zoom', 406, 316),
                                          (b'MF Subject Detection', 466, 364),
                                          (b'Version', 159, 123)):
            # Font4 remains a control: it covers lowercase but has the wrong
            # smaller/bolder appearance. BF+ ASCII values now use font6 too.
            for font, text, height, expected_width in ((6, label, 60, width),
                    (5, b'\x1b\x06'+label, 60, width), (4, label, 52, small_width)):
                with self.subTest(font=font, text=text):
                    m.uc.mem_write(STACK+0x5000, text+b'\0')
                    m.uc.mem_write(PARAMS, struct.pack('<4HQ8xIIH6x', 48, 142, 916, 90,
                                                      STACK+0x5000, 1, font, 4))
                    metrics = []
                    for routine, args in ((TEXT_WIDTH, (font, PARAMS+8, 0)),
                                          (TEXT_HEIGHT, (font, PARAMS+8)),
                                          (TEXT_DRAW, (SURFACE, PARAMS))):
                        m.text_calls.clear()
                        m.glyph_calls.clear()
                        metrics.append(m.run(routine, *args))
                        self.assertEqual([g['codepoint'] for g in m.glyph_calls], list(label))
                        for glyph in m.glyph_calls:
                            self.assertEqual(glyph['height'], height)
                            self.assertNotIn(glyph['index'], (None, 0xffffffff))
                    self.assertEqual(metrics, [expected_width, height, expected_width])

    @unittest.skipUnless(FIRMWARE.is_file(), 'requires supplied decoded segment05')
    def test_original_glyph_lookup_rejects_old_mixed_case_labels(self):
        m = NativeGlyphMachine(self.blob, self.syms)
        old_characters = set('Touch focus zoomVersion')
        missing = {character for character in old_characters
                   if m.glyph(5, character) == 0xffffffff}
        self.assertEqual(missing, set('ouchfszerin'))
        # Negative control: the original labels really do trigger missing
        # glyphs in font5, while the old font4 alternative covers lowercase.
        for character in sorted(old_characters):
            with self.subTest(character=character):
                self.assertNotEqual(m.glyph(4, character), 0xffffffff)
        for character, index in (('T', 59), ('V', 61), ('m', 48)):
            self.assertEqual(m.glyph(5, character), index)

    @unittest.skipUnless(FIRMWARE.is_file(), 'requires supplied decoded segment05')
    def test_original_scene_engine_push_pop_and_parent_resume(self):
        m = NativeSceneMachine(self.blob, self.syms)
        m.initialize()
        parent = RESIDENT+self.syms['menu_parent_scene']
        child = RESIDENT+self.syms['menu_submenu_scene']
        dispatch = STACK+0x5200
        m.uc.mem_write(SCENES+4*32, m.read(parent, 32))
        m.put(DEPTH, 4, 4)
        m.select(10, scroll=412)
        m.send(changed=1, touch=1, press=1)
        self.assertEqual(m.get(PENDING, 4), 5)
        self.assertEqual(m.read(PENDING_SCENE, 32), m.read(child, 32))
        m.run(0x4d3323ca0, dispatch)
        self.assertEqual((m.get(DEPTH, 4), m.get(PENDING, 4)), (5, 12))
        self.assertEqual(m.read(SCENES+5*32, 32), m.read(child, 32))
        self.assertEqual(struct.unpack('<2Q', m.read(dispatch, 16)),
                         (RESIDENT+self.syms['menu_submenu_input_wrapper'], 0))
        m.send(submenu=True, changed=1, touch=1, press=1)
        self.assertEqual(m.mode, 1)
        self.assertEqual(m.get(PENDING, 4), 6)
        picker = RESIDENT+self.syms['menu_picker_scene']
        self.assertEqual(m.read(PENDING_SCENE, 32), m.read(picker, 32))
        m.run(0x4d3323ca0, dispatch)
        self.assertEqual((m.get(DEPTH,4),m.get(PENDING,4)),(6,12))
        self.assertEqual(m.get(RESIDENT+self.syms['menu_view']+4,4),0)
        self.assertEqual(m.get(dispatch),RESIDENT+self.syms['menu_picker_input_wrapper'])
        # Select OFF tentatively, cancel, and prove the resumed BF+ still says ON.
        m.send(picker=True, key=False, dial=(-1,0))
        self.assertEqual(m.mode,1)
        m.send(picker=True, changed=2, press=2)
        m.calls.clear()
        m.run(0x4d3323ca0, dispatch)
        self.assertEqual((m.get(DEPTH,4),m.get(PENDING,4)),(5,12))
        self.assertEqual(m.mode,1)
        self.assertEqual(m.get(RESIDENT+self.syms['menu_view']+4,4),1)
        self.assertEqual(m.get(RESIDENT+self.syms['menu_picker_active'],4),0)
        rows = [c for c in m.calls if c[0]=='paint']
        self.assertEqual([m.text(c[3][5]) for c in rows],[ON,OFF,OFF,b'1.0'])
        # Reopen, choose OFF and confirm; resume repaints the new private value.
        m.send(submenu=True, changed=1, press=1)
        m.run(0x4d3323ca0, dispatch)
        m.send(picker=True, changed=16, press=16)
        m.send(picker=True, changed=4, press=4)
        self.assertEqual(m.mode, 0)
        m.calls.clear()
        m.run(0x4d3323ca0, dispatch)
        self.assertEqual((m.get(DEPTH,4),m.get(PENDING,4)),(5,12))
        self.assertEqual(m.get(dispatch),RESIDENT+self.syms['menu_submenu_input_wrapper'])
        rows = [c for c in m.calls if c[0]=='paint']
        self.assertEqual([m.text(c[3][5]) for c in rows],[OFF,OFF,OFF,b'1.0'])
        # The second option has an independent value and retains its row on
        # native resume. Cancel, then confirm, while Touch focus zoom is OFF.
        target = RESIDENT+self.syms['focus_target']
        view = RESIDENT+self.syms['menu_view']
        m.send(submenu=True, changed=8, press=8)
        self.assertEqual(m.get(view+16,4),1)
        for confirm in (False,True):
            m.send(submenu=True, changed=1, press=1)
            m.run(0x4d3323ca0, dispatch)
            self.assertEqual(m.picker_state()[:5],(232,2,0,255,0))
            m.send(picker=True, changed=8, press=8)
            self.assertEqual((m.mode,m.get(target,4)),(0,0))
            m.send(picker=True, changed=1 if confirm else 2, press=1 if confirm else 2)
            m.calls.clear()
            m.run(0x4d3323ca0, dispatch)
            self.assertEqual(m.get(view+16,4),1)
            self.assertEqual((m.mode,m.get(target,4)),(0,int(confirm)))
            rows = [c for c in m.calls if c[0]=='paint']
            self.assertEqual([m.text(c[3][5]) for c in rows],
                             [OFF,ON if confirm else OFF,OFF,b'1.0'])
        m.send(submenu=True, changed=2, touch=2, press=2)
        self.assertEqual(m.get(PENDING, 4), 4)
        self.assertEqual(m.read(PENDING_SCENE, 32), m.read(parent, 32))
        m.run(0x4d3323ca0, dispatch)
        self.assertEqual((m.get(DEPTH, 4), m.get(PENDING, 4)), (4, 12))
        self.assertEqual((m.get(CURRENT, 1), m.get(PREVIOUS, 1)), (10, 10))
        self.assertEqual((m.get(SCROLL, 2), m.get(HIGHLIGHT, 2)), (412, 592))
        self.assertEqual(struct.unpack('<2Q', m.read(dispatch, 16)),
                         (RESIDENT+self.syms['menu_input_wrapper'], 0x4d3372c30))
        self.assertEqual(m.get(RESIDENT+self.syms['menu_view']+4, 4), 0)
        self.assertEqual(m.get(RESIDENT+self.syms['menu_view']+12, 4), 0)

    def test_subject_option_picker_is_independent_and_cancellable(self):
        # This coverage runs even without the local firmware fixture.
        m=self.m
        target=RESIDENT+self.syms['focus_target']
        view=RESIDENT+self.syms['menu_view']
        for confirm in (False,True):
            m.mode=0; m.put(target,0,4)
            m.enter_submenu()
            m.send(submenu=True,changed=8,press=8)
            m.send(submenu=True,changed=1,press=1)
            m.run(RESIDENT+self.syms['menu_submenu_leave'])
            m.run(RESIDENT+self.syms['menu_picker_enter'],STACK+0x5000,STACK+0x5100,0)
            self.assertEqual(m.picker_state()[:5],(232,2,0,255,0))
            m.put(DEPTH,6,4); m.put(PENDING,12,4)
            m.send(picker=True,changed=8,press=8)
            self.assertEqual(m.get(target,4),0)
            m.send(picker=True,changed=1 if confirm else 2,press=1 if confirm else 2)
            self.assertEqual((m.mode,m.get(target,4)),(0,int(confirm)))
            m.run(RESIDENT+self.syms['menu_submenu_resume'],STACK+0x5000,STACK+0x5100,0)
            self.assertEqual(m.get(view+16,4),1)






    def test_readonly_version_rejects_stale_picker_entry(self):
        m=self.m
        m.enter_picker(row=2)
        m.put(RESIDENT+self.syms['menu_view']+16,3,4)
        m.calls.clear()
        m.run(RESIDENT+self.syms['menu_picker_enter'],STACK+0x5000,STACK+0x5100,0)
        self.assertEqual(m.read(STACK+0x5100,16),bytes(16))
        self.assertEqual(m.get(RESIDENT+self.syms['menu_picker_active'],4),0)
        m.send(picker=True,changed=1,press=1)
        self.assertEqual(m.calls,[])
        self.assertEqual(m.aspect_writes,[])



    def test_extra_aspects_defaults_off_and_uses_two_native_boolean_choices(self):
        m=self.m; enabled=RESIDENT+self.syms['aspect_extra_enabled']
        self.assertEqual(m.get(enabled,4),0)
        for initial in (0,1):
            m.put(enabled,initial,4)
            m.enter_picker(row=2)
            p=m.picker_state()
            self.assertEqual(p[:5],(322,2,initial,255,initial))
            self.assertEqual(p[7],2)
            self.assertEqual([m.text(m.get(p[9]+8*i)) for i in range(2)],[OFF,ON])
            m.send(picker=True,key=False,dial=(-1 if initial else 1,0))
            self.assertEqual(m.get(enabled,4),initial)
            m.send(picker=True,changed=2,press=2)
            self.assertEqual(m.get(enabled,4),initial)

    def test_extra_aspect_confirmation_preserves_touch_and_mf_settings(self):
        m=self.m; enabled=RESIDENT+self.syms['aspect_extra_enabled']
        target=RESIDENT+self.syms['focus_target']
        for initial in (0,1):
            m.put(enabled,initial,4); m.mode=1; m.put(target,1,4)
            m.enter_picker(row=2)
            m.send(picker=True,key=False,dial=(-1 if initial else 1,0))
            m.send(picker=True,changed=1,press=1)
            self.assertEqual(m.get(enabled,4),1-initial)
            self.assertEqual((m.mode,m.get(target,4)),(1,1))
            self.assertEqual(m.aspect,0)

    def test_lcd_packets_do_not_scroll_open_or_select_menus(self):
        m=self.m
        packets=[struct.pack('<10H',800,400,800,400,800,100,0,0,flags,0)
                 for flags in (1,0x100,0x200,0x400)]
        for packet in packets:
            m.select(9,scroll=322)
            m.send(key=False,lcd=packet)
            self.assertEqual((m.get(CURRENT,1),m.get(SCROLL,2)),(9,322))
            self.assertFalse(any(c[0]=='push' for c in m.calls))
            m.enter_submenu();before=m.get(RESIDENT+self.syms['menu_view']+16,4)
            m.send(submenu=True,key=False,lcd=packet)
            self.assertEqual(m.get(RESIDENT+self.syms['menu_view']+16,4),before)
            self.assertFalse(any(c[0]=='push' for c in m.calls))
            m.enter_picker();before=m.picker_state()
            m.send(picker=True,key=False,lcd=packet)
            self.assertEqual(m.picker_state(),before)
            self.assertFalse(any(c[0]=='pop' for c in m.calls))

    def test_production_has_no_rotation_touch_or_focus_guide_runtime(self):
        self.assertEqual(self.syms['__scratch_size'],0)
        for name in self.syms:
            self.assertFalse(name.startswith(('ui_', 'native_touch_', 'orientation_', 'global_orientation_', 'focus_guide')))
        for name in ('ui','menu_orientation','menu_touch','menu_portrait','menu_parent_update_wrapper'):
            self.assertNotIn(name,self.syms)
        self.assertNotIn(b'Auto Rotate UI',self.blob)
        self.assertIn(b'Extra Aspect Ratios',self.blob)



if __name__ == '__main__':
    unittest.main()
