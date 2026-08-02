from __future__ import annotations

import os
import unittest
from pathlib import Path

from install_launch_agent import build_launch_path


class LaunchAgentInstallerTests(unittest.TestCase):
    def test_service_path_includes_detected_node_and_codex_directories(self) -> None:
        commands = {
            "node": "/custom/node/bin/node",
            "codex": "/custom/codex/bin/codex",
        }
        result = build_launch_path(
            path_lookup=commands.get,
            home=Path("/Users/tester"),
        ).split(os.pathsep)

        self.assertEqual(result[:2], ["/custom/node/bin", "/custom/codex/bin"])
        self.assertIn("/Users/tester/.npm-global/bin", result)
        self.assertIn("/opt/homebrew/bin", result)
        self.assertIn("/usr/bin", result)


if __name__ == "__main__":
    unittest.main()
