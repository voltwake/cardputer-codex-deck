#!/usr/bin/env python3
"""Generate a compact SPDX 2.3 software bill of materials for a release."""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.metadata
import json
import re
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def spdx_id(name: str) -> str:
    return "SPDXRef-" + re.sub(r"[^A-Za-z0-9.-]+", "-", name).strip("-")


def package(name: str, version: str, license_id: str = "NOASSERTION") -> dict[str, object]:
    return {
        "name": name,
        "SPDXID": spdx_id(name),
        "versionInfo": version,
        "downloadLocation": "NOASSERTION",
        "filesAnalyzed": False,
        "licenseConcluded": license_id,
        "licenseDeclared": license_id,
        "copyrightText": "NOASSERTION",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Codex Deck SPDX SBOM")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    versions = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
    packages = [
        package("CodexDeck", versions["release"], "MIT"),
        package("CardBridge", versions["release"], "MIT"),
        package("CardBridgeMicrophone", versions["release"], "GPL-3.0-only"),
        package("SourceHanSansCN", "2.005R", "OFL-1.1"),
        package("Sparkle", versions["updates"]["sparkle_version"], "MIT"),
        package("M5Cardputer", "1.1.1"),
        package("ArduinoJson", "6.21.5", "MIT"),
    ]
    seen = {str(item["name"]).lower() for item in packages}
    for distribution in importlib.metadata.distributions():
        name = str(distribution.metadata.get("Name", "")).strip()
        if not name or name.lower() in seen or name.lower() == "cardbridge":
            continue
        packages.append(package(name, distribution.version))
        seen.add(name.lower())

    document = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"Codex-Deck-{versions['release']}",
        "documentNamespace": f"https://github.com/voltwake/codex-deck/sbom/{versions['release']}/{uuid.uuid4()}",
        "creationInfo": {
            "created": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "creators": ["Tool: Codex Deck tools/generate_sbom.py"],
        },
        "packages": sorted(packages, key=lambda item: str(item["name"]).lower()),
        "relationships": [
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relationshipType": "DESCRIBES",
                "relatedSpdxElement": "SPDXRef-CodexDeck",
            }
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
