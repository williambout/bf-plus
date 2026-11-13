"""Host deployment boundaries: no second upload, fresh completion, save result."""
import contextlib
import io
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import bfplus_cli as cli
import bfplus_loader as loader
from bfplus.loader_build import build as build_loader

BUF=0x447579000
STAGE=BUF+0xc000

class Camera:
    def __init__(self, symbols, *, bad_upload=False, stale=False, storage_rc=0):
        self.symbols=symbols
        self.bad_upload,self.stale,self.storage_rc=bad_upload,stale,storage_rc
        self.writes=[]
        self.payload=None
        self.triggered=False
    def qword(self,address):
        return {cli.CALLBACK_SLOT:cli.ORIGINAL_CALLBACK,cli.L2_SLOT:cli.L2_RO}[address]
    def write(self,address,data):
        self.writes.append((address,bytes(data)))
        if address==STAGE: self.payload=bytearray(data)
        elif address==cli.CALLBACK_SLOT:
            self.triggered=True
            offset=self.symbols['control']
            nonce=struct.unpack_from('<Q',self.payload,offset)[0]
            struct.pack_into('<Q',self.payload,offset+8,nonce if not self.stale else nonce^1)
            struct.pack_into('<Q',self.payload,offset+24,0x447702000)
            struct.pack_into('<I',self.payload,offset+72,self.storage_rc)
        else: raise AssertionError(address)
    def read(self,address,length):
        if address==STAGE and self.bad_upload: return bytes(length)
        start=address-STAGE
        return bytes(self.payload[start:start+length])

class CLITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Archived legacy artifact fixture: never rebuild it from current sources.
        cls.blob=bytes(0x3f40)
        cls.symbols={'control':0x200,'launch':0,'state':0x4000,'focus_target':0x300}
    def run_execute(self,p):
        with contextlib.redirect_stdout(io.StringIO()):
            return cli.execute(p,self.blob,self.symbols,BUF)
    def test_success_uses_exactly_one_upload_and_one_trigger(self):
        p=Camera(self.symbols)
        result=self.run_execute(p)
        self.assertEqual([a for a,_ in p.writes],[STAGE,cli.CALLBACK_SLOT])
        self.assertNotEqual(result['nonce'],0)
        self.assertEqual(result['resident'],0x447702000)
    def test_large_upload_is_verified_with_bounded_reads_before_trigger(self):
        p=Camera(self.symbols)
        read=p.read
        p.read=Mock(side_effect=read)
        self.run_execute(p)
        upload_reads=[args.args for args in p.read.call_args_list if args.args[1]>80]
        self.assertTrue(all(n<=0x1000 for _,n in upload_reads))
        self.assertEqual(sum(n for _,n in upload_reads),len(self.blob))
        self.assertEqual(len(p.writes),2)
    def test_bad_readback_never_triggers_or_rewrites(self):
        p=Camera(self.symbols,bad_upload=True)
        with patch.object(cli.time,'monotonic',side_effect=[0,10]):
            with self.assertRaisesRegex(RuntimeError,'readback failed'):
                self.run_execute(p)
        self.assertEqual(len(p.writes),1)
        self.assertFalse(p.triggered)
    def test_restored_callback_without_fresh_nonce_is_not_success(self):
        p=Camera(self.symbols,stale=True)
        with patch.object(cli.time,'monotonic',side_effect=[0,0,16]):
            with self.assertRaisesRegex(RuntimeError,'No completion nonce'):
                self.run_execute(p)
        self.assertEqual(len(p.writes),2)
    def test_storage_failure_is_not_reported_as_success(self):
        p=Camera(self.symbols,storage_rc=0xffffffff)
        with self.assertRaisesRegex(RuntimeError,'storage writer reported 0xffffffff'):
            self.run_execute(p)
        self.assertEqual(len(p.writes),2)

    def test_legacy_staging_cap_remains_16k(self):
        p=Camera(self.symbols)
        with self.assertRaisesRegex(RuntimeError,'too large'):
            cli.execute(p,bytes(0x4001),self.symbols,BUF)
        self.assertEqual(p.writes,[])

    def test_read_chunks_stops_on_bad_subread_without_retry(self):
        for failure in ('short','oversized','exception'):
            with self.subTest(failure=failure):
                p=Mock()
                def read(address,size):
                    self.assertLessEqual(size,0x1000)
                    if address==STAGE+0x1000:
                        if failure=='exception': raise OSError('read transport failed')
                        return bytes(size-1 if failure=='short' else size+1)
                    return bytes(size)
                p.read.side_effect=read
                with self.assertRaises(OSError if failure=='exception' else RuntimeError):
                    cli.read_chunks(p,STAGE,0x2345)
                self.assertEqual([call.args for call in p.read.call_args_list],
                                 [(STAGE,0x1000),(STAGE+0x1000,0x1000)])
                p.write.assert_not_called()

    def test_read_chunks_empty_and_negative_size_submit_nothing(self):
        p=Mock()
        self.assertEqual(cli.read_chunks(p,STAGE,0),b'')
        with self.assertRaisesRegex(RuntimeError,'read size'):
            cli.read_chunks(p,STAGE,-1)
        p.read.assert_not_called()
        p.write.assert_not_called()





    def test_new_hook_set_excludes_rotation_and_lcd_menu_adapters(self):
        names={name for _,_,name in cli.PATCHES}
        self.assertFalse(any(name.startswith(('ui_', 'native_touch_')) for name in names))
        self.assertNotIn('menu_parent_update_wrapper', names)
        self.assertNotIn(0x4d3320830, {a for a,_,_,_ in cli.CODE_PATCHES})
        self.assertFalse(hasattr(cli, 'ui_code_patches'))

    def test_expected_originals_match_local_firmware(self):
        path=cli.ROOT/'decoded-V104/rtos-alt.bin'
        if not path.exists(): self.skipTest('Optional local firmware not available')
        with path.open('rb') as f:
            for address,original,_,size in cli.CODE_PATCHES:
                f.seek(address-0x4d3000000)
                self.assertEqual(int.from_bytes(f.read(size),'little'),original,hex(address))

    def test_native_aspect_hooks_match_shared_macro_snapshot(self):
        source=(cli.ROOT/'bfplus/aspect_ratio.h').read_text()
        with patch.object(Path,'read_text',side_effect=AssertionError('must use snapshot')):
            entries=cli.native_aspect_code_patches(source)
        self.assertEqual(entries,cli.NATIVE_ASPECT_CODE_PATCHES)
        self.assertEqual(len(entries),9)
        self.assertEqual({a for a,_,_,_ in entries},
            {0x4d3394c10,0x4d33a3200,0x4d33a3644,0x4d33a3fb0,
             0x4d33a403c,0x4d33a41a0,0x4d33a2aa0,0x4d33a3700,0x4d336a134})
        with self.assertRaisesRegex(ValueError,'Unsupported'):
            cli.native_aspect_code_patches(source.replace('X(0x4d3394c10ULL)','X(UNKNOWN)'))
        with self.assertRaisesRegex(ValueError,'Duplicate native'):
            cli.native_aspect_code_patches(source.replace('X(0x4d33a3700ULL)','X(0x4d3394c10ULL)'))

    def test_status_reads_optional_target_state_and_accepts_old_installations(self):
        for supported in (False,True):
            with self.subTest(supported=supported):
                p=Mock()
                resident=0x447702000
                state=resident+self.symbols['state']
                target=resident+self.symbols['focus_target']
                symbols=self.symbols if supported else {'state':self.symbols['state']}
                record={'resident':resident,'state_address':state,'symbols':symbols}
                target_bytes=struct.pack('<4I4H2I',1,0,3,5,512,341,400,250,2,1)
                p.read.side_effect=lambda address,size: target_bytes if address==target else bytes(size)
                with patch.object(cli,'preflight',return_value=BUF), patch.object(cli,'installation',return_value=record):
                    result=cli.status(p)
                self.assertEqual('mf_subject_detection' in result,supported)
                if supported:
                    self.assertEqual(result['mf_subject_detection'],{
                        'enabled':True,'position_owned':False,'source':'legacy_candidate_2','attempts':5,
                        'last_position':(400,250),'misses':2,'unstable_snapshots':1})
                else:
                    self.assertNotIn(((target,32),{}),p.read.call_args_list)

    def test_status_omits_ui_fields_for_legacy_or_incomplete_saved_abi(self):
        for extra in ({},{'menu_orientation':0x4200},
                      {'menu_orientation':0x4200,'ui':0x4300,'__ui_displayed_offset':100}):
            with self.subTest(symbols=extra):
                p=Mock(); p.read.side_effect=lambda address,size: bytes(size)
                record={'resident':0x447702000,'state_address':0x447706000,
                        'symbols':{'state':0x4000,'__bss_start':0x4000,'__end':0x5000,**extra}}
                with patch.object(cli,'preflight',return_value=BUF), \
                     patch.object(cli,'installation',return_value=record), \
                     patch.object(cli,'read_manifest',return_value=None):
                    result=cli.status(p)
                self.assertNotIn('auto_rotate_ui',result)
                self.assertFalse(any(0x447706200<=call.args[0]<0x447707000
                                     for call in p.read.call_args_list))
                p.write.assert_not_called()

HOOK, STOCK, RESIDENT, OWNER = 0x4d3398860,0x4d3398940,0x447702000,0x447701123
CODE=0x4d3321270

class SegmentedCamera:
    """Protocol/state test double; compiled loader execution has its own suite."""
    def __init__(self,artifact,symbols):
        self.artifact,self.symbols=artifact,symbols
        self.memory={}; self.writes=[]; self.reads=[]; self.phases=[]
        self._io_lock=threading.RLock(); self._lock_file=object()
        self.fail_chunk=False; self.fail_writer=False
        self.corrupt_on_commit=False; self.control=None
        for address,value,size in ((cli.CALLBACK_SLOT,cli.ORIGINAL_CALLBACK,8),
            (cli.L2_SLOT,cli.L2_RO,8),(cli.UI_L2_SLOT,cli.UI_L2_RO,8),
            (cli.CACHE_SLOT,BUF,8),(0x4d7301a00,cli.BASE,8),
            (0x4d703469c,12,4),(0x4d70346a0,2,4),(0x4d70346a4,12,4),(HOOK,STOCK,8),
            (CODE,0x12345678,4),(0x4d7303098,STOCK,8)):
            self.put(address,value.to_bytes(size,'little'))
        self.put(0x4d7301c00,struct.pack('<4Q',0x4d3398930,0x4d33988b0,0x4d3393730,0x4d33936a0))
    def _require_open(self): pass
    def put(self,address,data): self.memory.update((address+i,b) for i,b in enumerate(data))
    def read(self,address,size):
        assert 0<size<=0x1000
        self.reads.append((address,size))
        return bytes(self.memory.get(address+i,0) for i in range(size))
    def qword(self,address): return int.from_bytes(self.read(address,8),'little')
    def write(self,address,data):
        from dataclasses import replace
        assert self._io_lock._is_owned() and 0<len(data)<=0x1000
        saved=json.loads(cli.MANIFEST.read_text())
        self.phases.append(saved['phase'])
        self.writes.append((address,bytes(data)))
        if RESIDENT<=address<RESIDENT+0x10000 and self.fail_chunk:
            raise OSError('uncertain chunk failure')
        self.put(address,data)
        if address!=cli.CALLBACK_SLOT: return
        offset=self.artifact.symbols['loader_control']
        c=loader.Control.unpack(self.read(STAGE+offset,256))
        if c.command==loader.PREPARE:
            assert c.resident==0
            c=replace(c,owner=OWNER,resident=RESIDENT,guard=RESIDENT-256,
                      allocation_size=256+4095+c.memory_size+c.scratch_size,phase=loader.PREPARING)
        elif c.command==loader.COMMIT:
            # Native CRC/hash access is local memory, not a host READ transaction.
            image=bytes(self.memory.get(RESIDENT+i,0) for i in range(c.image_size))
            assert hashlib.sha256(image).digest()==c.image_sha256
            self.put(RESIDENT+self.symbols['state'],struct.pack('<QIIQQ',cli.MAGIC,1,c.mode,c.identity_nonce,c.owner))
            self.put(HOOK,struct.pack('<Q',RESIDENT+self.symbols['live_wrapper']))
            self.put(CODE,struct.pack('<I',0x87654321))
            # Real installation mutates initialized configuration legitimately.
            self.put(RESIDENT+self.symbols['focus_target'],struct.pack('<I',1))
            if self.corrupt_on_commit: self.put(RESIDENT+0x120,b'!')
            c=replace(c,phase=loader.COMMITTED)
        else:
            assert c.command==loader.REMOVE and c.resident==RESIDENT
            self.put(HOOK,struct.pack('<Q',STOCK)); self.put(CODE,struct.pack('<I',0x12345678))
            c=replace(c,phase=loader.REMOVED)
        c=replace(c,done=c.request_nonce,el=4,
                  storage_rc=0xffffffff if self.fail_writer and c.command==loader.COMMIT else 0)
        self.put(c.guard,loader.GUARD.pack(loader.GUARD_MAGIC,loader.ABI,c.phase,c.identity_nonce,
            c.owner,c.resident,c.image_size,c.memory_size,c.scratch_size,c.entry_offset,
            c.image_crc32,c.mode,c.image_sha256,c.allocation_size,c.request_nonce,0,*([0]*31)))
        self.put(cli.CALLBACK_SLOT,struct.pack('<Q',cli.ORIGINAL_CALLBACK))
        self.put(STAGE+offset,c.pack()); self.control=c

class SegmentedCLITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loader_blob,cls.loader_symbols=build_loader()
        cls.artifact=loader.LoaderArtifact(cls.loader_blob,cls.loader_symbols)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.work=Path(self.tmp.name)
        self.symbols={'__start':0,'__image_end':0x8040,'__end':0x9200,
                      '__bss_start':0x8040,'__bss_end':0x9200,'__scratch_size':0x4a9800,
                      'resident_entry':0x100,'state':0x8040,'focus_target':0x8000,
                      'live_wrapper':0x200,'launch':0,'bootstrap':0x100,'control':0x8080}
        self.blob=self.artifact.image[:256]+bytes((i*17)&255 for i in range(0x7f40))
        self.layout={'image_size':len(self.blob),'memory_size':0x9200,'bss_start':0x8040,
            'bss_end':0x9200,'alignment':4096,'scratch_size':0x4a9800,'scratch_alignment':64,
            'entry_offset':0x100,'immutable_ranges':[[0,0x7800]],'executable_ranges':[[0,0x7800]]}
        self.firmware=self.work/'firmware.bin'; self.firmware.write_bytes(b'test package')
        for name,value in {'WORK':self.work,'MANIFEST':self.work/'installation.json',
            'PACKAGE_SHA256':hashlib.sha256(b'test package').hexdigest(),
            'PATCHES':((HOOK,STOCK,'live_wrapper'),),'CODE_PATCHES':((CODE,0x12345678,0x87654321,4),),
            'FINGERPRINTS':{},'ASPECT_FINGERPRINTS':{}}.items():
            self.patch(name,value)
        self.builder=self.patch('build',Mock(return_value=(self.blob,self.symbols)))
        self.loader_builder=self.patch('build_loader',Mock(return_value=(self.loader_blob,self.loader_symbols)))
        self.layout_mock=self.patch('resident_layout',Mock(return_value=self.layout))
        self.p=SegmentedCamera(self.artifact,self.symbols)

    def patch(self,name,value):
        p=patch.object(cli,name,value); p.start(); self.addCleanup(p.stop); return value
    def install(self,**kwargs):
        with contextlib.redirect_stdout(io.StringIO()): cli.install(self.p,self.firmware,**kwargs)
        return cli.read_manifest()
    def remove(self):
        with contextlib.redirect_stdout(io.StringIO()): cli.remove(self.p)
        return cli.read_manifest()

    def test_segmented_install_archives_immutable_loader_and_resident_then_exact_remove(self):
        m=self.install(enabled=True,subject_detection=True)
        self.assertEqual(m['phase'],'committed')
        self.assertEqual(m['format'],loader.FORMAT)
        self.assertEqual(m['nonce'],self.p.control.identity_nonce)
        self.assertNotEqual(m['nonce'],self.p.control.request_nonce)
        self.assertEqual(m['layout']['scratch_size'],0x4a9800)
        self.assertEqual((self.work/m['loader']['image']).read_bytes(),self.loader_blob)
        self.assertEqual(self.p.phases,['preparing']*2+['loading']*9+['committing']*2)
        self.assertEqual([len(b) for a,b in self.p.writes if RESIDENT<=a<RESIDENT+0x10000],
                         [0x1000]*8+[0x40])
        self.assertEqual(cli.installation(self.p)['resident'],RESIDENT)
        before=len(self.p.writes)
        self.p.reads.clear()
        result=cli.status(self.p)
        self.assertTrue(result['installed'])
        self.assertEqual(result['mode'],1)
        self.assertTrue(result['mf_subject_detection']['enabled'])
        self.assertEqual([(a,n) for a,n in self.p.reads if RESIDENT<=a<RESIDENT+0x7800],
                         [(RESIDENT+i,min(0x1000,0x7800-i)) for i in range(0,0x7800,0x1000)])
        self.assertEqual(len(self.p.writes),before)
        self.builder.side_effect=AssertionError('must not rebuild resident for removal')
        self.loader_builder.side_effect=AssertionError('must not rebuild loader for removal')
        removed=self.remove()
        self.assertEqual(removed['phase'],'removed')
        self.assertEqual([a for a,_ in self.p.writes[before:]],[STAGE,cli.CALLBACK_SLOT])
        self.assertIsNone(cli.installation(self.p))
        self.assertEqual(removed['loader'],m['loader'])

    def test_interrupted_loading_is_recorded_uncertain_and_cannot_restart(self):
        self.p.fail_chunk=True
        with self.assertRaisesRegex(OSError,'chunk'): self.install()
        self.assertEqual(cli.read_manifest()['phase'],'uncertain')
        before=len(self.p.writes)
        self.p.fail_chunk=False
        with self.assertRaisesRegex(RuntimeError,'incomplete/uncertain'): self.install()
        self.assertEqual(len(self.p.writes),before)
        self.assertEqual(cli.status(self.p)['outcome_uncertain'],True)
        self.assertFalse(cli.status(self.p)['installed'])

    def test_writer_failure_after_commit_remains_inspectable_but_not_mutable(self):
        self.p.fail_writer=True
        with self.assertRaisesRegex(RuntimeError,'Storage writer'): self.install()
        m=cli.read_manifest()
        self.assertEqual((m['phase'],m['loader_record']['control']['phase']),('uncertain',loader.COMMITTED))
        self.assertTrue(cli.status(self.p)['installed'])
        before=len(self.p.writes)
        for operation in (lambda:cli.remove(self.p),lambda:cli.set_mode(self.p,False)):
            with self.assertRaisesRegex(RuntimeError,'uncertain'): operation()
        self.assertEqual(len(self.p.writes),before)

    def test_postcommit_code_corruption_records_uncertainty(self):
        self.p.corrupt_on_commit=True
        with self.assertRaisesRegex(RuntimeError,'resident code differs'): self.install()
        self.assertEqual(cli.read_manifest()['phase'],'uncertain')
        self.assertEqual(len(self.p.writes),13)

    def test_modified_archives_or_resident_code_refuse_removal_before_writes(self):
        m=self.install(); before=len(self.p.writes)
        for kind in ('loader','resident','code'):
            with self.subTest(kind=kind):
                if kind=='code':
                    original=self.p.read(RESIDENT+0x100,1)
                    self.p.put(RESIDENT+0x100,b'!')
                else:
                    filename=m['loader']['image'] if kind=='loader' else m['image']
                    original=(self.work/filename).read_bytes()
                    (self.work/filename).write_bytes(b'changed')
                with self.assertRaisesRegex(RuntimeError,'hash mismatch|code differs'): self.remove()
                self.assertEqual(len(self.p.writes),before)
                if kind=='code': self.p.put(RESIDENT+0x100,original)
                else: (self.work/filename).write_bytes(original)

    def test_durable_manifest_failure_prevents_first_camera_write(self):
        with patch.object(cli,'save_manifest',side_effect=OSError('disk failed')):
            with self.assertRaisesRegex(OSError,'disk failed'): self.install()
        self.assertEqual(self.p.writes,[])

    def test_native_node_replacement_pending_refuses_install_and_remove(self):
        self.p.put(0x4d703469c,struct.pack('<I',1))
        with self.assertRaisesRegex(RuntimeError,'idle still shooting'): self.install()
        self.assertEqual(self.p.writes,[])
        self.builder.assert_not_called()
        self.p.put(0x4d703469c,struct.pack('<I',12))
        self.install()
        before=len(self.p.writes); saved=cli.MANIFEST.read_bytes()
        self.p.put(0x4d703469c,struct.pack('<I',0))
        with self.assertRaisesRegex(RuntimeError,'idle still shooting'): self.remove()
        self.assertEqual(len(self.p.writes),before)
        self.assertEqual(cli.MANIFEST.read_bytes(),saved)

    def test_immutable_archive_is_not_overwritten_and_paths_are_confined(self):
        name,digest=cli.archive_image('loader',b'original')
        (self.work/name).write_bytes(b'corrupted')
        with self.assertRaisesRegex(RuntimeError,'immutable artifact differs'):
            cli.archive_image('loader',b'original')
        self.assertEqual((self.work/name).read_bytes(),b'corrupted')
        with self.assertRaisesRegex(RuntimeError,'artifact name'): cli.archived_image('../elsewhere',digest)

    def test_stale_guard_and_state_owner_refuse_removal_without_write(self):
        m=self.install(); before=len(self.p.writes)
        self.p.put(RESIDENT-256+16,struct.pack('<Q',m['nonce']^1))
        with self.assertRaisesRegex(RuntimeError,'Guard identity'): self.remove()
        with self.assertRaisesRegex(RuntimeError,'Guard identity'): cli.set_mode(self.p,True)
        self.assertEqual(len(self.p.writes),before)
        self.p.put(RESIDENT+self.symbols['state']+24,struct.pack('<Q',OWNER+1))
        with self.assertRaisesRegex(RuntimeError,'owner/identity'): self.remove()
        self.assertEqual(len(self.p.writes),before)

    def with_ui(self):
        self.symbols.update(ui=0x9140,__ui_removing_offset=0,__ui_displayed_offset=4,
                            __ui_ready_offset=8,__ui_frame_offset=12)
        self.install()
        self.p.put(RESIDENT+0x9140,struct.pack('<4I',0,1,0,3))

    def test_status_reports_ui_off_portrait_and_draining_without_writes(self):
        self.symbols['menu_orientation']=0x9100
        self.with_ui()
        before=len(self.p.writes)
        for enabled,raw,ready,frame,removing,phase in (
            (0,0,1,0,0,'committed'),(1,1,1,0,0,'committed'),
            (1,3,1,0,0,'committed'),(1,1,0,3,1,'draining'),(1,0,1,0,1,'drained')):
            with self.subTest(raw=raw,phase=phase,enabled=enabled):
                self.p.put(RESIDENT+0x9114,struct.pack('<I',enabled))
                self.p.put(RESIDENT+0x9140,struct.pack('<4I',removing,raw,ready,frame))
                m=cli.read_manifest(); m['phase']=phase; cli.save_manifest(m)
                manifest_bytes=cli.MANIFEST.read_bytes()
                result=cli.status(self.p)
                self.assertEqual(result['auto_rotate_ui'],{
                    'enabled':bool(enabled),'displayed_raw':raw,
                    'displayed_orientation':'portrait' if raw else 'landscape',
                    'input_ready':bool(ready),'frame_mask':frame,'removing':bool(removing)})
                self.assertEqual(result['phase'],phase)
                self.assertEqual(len(self.p.writes),before)
                self.assertEqual(cli.MANIFEST.read_bytes(),manifest_bytes)

    def test_status_rejects_invalid_saved_ui_offset_before_reading_it(self):
        self.symbols['menu_orientation']=0x9100
        self.with_ui()
        m=cli.read_manifest(); m['symbols']['__ui_displayed_offset']=0x10000
        cli.save_manifest(m)
        before=len(self.p.writes); self.p.reads=[]
        with self.assertRaisesRegex(RuntimeError,'status fields are outside resident BSS'):
            cli.status(self.p)
        self.assertEqual(len(self.p.writes),before)
        self.assertNotIn((RESIDENT+0x19140,4),self.p.reads)

    def test_ui_removal_drains_before_loader_and_preserves_user_option(self):
        self.with_ui(); before=len(self.p.writes)
        write=self.p.write
        def drain(address,data):
            write(address,data)
            if address==RESIDENT+0x9140:
                self.assertEqual(cli.read_manifest()['phase'],'draining')
                self.p.put(address+4,struct.pack('<3I',0,1,0))
        self.p.write=drain
        m=self.remove()
        self.assertEqual([a for a,_ in self.p.writes[before:]],
                         [RESIDENT+0x9140,STAGE,cli.CALLBACK_SLOT])
        self.assertEqual((m['phase'],m['ui_drain']['phase']),('removed','drained'))
        self.assertEqual(self.p.qword(RESIDENT+0x9140)&0xffffffff,1)

    def test_ui_drain_timeout_records_uncertainty_without_remover_or_cleanup_write(self):
        self.with_ui(); before=len(self.p.writes)
        with patch.object(cli.time,'monotonic',side_effect=[0,16]):
            with self.assertRaisesRegex(RuntimeError,'UI drain did not complete'): self.remove()
        m=cli.read_manifest()
        self.assertEqual((m['phase'],m['ui_drain']['phase']),('uncertain','uncertain'))
        self.assertEqual([a for a,_ in self.p.writes[before:]],[RESIDENT+0x9140])
        with self.assertRaisesRegex(RuntimeError,'uncertain'): self.remove()
        self.assertEqual(len(self.p.writes),before+1)

    def test_ui_drain_validates_identity_and_exported_offsets_before_write(self):
        self.with_ui(); before=len(self.p.writes)
        m=cli.read_manifest(); m['symbols']['__ui_ready_offset']=0x10000
        cli.save_manifest(m)
        with self.assertRaisesRegex(RuntimeError,'outside resident BSS'): self.remove()
        self.assertEqual(len(self.p.writes),before)

    def test_aspect_pending_jobs_block_drain_and_removal(self):
        self.symbols.update(aspect_ratio=0x9100,aspect_jobs=0x9140)
        self.install(); before=len(self.p.writes)
        for address,value in ((RESIDENT+0x910c,0x100),(RESIDENT+0x9140,1)):
            self.p.put(address,struct.pack('<I',value))
            with self.assertRaisesRegex(RuntimeError,'queued or saving'): self.remove()
            self.p.put(address,bytes(4))
        self.assertEqual(len(self.p.writes),before)

    def test_unknown_hooks_and_code_are_not_accepted_as_removed(self):
        m=self.install()
        self.p.put(HOOK,struct.pack('<Q',STOCK))
        with self.assertRaisesRegex(RuntimeError,'Saved code hooks'): cli.installation(self.p)
        self.assertEqual(cli.read_manifest()['phase'],'committed')

    def test_status_and_remove_use_saved_symbols_and_hooks_after_source_map_changes(self):
        m=self.install()
        self.patch('PATCHES',((HOOK,STOCK,'new_wrapper_not_in_saved_symbols'),(HOOK+8,123,'new_hook')))
        self.patch('CODE_PATCHES',((CODE,0x12345678,0x99999999,4),(CODE+8,456,789,4)))
        self.p.put(HOOK+8,struct.pack('<Q',123)); self.p.put(CODE+8,struct.pack('<I',456))
        self.assertTrue(cli.status(self.p)['installed'])
        removed=self.remove()
        self.assertEqual((removed['patches'],removed['code_patches']),(m['patches'],m['code_patches']))
        self.assertEqual((self.p.qword(HOOK+8),cli.u32(self.p.read(CODE+8,4))),(123,456))

    def test_legacy_removal_uses_original_archived_image_and_executor(self):
        image=b'archived legacy'; name,digest=cli.archive_image('legacy',image)
        m={'symbols':{'state':0x8000,'live_wrapper':0x200},'image':name,'image_sha256':digest,
           'resident':RESIDENT,'nonce':123,'phase':'installed','patches':cli.PATCHES,
           'code_patches':cli.CODE_PATCHES}
        self.p.put(HOOK,struct.pack('<Q',RESIDENT+0x200)); self.p.put(CODE,struct.pack('<I',0x87654321))
        self.p.put(RESIDENT+0x8000,struct.pack('<QIIQ',cli.MAGIC,1,0,123))
        cli.save_manifest(m)
        # The added second-L2 preflight gate also applies to archived legacy
        # removal. Refuse an unexpected descriptor without dispatch or writes.
        original_manifest=cli.MANIFEST.read_bytes()
        self.p.put(cli.UI_L2_SLOT,struct.pack('<Q',cli.UI_L2_RO^0x80))
        with patch.object(cli,'execute') as legacy_call, patch.object(loader,'remove') as segmented_call:
            with self.assertRaisesRegex(RuntimeError,'UI code page descriptor'):
                self.remove()
        legacy_call.assert_not_called(); segmented_call.assert_not_called()
        self.assertEqual(self.p.writes,[])
        self.assertEqual(cli.MANIFEST.read_bytes(),original_manifest)
        self.p.put(cli.UI_L2_SLOT,struct.pack('<Q',cli.UI_L2_RO))
        self.p.reads=[]
        def legacy(p,blob,symbols,buf,**kw):
            self.assertEqual(blob,image); self.assertEqual(kw,{'command':1,'resident':RESIDENT})
            p.put(HOOK,struct.pack('<Q',STOCK)); p.put(CODE,struct.pack('<I',0x12345678))
        with patch.object(cli,'execute',side_effect=legacy) as call, patch.object(loader,'remove') as segmented_remove:
            self.remove()
        call.assert_called_once(); segmented_remove.assert_not_called()
        self.assertIn((cli.L2_SLOT,8),self.p.reads)
        self.assertIn((cli.UI_L2_SLOT,8),self.p.reads)
        self.assertEqual(cli.read_manifest()['phase'],'removed')
        self.builder.assert_not_called(); self.loader_builder.assert_not_called()

    def test_actual_elf_section_extraction_rejects_mismatch(self):
        # Minimal original ELF64 fixture: text, mutable data, BSS and names.
        names=b'\0.text\0.data\0.bss\0.shstrtab\0'
        raw=bytearray(0x100+len(self.blob)+len(names)+5*64)
        raw[:7]=b'\x7fELF\x02\x01\x01'; struct.pack_into('<HH',raw,16,2,183)
        sections=0x100+len(self.blob)+len(names)
        struct.pack_into('<Q',raw,40,sections); struct.pack_into('<3H',raw,58,64,5,4)
        raw[0x100:0x100+len(self.blob)]=self.blob
        raw[0x100+len(self.blob):sections]=names
        for i,entry in enumerate(((1,1,6,0,0x100,0x7800),
            (7,1,3,0x7800,0x7900,len(self.blob)-0x7800),
            (13,8,3,0x8040,0,0x11c0),(18,3,0,0,0x100+len(self.blob),len(names))),1):
            struct.pack_into('<II4QII2Q',raw,sections+i*64,*entry,0,0,1,0)
        path=self.work/'fixture.elf'; path.write_bytes(raw)
        with patch.object(cli,'resident_layout',RESIDENT_LAYOUT):
            self.assertEqual(cli.resident_layout(self.blob,self.symbols,path),self.layout)
            with self.assertRaisesRegex(RuntimeError,'ELF and initialized image differ'):
                cli.resident_layout(b'!'+self.blob[1:],self.symbols,path)

RESIDENT_LAYOUT=cli.resident_layout

if __name__=='__main__': unittest.main()
