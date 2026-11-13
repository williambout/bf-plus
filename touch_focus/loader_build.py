"""Build only the standalone segmented loader, never the production resident.

build() uses temporary output by default. CLI: python -m touch_focus.loader_build
--out /chosen/directory. No device access and no imports from the legacy builder.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

SOURCE = Path(__file__).resolve().parent
FLAGS = ['--target=aarch64-none-elf', '-std=c11', '-Oz', '-ffreestanding',
         '-fno-builtin', '-fno-stack-protector', '-fno-unwind-tables',
         '-fno-asynchronous-unwind-tables', '-mgeneral-regs-only', '-ffixed-x18',
         '-fno-jump-tables', '-ffunction-sections', '-fdata-sections',
         '-mcmodel=tiny', '-fpie', '-fvisibility=hidden', '-Wall', '-Wextra', '-Werror']


def tool(name):
    package = 'lld' if name == 'ld.lld' else 'llvm'
    local = Path('/opt/homebrew/opt') / package / 'bin' / name
    found = str(local) if local.is_file() else shutil.which(name)
    if not found:
        raise RuntimeError(f'Missing offline build tool: {name}')
    return found


def _build(directory):
    directory = Path(directory).resolve()
    if directory == (SOURCE.parent/'.touch-focus/build').resolve():
        raise ValueError('Refusing the shared production build directory')
    directory.mkdir(parents=True, exist_ok=True)
    obj, launch, elf, binary = (directory/name for name in
                                ('loader.o', 'loader-launch.o', 'loader.elf', 'loader.bin'))
    subprocess.run([tool('clang'), *FLAGS, '-c', str(SOURCE/'loader.c'), '-o', str(obj)], check=True)
    subprocess.run([tool('clang'), '--target=aarch64-none-elf', '-c', str(SOURCE/'launch.S'),
                    '-o', str(launch)], check=True)
    relocs = subprocess.check_output([tool('llvm-readelf'), '-r', str(obj), str(launch)], text=True)
    allowed = {'R_AARCH64_ADR_PREL_LO21', 'R_AARCH64_LD_PREL_LO19',
               'R_AARCH64_CALL26', 'R_AARCH64_JUMP26', 'R_AARCH64_PREL32'}
    unexpected = set(re.findall(r'R_AARCH64_\w+', relocs)) - allowed
    if unexpected:
        raise RuntimeError(f'Non-PIC loader relocations: {unexpected}')
    subprocess.run([tool('ld.lld'), '--gc-sections', '-T', str(SOURCE/'loader.ld'),
                    str(launch), str(obj), '-o', str(elf)], check=True)
    if subprocess.check_output([tool('llvm-nm'), '--undefined-only', str(elf)], text=True).strip():
        raise RuntimeError('Unresolved standalone loader dependency')
    symbols = {}
    for line in subprocess.check_output([tool('llvm-nm'), '--defined-only', str(elf)], text=True).splitlines():
        fields = line.split()
        if len(fields) == 3:
            symbols[fields[2]] = int(fields[0], 16)
    extent = symbols['__image_end']
    if not (symbols['launch'] == 0 and symbols['bootstrap'] == 0x100 and
            symbols['__end'] == extent and 0 < extent <= 0x4000 and
            0x100 <= symbols['loader_control'] <= extent-256 and
            symbols['loader_control'] % 64 == 0):
        raise RuntimeError('Invalid loader layout')
    sections = json.loads(subprocess.check_output(
        [tool('llvm-readelf'), '--elf-output-style=JSON', '-S', str(elf)], text=True))[0]['Sections']
    for entry in sections:
        s = entry['Section']
        if not s['Flags']['Value'] & 2 or s['Size'] == 0:
            continue
        if not (s['Name']['Name'] in ('.text', '.rodata', '.data') and
                s['Type']['Name'] == 'SHT_PROGBITS' and
                0 <= s['Address'] <= s['Address']+s['Size'] <= extent):
            raise RuntimeError(f'Unexpected allocated loader section: {s["Name"]["Name"]}')
    subprocess.run([tool('llvm-objcopy'), '-O', 'binary', str(elf), str(binary)], check=True)
    raw = binary.read_bytes()
    if len(raw) > extent:
        raise RuntimeError('Loader binary exceeds declared image')
    raw = raw.ljust(extent, b'\0')
    if any(raw[symbols['loader_control']:symbols['loader_control']+256]):
        raise RuntimeError('Immutable loader artifact contains live control state')
    binary.write_bytes(raw)
    manifest = {'format': 'bfplus-loader-v1', 'abi_version': 1,
                'image_size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
                'stage_offset': 0xc000, 'control_size': 256, 'symbols': symbols}
    (directory/'loader.json').write_text(json.dumps(manifest, indent=2)+'\n')
    return raw, symbols


def build(directory=None):
    if directory is not None:
        return _build(directory)
    with tempfile.TemporaryDirectory(prefix='bf-segmented-loader-build-') as temporary:
        return _build(temporary)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    blob, syms = build(args.out)
    print(json.dumps({'bytes': len(blob), 'sha256': hashlib.sha256(blob).hexdigest(),
                      'symbols': syms}, indent=2))
