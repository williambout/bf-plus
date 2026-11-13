#!/usr/bin/env python3
"""Offline Doom module/host build. All generated files stay in .touch-focus/."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

from .prepare_engine import prepare, UPSTREAM_SHA256

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_OUT = ROOT / ".touch-focus/doom-engine/build"


def tool(name):
    candidates = [shutil.which(name), f"/opt/homebrew/opt/llvm/bin/{name}",
                  f"/opt/homebrew/opt/lld/bin/{name}"]
    for p in candidates:
        if p and Path(p).is_file():
            return p
    raise RuntimeError(f"Missing {name}; install Clang and lld")


def run(args):
    subprocess.run([str(x) for x in args], check=True)


def inspect_elf(path):
    """Validate the loader contract without pyelftools or external utilities."""
    data = Path(path).read_bytes()
    h = struct.unpack_from("<16sHHIQQQIHHHHHH", data)
    assert h[0][:6] == b"\x7fELF\x02\x01" and h[1:3] == (3, 183), "Expected AArch64 LE ET_DYN"
    entry, phoff, shoff = h[4:7]
    loads = []
    for i in range(h[10]):
        typ, flags, off, va, pa, fs, ms, align = struct.unpack_from("<IIQQQQQQ", data, phoff + i*h[9])
        if typ != 1:
            continue
        assert fs <= ms and off + fs <= len(data)
        assert flags & 3 != 3, "Writable executable segment"
        assert all(va + ms <= s["vaddr"] or s["vaddr"] + s["memsz"] <= va for s in loads)
        loads.append(dict(offset=off, vaddr=va, filesz=fs, memsz=ms, flags=flags, align=align))
    assert loads and min(s["vaddr"] for s in loads) == 0
    extent = max(s["vaddr"] + s["memsz"] for s in loads)
    assert extent <= 4*1024*1024, "Module exceeds loader limit"
    assert any(s["flags"] & 1 and s["vaddr"] <= entry < s["vaddr"]+s["filesz"] for s in loads)
    sections = [struct.unpack_from("<IIQQQQIIQQ", data, shoff + i*h[11]) for i in range(h[12])]
    count = 0
    symbols = {}
    for sec in sections:
        _, typ, flags, va, off, size, link, info, alignment, entsize = sec
        if typ == 4:  # SHT_RELA
            for p in range(off, off+size, entsize):
                target, rinfo, addend = struct.unpack_from("<QQq", data, p)
                assert rinfo == 1027, f"Unexpected relocation {rinfo:#x}"
                assert target % 8 == 0 and 0 <= addend < extent
                assert any(s["flags"] & 2 and s["vaddr"] <= target and
                           target+8 <= s["vaddr"]+s["filesz"] for s in loads)
                count += 1
        if typ == 9:
            raise AssertionError("REL relocations unsupported")
        if typ in (2, 11):
            st = sections[link]
            strings = data[st[4]:st[4]+st[5]]
            for p in range(off, off+size, entsize):
                name, sinfo, other, index, value, ssize = struct.unpack_from("<IBBHQQ", data, p)
                symbol = strings[name:].split(b"\0", 1)[0].decode()
                assert index != 0 or not symbol, f"Unresolved symbol: {symbol}"
                if symbol:
                    symbols[symbol] = value
    assert count and symbols["bfdoom_entry"] == entry
    return dict(abi_version=1, format="ELF64-LE-AArch64-ET_DYN", entry=entry,
                entry_symbol="bfdoom_entry", image_base=0, memory_size=extent,
                elf_bytes=len(data), initialized_bytes=sum(s["filesz"] for s in loads),
                relative_relocations=count, segments=loads,
                state_bytes=symbols["__stop_bfdoom_state"]-symbols["__start_bfdoom_state"],
                recommended_heap=24*1024*1024, recommended_stack=256*1024,
                sha256=hashlib.sha256(data).hexdigest(), upstream_sha256=UPSTREAM_SHA256)


def build(out=DEFAULT_OUT, host=False, sdl=False, sanitize=False):
    out = Path(out).resolve()
    if not out.is_relative_to(ROOT / ".touch-focus"):
        raise ValueError("Build artifacts must be under .touch-focus/")
    out.mkdir(parents=True, exist_ok=True)
    prepare(out / "PureDOOM_bf.h")
    cc = tool("clang")
    flags = ["-std=gnu11", "-O2", "-fwrapv", "-ffreestanding", "-fno-builtin",
             "-fno-stack-protector", "-fno-unwind-tables", "-fno-asynchronous-unwind-tables",
             "-fPIC", "-fvisibility=hidden", "-Wall", "-Wextra", "-Werror",
             f"-ffile-prefix-map={ROOT}=.",
             f"-ffile-prefix-map={out}=bfplus/doom_engine/generated", "-I", str(out)]
    armflags = ["--target=aarch64-none-elf", "-mgeneral-regs-only", "-ffixed-x18", "-DBFDOOM_GENERAL_REGS"]
    run([cc, *flags, *armflags, "-c", HERE / "bfdoom.c", "-o", out / "engine.o"])
    run([cc, *armflags, "-c", HERE / "bfdoom_jump.S", "-o", out / "jump.o"])
    run([tool("ld.lld"), "-shared", "-Bsymbolic", "--no-undefined", "-z", "max-page-size=4096",
         "-T", HERE / "module.ld", out / "engine.o", out / "jump.o", "-o", out / "bfdoom.elf"])
    metadata = inspect_elf(out / "bfdoom.elf")
    (out / "module.json").write_text(json.dumps(metadata, indent=2) + "\n")
    if host or sdl or sanitize:
        native = ["-fsanitize=address", "-g", "-fno-omit-frame-pointer"] if sanitize else []
        run([cc, *flags, *native, "-c", HERE / "bfdoom.c", "-o", out / "host-engine.o"])
        run([cc, "-c", HERE / "bfdoom_jump.S", "-o", out / "host-jump.o"])
        objects = [out / "host-engine.o", out / "host-jump.o"]
        # Library used by Python ABI tests; sanitizer runs in the executable.
        if not sanitize:
            lib = out / ("libbfdoom.dylib" if sys.platform == "darwin" else "libbfdoom.so")
            run([cc, "-dynamiclib" if sys.platform == "darwin" else "-shared", *objects, "-o", lib])
        run([cc, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", *native,
             HERE / "host_main.c", *objects, "-o", out / "bfdoom-host"])
        if sdl:
            import shlex
            sdlf = shlex.split(subprocess.check_output(["pkg-config", "--cflags", "--libs", "sdl2"], text=True))
            run([cc, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-DBFDOOM_SDL", *native,
                 HERE / "host_main.c", *objects, *sdlf, "-o", out / "bfdoom-sdl"])
    return metadata


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--host", action="store_true")
    p.add_argument("--sdl", action="store_true")
    p.add_argument("--sanitize", action="store_true")
    a = p.parse_args()
    print(json.dumps(build(a.out, a.host, a.sdl, a.sanitize), indent=2))


if __name__ == "__main__":
    main()
