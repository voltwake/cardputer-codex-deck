#!/usr/bin/env python3
"""Collect project and bundled dependency notices into the App bundle."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import re
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON_DISTRIBUTIONS = {
    "altgraph",
    "cffi",
    "ifaddr",
    "macholib",
    "numpy",
    "packaging",
    "pycparser",
    "pyinstaller",
    "pyinstaller-hooks-contrib",
    "pyobjc-core",
    "pyobjc-framework-applicationservices",
    "pyobjc-framework-cocoa",
    "pyobjc-framework-coretext",
    "pyobjc-framework-quartz",
    "pyobjc-framework-security",
    "sounddevice",
    "zeroconf",
}


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect CardBridge license notices")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    project_files = {
        "CardBridge-MIT.txt": ROOT / "LICENSE",
        "CardBridge-NOTICE.md": ROOT / "NOTICE.md",
        "THIRD_PARTY_NOTICES.md": ROOT / "THIRD_PARTY_NOTICES.md",
        "CardBridgeMicrophone-GPL-3.0.txt": ROOT / "bridge/driver/LICENSE-GPL-3.0.txt",
        "CardBridgeMicrophone-NOTICE.md": ROOT / "bridge/driver/NOTICE.md",
        "SourceHanSans-OFL.txt": ROOT / "firmware/m5stack-cardputer-adv/assets/fonts/LICENSE-SourceHanSans.txt",
        "Sparkle-LICENSE.txt": ROOT / "bridge/macos/.deps/Sparkle/LICENSE",
    }
    for name, source in project_files.items():
        if not source.exists():
            raise SystemExit(f"required license file is missing: {source}")
        shutil.copyfile(source, output / name)

    index: list[dict[str, object]] = []
    for distribution in importlib.metadata.distributions():
        name = str(distribution.metadata.get("Name", "")).lower()
        if name not in PYTHON_DISTRIBUTIONS:
            continue
        copied: list[str] = []
        for relative in distribution.files or []:
            basename = Path(str(relative)).name.upper()
            if not basename.startswith(("LICENSE", "COPYING", "NOTICE")):
                continue
            source = Path(distribution.locate_file(relative))
            if not source.is_file():
                continue
            if source.suffix.lower() not in {
                "",
                ".txt",
                ".md",
                ".rst",
                ".html",
                ".apache",
                ".bsd",
                ".mit",
                ".license",
            }:
                continue
            target_name = f"Python-{safe_name(name)}-{safe_name(Path(str(relative)).name)}"
            shutil.copyfile(source, output / target_name)
            copied.append(target_name)
        index.append(
            {
                "name": distribution.metadata.get("Name", name),
                "version": distribution.version,
                "license_expression": distribution.metadata.get("License-Expression"),
                "license_files": sorted(set(copied)),
            }
        )
    (output / "Python-dependencies.json").write_text(
        json.dumps(sorted(index, key=lambda item: str(item["name"]).lower()), indent=2)
        + "\n",
        encoding="utf-8",
    )
    print(f"Collected licenses in {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
