"""Build a Windows x64 portable ZIP with dependency licenses and checksums."""
from pathlib import Path
import hashlib
import importlib.metadata
import json
import os
import shutil
import struct
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from version import __version__


def main():
    if sys.platform != "win32" or struct.calcsize("P") != 8:
        raise SystemExit("Build this release with 64-bit Python on Windows.")
    os.chdir(ROOT)
    env = dict(os.environ, PYINSTALLER_CONFIG_DIR=str(ROOT / "build" / "cache"))
    # Do not let unrelated applications on PATH supply incompatible ICU/OpenSSL
    # DLLs. Qt's hook adds its own wheel directory during binary discovery.
    windows = Path(os.environ.get("SystemRoot", "C:/Windows"))
    env["PATH"] = os.pathsep.join(map(str, (
        Path(sys.executable).parent, Path(sys.base_prefix), Path(sys.base_prefix) / "DLLs",
        windows / "System32", windows,
    )))
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--onedir", "--windowed", "--name", "Nova",
        "--version-file", str(ROOT / "packaging" / "windows-version.txt"),
        "--collect-submodules", "serial.urlhandler",
        "--distpath", "dist", "--workpath", "build/pyinstaller",
        "--specpath", "build", "main.py",
    ], check=True, env=env)
    package = ROOT / "dist" / "Nova"
    shutil.copy2(ROOT / "packaging" / "PORTABLE_README.txt", package / "README.txt")
    shutil.copytree(ROOT / "packaging" / "licenses", package / "third_party_licenses", dirs_exist_ok=True)
    versions = {}
    for name in ("PySide6", "PySide6_Addons", "PySide6_Essentials", "shiboken6",
                 "numpy", "pyqtgraph", "pyserial", "PyInstaller"):
        distribution = importlib.metadata.distribution(name)
        versions[name] = distribution.version
        metadata = distribution.read_text("METADATA")
        if metadata:
            target = package / "third_party_licenses" / name / "PACKAGE_METADATA.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(metadata, encoding="utf-8")
        for item in distribution.files or []:
            if any("license" in part.lower() or "copying" in part.lower() for part in item.parts):
                source = Path(distribution.locate_file(item))
                if source.is_file() and ".." not in item.parts:
                    target = package / "third_party_licenses" / name / str(item)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    for folder in (Path(sys.base_prefix), Path(sys.prefix)):
        license_file = folder / "LICENSE.txt"
        if license_file.is_file():
            target = package / "third_party_licenses" / "Python-LICENSE.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(license_file, target)
            break
    info = {"version": __version__, "platform": "windows-x64",
            "python": sys.version.split()[0], "dependencies": versions}
    (package / "BUILD_INFO.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    archive = ROOT / "dist" / f"Nova-v{__version__}-windows-x64.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as output:
        for path in sorted(package.rglob("*")):
            if path.is_file():
                output.write(path, Path("Nova") / path.relative_to(package))
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    (ROOT / "dist" / "SHA256SUMS.txt").write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    print(f"Built {archive.name}: {archive.stat().st_size} bytes", flush=True)
    print(f"SHA256: {digest}", flush=True)


if __name__ == "__main__":
    main()
