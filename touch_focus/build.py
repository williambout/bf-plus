"""Compile only original hook code; never include or modify Sigma firmware."""
from pathlib import Path
import json
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / ".touch-focus" / "build"

def tool(name, fallback):
    p = shutil.which(name) or fallback
    if not Path(p).is_file():
        raise RuntimeError(f"Missing {name}: install LLVM and lld")
    return p

def build():
    BUILD.mkdir(parents=True, exist_ok=True)
    clang = tool("clang", "/opt/homebrew/opt/llvm/bin/clang")
    ld = tool("ld.lld", "/opt/homebrew/opt/lld/bin/ld.lld")
    objcopy = tool("llvm-objcopy", "/opt/homebrew/opt/llvm/bin/llvm-objcopy")
    nm = tool("llvm-nm", "/opt/homebrew/opt/llvm/bin/llvm-nm")
    readelf = tool("llvm-readelf", "/opt/homebrew/opt/llvm/bin/llvm-readelf")
    src = ROOT / "touch_focus" / "payload.c"
    obj, elf, binary = (BUILD / name for name in ("payload.o", "payload.elf", "payload.bin"))
    launcher = BUILD / "launch.o"
    for source, output in ((src, obj),):
        subprocess.run([clang, "--target=aarch64-none-elf", "-Oz", "-ffreestanding",
                    "-fno-builtin", "-fno-stack-protector", "-fno-unwind-tables",
                    "-fno-asynchronous-unwind-tables", "-mgeneral-regs-only", "-ffixed-x18",
                    "-fno-jump-tables", "-ffunction-sections", "-fdata-sections",
                    "-mcmodel=tiny", "-fpie", "-fvisibility=hidden", "-Wall", "-Wextra", "-Werror",
                    "-c", str(source), "-o", str(output)], check=True)
    subprocess.run([clang, "--target=aarch64-none-elf", "-c",
                    str(ROOT / "touch_focus" / "launch.S"), "-o", str(launcher)], check=True)
    relocs = subprocess.check_output([readelf, "-r", str(obj), str(launcher)], text=True)
    allowed = {"R_AARCH64_ADR_PREL_LO21", "R_AARCH64_LD_PREL_LO19",
               "R_AARCH64_CALL26", "R_AARCH64_JUMP26", "R_AARCH64_PREL32"}
    unexpected = set(re.findall(r"R_AARCH64_\w+", relocs)) - allowed
    if unexpected:
        raise RuntimeError(f"Payload is not position independent: {unexpected}")
    subprocess.run([ld, "--gc-sections", "-T", str(ROOT / "touch_focus" / "payload.ld"),
                    str(launcher), str(obj), "-o", str(elf)], check=True)
    subprocess.run([objcopy, "-O", "binary", str(elf), str(binary)], check=True)
    output = subprocess.check_output([nm, "--defined-only", str(elf)], text=True)
    symbols = {}
    for line in output.splitlines():
        fields = line.split()
        if len(fields) == 3:
            symbols[fields[2]] = int(fields[0], 16)
    raw = binary.read_bytes()
    image_size, memory_size = symbols["__image_end"], symbols["__end"]
    # This is the resident image. Images exceeding one transfer require the
    # separate segmented loader; host execute() still rejects oversized staging.
    if not (0 < image_size <= memory_size <= 0x10000):
        raise RuntimeError("Invalid upload/resident extent")
    if symbols["__bss_start"] != image_size or symbols["__bss_end"] > memory_size:
        raise RuntimeError("Invalid zero-initialized tail")
    if len(raw) > image_size or symbols["control"] + 80 > image_size or symbols["focus_target"] + 32 > image_size:
        raise RuntimeError("Initialized image or host configuration lies beyond upload")
    # Reject orphan allocated sections: everything copied must be in the
    # uploaded prefix, and everything after it must be zero-initialized.
    sections = json.loads(subprocess.check_output(
        [readelf, "--elf-output-style=JSON", "-S", str(elf)], text=True))[0]["Sections"]
    for entry in sections:
        section = entry["Section"]
        if not section["Flags"]["Value"] & 2:
            continue
        name, kind = section["Name"]["Name"], section["Type"]["Name"]
        first, last = section["Address"], section["Address"] + section["Size"]
        if name in (".text", ".rodata", ".data"):
            valid = kind == "SHT_PROGBITS" and 0 <= first <= last <= image_size
        elif name == ".bss":
            valid = kind == "SHT_NOBITS" and image_size <= first <= last <= memory_size
        else:
            valid = False
        if not valid:
            raise RuntimeError(f"Unexpected allocated section or extent: {name}")
    if subprocess.check_output([nm, "--undefined-only", str(elf)], text=True).strip():
        raise RuntimeError("Unresolved freestanding dependency")
    blob = raw.ljust(image_size, b"\0")
    if len(blob) > 0x10000 or symbols["launch"] != 0 or symbols["bootstrap"] != 0x100:
        raise RuntimeError("Resident image exceeds supported size or entry moved")
    binary.write_bytes(blob)
    (BUILD / "symbols.json").write_text(json.dumps(symbols, indent=2)+"\n")
    return blob, symbols

if __name__ == "__main__":
    b, s = build()
    print(json.dumps({"bytes":len(b), "symbols":s}, indent=2))
