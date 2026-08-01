"""
Build CatSwitch onedir folder, then optionally Inno Setup installer.

Usage (from repository/):
  pip install -r requirements-dev.txt
  python package.py              # dist/CatSwitch/
  python package.py --installer  # + Setup (requires Inno Setup ISCC on PATH)
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
REQUIREMENTS_DEV = os.path.join(ROOT, "requirements-dev.txt")
THIRD_PARTY_NOTICES = os.path.join(ROOT, "THIRD_PARTY_NOTICES.txt")


def _app_version() -> str:
    sys.path.insert(0, ROOT)
    from catswitch.version import APP_VERSION

    return APP_VERSION


def _ensure_dev_dependencies() -> bool:
    """Install packaging deps from requirements-dev.txt (includes PyInstaller)."""
    if not os.path.isfile(REQUIREMENTS_DEV):
        print(f"Missing {REQUIREMENTS_DEV}")
        return False
    print(f"Ensuring packaging dependencies from {os.path.basename(REQUIREMENTS_DEV)}...")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", REQUIREMENTS_DEV],
            check=True,
            cwd=ROOT,
        )
        return True
    except subprocess.CalledProcessError as exc:
        print(f"Failed to install packaging dependencies: {exc}")
        return False


def _write_version_file(version: str) -> str:
    """Write a PyInstaller version-info resource file under dist/ and return its path."""
    from datetime import datetime

    parts = [int(p) for p in version.split(".")[:4]]
    while len(parts) < 4:
        parts.append(0)
    ver_tuple = tuple(parts)
    # Copyright notice for the PE version resource (LICENSE file itself is R02).
    legal_copyright = f"Copyright (c) {datetime.now().year} github.com/0yz"
    dist_dir = os.path.join(ROOT, "dist")
    os.makedirs(dist_dir, exist_ok=True)
    path = os.path.join(dist_dir, "file_version_info.txt")
    content = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={ver_tuple!r},
    prodvers={ver_tuple!r},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u'040904B0',
        [
          StringStruct(u'CompanyName', u'github.com/0yz'),
          StringStruct(u'FileDescription', u'CatSwitch'),
          StringStruct(u'FileVersion', u'{version}'),
          StringStruct(u'InternalName', u'CatSwitch'),
          StringStruct(u'LegalCopyright', u'{legal_copyright}'),
          StringStruct(u'OriginalFilename', u'CatSwitch.exe'),
          StringStruct(u'ProductName', u'CatSwitch'),
          StringStruct(u'ProductVersion', u'{version}')
        ]
      )
    ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"""
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
    return path


def build_exe(version: str) -> bool:
    print(f"Building CatSwitch onedir (v{version})...")
    if not _ensure_dev_dependencies():
        return False

    _write_inno_version_define(version)
    _write_version_file(version)

    # Tiny entry so PyInstaller keeps repo root on sys.path (not catswitch/).
    dist_dir = os.path.join(ROOT, "dist")
    os.makedirs(dist_dir, exist_ok=True)
    entry_path = os.path.join(dist_dir, "pyi_entry.py")
    with open(entry_path, "w", encoding="utf-8") as handle:
        handle.write(
            "from catswitch.__main__ import main\n\n"
            "if __name__ == '__main__':\n"
            "    main()\n"
        )

    # Use the checked-in .spec (SPECPATH-relative) — do not pass CLI flags that
    # would regenerate it with absolute machine paths.
    spec_path = os.path.join(ROOT, "CatSwitch.spec")
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        spec_path,
    ]
    try:
        subprocess.run(cmd, check=True, cwd=ROOT)
    except subprocess.CalledProcessError as exc:
        print(f"PyInstaller failed: {exc}")
        return False

    app_dir = os.path.join(ROOT, "dist", "CatSwitch")
    exe_path = os.path.join(app_dir, "CatSwitch.exe")
    if not os.path.isfile(exe_path):
        print(f"Expected output missing: {exe_path}")
        return False
    if not _copy_third_party_notices(app_dir):
        return False
    print(f"App folder ready: {app_dir}")
    return True


def _copy_third_party_notices(app_dir: str) -> bool:
    """Place THIRD_PARTY_NOTICES.txt next to the exe (Inno installs the folder)."""
    if not os.path.isfile(THIRD_PARTY_NOTICES):
        print(f"Missing {THIRD_PARTY_NOTICES}")
        return False
    dest = os.path.join(app_dir, "THIRD_PARTY_NOTICES.txt")
    shutil.copy2(THIRD_PARTY_NOTICES, dest)
    print(f"Notices ready: {dest}")
    return True


def _write_inno_version_define(version: str) -> str:
    """Write dist/version_define.iss from APP_VERSION for CatSwitch.iss #include."""
    dist_dir = os.path.join(ROOT, "dist")
    os.makedirs(dist_dir, exist_ok=True)
    path = os.path.join(dist_dir, "version_define.iss")
    content = (
        "; Generated by package.py from catswitch.version.APP_VERSION — do not edit.\n"
        f'#define MyAppVersion "{version}"\n'
    )
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
    return path


def find_iscc() -> str | None:
    candidates = [
        shutil.which("ISCC"),
        shutil.which("iscc"),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"),
    ]
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return None


def build_installer(version: str) -> bool:
    iscc = find_iscc()
    if not iscc:
        print(
            "Inno Setup (ISCC) not found. Install Inno Setup 6 and ensure ISCC is on PATH,\n"
            "or re-run after installing to the default Program Files location."
        )
        return False

    _write_inno_version_define(version)
    iss = os.path.join(ROOT, "CatSwitch.iss")
    cmd = [iscc, iss]
    print(f"Building installer with {iscc} (MyAppVersion={version})...")
    try:
        subprocess.run(cmd, check=True, cwd=ROOT)
    except subprocess.CalledProcessError as exc:
        print(f"Inno Setup failed: {exc}")
        return False

    setup = os.path.join(ROOT, "dist", f"CatSwitch-Setup-{version}.exe")
    if not os.path.isfile(setup):
        print(f"Expected installer missing: {setup}")
        return False
    print(f"Installer ready: {setup}")
    digest = _sha256_file(setup)
    print(f"SHA256: {digest}")
    print("(GitHub Releases also expose this as asset.digest after upload — no code signing yet.)")
    return True


def _sha256_file(path: str) -> str:
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 256), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Package CatSwitch for Windows")
    parser.add_argument(
        "--installer",
        action="store_true",
        help="Also build the Inno Setup installer (requires ISCC)",
    )
    args = parser.parse_args()
    version = _app_version()

    if not build_exe(version):
        return 1
    if args.installer and not build_installer(version):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
