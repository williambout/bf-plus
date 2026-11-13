"""Explicit opt-in download of redistributable Freedoom 0.13.0 test data.

Builds and tests never invoke this script or require network access.
"""
import hashlib
from pathlib import Path
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / ".touch-focus/doom-engine"
URL = "https://github.com/freedoom/freedoom/releases/download/v0.13.0/freedoom-0.13.0.zip"
SHA256 = "3f9b264f3e3ce503b4fb7f6bdcb1f419d93c7b546f4df3e874dd878db9688f59"
WADS = {
    "freedoom1.wad": "7323bcc168c5a45ff10749b339960e98314740a734c30d4b9f3337001f9e703d",
    "freedoom2.wad": "a8772e088847032510d97ba2312406a6998f21cbab44d4ff10696faa9c0ecd4b",
}


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    archive = DEST / "freedoom-0.13.0.zip"
    if not archive.exists():
        with urllib.request.urlopen(URL, timeout=60) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != SHA256:
            raise RuntimeError("Freedoom archive SHA256 mismatch")
        archive.write_bytes(data)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise RuntimeError("Freedoom archive SHA256 mismatch")
    target = DEST / "freedoom-0.13.0"
    target.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for name in (*WADS, "COPYING.txt", "CREDITS.txt", "CREDITS-MUSIC.txt", "README.html"):
            data = z.read("freedoom-0.13.0/" + name)
            if name in WADS and hashlib.sha256(data).hexdigest() != WADS[name]:
                raise RuntimeError(f"Freedoom WAD SHA256 mismatch: {name}")
            (target / name).write_bytes(data)
    print(target)


if __name__ == "__main__":
    main()
