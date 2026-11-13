"""Apply small, checked adaptations; retain the pinned upstream file verbatim."""
import hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
UPSTREAM_SHA256 = "ec16ce721436bf3fa4c338320afedd56a93c0b563a94ebf283718503c71ca780"


def prepare(output):
    raw = (HERE / "vendor/PureDOOM.h").read_bytes()
    if hashlib.sha256(raw).hexdigest() != UPSTREAM_SHA256:
        raise RuntimeError("PureDOOM pinned source checksum mismatch")
    src = raw.decode("utf-8")
    # FixedDiv2 is the only floating-point arithmetic in upstream. This port
    # must run with SIMD/FP disabled and cannot depend on compiler-rt helpers.
    old = '''    double c;

    c = ((double)a) / ((double)b) * FRACUNIT;

    if (c >= 2147483648.0 || c < -2147483648.0)
        I_Error("Error: FixedDiv: divide by zero");
    return (fixed_t)c;'''
    new = '''    long long c;
    if (!b) I_Error("Error: FixedDiv: divide by zero");
    c = ((long long)a * FRACUNIT) / b;
    if (c > 2147483647LL || c < -2147483648LL)
        I_Error("Error: FixedDiv: overflow");
    return (fixed_t)c;'''
    assert src.count(old) == 1
    src = src.replace(old, new)
    # Three top-level const objects would conflict with the writable snapshot
    # section. Their values still never change, but reside with engine state.
    for declaration in ("const char french_shiftxform[]", "const char english_shiftxform[]",
                        "const int custom_texts_count"):
        assert src.count(declaration) == 1
        src = src.replace(declaration, declaration.removeprefix("const "))
    # The caller owns WAD data and has no save/config filesystem. Remove the
    # Save/Load menu actions rather than letting their write failures be fatal.
    for name in ("M_SaveGame", "M_LoadGame", "M_QuickSave", "M_QuickLoad"):
        import re
        pattern = r"(void " + name + r"\([^;{}]*\)\s*\{)"
        src, count = re.subn(pattern, r"\1\n    return; /* BF+: no persistent save storage. */", src)
        assert count == 1, name
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(src)
    return output
