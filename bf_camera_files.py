#!/usr/bin/env python3
"""Read camera photo objects over MTP using the shared BF transport lock.

This helper exposes only standard read operations. It never changes camera
settings, captures a photo, deletes an object, or performs a vendor RAM write.
"""
import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import struct

from bf_touch_ptp import PTP, PTPError, ProtocolError, HEADER, DATA


@dataclass(frozen=True)
class DataBound:
    minimum: int
    maximum: int


class CameraFiles(PTP):
    def _receive(self, operation, tid, expected_data, deadline):
        if isinstance(expected_data,DataBound):
            while len(self._rx)<HEADER.size:
                self._read_usb(deadline)
            size,kind,_,_=HEADER.unpack_from(self._rx)
            if kind==DATA:
                length=size-HEADER.size
                if not expected_data.minimum<=length<=expected_data.maximum:
                    raise ProtocolError(f'Photo data length {length} exceeds {expected_data}')
                expected_data=length
        # Keep the parent's transaction, opcode, framing and response checks.
        return super()._receive(operation,tid,expected_data,deadline)

    def write(self,*args,**kwargs):
        raise RuntimeError('CameraFiles does not support writes')

    def handles(self):
        with self._io_lock:
            self._require_open()
            _,data=self._exchange(0x1007,(0xffffffff,0,0),expected_data=DataBound(4,400004))
        count=struct.unpack_from('<I',data)[0]
        if len(data)!=4+count*4:
            raise ProtocolError('Object handle count disagrees with its data size')
        return list(struct.unpack_from(f'<{count}I',data,4))

    def info(self,handle):
        with self._io_lock:
            self._require_open()
            _,data=self._exchange(0x1008,(handle,),expected_data=DataBound(52,4096))
        return object_info(data,handle)

    def download(self,info,directory):
        size=info['bytes']
        if not 0<size<=128*1024*1024:
            raise ValueError('Photo exceeds the supported 128 MiB read bound')
        name=info['filename']
        if Path(name).suffix.lower() not in ('.jpg','.jpeg','.dng'):
            raise ValueError('Only JPEG and DNG photo objects are downloaded')
        safe=re.sub(r'[^A-Za-z0-9_.-]','_',name)
        directory=Path(directory); directory.mkdir(parents=True,exist_ok=True)
        target=directory/f'{info["handle"]:08x}-{safe}'
        if target.exists():
            raise FileExistsError(f'Existing local photo is preserved: {target}')
        with self._io_lock:
            self._require_open()
            _,data=self._exchange(0x1009,(info['handle'],),expected_data=size)
        # A complete, matched PTP response precedes creation of the local file.
        with target.open('xb') as stream:
            stream.write(data)
        return {'path':str(target.resolve()),'sha256':hashlib.sha256(data).hexdigest(),
                **inspect_photo(data,target.suffix)}


def object_info(data,handle):
    if len(data)<52:
        raise ProtocolError('Truncated object information')
    position=52
    strings=[]
    for _ in range(4):
        if position>=len(data):
            raise ProtocolError('Missing object information string')
        count=data[position]; position+=1
        end=position+count*2
        if end>len(data):
            raise ProtocolError('Truncated object information string')
        text=data[position:end]
        if count and text[-2:]!=b'\0\0':
            raise ProtocolError('Object information string lacks terminator')
        strings.append(text[:-2].decode('utf-16-le') if count else '')
        position=end
    return {'handle':handle,'storage':struct.unpack_from('<I',data)[0],
            'format':struct.unpack_from('<H',data,4)[0],
            'bytes':struct.unpack_from('<I',data,8)[0],
            'width':struct.unpack_from('<I',data,26)[0],
            'height':struct.unpack_from('<I',data,30)[0],
            'filename':strings[0],'captured':strings[1],'modified':strings[2]}


def jpeg_size(data):
    if data[:2]!=b'\xff\xd8':
        raise ValueError('Missing JPEG SOI')
    position=2
    while position<len(data):
        if data[position]!=255:
            raise ValueError('Invalid JPEG marker boundary')
        while position<len(data) and data[position]==255:
            position+=1
        if position>=len(data): break
        marker=data[position]; position+=1
        if marker in (0xd9,0xda): break
        if marker==1 or 0xd0<=marker<=0xd8: continue
        if position+2>len(data): break
        length=int.from_bytes(data[position:position+2],'big')
        if length<2 or position+length>len(data):
            raise ValueError('Truncated JPEG segment')
        if marker in (0xc0,0xc1,0xc2,0xc3,0xc5,0xc6,0xc7,0xc9,0xca,0xcb,0xcd,0xce,0xcf):
            if length<8: raise ValueError('Truncated JPEG frame')
            height,width=struct.unpack_from('>HH',data,position+3)
            if not width or not height: raise ValueError('Empty JPEG frame')
            return width,height
        position+=length
    raise ValueError('JPEG frame dimensions not found')


def dng_metadata(data):
    if data[:2] not in (b'II',b'MM'):
        raise ValueError('Missing TIFF byte order')
    order='<' if data[:2]==b'II' else '>'
    if len(data)<8 or struct.unpack_from(order+'H',data,2)[0]!=42:
        raise ValueError('Unsupported TIFF header')
    pending=[struct.unpack_from(order+'I',data,4)[0]]; seen=set(); directories=[]
    type_sizes={1:1,2:1,3:2,4:4,5:8,6:1,7:1,8:2,9:4,10:8,11:4,12:8}
    wanted={0x100:'width',0x101:'height',0xa002:'pixel_width',0xa003:'pixel_height',
            0xc61f:'default_crop_origin',
            0xc620:'default_crop_size',0xc68d:'active_area',0xc7b5:'default_user_crop',
            0x201:'jpeg_offset',0x202:'jpeg_bytes'}
    while pending:
        offset=pending.pop()
        if not offset or offset in seen: continue
        if len(seen)>=32 or offset+2>len(data):
            raise ValueError('Invalid TIFF directory graph')
        seen.add(offset)
        count=struct.unpack_from(order+'H',data,offset)[0]
        end=offset+2+count*12
        if count>4096 or end+4>len(data):
            raise ValueError('Truncated TIFF directory')
        row={'offset':offset}
        for index in range(count):
            entry=offset+2+index*12
            tag,kind,length=struct.unpack_from(order+'HHI',data,entry)
            if tag not in wanted and tag not in (0x14a,0x8769): continue
            if kind not in type_sizes or length>4096:
                raise ValueError('Unsupported TIFF metadata type/length')
            size=type_sizes[kind]*length
            location=entry+8 if size<=4 else struct.unpack_from(order+'I',data,entry+8)[0]
            if location+size>len(data): raise ValueError('TIFF metadata points outside file')
            raw=data[location:location+size]
            if kind==3: values=list(struct.unpack(order+f'{length}H',raw))
            elif kind==4: values=list(struct.unpack(order+f'{length}I',raw))
            elif kind==5:
                values=list(struct.iter_unpack(order+'II',raw))
                if any(not denominator for _,denominator in values):
                    raise ValueError('Zero TIFF rational denominator')
            else: continue
            if tag in (0x14a,0x8769):
                if kind not in (3,4): raise ValueError('Invalid TIFF directory pointer')
                pending.extend(values)
            else: row[wanted[tag]]=values[0] if length==1 else values
        next_ifd=struct.unpack_from(order+'I',data,end)[0]
        if next_ifd: pending.append(next_ifd)
        if 'jpeg_offset' in row and 'jpeg_bytes' in row:
            start=row['jpeg_offset']; finish=start+row['jpeg_bytes']
            if finish>len(data): raise ValueError('Embedded JPEG exceeds DNG')
            row['embedded_jpeg_size']=jpeg_size(data[start:finish])
        directories.append(row)
    return directories


def jpeg_exif_metadata(data):
    if data[:2]!=b'\xff\xd8':
        raise ValueError('Missing JPEG SOI')
    position=2
    while position<len(data):
        if data[position]!=255: raise ValueError('Invalid JPEG marker boundary')
        while position<len(data) and data[position]==255: position+=1
        if position>=len(data): break
        marker=data[position]; position+=1
        if marker in (0xda,0xd9): break
        if marker==1 or 0xd0<=marker<=0xd8: continue
        if position+2>len(data): break
        length=int.from_bytes(data[position:position+2],'big')
        if length<2 or position+length>len(data): raise ValueError('Truncated JPEG segment')
        if marker==0xe1 and data[position+2:position+8]==b'Exif\0\0':
            return dng_metadata(data[position+8:position+length])
        position+=length
    return []


def inspect_photo(data,suffix):
    if suffix.lower() in ('.jpg','.jpeg'):
        width,height=jpeg_size(data)
        if not data.rstrip(b'\0').endswith(b'\xff\xd9'):
            raise ValueError('JPEG lacks its final end marker')
        exif=jpeg_exif_metadata(data)
        for directory in exif:
            if (directory.get('pixel_width',width)!=width or
                directory.get('pixel_height',height)!=height):
                raise ValueError('JPEG EXIF pixel dimensions disagree with its frame')
        return {'type':'JPEG','width':width,'height':height,'exif':exif}
    if suffix.lower()=='.dng':
        return {'type':'DNG','directories':dng_metadata(data)}
    raise ValueError('Unsupported photo type')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('baseline','list','download'))
    parser.add_argument('--baseline',type=Path)
    parser.add_argument('--output',type=Path,default=Path('.touch-focus/aspect-photos'))
    parser.add_argument('--handles',type=lambda value:int(value,0),nargs='+')
    parser.add_argument('--last',type=int,default=12)
    args=parser.parse_args()
    try:
        with CameraFiles(timeout_ms=60000) as camera:
            if args.command=='baseline':
                if not args.baseline: parser.error('baseline requires --baseline PATH')
                handles=camera.handles()
                args.baseline.parent.mkdir(parents=True,exist_ok=True)
                with args.baseline.open('x') as stream: json.dump(handles,stream)
                print(json.dumps({'objects':len(handles),'baseline':str(args.baseline)})); return
            handles=args.handles if args.handles is not None else camera.handles()
            if args.baseline:
                previous=set(json.loads(args.baseline.read_text()))
                handles=[handle for handle in handles if handle not in previous]
            elif args.handles is None:
                if not 1<=args.last<=100: parser.error('--last must be 1..100')
                handles=handles[-args.last:]
            for handle in handles:
                info=camera.info(handle)
                if args.command=='download':
                    info.update(camera.download(info,args.output))
                print(json.dumps(info),flush=True)
    except (PTPError,RuntimeError,OSError,ValueError,UnicodeError) as exc:
        parser.exit(1,f'{exc}\n')


if __name__=='__main__': main()
