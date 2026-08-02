# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules


bridge_dir = Path(SPECPATH).parent
sounddevice_data, sounddevice_binaries, sounddevice_hidden = collect_all("sounddevice")

analysis = Analysis(
    [str(bridge_dir / "packaging" / "agent_entry.py")],
    pathex=[str(bridge_dir)],
    binaries=sounddevice_binaries,
    datas=sounddevice_data,
    hiddenimports=(
        sounddevice_hidden
        + collect_submodules("zeroconf")
        + [
            "ApplicationServices",
            "AppKit",
            "Quartz",
            "Security",
        ]
    ),
    noarchive=False,
)

python_archive = PYZ(analysis.pure)

executable = EXE(
    python_archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="CardBridgeAgent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    target_arch="arm64",
)

collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="CardBridgeAgent",
)

app = BUNDLE(
    collection,
    name="CardBridgeAgent.app",
    icon=None,
    bundle_identifier="com.voltwake.cardbridge.agent",
)
