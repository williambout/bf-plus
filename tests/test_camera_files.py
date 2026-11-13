"""Bounded standard MTP reads and photo header parsing; never open USB."""
import contextlib
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from bfplus_camera_files import CameraFiles, object_info, jpeg_size, dng_metadata, inspect_photo
from bfplus_ptp import HEADER, DATA, ProtocolError
from tests.test_touch_ptp import FakeUSB, data, response


def text(value):
    encoded=(value+'\0').encode('utf-16-le')
    return bytes([len(encoded)//2])+encoded


class FileReadTests(unittest.TestCase):
    def setUp(self):
        self.context=contextlib.ExitStack()
        self.addCleanup(self.context.close)
        self.directory=self.context.enter_context(tempfile.TemporaryDirectory())
        for name in ('claim_interface','release_interface','dispose_resources'):
            self.context.enter_context(patch('bfplus_ptp.usb.util.'+name))
        self.context.enter_context(patch('bfplus_ptp.usb.core.find',side_effect=AssertionError('no real USB')))

    def camera(self,incoming):
        device=FakeUSB(incoming)
        camera=self.context.enter_context(CameraFiles(device=device,state_dir=self.directory))
        return camera,device

    def test_variable_handle_count_retains_transaction_validation(self):
        payload=struct.pack('<4I',3,12,19,25)
        camera,device=self.camera([data(1,payload,0x1007)+response(1)])
        self.assertEqual(camera.handles(),[12,19,25])
        self.assertEqual(len(device.commands(0x1007)),1)
        self.assertEqual(len(device.commands(0x900a)),0)
        with self.assertRaisesRegex(RuntimeError,'does not support writes'):
            camera.write(0,b'bad')

    def test_bad_length_is_rejected_before_receiving_an_unbounded_body(self):
        camera,device=self.camera([HEADER.pack(500000,DATA,0x1007,1)])
        with self.assertRaisesRegex(ProtocolError,'exceeds'):
            camera.handles()
        self.assertEqual(len(device.read_calls),2)
        self.assertTrue(camera._broken)

    def test_variable_data_still_checks_opcode_and_tid(self):
        for wrong_tid,wrong_opcode in ((2,0x1007),(1,0x1008)):
            with self.subTest(tid=wrong_tid,opcode=wrong_opcode):
                # Separate state directory/context: each owns one transport.
                with tempfile.TemporaryDirectory() as directory:
                    device=FakeUSB([data(wrong_tid,struct.pack('<I',0),wrong_opcode)])
                    with CameraFiles(device=device,state_dir=directory) as camera:
                        with self.assertRaises(ProtocolError): camera.handles()
                        self.assertEqual(len(device.commands(0x1007)),1)

    def test_object_strings_and_dimensions_are_bounded(self):
        header=bytearray(52)
        struct.pack_into('<I',header,8,12345)
        struct.pack_into('<II',header,26,5980,2208)
        payload=header+text('BF000123.JPG')+text('20261112T210000')+text('')+text('')
        result=object_info(payload,99)
        self.assertEqual((result['width'],result['height']),(5980,2208))
        self.assertEqual(result['filename'],'BF000123.JPG')
        with self.assertRaises(ProtocolError): object_info(payload[:-1],99)

    def test_handle_array_does_not_accept_truncated_ids(self):
        camera,_=self.camera([data(1,struct.pack('<2I',2,123),0x1007)+response(1)])
        with self.assertRaisesRegex(ProtocolError,'count disagrees'):
            camera.handles()


class PhotoHeaderTests(unittest.TestCase):
    def test_jpeg_frame_after_application_data(self):
        frame=b'\x08'+struct.pack('>HHB',2208,5980,3)+b'\x01\x11\0\x02\x11\0\x03\x11\0'
        image=b'\xff\xd8\xff\xe1\0\x06Exif\xff\xc0'+struct.pack('>H',len(frame)+2)+frame+b'\xff\xd9'
        self.assertEqual(jpeg_size(image),(5980,2208))
        with self.assertRaises(ValueError): jpeg_size(image[:16])

    def test_jpeg_exif_dimensions_agree_with_frame_and_mismatch_is_reported(self):
        exif=bytearray(64)
        struct.pack_into('<2sHI',exif,0,b'II',42,8)
        struct.pack_into('<H',exif,8,1)
        struct.pack_into('<HHII',exif,10,0x8769,4,1,32)
        struct.pack_into('<H',exif,32,2)
        struct.pack_into('<HHII',exif,34,0xa002,4,1,5980)
        struct.pack_into('<HHII',exif,46,0xa003,4,1,2208)
        frame=b'\x08'+struct.pack('>HHB',2208,5980,3)+b'\x01\x11\0\x02\x11\0\x03\x11\0'
        def jpeg():
            app1=b'Exif\0\0'+exif
            return (b'\xff\xd8\xff\xe1'+struct.pack('>H',len(app1)+2)+app1+
                    b'\xff\xc0'+struct.pack('>H',len(frame)+2)+frame+b'\xff\xd9')
        info=inspect_photo(jpeg(),'.JPG')
        self.assertEqual((info['exif'][1]['pixel_width'],info['exif'][1]['pixel_height']),
                         (5980,2208))
        struct.pack_into('<I',exif,42,6016)
        with self.assertRaisesRegex(ValueError,'disagree'):
            inspect_photo(jpeg(),'.jpg')

    def test_dng_subifd_and_exact_rationals(self):
        image=bytearray(160)
        struct.pack_into('<2sHI',image,0,b'II',42,8)
        struct.pack_into('<H',image,8,1)
        struct.pack_into('<HHII',image,10,0x14a,4,1,32)
        struct.pack_into('<H',image,32,4)
        for index,entry in enumerate(((0x100,4,1,6080),(0x101,4,1,4042),
                                      (0xc7b5,5,4,96),(0xc620,4,2,128))):
            struct.pack_into('<HHII',image,34+12*index,*entry)
        values=(902,4011,16,6015,3109,4011,5995,6015)
        struct.pack_into('<8I',image,96,*values)
        struct.pack_into('<2I',image,128,6016,4012)
        raw=dng_metadata(image)[1]
        self.assertEqual((raw['width'],raw['height']),(6080,4042))
        self.assertEqual(raw['default_crop_size'],[6016,4012])
        self.assertEqual(raw['default_user_crop'],[(902,4011),(16,6015),(3109,4011),(5995,6015)])
        struct.pack_into('<I',image,34+12*2+8,10000)
        with self.assertRaisesRegex(ValueError,'outside file'): dng_metadata(image)


if __name__=='__main__': unittest.main()
