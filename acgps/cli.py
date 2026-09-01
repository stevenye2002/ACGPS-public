from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from acgps.contracts import validate_contract
from acgps.human_decisions import DecisionQueue
from acgps.policy import load_policy_bundle, validate_project_registration
from acgps.review_adapter import build_release_candidate_manifest, verify_release_candidate_manifest
from acgps.supervised_handoff import (
    build_supervised_coder_handoff_preview,
    build_supervised_coder_result_receipt_preview,
    build_supervised_planner_handoff_preview,
    build_supervised_planner_result_receipt_preview,
    build_supervised_reviewer_handoff_preview,
    build_supervised_reviewer_result_receipt_preview,
    build_supervised_verifier_handoff_preview,
    build_supervised_verifier_result_receipt_preview,
)
from acgps.task_packets import generate_task_packet
from acgps.workflow_engine import WorkflowEngine
from acgps.workflow_contracts import canonical_json_bytes
from acgps.workflow_store import (
    WorkflowStore,
    WorkflowStoreError,
    safe_state_path,
    write_state_atomic,
)
from acgps.yaml_loader import load_yaml_strict


def _read_mapping(path: Path) -> dict[str, Any]:
    source = Path(path)
    text = source.read_text(encoding="utf-8")
    if source.suffix.casefold() == ".json":
        record = json.loads(text)
    else:
        record = load_yaml_strict(text, logical_path=str(source))
    if not isinstance(record, dict):
        raise ValueError(f"record must be a mapping: {source}")
    return record


def _read_canonical_json_mapping(path: Path) -> dict[str, Any]:
    source = Path(path)
    payload = source.read_bytes()
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"record is not valid UTF-8: {source}") from exc

    def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        folded: set[str] = set()
        for key, value in pairs:
            if key in result or key.casefold() in folded:
                raise ValueError(f"duplicate or case-fold-colliding JSON key: {key}")
            result[key] = value
            folded.add(key.casefold())
        return result

    record = json.loads(text, object_pairs_hook=reject_duplicate_pairs)
    if not isinstance(record, dict):
        raise ValueError(f"record must be a mapping: {source}")
    if canonical_json_bytes(record) + b"\n" != payload:
        raise ValueError(f"record must use canonical JSON bytes with one terminal LF: {source}")
    return record


def _engine(args: argparse.Namespace) -> WorkflowEngine:
    return WorkflowEngine(
        policy_root=Path(args.policy_root),
        state_root=Path(args.state_root),
        project_root=Path(args.project_root),
        profile_id=args.profile_id,
    )


def _read_only_decision_queue(state_root: Path) -> DecisionQueue:
    resolved_state_root = Path(state_root).resolve(strict=True)
    if not resolved_state_root.is_dir():
        raise ValueError("state root must be a directory")
    workflow_store = WorkflowStore(resolved_state_root, read_only=True)
    decision_root = resolved_state_root / "decisions"
    if decision_root.exists():
        resolved_decision_root = decision_root.resolve(strict=True)
        if not resolved_decision_root.is_dir() or not resolved_decision_root.is_relative_to(
            resolved_state_root
        ):
            raise ValueError("decision root must remain beneath state root")
    else:
        resolved_decision_root = decision_root
    return DecisionQueue(
        resolved_decision_root,
        workflow_store=workflow_store,
        create_root=False,
    )


def _add_project_arguments(parser: argparse.ArgumentParser, *, include_state: bool) -> None:
    parser.add_argument("--policy-root", required=True)
    if include_state:
        parser.add_argument("--state-root", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--profile-id", required=True)


def _state_output_path(state_root: Path, requested: Path) -> Path:
    root = Path(state_root).resolve(strict=True)
    path = Path(requested)
    candidate = path.resolve(strict=False) if path.is_absolute() else (root / path).resolve(strict=False)
    try:
        relative = candidate.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError("output path must remain beneath state root") from exc
    return safe_state_path(root, relative)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m acgps")
    commands = parser.add_subparsers(dest="group", required=True)

    project = commands.add_parser("project")
    project_commands = project.add_subparsers(dest="command", required=True)
    project_validate = project_commands.add_parser("validate")
    _add_project_arguments(project_validate, include_state=False)
    project_progress_summary = project_commands.add_parser("progress-summary")
    _add_project_arguments(project_progress_summary, include_state=True)
    project_progress_summary_verify = project_commands.add_parser(
        "progress-summary-verify"
    )
    _add_project_arguments(project_progress_summary_verify, include_state=True)
    project_progress_summary_verify.add_argument("--summary", required=True)
    project_next_action_queue = project_commands.add_parser("next-action-queue")
    _add_project_arguments(project_next_action_queue, include_state=True)
    project_pending_decision_queue = project_commands.add_parser(
        "pending-decision-queue"
    )
    _add_project_arguments(project_pending_decision_queue, include_state=True)
    project_pending_decision_resolution_preview = project_commands.add_parser(
        "pending-decision-resolution-preview"
    )
    _add_project_arguments(
        project_pending_decision_resolution_preview,
        include_state=True,
    )
    project_pending_decision_resolution_preview.add_argument(
        "--resolution",
        required=True,
    )
    project_pending_decision_resolution_preview_verify = project_commands.add_parser(
        "pending-decision-resolution-preview-verify"
    )
    _add_project_arguments(
        project_pending_decision_resolution_preview_verify,
        include_state=True,
    )
    project_pending_decision_resolution_preview_verify.add_argument(
        "--preview",
        required=True,
    )
    project_pending_decision_resolution_to_resume_gate_preview = (
        project_commands.add_parser(
            "pending-decision-resolution-to-resume-gate-preview"
        )
    )
    _add_project_arguments(
        project_pending_decision_resolution_to_resume_gate_preview,
        include_state=True,
    )
    project_pending_decision_resolution_to_resume_gate_preview.add_argument(
        "--preview",
        required=True,
    )
    project_pending_decision_resolution_to_resume_gate_preview.add_argument(
        "--actor",
        required=True,
    )
    project_pending_decision_resolution_to_resume_gate_preview.add_argument(
        "--created-at-utc",
        required=True,
    )
    project_pending_decision_resolution_to_resume_gate_preview.add_argument(
        "--evidence",
        action="append",
        required=True,
    )
    project_pending_decision_resolution_to_resume_gate_preview.add_argument(
        "--risk-trigger",
        action="append",
        default=[],
    )
    project_pending_decision_resolution_to_resume_gate_preview.add_argument(
        "--human-trigger",
        action="append",
        default=[],
    )
    project_pending_decision_resolution_to_resume_gate_preview.add_argument(
        "--task-attribute",
        action="append",
        default=[],
    )
    project_pending_decision_queue_verify = project_commands.add_parser(
        "pending-decision-queue-verify"
    )
    _add_project_arguments(project_pending_decision_queue_verify, include_state=True)
    project_pending_decision_queue_verify.add_argument("--queue", required=True)
    project_next_action_queue_verify = project_commands.add_parser(
        "next-action-queue-verify"
    )
    _add_project_arguments(project_next_action_queue_verify, include_state=True)
    project_next_action_queue_verify.add_argument("--queue", required=True)

    task = commands.add_parser("task")
    task_commands = task.add_subparsers(dest="command", required=True)
    task_intake = task_commands.add_parser("intake")
    _add_project_arguments(task_intake, include_state=True)
    task_intake.add_argument("--intake", required=True)
    task_intake.add_argument("--actor", default="PLANNER")

    task_status = task_commands.add_parser("status")
    _add_project_arguments(task_status, include_state=True)
    task_status.add_argument("--task-id", required=True)
    task_status.add_argument("--include-audit", action="store_true")

    task_audit_verify = task_commands.add_parser("audit-verify")
    _add_project_arguments(task_audit_verify, include_state=True)
    task_audit_verify.add_argument("--task-id", required=True)

    task_next_action_preview = task_commands.add_parser("next-action-preview")
    _add_project_arguments(task_next_action_preview, include_state=True)
    task_next_action_preview.add_argument("--task-id", required=True)

    task_progress_summary = task_commands.add_parser("progress-summary")
    _add_project_arguments(task_progress_summary, include_state=True)
    task_progress_summary.add_argument("--task-id", required=True)

    task_gate_preview = task_commands.add_parser("gate-preview")
    _add_project_arguments(task_gate_preview, include_state=True)
    task_gate_preview.add_argument("--task-id", required=True)
    task_gate_preview.add_argument("--to-state", required=True)
    task_gate_preview.add_argument("--actor", required=True)
    task_gate_preview.add_argument("--created-at-utc", required=True)
    task_gate_preview.add_argument("--evidence", action="append", required=True)
    task_gate_preview.add_argument("--risk-trigger", action="append", default=[])
    task_gate_preview.add_argument("--human-trigger", action="append", default=[])
    task_gate_preview.add_argument("--task-attribute", action="append", default=[])

    task_resume_gate_preview = task_commands.add_parser("resume-gate-preview")
    _add_project_arguments(task_resume_gate_preview, include_state=True)
    task_resume_gate_preview.add_argument("--task-id", required=True)
    task_resume_gate_preview.add_argument("--to-state", required=True)
    task_resume_gate_preview.add_argument("--actor", required=True)
    task_resume_gate_preview.add_argument("--created-at-utc", required=True)
    task_resume_gate_preview.add_argument("--evidence", action="append", required=True)
    task_resume_gate_preview.add_argument("--decision-resolution", required=True)
    task_resume_gate_preview.add_argument("--risk-trigger", action="append", default=[])
    task_resume_gate_preview.add_argument("--human-trigger", action="append", default=[])
    task_resume_gate_preview.add_argument("--task-attribute", action="append", default=[])

    task_resume_transition_commit_verify = task_commands.add_parser(
        "resume-transition-commit-verify"
    )
    _add_project_arguments(
        task_resume_transition_commit_verify,
        include_state=True,
    )
    task_resume_transition_commit_verify.add_argument("--task-id", required=True)

    task_closed_transition_commit_verify = task_commands.add_parser(
        "closed-transition-commit-verify"
    )
    _add_project_arguments(
        task_closed_transition_commit_verify,
        include_state=True,
    )
    task_closed_transition_commit_verify.add_argument("--task-id", required=True)

    task_transition_commit_verify = task_commands.add_parser(
        "transition-commit-verify"
    )
    _add_project_arguments(
        task_transition_commit_verify,
        include_state=True,
    )
    task_transition_commit_verify.add_argument("--task-id", required=True)

    task_advance = task_commands.add_parser("advance")
    _add_project_arguments(task_advance, include_state=True)
    task_advance.add_argument("--task-id", required=True)
    task_advance.add_argument("--to-state", required=True)
    task_advance.add_argument("--actor", required=True)
    task_advance.add_argument("--created-at-utc", required=True)
    task_advance.add_argument("--evidence", action="append", required=True)
    task_advance.add_argument("--risk-trigger", action="append", default=[])
    task_advance.add_argument("--human-trigger", action="append", default=[])
    task_advance.add_argument("--task-attribute", action="append", default=[])
    task_advance.add_argument("--decision-resolution")

    packet = commands.add_parser("packet")
    packet_commands = packet.add_subparsers(dest="command", required=True)
    packet_generate = packet_commands.add_parser("generate")
    _add_project_arguments(packet_generate, include_state=True)
    packet_generate.add_argument("--task-id", required=True)
    packet_generate.add_argument("--role", required=True)
    packet_generate.add_argument("--created-at-utc", required=True)
    packet_generate.add_argument("--output", required=True)
    packet_verify = packet_commands.add_parser("verify")
    _add_project_arguments(packet_verify, include_state=True)
    packet_verify.add_argument("--task-id", required=True)
    packet_verify.add_argument("--packet", required=True)
    packet_trusted_handoff_preview = packet_commands.add_parser(
        "trusted-handoff-preview"
    )
    _add_project_arguments(packet_trusted_handoff_preview, include_state=True)
    packet_trusted_handoff_preview.add_argument("--task-id", required=True)
    packet_trusted_handoff_preview.add_argument("--packet", required=True)
    packet_trusted_result_receipt_preview = packet_commands.add_parser(
        "trusted-result-receipt-preview"
    )
    _add_project_arguments(packet_trusted_result_receipt_preview, include_state=True)
    packet_trusted_result_receipt_preview.add_argument("--task-id", required=True)
    packet_trusted_result_receipt_preview.add_argument("--packet", required=True)
    packet_trusted_result_receipt_preview.add_argument("--result", required=True)
    packet_trusted_result_transition_gate_preview = packet_commands.add_parser(
        "trusted-result-transition-gate-preview"
    )
    _add_project_arguments(
        packet_trusted_result_transition_gate_preview,
        include_state=True,
    )
    packet_trusted_result_transition_gate_preview.add_argument("--task-id", required=True)
    packet_trusted_result_transition_gate_preview.add_argument("--packet", required=True)
    packet_trusted_result_transition_gate_preview.add_argument("--result", required=True)
    packet_trusted_result_transition_gate_preview.add_argument(
        "--created-at-utc",
        required=True,
    )
    packet_trusted_result_transition_gate_preview.add_argument(
        "--evidence",
        action="append",
        default=[],
    )
    packet_trusted_result_transition_gate_preview.add_argument(
        "--risk-trigger",
        action="append",
        default=[],
    )
    packet_trusted_result_transition_gate_preview.add_argument(
        "--human-trigger",
        action="append",
        default=[],
    )
    packet_trusted_result_transition_gate_preview.add_argument(
        "--task-attribute",
        action="append",
        default=[],
    )
    packet_trusted_result_transition_advance = packet_commands.add_parser(
        "trusted-result-transition-advance"
    )
    _add_project_arguments(
        packet_trusted_result_transition_advance,
        include_state=True,
    )
    packet_trusted_result_transition_advance.add_argument("--task-id", required=True)
    packet_trusted_result_transition_advance.add_argument("--packet", required=True)
    packet_trusted_result_transition_advance.add_argument("--result", required=True)
    packet_trusted_result_transition_advance.add_argument(
        "--created-at-utc",
        required=True,
    )
    packet_trusted_result_transition_advance.add_argument(
        "--evidence",
        action="append",
        default=[],
    )
    packet_trusted_result_transition_advance.add_argument(
        "--risk-trigger",
        action="append",
        default=[],
    )
    packet_trusted_result_transition_advance.add_argument(
        "--human-trigger",
        action="append",
        default=[],
    )
    packet_trusted_result_transition_advance.add_argument(
        "--task-attribute",
        action="append",
        default=[],
    )
    packet_trusted_result_transition_commit_verify = packet_commands.add_parser(
        "trusted-result-transition-commit-verify"
    )
    _add_project_arguments(
        packet_trusted_result_transition_commit_verify,
        include_state=True,
    )
    packet_trusted_result_transition_commit_verify.add_argument(
        "--task-id",
        required=True,
    )
    packet_trusted_handoff_transition_commit_verify = packet_commands.add_parser(
        "trusted-handoff-transition-commit-verify"
    )
    _add_project_arguments(
        packet_trusted_handoff_transition_commit_verify,
        include_state=True,
    )
    packet_trusted_handoff_transition_commit_verify.add_argument(
        "--task-id",
        required=True,
    )

    decision = commands.add_parser("decision")
    decision_commands = decision.add_subparsers(dest="command", required=True)
    decision_pending = decision_commands.add_parser("pending")
    decision_pending.add_argument("--state-root", required=True)
    decision_resolution_preview = decision_commands.add_parser("resolution-preview")
    decision_resolution_preview.add_argument("--state-root", required=True)
    decision_resolution_preview.add_argument("--resolution", required=True)

    rc = commands.add_parser("rc")
    rc_commands = rc.add_subparsers(dest="command", required=True)
    rc_prepare = rc_commands.add_parser("prepare")
    rc_prepare.add_argument("--output-dir", required=True)
    rc_prepare.add_argument("--project-id", required=True)
    rc_prepare.add_argument("--rc-id", required=True)
    rc_prepare.add_argument("--version", required=True)
    rc_prepare.add_argument("--source", required=True)
    rc_prepare.add_argument("--build-artifact", action="append", required=True)
    rc_prepare.add_argument("--verification", action="append", required=True)
    rc_prepare.add_argument("--review", action="append", required=True)
    rc_prepare.add_argument("--rollback", required=True)
    rc_prepare.add_argument("--created-at-utc", required=True)
    rc_verify = rc_commands.add_parser("verify")
    rc_verify.add_argument("--manifest", required=True)
    rc_verify.add_argument("--expected-project-id")
    rc_verify.add_argument("--expected-task-id")
    rc_verify.add_argument("--require-build-artifacts", action="store_true")
    rc_task_gate_preview = rc_commands.add_parser("task-gate-preview")
    _add_project_arguments(rc_task_gate_preview, include_state=True)
    rc_task_gate_preview.add_argument("--task-id", required=True)
    rc_task_gate_preview.add_argument("--manifest", required=True)
    rc_task_gate_preview.add_argument("--actor", required=True)
    rc_task_gate_preview.add_argument("--created-at-utc", required=True)
    rc_task_gate_preview.add_argument("--risk-trigger", action="append", default=[])
    rc_task_gate_preview.add_argument("--human-trigger", action="append", default=[])
    rc_task_gate_preview.add_argument("--task-attribute", action="append", default=[])
    rc_task_transition_commit_verify = rc_commands.add_parser(
        "task-transition-commit-verify"
    )
    _add_project_arguments(rc_task_transition_commit_verify, include_state=True)
    rc_task_transition_commit_verify.add_argument("--task-id", required=True)

    plan = commands.add_parser("plan")
    plan_commands = plan.add_subparsers(dest="command", required=True)
    plan_handoff_preview = plan_commands.add_parser("handoff-preview")
    plan_handoff_preview.add_argument("--packet", required=True)
    plan_result_receipt_preview = plan_commands.add_parser("result-receipt-preview")
    plan_result_receipt_preview.add_argument("--packet", required=True)
    plan_result_receipt_preview.add_argument("--result", required=True)

    coding = commands.add_parser("coding")
    coding_commands = coding.add_subparsers(dest="command", required=True)
    coding_gate_init = coding_commands.add_parser("gate-init")
    coding_gate_init.add_argument("--state-root", required=True)
    coding_gate_init.add_argument("--gate-id", required=True)
    coding_gate_init.add_argument("--task-id", required=True)
    coding_gate_status = coding_commands.add_parser("gate-status")
    coding_gate_status.add_argument("--state-root", required=True)
    coding_gate_status.add_argument("--gate-id", required=True)
    coding_record_validate = coding_commands.add_parser("record-validate")
    coding_record_validate.add_argument("--record", required=True)
    coding_handoff_preview = coding_commands.add_parser("handoff-preview")
    coding_handoff_preview.add_argument("--packet", required=True)
    coding_result_receipt_preview = coding_commands.add_parser("result-receipt-preview")
    coding_result_receipt_preview.add_argument("--packet", required=True)
    coding_result_receipt_preview.add_argument("--result", required=True)

    review = commands.add_parser("review")
    review_commands = review.add_subparsers(dest="command", required=True)
    review_handoff_preview = review_commands.add_parser("handoff-preview")
    review_handoff_preview.add_argument("--packet", required=True)
    review_result_receipt_preview = review_commands.add_parser("result-receipt-preview")
    review_result_receipt_preview.add_argument("--packet", required=True)
    review_result_receipt_preview.add_argument("--result", required=True)

    verify = commands.add_parser("verify")
    verify_commands = verify.add_subparsers(dest="command", required=True)
    verify_handoff_preview = verify_commands.add_parser("handoff-preview")
    verify_handoff_preview.add_argument("--packet", required=True)
    verify_result_receipt_preview = verify_commands.add_parser("result-receipt-preview")
    verify_result_receipt_preview.add_argument("--packet", required=True)
    verify_result_receipt_preview.add_argument("--result", required=True)
    return parser


def _parse_attributes(items: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in items:
        name, separator, value = item.partition("=")
        if not separator or not name or name in result:
            raise ValueError("task attributes must be unique NAME=VALUE pairs")
        result[name] = value
    return result


def _dispatch(args: argparse.Namespace) -> dict[str, Any]:
    if args.group == "project" and args.command == "validate":
        bundle = load_policy_bundle(Path(args.policy_root))
        profile_record = bundle.project_profiles.get(args.profile_id)
        if not isinstance(profile_record, dict) or not isinstance(profile_record.get("profile"), dict):
            raise ValueError(f"unknown project profile: {args.profile_id}")
        required_files = validate_project_registration(Path(args.project_root), profile_record["profile"])
        return {
            "status": "VALID",
            "profile_id": args.profile_id,
            "project_root": str(Path(args.project_root).resolve(strict=True)),
            "required_files": {key: str(value) for key, value in sorted(required_files.items())},
        }

    if args.group == "project" and args.command == "progress-summary":
        return WorkflowEngine(
            policy_root=Path(args.policy_root),
            state_root=Path(args.state_root),
            project_root=Path(args.project_root),
            profile_id=args.profile_id,
            read_only=True,
        ).trusted_project_progress_summary()

    if args.group == "project" and args.command == "progress-summary-verify":
        return WorkflowEngine(
            policy_root=Path(args.policy_root),
            state_root=Path(args.state_root),
            project_root=Path(args.project_root),
            profile_id=args.profile_id,
            read_only=True,
        ).trusted_project_progress_summary_verification(Path(args.summary))

    if args.group == "project" and args.command == "next-action-queue":
        return WorkflowEngine(
            policy_root=Path(args.policy_root),
            state_root=Path(args.state_root),
            project_root=Path(args.project_root),
            profile_id=args.profile_id,
            read_only=True,
        ).trusted_project_next_action_queue()

    if args.group == "project" and args.command == "pending-decision-queue":
        return WorkflowEngine(
            policy_root=Path(args.policy_root),
            state_root=Path(args.state_root),
            project_root=Path(args.project_root),
            profile_id=args.profile_id,
            read_only=True,
        ).trusted_project_pending_decision_queue()

    if (
        args.group == "project"
        and args.command == "pending-decision-resolution-preview"
    ):
        return WorkflowEngine(
            policy_root=Path(args.policy_root),
            state_root=Path(args.state_root),
            project_root=Path(args.project_root),
            profile_id=args.profile_id,
            read_only=True,
        ).trusted_project_pending_decision_resolution_preview(
            Path(args.resolution)
        )

    if (
        args.group == "project"
        and args.command == "pending-decision-resolution-preview-verify"
    ):
        return WorkflowEngine(
            policy_root=Path(args.policy_root),
            state_root=Path(args.state_root),
            project_root=Path(args.project_root),
            profile_id=args.profile_id,
            read_only=True,
        ).trusted_project_pending_decision_resolution_preview_verification(
            Path(args.preview)
        )

    if (
        args.group == "project"
        and args.command
        == "pending-decision-resolution-to-resume-gate-preview"
    ):
        return WorkflowEngine(
            policy_root=Path(args.policy_root),
            state_root=Path(args.state_root),
            project_root=Path(args.project_root),
            profile_id=args.profile_id,
            read_only=True,
        ).trusted_project_pending_decision_resolution_to_resume_gate_preview(
            Path(args.preview),
            actor=args.actor,
            evidence_paths=[Path(path) for path in args.evidence],
            created_at_utc=args.created_at_utc,
            risk_triggers=args.risk_trigger,
            human_triggers=args.human_trigger,
            task_attributes=_parse_attributes(args.task_attribute),
        )

    if args.group == "project" and args.command == "pending-decision-queue-verify":
        return WorkflowEngine(
            policy_root=Path(args.policy_root),
            state_root=Path(args.state_root),
            project_root=Path(args.project_root),
            profile_id=args.profile_id,
            read_only=True,
        ).trusted_project_pending_decision_queue_verification(Path(args.queue))

    if args.group == "project" and args.command == "next-action-queue-verify":
        return WorkflowEngine(
            policy_root=Path(args.policy_root),
            state_root=Path(args.state_root),
            project_root=Path(args.project_root),
            profile_id=args.profile_id,
            read_only=True,
        ).trusted_project_next_action_queue_verification(Path(args.queue))

    if args.group == "task" and args.command == "intake":
        return _engine(args).intake(_read_mapping(Path(args.intake)), actor=args.actor)

    if args.group == "task" and args.command == "status":
        engine = _engine(args)
        state = engine.status(args.task_id)
        return {"state": state, "audit": engine.audit(args.task_id)} if args.include_audit else state

    if args.group == "task" and args.command == "audit-verify":
        return WorkflowEngine(
            policy_root=Path(args.policy_root),
            state_root=Path(args.state_root),
            project_root=Path(args.project_root),
            profile_id=args.profile_id,
            read_only=True,
        ).audit_lineage_verification(args.task_id)

    if args.group == "task" and args.command == "next-action-preview":
        return WorkflowEngine(
            policy_root=Path(args.policy_root),
            state_root=Path(args.state_root),
            project_root=Path(args.project_root),
            profile_id=args.profile_id,
            read_only=True,
        ).next_action_preview(args.task_id)

    if args.group == "task" and args.command == "progress-summary":
        return WorkflowEngine(
            policy_root=Path(args.policy_root),
            state_root=Path(args.state_root),
            project_root=Path(args.project_root),
            profile_id=args.profile_id,
            read_only=True,
        ).trusted_task_progress_summary(args.task_id)

    if args.group == "task" and args.command == "gate-preview":
        return WorkflowEngine(
            policy_root=Path(args.policy_root),
            state_root=Path(args.state_root),
            project_root=Path(args.project_root),
            profile_id=args.profile_id,
            read_only=True,
        ).direct_transition_gate_preview(
            args.task_id,
            args.to_state,
            actor=args.actor,
            evidence_paths=[Path(path) for path in args.evidence],
            created_at_utc=args.created_at_utc,
            risk_triggers=args.risk_trigger,
            human_triggers=args.human_trigger,
            task_attributes=_parse_attributes(args.task_attribute),
        )

    if args.group == "task" and args.command == "resume-gate-preview":
        resolution = _read_canonical_json_mapping(Path(args.decision_resolution))
        return WorkflowEngine(
            policy_root=Path(args.policy_root),
            state_root=Path(args.state_root),
            project_root=Path(args.project_root),
            profile_id=args.profile_id,
            read_only=True,
        ).waiting_human_resume_gate_preview(
            args.task_id,
            to_state=args.to_state,
            actor=args.actor,
            evidence_paths=[Path(path) for path in args.evidence],
            decision_resolution=resolution,
            created_at_utc=args.created_at_utc,
            risk_triggers=args.risk_trigger,
            human_triggers=args.human_trigger,
            task_attributes=_parse_attributes(args.task_attribute),
        )

    if (
        args.group == "task"
        and args.command == "resume-transition-commit-verify"
    ):
        return WorkflowEngine(
            policy_root=Path(args.policy_root),
            state_root=Path(args.state_root),
            project_root=Path(args.project_root),
            profile_id=args.profile_id,
            read_only=True,
        ).waiting_human_resume_transition_commit_verification(args.task_id)

    if (
        args.group == "task"
        and args.command == "closed-transition-commit-verify"
    ):
        return WorkflowEngine(
            policy_root=Path(args.policy_root),
            state_root=Path(args.state_root),
            project_root=Path(args.project_root),
            profile_id=args.profile_id,
            read_only=True,
        ).closed_transition_commit_verification(args.task_id)

    if (
        args.group == "task"
        and args.command == "transition-commit-verify"
    ):
        return WorkflowEngine(
            policy_root=Path(args.policy_root),
            state_root=Path(args.state_root),
            project_root=Path(args.project_root),
            profile_id=args.profile_id,
            read_only=True,
        ).transition_commit_verification(args.task_id)

    if args.group == "task" and args.command == "advance":
        resolution = _read_mapping(Path(args.decision_resolution)) if args.decision_resolution else None
        return _engine(args).advance(
            args.task_id,
            args.to_state,
            actor=args.actor,
            evidence_paths=[Path(path) for path in args.evidence],
            created_at_utc=args.created_at_utc,
            risk_triggers=args.risk_trigger,
            human_triggers=args.human_trigger,
            task_attributes=_parse_attributes(args.task_attribute),
            decision_resolution=resolution,
        )

    if args.group == "packet" and args.command == "generate":
        engine = WorkflowEngine(
            policy_root=Path(args.policy_root),
            state_root=Path(args.state_root),
            project_root=Path(args.project_root),
            profile_id=args.profile_id,
            read_only=True,
        )
        intake_path = safe_state_path(Path(args.state_root), f"tasks/{args.task_id}/intake.json")
        intake = _read_mapping(intake_path)
        policy_result = engine.trusted_classification_policy_result(
            args.task_id,
            intake=intake,
        )
        packet = generate_task_packet(args.role, intake, policy_result)
        write_state_atomic(_state_output_path(Path(args.state_root), Path(args.output)), packet)
        return packet

    if args.group == "packet" and args.command == "verify":
        return WorkflowEngine(
            policy_root=Path(args.policy_root),
            state_root=Path(args.state_root),
            project_root=Path(args.project_root),
            profile_id=args.profile_id,
            read_only=True,
        ).task_packet_verification(
            args.task_id,
            Path(args.packet),
        )

    if args.group == "packet" and args.command == "trusted-handoff-preview":
        return WorkflowEngine(
            policy_root=Path(args.policy_root),
            state_root=Path(args.state_root),
            project_root=Path(args.project_root),
            profile_id=args.profile_id,
            read_only=True,
        ).trusted_task_packet_handoff_preview(
            args.task_id,
            Path(args.packet),
        )

    if args.group == "packet" and args.command == "trusted-result-receipt-preview":
        return WorkflowEngine(
            policy_root=Path(args.policy_root),
            state_root=Path(args.state_root),
            project_root=Path(args.project_root),
            profile_id=args.profile_id,
            read_only=True,
        ).trusted_task_packet_result_receipt_preview(
            args.task_id,
            Path(args.packet),
            Path(args.result),
        )

    if (
        args.group == "packet"
        and args.command == "trusted-result-transition-gate-preview"
    ):
        return WorkflowEngine(
            policy_root=Path(args.policy_root),
            state_root=Path(args.state_root),
            project_root=Path(args.project_root),
            profile_id=args.profile_id,
            read_only=True,
        ).trusted_task_packet_result_transition_gate_preview(
            args.task_id,
            Path(args.packet),
            Path(args.result),
            evidence_paths=[Path(path) for path in args.evidence],
            created_at_utc=args.created_at_utc,
            risk_triggers=args.risk_trigger,
            human_triggers=args.human_trigger,
            task_attributes=_parse_attributes(args.task_attribute),
        )

    if (
        args.group == "packet"
        and args.command == "trusted-result-transition-advance"
    ):
        return _engine(args).trusted_task_packet_result_transition_advance(
            args.task_id,
            Path(args.packet),
            Path(args.result),
            evidence_paths=[Path(path) for path in args.evidence],
            created_at_utc=args.created_at_utc,
            risk_triggers=args.risk_trigger,
            human_triggers=args.human_trigger,
            task_attributes=_parse_attributes(args.task_attribute),
        )

    if (
        args.group == "packet"
        and args.command == "trusted-result-transition-commit-verify"
    ):
        return WorkflowEngine(
            policy_root=Path(args.policy_root),
            state_root=Path(args.state_root),
            project_root=Path(args.project_root),
            profile_id=args.profile_id,
            read_only=True,
        ).trusted_task_packet_result_transition_commit_verification(args.task_id)

    if (
        args.group == "packet"
        and args.command == "trusted-handoff-transition-commit-verify"
    ):
        return WorkflowEngine(
            policy_root=Path(args.policy_root),
            state_root=Path(args.state_root),
            project_root=Path(args.project_root),
            profile_id=args.profile_id,
            read_only=True,
        ).trusted_task_packet_handoff_transition_commit_verification(args.task_id)

    if args.group == "decision" and args.command == "pending":
        decisions = _read_only_decision_queue(Path(args.state_root)).list_pending()
        for decision_record in decisions:
            validate_contract("human_decision_request", decision_record, mode="runtime")
        return {"decisions": decisions, "status": "PENDING" if decisions else "CLEAR"}

    if args.group == "decision" and args.command == "resolution-preview":
        resolution = _read_canonical_json_mapping(Path(args.resolution))
        decisions = _read_only_decision_queue(Path(args.state_root))
        pending_records = decisions.list_pending()
        request = decisions.validate_resolution(resolution)
        authoritative_matches = [
            record
            for record in pending_records
            if record["decision_id"] == request["decision_id"]
        ]
        if len(authoritative_matches) != 1:
            raise ValueError(
                "resolution request does not match the authoritative pending decision"
            )
        if authoritative_matches[0] != request:
            raise ValueError(
                "resolution request does not match the authoritative pending decision"
            )
        return {
            "status": "RESOLUTION_PREVIEW",
            "decision_id": resolution["decision_id"],
            "project_id": resolution["project_id"],
            "task_id": resolution["task_id"],
            "selected_option": resolution["selected_option"],
            "resume_state": resolution["resume_state"],
            "pending_request_status": request["status"],
            "authorization_status": "NOT_EVALUATED",
            "controls": {
                "model_execution": "NOT_STARTED",
                "process_launch": "NOT_STARTED",
                "state_write": "NOT_PERFORMED",
                "workflow_transition": "NOT_PERFORMED",
            },
        }

    if args.group == "rc" and args.command == "prepare":
        manifest_path = build_release_candidate_manifest(
            output_dir=Path(args.output_dir),
            project_id=args.project_id,
            rc_id=args.rc_id,
            version=args.version,
            source_path=Path(args.source),
            build_artifact_paths=[Path(path) for path in args.build_artifact],
            verification_paths=[Path(path) for path in args.verification],
            review_paths=[Path(path) for path in args.review],
            rollback_path=Path(args.rollback),
            created_at_utc=args.created_at_utc,
        )
        verify_release_candidate_manifest(manifest_path, require_build_artifacts=True)
        return {"status": "RC_READY", "manifest_path": str(manifest_path.resolve(strict=True))}

    if args.group == "rc" and args.command == "verify":
        manifest_path = Path(args.manifest)
        verify_release_candidate_manifest(
            manifest_path,
            expected_project_id=args.expected_project_id,
            expected_task_id=args.expected_task_id,
            require_build_artifacts=args.require_build_artifacts,
        )
        return {
            "status": "VALID",
            "manifest_path": str(manifest_path.resolve(strict=True)),
        }

    if args.group == "rc" and args.command == "task-gate-preview":
        return WorkflowEngine(
            policy_root=Path(args.policy_root),
            state_root=Path(args.state_root),
            project_root=Path(args.project_root),
            profile_id=args.profile_id,
            read_only=True,
        ).rc_ready_gate_preview(
            args.task_id,
            manifest_path=Path(args.manifest),
            actor=args.actor,
            created_at_utc=args.created_at_utc,
            risk_triggers=args.risk_trigger,
            human_triggers=args.human_trigger,
            task_attributes=_parse_attributes(args.task_attribute),
        )

    if args.group == "rc" and args.command == "task-transition-commit-verify":
        return WorkflowEngine(
            policy_root=Path(args.policy_root),
            state_root=Path(args.state_root),
            project_root=Path(args.project_root),
            profile_id=args.profile_id,
            read_only=True,
        ).rc_ready_transition_commit_verification(args.task_id)

    if args.group == "coding" and args.command == "gate-init":
        return WorkflowStore(Path(args.state_root)).initialize_coding_execution_slot(args.gate_id, args.task_id)

    if args.group == "coding" and args.command == "gate-status":
        return WorkflowStore(Path(args.state_root)).read_coding_execution_slot(args.gate_id)

    if args.group == "coding" and args.command == "record-validate":
        record = _read_canonical_json_mapping(Path(args.record))
        validate_contract("coding_execution_record", record)
        return {
            "status": "VALID",
            "execution_id": record["execution_id"],
            "gate_id": record["gate_id"],
            "outcome": record["outcome"],
        }

    if args.group == "plan" and args.command == "handoff-preview":
        packet = _read_canonical_json_mapping(Path(args.packet))
        return build_supervised_planner_handoff_preview(packet)

    if args.group == "plan" and args.command == "result-receipt-preview":
        packet = _read_canonical_json_mapping(Path(args.packet))
        agent_result = _read_canonical_json_mapping(Path(args.result))
        return build_supervised_planner_result_receipt_preview(packet, agent_result)

    if args.group == "coding" and args.command == "handoff-preview":
        packet = _read_canonical_json_mapping(Path(args.packet))
        return build_supervised_coder_handoff_preview(packet)

    if args.group == "coding" and args.command == "result-receipt-preview":
        packet = _read_canonical_json_mapping(Path(args.packet))
        agent_result = _read_canonical_json_mapping(Path(args.result))
        return build_supervised_coder_result_receipt_preview(packet, agent_result)

    if args.group == "review" and args.command == "handoff-preview":
        packet = _read_canonical_json_mapping(Path(args.packet))
        return build_supervised_reviewer_handoff_preview(packet)

    if args.group == "review" and args.command == "result-receipt-preview":
        packet = _read_canonical_json_mapping(Path(args.packet))
        agent_result = _read_canonical_json_mapping(Path(args.result))
        return build_supervised_reviewer_result_receipt_preview(packet, agent_result)

    if args.group == "verify" and args.command == "handoff-preview":
        packet = _read_canonical_json_mapping(Path(args.packet))
        return build_supervised_verifier_handoff_preview(packet)

    if args.group == "verify" and args.command == "result-receipt-preview":
        packet = _read_canonical_json_mapping(Path(args.packet))
        agent_result = _read_canonical_json_mapping(Path(args.result))
        return build_supervised_verifier_result_receipt_preview(packet, agent_result)

    raise ValueError("unsupported command")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        result = _dispatch(args)
    except (OSError, ValueError, WorkflowStoreError, json.JSONDecodeError) as exc:
        json.dump({"status": "REJECTED", "error": str(exc)}, sys.stdout, sort_keys=True)
        sys.stdout.write("\n")
        return 2
    json.dump(result, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0
