from __future__ import annotations

import unittest

from tools.healthcheck import agent_has_settled, agent_matches_expected


class HealthcheckTests(unittest.TestCase):
    def test_agent_version_match_requires_the_exact_build(self) -> None:
        expected = {"version": "1.1.0", "build": 12}
        self.assertTrue(
            agent_matches_expected(
                {"agent": {"version": "1.1.0", "build": 12}},
                expected,
            )
        )
        self.assertFalse(
            agent_matches_expected(
                {"agent": {"version": "1.1.0", "build": 11}},
                expected,
            )
        )

    def test_agent_must_leave_transitional_state_before_healthcheck_returns(self) -> None:
        self.assertFalse(agent_has_settled({"agent": {"state": "stopping"}}))
        self.assertFalse(agent_has_settled({"agent": {"state": "starting"}}))
        self.assertTrue(agent_has_settled({"agent": {"state": "connected"}}))
        self.assertTrue(agent_has_settled({"agent": {"state": "degraded"}}))
