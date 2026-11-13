#!/usr/bin/env python3
"""Reversible BF 1.04 touch focus experiment. See docs/TOUCH-FOCUS.md."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import struct
import time

from bf_touch_ptp import PTP, PTPError, BASE, CALLBACK_SLOT, ORIGINAL_CALLBACK
from touch_focus.build import build, ROOT, BUILD
from touch_focus.loader_build import build as build_loader
import bf_plus_loader as segmented

WORK = ROOT / '.touch-focus'
MANIFEST = WORK / 'installation.json'
PACKAGE_SHA256 = '0c6cb624967c0d2254fa3e532ea25f389f09b007e9e31788df7e9682995e478b'
RTOS_SHA256 = 'f747c1350f00526b9c68c65aaef44d6e7b644b0169992342e12f059c42e150dc'
MAGIC = 0x314843554f544642
CACHE_SLOT = 0x4d72c2230
L2_SLOT, L2_RO = 0x4d71484c8, 0x4d3200781
LEGACY_PATCHES = (
    (0x4d3398860, 0x4d3398940, 'live_wrapper'),
    (0x4d33a1388, 0x4d33a1670, 'mag_wrapper'),
    (0x4d3398868, 0x4d3396120, 'live_update_wrapper'),
    (0x4d33a1390, 0x4d33a1420, 'mag_update_wrapper'),
    (0x4d3392b60, 0x4d3392c40, 'cine_wrapper'),
    (0x4d3392b68, 0x4d338ef10, 'cine_update_wrapper'),
) + tuple((a,0x4d7042c18,'menu_rows') for a in (
    0x4d3372868,0x4d3372980,0x4d3372be8,0x4d3372d50,
    0x4d3372ef0,0x4d3373160,0x4d33738c8,
)) + tuple((a,0x4d3564220,'menu_callbacks') for a in (
    0x4d3372d60,0x4d3372f00,0x4d3373170,0x4d33738e0,
)) + tuple((a,0x4d3373200,'menu_input_wrapper') for a in (0x4d3372f38,0x4d33731a8))
BASE_PATCHES = LEGACY_PATCHES + (
    (0x4d33731d0, 0x4d3e88bc8, 'menu_parent_scene'),
    (0x4d3321278, 0, 'detector_gate_wrapper'),
    (0x4d331ce58, 0, 'subject_frame_wrapper'),
)

def branch_instruction(source, target, link=False):
    delta=target-source
    if delta%4 or not -(1<<27)<=delta<(1<<27):
        raise ValueError('AArch64 branch out of range or unaligned')
    return (0x94000000 if link else 0x14000000) | ((delta>>2)&0x3ffffff)

def load_unsigned(rt, rn, offset, wide):
    return (0xf9400000 if wide else 0xb9400000) | ((offset//(8 if wide else 4))<<10) | (rn<<5) | rt

ASPECT_RAW_ORIGINAL = 0x90000000 | (load_unsigned(0,0,0x688,True)<<32)
ASPECT_RAW_SLOT_ORIGINAL = load_unsigned(0,0,0,True) | (load_unsigned(0,0,0x18,False)<<32)
ASPECT_SMALL_ORIGINAL = 0x2a0103e0 | (0xaa0203e1<<32)
ASPECT_SMALL_SLOT_ORIGINAL = 0xaa0303e2 | (branch_instruction(0x4d3288b8c,0x4d3295f60)<<32)
ASPECT_PATCHES = (
    (0x4d3317678, ASPECT_RAW_SLOT_ORIGINAL, 'aspect_raw_wrapper'),
    (0x4d33208a8, 0, 'aspect_stock_set_wrapper'),
    (0x4d33208b8, 0, 'aspect_label_wrapper'),
    (0x4d3288b68, 0, 'aspect_main_wrapper'),
    (0x4d3288b78, 0, 'aspect_half_wrapper'),
    (0x4d3288b88, ASPECT_SMALL_SLOT_ORIGINAL, 'aspect_small_wrapper'),
    (0x4d33208c8, 0, 'aspect_meta_wrapper'),
    (0x4d33208d8, 0, 'aspect_dng_wrapper'),
    (0x4d33208e8, 0, 'aspect_release_wrapper'),
    (0x4d33208f8, 0, 'aspect_reserve_wrapper'),
) + tuple((a,0x4d3cabc60,'aspect_view') for a in (
    0x4d3269718,0x4d3269738,0x4d3269768,0x4d32697c8,
    0x4d32697f8,0x4d3269828,0x4d3269878,
))
# Keep the second page check and saved-ABI drain/status helpers for removing
# archived UI builds. No rotation/touch hooks are part of a new installation.
UI_L2_SLOT, UI_L2_RO = 0x4d71484c0, 0x4d3000781
PATCHES = BASE_PATCHES + ASPECT_PATCHES
ASPECT_SNAPSHOT_SITES = (0x4d324358c,0x4d3243ac4,0x4d3244174,0x4d3244280,
                         0x4d324447c,0x4d3244820,0x4d3244b50)

# The raw-setting veneer keeps its original behavior except for this one
# detector caller. Reconstructed branch encodings, not extracted code blobs.
CODE_PATCHES = (
    (0x4d3321270, branch_instruction(0x4d3321270,0x4d3318500), 0xd61f020058000050, 8),
    (0x4d326dcd4, branch_instruction(0x4d326dcd4,0x4d31559d0,True),
     branch_instruction(0x4d326dcd4,0x4d3321270,True), 4),
    (0x4d331ce50, branch_instruction(0x4d331ce50,0x4d3319b60), 0xd61f020058000050, 8),
    (0x4d3317670, ASPECT_RAW_ORIGINAL, 0xd61f020058000050, 8),
    (0x4d33208a0, branch_instruction(0x4d33208a0,0x4d3317690), 0xd61f020058000050, 8),
    (0x4d33208b0, branch_instruction(0x4d33208b0,0x4d33176b0), 0xd61f020058000050, 8),
    (0x4d3288b60, branch_instruction(0x4d3288b60,0x4d3295ec0), 0xd61f020058000050, 8),
    (0x4d3288b70, branch_instruction(0x4d3288b70,0x4d3295f10), 0xd61f020058000050, 8),
    (0x4d3288b80, ASPECT_SMALL_ORIGINAL, 0xd61f020058000050, 8),
    (0x4d33208c0, branch_instruction(0x4d33208c0,0x4d33176d0), 0xd61f020058000050, 8),
    (0x4d33208d0, branch_instruction(0x4d33208d0,0x4d33176f0), 0xd61f020058000050, 8),
    (0x4d33208e0, branch_instruction(0x4d33208e0,0x4d3317860), 0xd61f020058000050, 8),
    (0x4d33208f0, branch_instruction(0x4d33208f0,0x4d33179c0), 0xd61f020058000050, 8),
    (0x4d32fd9dc, load_unsigned(0,21,0x10,False),
     branch_instruction(0x4d32fd9dc,0x4d33208c0,True), 4),
    (0x4d32621bc, branch_instruction(0x4d32621bc,0x4d3007fc0,True),
     branch_instruction(0x4d32621bc,0x4d33208d0,True), 4),
    (0x4d3268fec, branch_instruction(0x4d3268fec,0x4d30339d0,True),
     branch_instruction(0x4d3268fec,0x4d33208e0,True), 4),
    (0x4d3268ea8, branch_instruction(0x4d3268ea8,0x4d3033ab0,True),
     branch_instruction(0x4d3268ea8,0x4d33208f0,True), 4),
    (0x4d335693c, branch_instruction(0x4d335693c,0x4d33724b0,True),
     branch_instruction(0x4d335693c,0x4d33208b0,True), 4),
) + tuple((a,0x2a0003e2,0x12001c02,4) for a in ASPECT_SNAPSHOT_SITES)

def native_aspect_code_patches(header=None):
    """Use the resident's native-chooser call lists; accept only literal sites."""
    source=(ROOT/'touch_focus/aspect_ratio.h').read_text() if header is None else header
    lines=source.splitlines()
    patches=[]
    for macro,original,target in (
            ('ASPECT_NATIVE_STEP_CALLS',0x4d33993e0,0x4d33208a0),
            ('ASPECT_NATIVE_LABEL_CALLS',0x4d33724b0,0x4d33208b0),
            ('ASPECT_NATIVE_SUBLCD_CALLS',0x4d332dce0,0x4d33208b0)):
        prefix='#define '+macro+'(X)'
        starts=[i for i,line in enumerate(lines) if line.startswith(prefix)]
        if len(starts)!=1: raise ValueError('Missing or duplicate '+macro)
        i=starts[0]; body=lines[i][len(prefix):]
        while body.rstrip().endswith('\\'):
            body=body.rstrip()[:-1]+' '
            i+=1
            if i>=len(lines): raise ValueError('Unterminated '+macro)
            body+=lines[i]
        pattern=r'X\((0x[0-9a-fA-F]+)ULL\)'
        sites=re.findall(pattern,body)
        if not sites or re.sub(pattern,'',body).strip():
            raise ValueError('Unsupported '+macro+' syntax')
        for site in sites:
            address=int(site,16)
            patches.append((address,branch_instruction(address,original,True),
                            branch_instruction(address,target,True),4))
    if len({a for a,_,_,_ in patches})!=len(patches):
        raise ValueError('Duplicate native aspect call')
    return tuple(patches)

NATIVE_ASPECT_CODE_PATCHES = native_aspect_code_patches()
CODE_PATCHES += NATIVE_ASPECT_CODE_PATCHES
# SHA-256 of 32-byte function prefixes; no extracted firmware is distributed.
FINGERPRINTS = {
    0x4d31254f0: 'ea4c602267662e5c09a93ad7ae29bb8350bf2d4775bde6aceaf3aba14352b87b',
    0x4d3398940: '0e46219d5ea1aac8aec998a6937fff4cc7346fcccd099f879fd59a76fc3d4379',
    0x4d33a1670: 'ba843ac224700ef2109d8749a1db9379dfaea2dff22af5c36327d9253b673006',
    0x4d33a1e70: '758c925dd2d0078a0b19ff232a38299dd97b95da2ed24a0f6a4c2faf890f0380',
    0x4d330c850: '55c767677bd4cfb238b11ac31b5b7177e2bffa2e248d8d5b8bf618d5b1648bc8',
    0x4d3324250: '7d24dcf531a99cbee13466533d0118839acd1de747fa925f70cec5b4abc3f575',
    0x4d3396120: '4363f24d9556ff8f87343fcc647cabf66995b42aba8ba135a14a0d0187cc49a0',
    0x4d33a1420: '0e8861d80fd5ed6c8307925970a1402d42203c663742766873128a4ca8685da1',
    0x4d3033a00: 'e212ddb4cfcd2187a9d3e00a4cb6e345bbb039136fa447a572cfd0633fec8fe7',
    0x4d3392c40: '4d3c25862ebfeafd9f55f49d87fd0552e6cf549df5fafd118ad4d882801a2184',
    0x4d338ef10: 'eb6284728468a2e9044ffc26f9c0716bb18b6f216321fe677196b69bf5894db3',
    0x4d3373200: '0a50796a934e4f64b7fd011dc6cba039c154f430144a1971e012243d937aee14',
    0x4d33726d0: 'b103369b4faee7e2f52f75f4f1d950628c3750f42214fad7ba65a755564c5b21',
    0x4d33729c0: 'b402631b352abc963f3252d5921f6a9022b9cb3927d4ccd6673962148f8cc0d8',
    0x4d3372a20: 'c26b7276ecfe2f0a67d4af033bcd55a55be107746968f454bb5b411ddd341ae7',
    0x4d3363df0: '68fc1ab8123ef19510578526f5f0eb158ba0d6765c749919b9429836e246263a',
    0x4d3322d90: 'cb6e060266988411119f99cff7829968e85c49ae38138e4d9b565135a92a668d',
    0x4d3325ca0: 'd6aca9393a970f69188479bd8abe88b5cc9385253fa60f16f3ee9eb9c107a586',
    0x4d3323400: 'b9c660f827c675e18641d91982dc02a7faf6c6dabcd0b5608e3d0cc7bdccd9b0',
    0x4d3363ca0: '1513130ccc576260db33fec4085d00e0eef61b576519135eed660394a1a5eec6',
    0x4d3363c60: 'd4c4b4ecd94ccf4d70cfb734660fdfe2f0c1a699ac89fc987b4bc0ba6a1f931d',
    0x4d3363d80: '0fd4518bc0339985b2df97fd3ee62f16450179c0e79bda23e84be54169438afc',
    0x4d3328cc0: '33ea96b4493a8ddc79c4b5912d30152b26a167e2273f4cbd14a6e8e795af5e3c',
    0x4d335d4b0: 'b0daa6c7df4232aea29108e68e0a307524b9e319c3cd4d2bbd0f366bc4168c81',
    0x4d335f000: 'f436742c7ecc1b27500c2d21669d93c2f5be5b6b95b8698f94bc2dfea5141f17',
    0x4d3372d90: 'cc6aad84467b819c4b8d8af3f875de9a3439ff346976298d174b73220921603a',
    0x4d3324110: 'c9d7bcaddcb4034c2985f3377e88a1d2dd88882f077af1712272deff9d56b1d0',
    0x4d33646d0: '8f2e834c13430ce3878b8f9143995f689dc5ac2af0c8458928774bcc2f9710f0',
    0x4d3364750: '27d6ce8d6f9c8747ae235503281a8a3ad91e9c28eabc776f55a2d42f9a8935f4',
    0x4d3364970: 'ad653062b9d5a6c7390648d74e7adef90ed88e7f0a559967c594cacd20e15c68',
    0x4d3327240: '2a053932cf551da534af4f8cd64351aec10195fbb551bd6528b9f07d01e34fa6',
    0x4d332b110: '26d8ef843eaf85f356a5b6ea2de2cc22538093a7b6638226065eff62fe58b0f6',
    0x4d335d380: '13c370b61beabd38a54f679dac09efa72495e5466bbabfc751ea931b34d9730f',
    0x4d3270e50: '416c61cd77350f8b02e941ae35c69f437f667bee57c3ecd333ab3a99159734fa',
    0x4d326ccd0: '6fa3596058918856b52ea633ecc4bdb17200a6b4fa3efdfedc2be1148e10a549',
    0x4d3319b00: 'ffa1ba1ed31d686e71a98adb84c0c4f0ec43d596684e64473356fe082d16b40d',
    0x4d3319b30: '49be9c308fbecbc2ffa904d7de30edd5eaf8181ed1a514309f52ee79732e6e0b',
    0x4d331d040: '490ec9550be89bb8925a7eb04bc70f65631afcc9eac4e4a1e19d49327ac7b472',
    0x4d33211c0: '676256bdb9ee7a687c56386103dcb28bd9ce5a672e21e8b329a62e4f0ef1394a',
    0x4d3318500: 'dde729ed7935897c56a280416da5f67a1992fec82f23d9566c13d8260d0282cd',
    0x4d326dc90: '03cd814ddc0542b376a2af3ff575dea31923fda2e203c1bdb2c9bd81d7cce92a',
    0x4d326dcf0: '25ad1268b047b416a0d862ba76dc85d5657a1373af42971a4bdf5e79228414e3',
    0x4d3274b60: '66af5416de5e0f8e8af0a30985e0fc76fa42bd61b1f643ac57745a204f761785',
    0x4d3319b60: '9794d20a622344a7db196b6403fdd16708826310dc93ad7d7ca54d5080428f16',
    0x4d31a7470: '9a9c88b7a1ffd0ab6e96f4aca3a7a987d2ef992ce075a7231af14d97b3bd85f6',
    0x4d31a7240: '71841d5e28cd2bb40bdacd831aa78b3d9421f0cfd3d3ff49e0d5f6f57de79e7f',
    0x4d335b860: 'd92ed70140e0f41384bf0caf4ec80ac2d4a7518705dadbeeb50c6394841fcd45',
}

# Untouched native crop tables and routines used by the aspect adapter.
ASPECT_FINGERPRINTS = {
    (0x4d3daa870, 168): '16a9cd70ede53624b9414065f6eb7c4a13caf5fe7d21c2853bd7c7a7efd385a1',
    (0x4d3daa720, 168): 'c11d47da89a12c8ee93ecf73db9e1217fc4de087494e14594058dc363a54bfc2',
    (0x4d3daa6c8, 84): '6f16cba841989a65e6ed5239f34b015050e0987458a851f967241e1c4d5d2c93',
    (0x4d3cab100, 448): '6779b7eaa91764b3ec2a4df9e516b40ea0dfef61460c2ccdce2ba9ec1e4b0750',
    (0x4d3cabc60, 28): '8468caf68add24a689ba0833ce20d6b42f161a76ed11b4c964ccbf9a26ba2020',
    (0x4d3daaac0, 168): 'e1cf2485f9143fdad91d296f8ab7ba937fcaa5c086617efbf7e58691ca730d30',
    (0x4d3daa970, 168): 'ed38e870b2c0a92557351beafbc47c493ac441fd3d2f0d44f0218434fd0a06e5',
    (0x4d3daa918, 84): '254a26ab81264646c3a9b6f02aa8a52147616ea88f9b1be804c76275d1e49972',
    (0x4d3300100, 32): '430a56bfef72e28b3926f5c3291ebc8f87fe9347ae7df8934de32bf29b89ad77',
    (0x4d3262190, 32): '539e46e8082a5882290f014aa5ff10e8d45f74c458112d164e493451362417b7',
    (0x4d3320850, 32): 'e4e9953b2fe6f72e18eaac239a90ae53a4b695d100b029dcb3f85148ad8ecaf6',
    (0x4d33226f0, 32): '6d743a80ceb808f855f6b475fae056ac9571336df5b4fae5c8ce92d4c9721f38',
    (0x4d3317680, 32): '9b2e136f476599d472f3b3841b63c1148b670585a64980e0aafcc07bc76b0fff',
    (0x4d3295ec0, 32): '543509466d0de516333e1af23ddb0e56e03816dfe7c69554d8b401e909f0b2bc',
    (0x4d3295f10, 32): 'b8227e12825d050414ffd5d3c808fb1ee08a00acc0324a66b85d7cd44ed377d6',
    (0x4d3295f60, 32): '011b1315308eec91891bd1903c85fda28f68d392ec90f678d6464c5308597a7f',
    (0x4d33a03a0, 32): '131dda9a6c5262d8fbf0debacb634a92d3bc0bfbc104401550e842fd98e66a12',
    (0x4d3033ab0, 32): '4776b2b8db81d8a4f61d3fb13cb7b02fbb02cd359aee6492715c35c2ba9907cf',
    (0x4d30339d0, 32): '28447530bc1d67d060fcdcdf2f6229ad9c13e4e506370154e5ebe8bf9c681740',
    (0x4d3268e70, 56): '66236159c273ee386f41a60764b302cbfa3243772393b5e0862c4ee0fe6ee080',
    (0x4d3268eac, 252): '385ad191ed2222cd29ffe1939c49b17c6a42a7c7b5cb8e6800a115657f0e5d84',
    (0x4d3268fb0, 60): 'e404e5c1521bfa7afe210228d392330f459a43f45a4c5308730f07ec0b6de374',
    (0x4d3268ff0, 80): '692406857696ba3f1020aff7bc1560e8153e476a0c14b6d5291c89cc9242ca1e',
    (0x4d32fd9b0, 44): '257d0f9ab95928652a8444b61c843f3a3ca535a927c24becaa7476c068d0a3e4',
    (0x4d32fd9e0, 32): 'c79f57691b2e23df12bbad201636da8994059803861c5db617807d2e834ca8b4',
    (0x4d3322ba0, 32): 'b68f9efb6cdf165d4a07dab2b3ffe60580d948874d0b24cec2d445ba48d368d7',
    # Native aspect chooser, arrows, and sub-LCD glyph sequence paths.
    (0x4d3394bf8, 24): 'ba87a281b89b4be21d16965b81e9a2740d36566ab95b445ab3538adf498ce656',
    (0x4d3394c14, 24): '285996033230f1c9ecb0199fc1cdec252fff8c01f5d91b76cdf4fe4dcc33a613',
    (0x4d33a31ec, 20): '89196415e321dd0c17f2ac4359fadf700fa0799fcc6ebefa35c6bf674be0f5c2',
    (0x4d33a3204, 8): 'dd5e65d3f759730cd725a97fba2a57bde15a9f927f70d5032782ab84a17c054a',
    (0x4d33a3630, 20): '632a099e8c21962e615b414ca5ef34e80f5a222dfedae7a8ab0b5341d20e3225',
    (0x4d33a3648, 80): 'cfe7f15a68c2cf423675924e737d6a7adef1e5145acea0c9e41de48159ebc35b',
    (0x4d33a3f9c, 20): '84f59191e2a3c5c0bcdea5fd95617b40e037bd16104a7d7daa7667e889a6e532',
    (0x4d33a3fb4, 8): '35a2a0db5210dbe940eb5f295d71b7b48e4b396518acfd40169a1a9d18acac6d',
    (0x4d33a4028, 20): '8fbb3261477f7fb44587c49ab6a961b55b403b3c1e1fd0fb51b9d997591314db',
    (0x4d33a4040, 8): '40a37ba52b52cf2de1954824da1811b1b50e85bf40b4b5e91e41f406692a42f2',
    (0x4d33a418c, 20): '72d54c0389dd77f7e7962f032f9cbc471ab94a24298197951513a455daa49b51',
    (0x4d33a41a4, 8): '92eb676ba78d913441964a9947ea44acd65cd7e26e8bce84757fa94bdcbe0212',
    (0x4d33993e0, 96): '2809cce283685dbbfcde4c1d7925d942b5ad557438f94c956aa4ad7c4b7f4ea8',
    (0x4d336a100, 52): '3b7c4d132448a5549c318c7e4897c9be746a1b538cff5dae7d31cb6ac9e66c85',
    (0x4d336a138, 24): 'e7caa55e34cc28ca00781ebb68eaa0af532885230211cf14c761a78e5ace299c',
    (0x4d332dce0, 72): '4713648fe69cb93f788750911fd4c3c778c80e1bed72df839eb7e512e7df5b45',
    (0x4d332dd30, 528): '5e811c4f0a2142a3a13322dc39b8d729761c27706a5a0e5e54f16bb268dd896e',
    (0x4d332e160, 24): 'b07ef0197d8e833bd8b19be9f46060d247cc960208cbd7be4e3a92f940684d23',
    (0x4d332e5c0, 128): 'de02d993dd846f0e900d4cc9d1a1c3edfeb3205c7c5e75626588ab1e07f16218',
    (0x4d7034730, 32): '63714dc9c6826125dad5bb390d5c968fc78dec6cfb9cdc67039656b18b024689',
    (0x4d3e21ba8, 4080): '23b15617ef11d59296fb1ba2ccfafce824104a8eaa55b2d837b39f84e548179c',
    (0x4d3e87fb8, 28): 'f8c2949ecae9f145d335ce6e7242cdd9c83323fd4ae07b9e133e34846bb63714',
}

def say(message): print(message, flush=True)
def u32(data, offset=0): return struct.unpack_from('<I',data,offset)[0]
def u64(data, offset=0): return struct.unpack_from('<Q',data,offset)[0]
def require(condition, message):
    if not condition: raise RuntimeError(message)

def check_callback(p):
    require(p.qword(CALLBACK_SLOT)==ORIGINAL_CALLBACK,
            'Storage callback is unexpected. Stop; power-cycle before another attempt.')

def require_idle_still(p):
    require(u32(p.read(0x4d703469c,4))==12 and u32(p.read(0x4d70346a0,4))==2 and
            u32(p.read(0x4d70346a4,4))==12 and
            p.read(0x4d7301c00,32)==struct.pack('<4Q',0x4d3398930,0x4d33988b0,0x4d3393730,0x4d33936a0),
            'Return to idle still shooting live view before installation or removal')

def preflight(p):
    require(p.qword(0x4d7301a00)==BASE, 'Adjustment base differs from supported firmware')
    check_callback(p)
    require(p.qword(L2_SLOT)==L2_RO, 'Code page descriptor differs from supported firmware')
    require(p.qword(UI_L2_SLOT)==UI_L2_RO, 'UI code page descriptor differs from supported firmware')
    for address, digest in FINGERPRINTS.items():
        require(hashlib.sha256(p.read(address,32)).hexdigest()==digest,
                f'Firmware fingerprint mismatch at {address:#x}; no writes made')
    for (address,length),digest in ASPECT_FINGERPRINTS.items():
        require(hashlib.sha256(p.read(address,length)).hexdigest()==digest,
                f'Aspect firmware fingerprint mismatch at {address:#x}; no writes made')
    buf=p.qword(CACHE_SLOT)
    require(BASE+0x10000<=buf<0x4fff00000 and not buf&0xfff, 'Unexpected read-buffer allocation')
    return buf

def read_manifest():
    m=json.loads(MANIFEST.read_text()) if MANIFEST.exists() else None
    require(m is None or isinstance(m,dict) and m.get('format') in (None,segmented.FORMAT),
            'Unknown installation manifest format; do not use the legacy remover')
    return m

def _sync_directory(path):
    fd=os.open(path,os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)

def archive_image(kind, blob):
    """Create once; never overwrite an archived installation artifact."""
    WORK.mkdir(parents=True,exist_ok=True)
    digest=hashlib.sha256(blob).hexdigest()
    name=f'{kind}-{digest}.bin'
    path=WORK/name
    try:
        with path.open('xb') as f:
            f.write(blob); f.flush(); os.fsync(f.fileno())
        _sync_directory(WORK)
    except FileExistsError:
        require(path.read_bytes()==blob, f'Existing immutable artifact differs: {name}')
    return name,digest

def archived_image(name, digest):
    require(isinstance(name,str) and Path(name).name==name and name not in ('','.','..'),
            'Invalid archived artifact name')
    raw=(WORK/name).read_bytes()
    require(hashlib.sha256(raw).hexdigest()==digest, 'Saved payload/loader hash mismatch')
    return raw

def read_chunks(p,address,size):
    require(size>=0, 'Invalid resident code read size')
    chunks=[]
    for offset in range(0,size,segmented.READ_MAX):
        count=min(segmented.READ_MAX,size-offset)
        raw=bytes(p.read(address+offset,count))
        require(len(raw)==count, 'Inexact resident code read; no retry')
        chunks.append(raw)
    return b''.join(chunks)

def resident_layout(blob,symbols,elf_path=None):
    """Record immutable ELF sections, not a guessed boundary in mutable .data."""
    raw=Path(elf_path or BUILD/'payload.elf').read_bytes()
    require(raw[:7]==b'\x7fELF\x02\x01\x01' and len(raw)>=64,
            'Expected little-endian ELF64 resident')
    require(struct.unpack_from('<HH',raw,16)==(2,183), 'Expected linked AArch64 resident')
    section_offset=struct.unpack_from('<Q',raw,40)[0]
    section_size,count,names_index=struct.unpack_from('<3H',raw,58)
    require(section_size==64 and 0<names_index<count and section_offset+count*64<=len(raw),
            'Invalid resident section table')
    sections=[struct.unpack_from('<II4QII2Q',raw,section_offset+i*64) for i in range(count)]
    name_section=sections[names_index]
    names=raw[name_section[4]:name_section[4]+name_section[5]]
    immutable=[]; executable=[]
    for name_index,kind,flags,start,offset,size,_,_,_,_ in sections:
        if not flags&2 or not size: continue
        name=names[name_index:].split(b'\0',1)[0]
        if kind==8:
            require(name==b'.bss' and len(blob)<=start<=start+size<=symbols['__end'],
                    'Unexpected resident BSS extent')
            continue
        require(kind==1 and name in (b'.text',b'.rodata',b'.data') and
                start+size<=len(blob) and offset+size<=len(raw) and
                raw[offset:offset+size]==blob[start:start+size],
                'Resident ELF and initialized image differ')
        if not flags&1: immutable.append([start,size])
        if flags&4: executable.append([start,size])
    layout={'image_size':len(blob),'memory_size':symbols['__end'],
            'bss_start':symbols['__bss_start'],'bss_end':symbols['__bss_end'],
            'alignment':4096,'scratch_size':symbols['__scratch_size'],
            'scratch_alignment':64,'entry_offset':symbols['resident_entry'],
            'immutable_ranges':immutable,'executable_ranges':executable}
    validate_layout(blob,symbols,layout)
    return layout

def validate_layout(blob,symbols,layout):
    require(symbols.get('__start')==0 and len(blob)==symbols.get('__image_end')==layout['image_size'] and
            layout['bss_start']==symbols['__bss_start']==len(blob) and
            len(blob)<=layout['bss_end']==symbols['__bss_end']<=layout['memory_size']==symbols['__end'] and
            layout['entry_offset']==symbols['resident_entry'] and
            layout['scratch_size']==symbols['__scratch_size'] and
            layout['alignment']==4096 and layout['scratch_alignment']==64,
            'Resident manifest layout differs from symbols')
    require(len(blob)<=symbols['state']<=layout['memory_size']-64,
            'Resident state is outside BSS')
    ranges=layout['immutable_ranges']
    require(ranges and ranges==sorted(ranges), 'Missing or unordered immutable resident sections')
    end=0
    for start,size in ranges:
        require(type(start) is int and type(size) is int and end<=start and
                0<size<=len(blob)-start, 'Invalid immutable resident range')
        end=start+size
    executable=layout['executable_ranges']
    require(executable and all(r in ranges for r in executable) and
            any(start<=layout['entry_offset']<=start+size-4 for start,size in executable),
            'Resident entry is outside immutable executable sections')

def receipt_control(record):
    fields=dict(record['control'])
    fields['image_sha256']=bytes.fromhex(fields['image_sha256'])
    fields['reserved']=tuple(fields['reserved'])
    c=segmented.Control(**fields)
    c.pack()  # Reject invalid integer widths before using any address.
    require(c.magic==segmented.CONTROL_MAGIC and c.abi_version==segmented.ABI and
            c.struct_size==256 and c.identity_nonce and not c.reserved0 and not any(c.reserved),
            'Invalid segmented control receipt')
    return c

def segmented_artifacts(m):
    require(m.get('format')==segmented.FORMAT and m.get('abi_version')==segmented.ABI,
            'Unsupported segmented manifest')
    saved=m['loader']
    artifact=segmented.LoaderArtifact(archived_image(saved['image'],saved['sha256']),
                                     saved['symbols'],saved['sha256'])
    blob=archived_image(m['image'],m['image_sha256'])
    validate_layout(blob,m['symbols'],m['layout'])
    layout=m['layout']
    package=segmented.ResidentImage(blob,layout['memory_size'],layout['entry_offset'],
                                    layout['scratch_size'],m['image_sha256'])
    if 'loader_record' in m:
        r=m['loader_record']; c=receipt_control(r)
        require(r['format']==segmented.FORMAT and r['abi_version']==segmented.ABI and
                r['loader_sha256']==artifact.sha256 and r['resident_sha256']==package.sha256 and
                (c.image_size,c.memory_size,c.scratch_size,c.entry_offset,c.image_crc32,c.image_sha256)==
                (len(blob),package.memory_size,package.scratch_size,package.entry_offset,
                 package.crc32,bytes.fromhex(package.sha256)), 'Saved segmented identity/layout mismatch')
    return artifact,package

def with_receipt(manifest,receipt):
    c=receipt['control']
    return {**manifest,'loader_record':receipt,'phase':receipt['phase'],
            'nonce':c['identity_nonce'],'resident':c['resident'],'buffer':c['transport_buffer'],
            'stage':c['transport_buffer']+segmented.STAGE_OFFSET}

def segmented_checks(manifest):
    def verify(p,command,receipt):
        buf=preflight(p)
        target=manifest['target']
        require(target['package_sha256']==PACKAGE_SHA256 and target['rtos_sha256']==RTOS_SHA256,
                'Saved package targets another firmware')
        for address,size,digest in target['fingerprints']:
            require(hashlib.sha256(read_chunks(p,address,size)).hexdigest()==digest,
                    f'Saved firmware fingerprint mismatch at {address:#x}')
        for address,value in target['permissions']:
            require(p.qword(address)==value, 'Saved code page permissions differ')
        expected=receipt['phase']=='committed' or command==segmented.REMOVE and receipt['phase']!='removed'
        found=installation(p,with_receipt(manifest,receipt))
        require((found is not None)==expected, 'Segmented hook postcondition mismatch')
        return buf
    return segmented.Checks(check_callback,require_idle_still,verify)

def phase_recorder(manifest):
    def persist(receipt):
        manifest.update(with_receipt(manifest,receipt))
        save_manifest(manifest)
    return persist

def save_manifest(record):
    WORK.mkdir(parents=True,exist_ok=True)
    tmp=MANIFEST.with_suffix('.tmp')
    with tmp.open('w') as f:
        f.write(json.dumps(record,indent=2)+'\n')
        f.flush(); os.fsync(f.fileno())
    tmp.replace(MANIFEST)
    _sync_directory(WORK)

def installation(p, record=None):
    m=record if record is not None else read_manifest()
    patches=m.get('patches',LEGACY_PATCHES) if m else PATCHES
    pointers=[p.qword(a) for a,_,_ in patches]
    if pointers==[o for _,o,_ in patches]:
        require(all(int.from_bytes(p.read(a,n),'little')==o
                    for a,o,_,n in (m or {}).get('code_patches',())),
                'Saved code hooks are not restored')
        require(all(p.qword(a)==o for a,o,_ in PATCHES),'Unexpected hooks outside the saved installation')
        require(all(int.from_bytes(p.read(a,n),'little')==o for a,o,_,n in CODE_PATCHES),
                'Unexpected code hooks without an installed image')
        return None
    require(m is not None, 'Unrecognized hooks; local installation record is missing')
    require('nonce' in m and 'symbols' in m, 'Local record is incomplete; power-cycle to restore stock hooks')
    if 'resident' not in m:
        require(m.get('format')!=segmented.FORMAT,
                'Segmented allocation receipt missing; do not infer or resume it')
        # Recover only from the exact uploaded image/nonce if the host stopped
        # after triggering but before writing its final installation record.
        m['resident']=pointers[0]-m['symbols']['live_wrapper']
    require(BASE+0x10000<=m['resident']<=0x4fff00000 and m['resident']%4096==0,
            'Resident address is outside the supported allocation range')
    require(pointers==[m['resident']+m['symbols'][name] for _,_,name in patches],
            'Hook pointers do not match this installation')
    covered_pointers={a for a,_,_ in patches}
    require(all(p.qword(a)==o for a,o,_ in PATCHES if a not in covered_pointers),
            'Unexpected pointer hooks outside the saved installation')
    code_patches=m.get('code_patches',())
    require(all(int.from_bytes(p.read(a,n),'little')==v for a,_,v,n in code_patches),
            'Code hooks do not match this installation')
    covered={a for a,_,_,_ in code_patches}
    require(all(int.from_bytes(p.read(a,n),'little')==o
                for a,o,_,n in CODE_PATCHES if a not in covered),
            'Unexpected code hooks outside the saved installation')
    address=m['resident']+m['symbols']['state']
    state=p.read(address,64)
    require(u64(state)==MAGIC and u32(state,8)==1 and u64(state,16)==m['nonce'],
            'Resident identity does not match this installation')
    if m.get('format')==segmented.FORMAT:
        artifact,package=segmented_artifacts(m)
        c=receipt_control(m['loader_record'])
        segmented._allocation(c)
        require(c.resident==m['resident'] and c.identity_nonce==m['nonce'] and
                u64(state,24)==c.owner, 'Segmented resident owner/identity mismatch')
        for start,size in m['layout']['immutable_ranges']:
            actual=read_chunks(p,m['resident']+start,size)
            require(actual==package.image[start:start+size],
                    f'Installed resident code differs from saved image at +{start:#x}')
    m['state_address']=address
    return m

def execute(p, blob, symbols, buf, command=0, resident=0, mode=0, record=None):
    # Read responses are limited to 0x4000. Code/results at +0x8000 cannot be
    # overwritten by readback. The permanent wrappers live in an RTOS allocation.
    nonce=secrets.randbits(64) or 1
    data=bytearray(blob)
    control=symbols['control']
    struct.pack_into('<8Q2IQ',data,control,nonce,0,0,resident,0,0,0,0,command,mode,0)
    # The first working prototype used +0x8000. The stable launcher is placed
    # at the previously unused +0xc000, and publishes future C-code uploads
    # before branching to their fixed +0x100 entry. Legacy removal uses its
    # byte-identical original image at its original staging address.
    stage=buf+(0xc000 if 'launch' in symbols else 0x8000)
    require(len(data)<=0x4000,'Payload is too large for single verified upload')
    if record is not None:
        record.update(nonce=nonce,stage=stage)
        save_manifest(record)
    check_callback(p)
    say(f'Uploading {len(data)} bytes to RAM; this transport also schedules a calibration save.')
    p.write(stage,data)
    deadline=time.monotonic()+6
    while True:
        # Keep readback below the camera's maximum-size response boundary.
        # This remains one upload; only the read-only comparison is chunked.
        readback=b''.join(p.read(stage+i,min(0x1000,len(data)-i))
                          for i in range(0,len(data),0x1000))
        if readback==data: break
        require(time.monotonic()<deadline,'Payload readback failed; no trigger or retry was sent')
        time.sleep(.2)
    # PTP.write enforces a persisted ten-second cooldown before this second write.
    check_callback(p)
    say('Upload verified. Waiting for the save cooldown, then triggering once.')
    p.write(CALLBACK_SLOT,struct.pack('<Q',stage))
    deadline=time.monotonic()+15
    while True:
        result=p.read(stage+control,80)
        if u64(result,8)==nonce: break
        require(time.monotonic()<deadline,
                'No completion nonce received. Outcome is uncertain; no retry was sent. Power-cycle to recover.')
        time.sleep(.2)
    check_callback(p)
    require(p.qword(L2_SLOT)==L2_RO,'Code page permissions did not restore')
    require(u32(result,72)==0,
            f'Original storage writer reported {u32(result,72):#x}; hooks may be installed. Do not retry.')
    require(u64(result,16)==0,f'Payload stopped with result {u64(result,16)}; no retry was sent')
    return {'nonce':nonce,'resident':u64(result,24),'stage':stage,
            'registers':dict(zip(('el','ctr','mair','tcr'),struct.unpack_from('<4Q',result,32)))}

def install(p, firmware, enabled=False, subject_detection=False):
    require(firmware and Path(firmware).is_file(),'Supply the original BF__V104.bin with --firmware')
    with open(firmware,'rb') as f: digest=hashlib.file_digest(f,'sha256').hexdigest()
    require(digest==PACKAGE_SHA256,'This is not the analyzed BF 1.04 package')
    buf=preflight(p)
    require(installation(p) is None,'Already installed. Remove before installing a different build.')
    require_idle_still(p)
    require(p.qword(0x4d7303098)==0x4d3398940,'Unexpected active still handler')
    blob,symbols=build()
    require(native_aspect_code_patches()==NATIVE_ASPECT_CODE_PATCHES,
            'Native aspect call list changed after CLI import; restart before installation')
    layout=resident_layout(blob,symbols)
    if subject_detection:
        configured=bytearray(blob)
        struct.pack_into('<I',configured,symbols['focus_target'],1)
        blob=bytes(configured)
    loader_bytes,loader_symbols=build_loader()
    artifact=segmented.LoaderArtifact(loader_bytes,loader_symbols)
    package=segmented.ResidentImage(blob,layout['memory_size'],layout['entry_offset'],layout['scratch_size'])
    previous=read_manifest()
    if previous:
        if previous.get('format')==segmented.FORMAT:
            require(previous.get('phase') in ('packaged','committed','removed'),
                    'Previous segmented operation is incomplete/uncertain; no automatic retry or resume')
        if previous.get('stage')==buf+0xc000:
            saved=previous['loader'] if previous.get('format')==segmented.FORMAT else {
                'image':previous['image'],'sha256':previous['image_sha256']}
            old=archived_image(saved['image'],saved['sha256'])
            require(old[:256]==artifact.image[:256],
                    'The fixed launcher changed at a previously used address; do not hot-replace it')
    image_name,image_hash=archive_image('resident',blob)
    loader_name,loader_hash=archive_image('loader',artifact.image)
    record={'format':segmented.FORMAT,'abi_version':segmented.ABI,
            'symbols':symbols,'image':image_name,'image_sha256':image_hash,
            'loader':{'image':loader_name,'sha256':loader_hash,'symbols':loader_symbols},
            'layout':layout,'package_sha256':digest,'buffer':buf,'phase':'packaged','patches':PATCHES,
            'bf_plus_version':'1.0','code_patches':CODE_PATCHES,
            'target':{'package_sha256':digest,'rtos_sha256':RTOS_SHA256,
                      'fingerprints':[[a,32,h] for a,h in FINGERPRINTS.items()]+
                                     [[a,n,h] for (a,n),h in ASPECT_FINGERPRINTS.items()],
                      'permissions':[[L2_SLOT,L2_RO],[UI_L2_SLOT,UI_L2_RO]]},
            'features':{'touch_zoom':bool(enabled),'mf_subject_detection':bool(subject_detection),
                        'aspect_ratios':True,'extra_aspect_ratios_default':False,
                        'touch_menus':False,'auto_rotate_ui':False,'focus_guide':False,'validation':'offline; hardware pending'}}
    save_manifest(record)
    say(f'Loading {len(blob)} resident bytes through the {len(artifact.image)}-byte segmented loader. '
        'Every write observes the calibration-save cooldown.')
    segmented.execute(p,artifact,package,checks=segmented_checks(record),
                      on_phase=phase_recorder(record),mode=int(enabled))
    say('BF+ v1.0 RAM hooks verified; touch zoom '+('enabled' if enabled else 'disabled')+'.')

def prepare_remove(p,m):
    """Prepare removal, including the saved drain ABI of older UI builds."""
    require_idle_still(p)
    state=p.read(m['state_address'],64)
    require(not u32(state,32),'Release the center button and return to live view before removal')
    if 'aspect_jobs' in m['symbols']:
        capture=u32(p.read(m['resident']+m['symbols']['aspect_ratio']+12,4))
        jobs=p.read(m['resident']+m['symbols']['aspect_jobs'],192)
        require(not (capture>>8) and not any(jobs),
                'Aspect photos are still queued or saving; removal has not started')
    if 'ui' not in m['symbols']: return  # Archived images predating global UI.
    symbols=m['symbols']
    names=('__ui_removing_offset','__ui_displayed_offset','__ui_ready_offset','__ui_frame_offset')
    require(all(name in symbols for name in names),
            'Saved UI image has no drain ABI; power-cycle instead of removing it')
    offsets=[symbols[name] for name in names]
    require(len(set(offsets))==4 and all(type(o) is int and o>=0 and o%4==0 and
            symbols['__bss_start']<=symbols['ui']+o<=symbols['__end']-4 for o in offsets),
            'Saved UI drain offsets are outside resident BSS')
    base=m['resident']+symbols['ui']
    m.update(phase='draining',ui_drain={'phase':'draining','address':base+offsets[0]})
    save_manifest(m)  # Durable intent precedes this asynchronous RAM write too.
    try:
        with p._io_lock:
            check_callback(p)
            p.write(base+offsets[0],struct.pack('<I',1))
            deadline=time.monotonic()+15
            while True:
                values=tuple(u32(p.read(base+o,4)) for o in offsets)
                if values==(1,0,1,0):
                    confirm=tuple(u32(p.read(base+o,4)) for o in offsets)
                    if confirm==values: break
                require(time.monotonic()<deadline,
                        'UI drain did not complete; no remover or retry sent. Inspect or power-cycle.')
                time.sleep(.2)
            check_callback(p)
            require_idle_still(p)
        m.update(phase='drained',ui_drain={**m['ui_drain'],'phase':'drained'})
        save_manifest(m)
    except BaseException as error:
        m.update(phase='uncertain',ui_drain={**m['ui_drain'],'phase':'uncertain','error':str(error)})
        try: save_manifest(m)
        except BaseException as failure: error.add_note(f'Could not record UI drain failure: {failure}')
        raise

def remove(p):
    buf=preflight(p); m=installation(p)
    if m is None: say('No touch-focus hooks are installed.'); return
    if m.get('format')==segmented.FORMAT:
        require(m.get('phase')=='committed' and m['loader_record']['phase']=='committed',
                'Segmented completion is uncertain; inspect, do not retry removal')
        artifact,package=segmented_artifacts(m)
        segmented._guard(p,receipt_control(m['loader_record']),segmented.COMMITTED)
        prepare_remove(p,m)
        try:
            segmented.remove(p,artifact,package,m['loader_record'],checks=segmented_checks(m),
                             on_phase=phase_recorder(m))
        except BaseException as error:
            if m.get('phase')=='drained':
                m.update(phase='uncertain',error=str(error))
                try: save_manifest(m)
                except BaseException as failure: error.add_note(f'Could not record removal failure: {failure}')
            raise
        say('Original hooks and permissions restored. Resident/scratch allocations remain until reboot.')
        return
    blob=archived_image(m['image'],m['image_sha256'])
    require(m.get('ui_drain',{}).get('phase') not in ('draining','drained','uncertain'),
            'Previous UI drain/removal is uncertain; no retry')
    prepare_remove(p,m)
    execute(p,blob,m['symbols'],buf,command=1,resident=m['resident'])
    require(installation(p) is None,'Removal did not verify')
    m['phase']='removed'; save_manifest(m)
    say('Original hooks and permissions restored. The small allocation is reclaimed on reboot.')

def set_mode(p, enabled):
    preflight(p); m=installation(p)
    require(m is not None,'Install the hooks first')
    require(m.get('format')!=segmented.FORMAT or m.get('phase')=='committed',
            'Segmented completion is uncertain; mode writes are disabled')
    if m.get('format')==segmented.FORMAT:
        segmented._guard(p,receipt_control(m['loader_record']),segmented.COMMITTED)
    addr=m['state_address']+12
    check_callback(p)
    p.write(addr,struct.pack('<I',int(enabled)))
    deadline=time.monotonic()+5
    while u32(p.read(addr,4))!=int(enabled):
        require(time.monotonic()<deadline,'Mode readback failed; no retry was sent')
        time.sleep(.2)
    say('Touch zoom '+('enabled.' if enabled else 'disabled.'))

def ui_status(p,m):
    """Read only the published UI ABI recorded with this installed image."""
    symbols=m['symbols']
    fields={'displayed_raw':'__ui_displayed_offset','input_ready':'__ui_ready_offset',
            'frame_mask':'__ui_frame_offset','removing':'__ui_removing_offset'}
    required={'menu_orientation','ui','__bss_start','__end',*fields.values()}
    if not required<=symbols.keys(): return None
    require(all(type(symbols[name]) is int for name in required), 'Invalid saved UI status ABI')
    offsets={name:symbols['ui']+symbols[export] for name,export in fields.items()}
    offsets['enabled']=symbols['menu_orientation']+20
    require(all(symbols[export]>=0 for export in fields.values()) and
            all(offset%4==0 and symbols['__bss_start']<=offset<=symbols['__end']-4
                for offset in offsets.values()), 'Saved UI status fields are outside resident BSS')
    values={name:u32(p.read(m['resident']+offset,4)) for name,offset in offsets.items()}
    for name in ('enabled','input_ready','removing'): values[name]=bool(values[name])
    values['displayed_orientation']={0:'landscape',1:'portrait',3:'portrait'}.get(
        values['displayed_raw'],'unknown')
    return values

def status(p):
    buf=preflight(p); m=installation(p)
    result={'installed':m is not None,'read_buffer':hex(buf),
            'raw_center':u32(p.read(0x4d72c2468,4))&0x401,
            'depth':u32(p.read(0x4d70346a0,4)), 'pending':u32(p.read(0x4d70346a4,4))}
    saved=read_manifest()
    if saved and saved.get('format')==segmented.FORMAT:
        result.update(format=segmented.FORMAT,phase=saved['phase'],
                      outcome_uncertain=saved['phase'] not in ('packaged','committed','removed'))
    if m:
        s=p.read(m['state_address'],64)
        result.update(resident=hex(m['resident']),version=m.get('bf_plus_version','prototype'),
                      mode=u32(s,12),active=u32(s,32),
                      held=u32(s,36),events=u32(s,48),replay_errors=u32(s,56),exit_errors=u32(s,60))
        if 'features' in m: result['installed_features']=m['features']
        orientation=ui_status(p,m)
        if orientation is not None: result['auto_rotate_ui']=orientation
        if 'focus_target' in m['symbols']:
            t=p.read(m['resident']+m['symbols']['focus_target'],32)
            result['mf_subject_detection']={
                'enabled':bool(u32(t)), 'position_owned':bool(u32(t,4)),
                'source':{0:'none',1:'native_target',2:'legacy_candidate_1',3:'legacy_candidate_2'}.get(u32(t,8),'unknown'),
                'attempts':u32(t,12), 'last_position':struct.unpack_from('<2H',t,20),
                'misses':u32(t,24), 'unstable_snapshots':u32(t,28)}
        if 'aspect_extra_enabled' in m['symbols']:
            result['extra_aspect_ratios']=bool(u32(p.read(m['resident']+m['symbols']['aspect_extra_enabled'],4)))
        if 'aspect_ratio' in m['symbols']:
            t=p.read(m['resident']+m['symbols']['aspect_ratio'],16)
            value=u32(t)
            result['aspect_ratio']={
                'selection':{0:'Native',1:'XPan (65:24)',2:'2.35:1',3:'5:4'}.get(value,'unknown'),
                'sensor_crop':u32(t,4), 'rejected_changes':u32(t,8),
                'pending_snapshots':u32(t,12)>>8, 'removal_sealed':bool(u32(t,12)&4),
                'active_photos':sum(bool(value) for value in p.read(
                    m['resident']+m['symbols']['aspect_jobs'],192))}
        if 'detector_gate' in m['symbols']:
            t=p.read(m['resident']+m['symbols']['detector_gate'],16)
            result['detector_processing']=dict(zip(
                ('calls','overrides','stock_mode','effective_mode'),struct.unpack('<4I',t)))
    return result

def observe(p,seconds):
    m=installation(p); previous=None; last_seq=0; last_state=None; start=time.monotonic()
    while time.monotonic()-start<seconds:
        raw=p.read(0x4d72c2468,16)
        if raw!=previous:
            say(json.dumps({'t':round(time.monotonic()-start,3),'raw':raw.hex(),
                            'center':u32(raw)&0x401}))
            previous=raw
        if m:
            s=p.read(m['state_address'],64+128*32)
            summary=(u32(s,12),u32(s,32),u32(s,36),u32(s,56),u32(s,60))
            if summary!=last_state:
                say(json.dumps(dict(zip(('mode','active','held','replay_errors','exit_errors'),summary))))
                last_state=summary
            sequence=u32(s,48)
            for seq in range(max(last_seq+1,sequence-127),sequence+1):
                offset=64+((seq-1)&127)*32
                values=struct.unpack_from('<4I5HHI',s,offset)
                if values[0]==seq:
                    say(json.dumps(dict(zip(('seq','scene','depth','pending','changed','touch','press',
                                             'repeat','count_padding','flags','lens'),values))))
            last_seq=sequence
        time.sleep(.08)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('build','status','install','remove','enable','disable','observe'))
    parser.add_argument('--firmware')
    parser.add_argument('--enable',action='store_true',help='Enable after install; otherwise only observe')
    parser.add_argument('--subject-detection',action='store_true',help='Install with MF Subject Detection On (default Off)')
    parser.add_argument('--seconds',type=float,default=60)
    args=parser.parse_args()
    try:
        if args.command=='build':
            blob,symbols=build(); loader_blob,loader_symbols=build_loader()
            say(json.dumps({'format':segmented.FORMAT,'bytes':len(blob),'symbols':symbols,
                            'layout':resident_layout(blob,symbols),
                            'loader':{'bytes':len(loader_blob),'symbols':loader_symbols,
                                      'sha256':hashlib.sha256(loader_blob).hexdigest()}},indent=2)); return
        with PTP() as p:
            if args.command=='status': say(json.dumps(status(p),indent=2))
            elif args.command=='install': install(p,args.firmware,args.enable,args.subject_detection)
            elif args.command=='remove': remove(p)
            elif args.command in ('enable','disable'): set_mode(p,args.command=='enable')
            elif args.command=='observe': observe(p,args.seconds)
    except KeyboardInterrupt:
        parser.exit(130,'Interrupted; no retry was made. If installation or removal was in progress, check status before continuing.\n')
    except (PTPError,RuntimeError,OSError,ValueError,KeyError,TypeError,struct.error) as exc:
        parser.exit(1,f'{exc}\n')

if __name__=='__main__': main()
