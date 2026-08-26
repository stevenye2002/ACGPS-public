from __future__ import annotations

import hashlib
import unittest

from acgps.supervised_handoff import build_supervised_coder_handoff_preview
from acgps.task_packets import generate_task_packet
from acgps.workflow_contracts import canonical_json_bytes
from tests.test_mvp_cli import valid_intake, valid_policy_result


class SupervisedCoderHandoffTests(unittest.TestCase):
    def test_builds_deterministic_validated_no_launch_preview(self) -> None:
        packet = generate_task_packet("CODER", valid_intake(), valid_policy_result())

        preview = build_supervised_coder_handoff_preview(packet)

        self.assertEqual(preview["status"], "HANDOFF_PREVIEW")
        self.assertEqual(preview["mode"], "HUMAN_SUPERVISED")
        self.assertEqual(preview["packet"], packet)
        self.assertEqual(
            preview["packet_sha256"],
            hashlib.sha256(canonical_json_bytes(packet)).hexdigest(),
        )
        self.assertEqual(
            preview["controls"],
            {
                "model_execution": "NOT_STARTED",
                "operator_authorization_required": True,
                "process_launch": "NOT_STARTED",
                "state_write": "NOT_PERFORMED",
            },
        )

    def test_rejects_non_coder_packets(self) -> None:
        packet = generate_task_packet("PLANNER", valid_intake(), valid_policy_result())

        with self.assertRaisesRegex(ValueError, "CODER"):
            build_supervised_coder_handoff_preview(packet)

    def test_rejects_unsafe_relevant_paths(self) -> None:
        unsafe_paths = (
            "../outside.py",
            "/absolute.py",
            "C:/absolute.py",
            "C:outside.py",
            r"docs\file.py",
        )
        for unsafe_path in unsafe_paths:
            with self.subTest(unsafe_path=unsafe_path):
                packet = generate_task_packet("CODER", valid_intake(), valid_policy_result())
                packet["relevant_paths"] = [unsafe_path]

                with self.assertRaisesRegex(ValueError, "relevant path"):
                    build_supervised_coder_handoff_preview(packet)


if __name__ == "__main__":
    unittest.main()
