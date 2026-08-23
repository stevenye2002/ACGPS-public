from __future__ import annotations

from typing import Any

from acgps.contracts import validate_contract


def generate_task_packet(
    role: str,
    intake: dict[str, Any],
    policy_result: dict[str, Any],
) -> dict[str, Any]:
    validate_contract("task_intake", intake, mode="runtime")
    validate_contract("policy_evaluation_result", policy_result, mode="runtime")
    result = policy_result["result"]
    packet = {
        "schema_version": 1,
        "packet_id": f"{intake['task_id']}-{role.lower()}-v1",
        "role": role,
        "project_id": intake["project_id"],
        "task_id": intake["task_id"],
        "objective": intake["requested_outcome"],
        "binding_constraints": list(intake["known_constraints"]),
        "non_goals": list(intake["out_of_scope"]),
        "relevant_paths": list(intake["source_paths"]),
        "interfaces_consumed": [],
        "interfaces_produced": [],
        "acceptance_criteria": list(intake["acceptance_criteria"]),
        "required_skills": list(result["required_skills"]),
        "required_evidence": list(result["mandatory_gates"]),
        "prohibited_actions": ["production release", *intake["out_of_scope"]],
        "return_schema": "templates/AGENT_RESULT.yaml",
    }
    validate_contract("agent_task_contract", packet, mode="runtime")
    return packet
