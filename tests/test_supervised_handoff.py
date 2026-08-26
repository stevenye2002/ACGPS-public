from __future__ import annotations

import hashlib
import unittest

import acgps.supervised_handoff as supervised_handoff
from acgps.supervised_handoff import (
    build_supervised_coder_handoff_preview,
    build_supervised_coder_result_receipt_preview,
)
from acgps.task_packets import generate_task_packet
from acgps.workflow_contracts import canonical_json_bytes
from tests.test_mvp_cli import valid_agent_result, valid_intake, valid_policy_result


class SupervisedCoderHandoffTests(unittest.TestCase):
    def test_builds_deterministic_validated_result_receipt_preview(self) -> None:
        packet = generate_task_packet("CODER", valid_intake(), valid_policy_result())
        agent_result = valid_agent_result()

        preview = build_supervised_coder_result_receipt_preview(packet, agent_result)

        self.assertEqual(preview["status"], "RESULT_RECEIPT_PREVIEW")
        self.assertEqual(preview["mode"], "HUMAN_SUPERVISED")
        self.assertEqual(preview["packet_id"], packet["packet_id"])
        self.assertEqual(
            preview["packet_sha256"],
            hashlib.sha256(canonical_json_bytes(packet)).hexdigest(),
        )
        self.assertEqual(preview["agent_result"], agent_result)
        self.assertEqual(
            preview["agent_result_sha256"],
            hashlib.sha256(canonical_json_bytes(agent_result)).hexdigest(),
        )
        self.assertEqual(
            preview["controls"],
            {
                "model_execution": "NOT_STARTED",
                "operator_authorization_required": True,
                "process_launch": "NOT_STARTED",
                "state_write": "NOT_PERFORMED",
                "workflow_transition": "NOT_PERFORMED",
            },
        )

    def test_rejects_result_for_a_different_packet(self) -> None:
        packet = generate_task_packet("CODER", valid_intake(), valid_policy_result())
        agent_result = valid_agent_result()
        agent_result["packet_id"] = "another-coder-packet-v1"

        with self.assertRaisesRegex(ValueError, "packet_id"):
            build_supervised_coder_result_receipt_preview(
                packet,
                agent_result,
            )

    def test_rejects_non_coder_packet_or_result(self) -> None:
        coder_packet = generate_task_packet("CODER", valid_intake(), valid_policy_result())
        planner_packet = generate_task_packet("PLANNER", valid_intake(), valid_policy_result())
        cases = (
            (
                planner_packet,
                dict(valid_agent_result(), packet_id=planner_packet["packet_id"]),
            ),
            (
                coder_packet,
                dict(valid_agent_result(), role="PLANNER"),
            ),
        )

        for packet, agent_result in cases:
            with self.subTest(packet_role=packet["role"], result_role=agent_result["role"]):
                with self.assertRaisesRegex(ValueError, "CODER"):
                    build_supervised_coder_result_receipt_preview(
                        packet,
                        agent_result,
                    )

    def test_rejects_unsafe_result_file_claims(self) -> None:
        packet = generate_task_packet("CODER", valid_intake(), valid_policy_result())
        unsafe_paths = (
            "../outside.py",
            "/absolute.py",
            "C:/absolute.py",
            "C:outside.py",
            r"docs\file.py",
        )

        for field_name in ("changed_files", "created_files"):
            for unsafe_path in unsafe_paths:
                with self.subTest(field_name=field_name, unsafe_path=unsafe_path):
                    agent_result = valid_agent_result()
                    agent_result[field_name] = [unsafe_path]

                    with self.assertRaisesRegex(ValueError, "result path"):
                        build_supervised_coder_result_receipt_preview(
                            packet,
                            agent_result,
                        )

    def test_result_receipt_rejects_unsafe_packet_paths(self) -> None:
        packet = generate_task_packet("CODER", valid_intake(), valid_policy_result())
        packet["relevant_paths"] = ["C:outside.py"]

        with self.assertRaisesRegex(ValueError, "relevant path"):
            build_supervised_coder_result_receipt_preview(
                packet,
                valid_agent_result(),
            )

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


class SupervisedReviewerHandoffTests(unittest.TestCase):
    @staticmethod
    def _builder():
        builder = getattr(
            supervised_handoff,
            "build_supervised_reviewer_handoff_preview",
            None,
        )
        if not callable(builder):
            raise AssertionError("Reviewer handoff preview builder is unavailable")
        return builder

    @staticmethod
    def _result_builder():
        builder = getattr(
            supervised_handoff,
            "build_supervised_reviewer_result_receipt_preview",
            None,
        )
        if not callable(builder):
            raise AssertionError("Reviewer result receipt preview builder is unavailable")
        return builder

    @staticmethod
    def _valid_result(packet: dict[str, object]) -> dict[str, object]:
        return dict(
            valid_agent_result(),
            packet_id=packet["packet_id"],
            role="REVIEWER",
            changed_files=[],
            recommended_next_state="INTEGRATING",
        )

    def test_builds_deterministic_validated_no_launch_preview(self) -> None:
        packet = generate_task_packet("REVIEWER", valid_intake(), valid_policy_result())

        preview = self._builder()(packet)

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

    def test_rejects_non_reviewer_packets(self) -> None:
        packet = generate_task_packet("CODER", valid_intake(), valid_policy_result())

        with self.assertRaisesRegex(ValueError, "REVIEWER"):
            self._builder()(packet)

    def test_rejects_unsafe_relevant_paths(self) -> None:
        packet = generate_task_packet("REVIEWER", valid_intake(), valid_policy_result())
        packet["relevant_paths"] = ["C:outside.py"]

        with self.assertRaisesRegex(ValueError, "relevant path"):
            self._builder()(packet)

    def test_builds_deterministic_validated_result_receipt_preview(self) -> None:
        packet = generate_task_packet("REVIEWER", valid_intake(), valid_policy_result())
        agent_result = self._valid_result(packet)

        preview = self._result_builder()(packet, agent_result)

        self.assertEqual(preview["status"], "RESULT_RECEIPT_PREVIEW")
        self.assertEqual(preview["mode"], "HUMAN_SUPERVISED")
        self.assertEqual(preview["packet_id"], packet["packet_id"])
        self.assertEqual(
            preview["packet_sha256"],
            hashlib.sha256(canonical_json_bytes(packet)).hexdigest(),
        )
        self.assertEqual(preview["agent_result"], agent_result)
        self.assertEqual(
            preview["agent_result_sha256"],
            hashlib.sha256(canonical_json_bytes(agent_result)).hexdigest(),
        )
        self.assertEqual(
            preview["controls"],
            {
                "model_execution": "NOT_STARTED",
                "operator_authorization_required": True,
                "process_launch": "NOT_STARTED",
                "state_write": "NOT_PERFORMED",
                "workflow_transition": "NOT_PERFORMED",
            },
        )

    def test_result_receipt_rejects_result_for_a_different_packet(self) -> None:
        packet = generate_task_packet("REVIEWER", valid_intake(), valid_policy_result())
        agent_result = self._valid_result(packet)
        agent_result["packet_id"] = "another-reviewer-packet-v1"

        with self.assertRaisesRegex(ValueError, "packet_id"):
            self._result_builder()(packet, agent_result)

    def test_result_receipt_rejects_non_reviewer_records(self) -> None:
        reviewer_packet = generate_task_packet(
            "REVIEWER", valid_intake(), valid_policy_result()
        )
        coder_packet = generate_task_packet("CODER", valid_intake(), valid_policy_result())
        cases = (
            (coder_packet, dict(self._valid_result(coder_packet), role="REVIEWER")),
            (reviewer_packet, dict(self._valid_result(reviewer_packet), role="CODER")),
        )

        for packet, agent_result in cases:
            with self.subTest(packet_role=packet["role"], result_role=agent_result["role"]):
                with self.assertRaisesRegex(ValueError, "REVIEWER"):
                    self._result_builder()(packet, agent_result)

    def test_result_receipt_rejects_unsafe_result_file_claims(self) -> None:
        packet = generate_task_packet("REVIEWER", valid_intake(), valid_policy_result())
        unsafe_paths = (
            "../outside.json",
            "/absolute.json",
            "C:/absolute.json",
            "C:outside.json",
            r"reviews\finding.json",
        )

        for field_name in ("changed_files", "created_files"):
            for unsafe_path in unsafe_paths:
                with self.subTest(field_name=field_name, unsafe_path=unsafe_path):
                    agent_result = self._valid_result(packet)
                    agent_result[field_name] = [unsafe_path]

                    with self.assertRaisesRegex(ValueError, "result path"):
                        self._result_builder()(packet, agent_result)

    def test_result_receipt_rejects_unsafe_packet_paths(self) -> None:
        packet = generate_task_packet("REVIEWER", valid_intake(), valid_policy_result())
        packet["relevant_paths"] = ["C:outside.py"]

        with self.assertRaisesRegex(ValueError, "relevant path"):
            self._result_builder()(packet, self._valid_result(packet))


if __name__ == "__main__":
    unittest.main()
