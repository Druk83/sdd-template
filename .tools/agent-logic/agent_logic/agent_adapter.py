"""Vendor-neutral consumer for the ASIR agent context."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .errors import InputError
from .proof_contract import PROOF_STATUSES, validate_formal_claim, validate_proof_explanation
from .runtime_store import RuntimeStore

INTEGRATION_CONTRACT_VERSION = '1.0'
INTEGRATION_MESSAGE_TYPES = {
    'analysis_request',
    'analysis_result',
    'human_decision',
    'action_confirmation',
}
FORBIDDEN_PROVIDER_FIELDS = {'provider', 'vendor', 'codex', 'copilot'}


def _required_string(message: Mapping, field: str) -> str:
    value = message.get(field)
    if not isinstance(value, str) or not value.strip():
        raise InputError(f'integration message requires non-empty {field}')
    return value


def _validate_provenance(value: object) -> list[dict]:
    if not isinstance(value, list) or not value:
        raise InputError('integration message requires non-empty provenance')
    provenance: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            raise InputError('provenance must contain objects')
        provenance.append(dict(item))
    return provenance


def _validate_execution_policy(value: object) -> dict:
    if not isinstance(value, dict):
        raise InputError('execution_policy must be an object')
    if not isinstance(value.get('allowed'), bool):
        raise InputError('execution_policy.allowed must be boolean')
    if value.get('mode') not in {'execute', 'review'}:
        raise InputError('execution_policy.mode must be execute or review')
    blockers = value.get('blockers', [])
    if not isinstance(blockers, list) or not all(isinstance(item, str) for item in blockers):
        raise InputError('execution_policy.blockers must be an array of strings')
    return dict(value)


def validate_integration_message(message: object) -> dict:
    if not isinstance(message, Mapping):
        raise InputError('integration message must be a JSON object')
    normalized = dict(message)
    if any(str(key).casefold() in FORBIDDEN_PROVIDER_FIELDS for key in normalized):
        raise InputError('integration message must not contain provider fields')
    if normalized.get('contract_version') != INTEGRATION_CONTRACT_VERSION:
        raise InputError('unsupported integration contract version')
    message_type = _required_string(normalized, 'message_type')
    if message_type not in INTEGRATION_MESSAGE_TYPES:
        raise InputError('unsupported integration message type')
    _required_string(normalized, 'request_id')
    _required_string(normalized, 'status')
    _validate_provenance(normalized.get('provenance'))
    _validate_execution_policy(normalized.get('execution_policy'))

    if message_type == 'analysis_request':
        _required_string(normalized, 'source_path')
        _required_string(normalized, 'source_version')
        if normalized.get('status') != 'requested':
            raise InputError('analysis request status must be requested')
        for field in ('applicable_rules', 'user_requirements'):
            values = normalized.get(field)
            if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
                raise InputError(f'{field} must be an array of strings')
    elif message_type == 'analysis_result':
        _required_string(normalized, 'compilation_id')
        model_version = _required_string(normalized, 'model_version')
        context = validate_agent_context(normalized.get('agent_context'))
        if context.get('model_version') != model_version:
            raise InputError('agent_context targets an outdated model version')
        if context.get('status') != normalized.get('status'):
            raise InputError('agent_context status does not match integration result')
        if context.get('execution_policy') != normalized.get('execution_policy'):
            raise InputError('agent_context execution_policy does not match integration result')
    elif message_type == 'human_decision':
        _required_string(normalized, 'decision_card_id')
        _required_string(normalized, 'base_model_version')
        if normalized.get('status') not in {'approved', 'rejected'}:
            raise InputError('human decision status must be approved or rejected')
        if normalized.get('status') == 'approved':
            _required_string(normalized, 'selected_variant')
    else:
        _required_string(normalized, 'model_version')
        _required_string(normalized, 'action')
        _required_string(normalized, 'initiator')
        _required_string(normalized, 'basis')
        if normalized.get('status') not in {'completed', 'failed'}:
            raise InputError('action confirmation status must be completed or failed')
        _required_string(normalized, 'result')
    return normalized


def create_analysis_request(
    *,
    request_id: str,
    source_path: str,
    source_version: str,
    provenance: list[dict],
    applicable_rules: list[str],
    user_requirements: list[str],
) -> dict:
    request = {
        'contract_version': INTEGRATION_CONTRACT_VERSION,
        'message_type': 'analysis_request',
        'request_id': request_id,
        'source_path': source_path,
        'source_version': source_version,
        'provenance': provenance,
        'applicable_rules': applicable_rules,
        'user_requirements': user_requirements,
        'status': 'requested',
        'execution_policy': {
            'allowed': False,
            'mode': 'review',
            'blockers': ['analysis_not_completed'],
        },
    }
    return validate_integration_message(request)


def create_analysis_result(request: Mapping, report: Mapping) -> dict:
    request_message = validate_integration_message(request)
    if request_message.get('message_type') != 'analysis_request':
        raise InputError('analysis result requires an analysis request')
    context = validate_agent_context(report.get('agent_context'))
    model_version = context.get('model_version')
    if not isinstance(model_version, str) or not model_version:
        raise InputError('agent_context requires model_version')
    result = {
        'contract_version': INTEGRATION_CONTRACT_VERSION,
        'message_type': 'analysis_result',
        'request_id': request_message['request_id'],
        'compilation_id': context.get('compilationId'),
        'model_version': model_version,
        'provenance': request_message['provenance'],
        'status': context.get('status'),
        'execution_policy': context.get('execution_policy'),
        'agent_context': dict(context),
        'decision_cards': context.get('decision_cards', []),
    }
    return validate_integration_message(result)


def create_human_decision_response(
    *,
    decision_card: Mapping,
    status: str,
    selected_variant: str | None = None,
    decided_by: str | None = None,
) -> dict:
    response = {
        'contract_version': INTEGRATION_CONTRACT_VERSION,
        'message_type': 'human_decision',
        'request_id': decision_card.get('id'),
        'decision_card_id': decision_card.get('id'),
        'base_model_version': decision_card.get('base_model_version'),
        'selected_variant': selected_variant,
        'decided_by': decided_by,
        'provenance': decision_card.get('sources', []),
        'status': status,
        'execution_policy': {
            'allowed': False,
            'mode': 'review',
            'blockers': ['human_decision_not_applied'],
        },
    }
    return validate_integration_message(response)


def validate_human_decision_response(message: object, current_model_version: str) -> dict:
    response = validate_integration_message(message)
    if response.get('message_type') != 'human_decision':
        raise InputError('integration message is not a human decision')
    if response.get('base_model_version') != current_model_version:
        raise InputError('human decision targets an outdated model version')
    return response


def create_action_confirmation(
    *,
    model_version: str,
    action: str,
    initiator: str,
    basis: str,
    result: str,
    provenance: list[dict],
    execution_policy: Mapping,
) -> dict:
    confirmation = {
        'contract_version': INTEGRATION_CONTRACT_VERSION,
        'message_type': 'action_confirmation',
        'request_id': action,
        'model_version': model_version,
        'action': action,
        'initiator': initiator,
        'basis': basis,
        'result': result,
        'provenance': provenance,
        'status': result,
        'execution_policy': dict(execution_policy),
    }
    return validate_integration_message(confirmation)


def register_action_confirmation(store: RuntimeStore, message: object) -> dict:
    confirmation = validate_integration_message(message)
    if confirmation.get('message_type') != 'action_confirmation':
        raise InputError('integration message is not an action confirmation')
    policy = _validate_execution_policy(confirmation.get('execution_policy'))
    if confirmation.get('status') == 'completed' and not policy.get('allowed'):
        raise InputError('completed action is blocked by execution_policy')
    return store.record_action(
        confirmation['model_version'],
        initiator=confirmation['initiator'],
        basis=confirmation['basis'],
        result=confirmation['result'],
    )


class FakeAgentAdapter:
    '''Provider-neutral adapter used for contract tests.'''

    def __init__(self, expected_model_version: str):
        self.expected_model_version = expected_model_version

    def receive(self, message: object) -> dict:
        result = validate_integration_message(message)
        if result.get('message_type') != 'analysis_result':
            raise InputError('fake adapter accepts only analysis results')
        if result.get('model_version') != self.expected_model_version:
            raise InputError('agent context targets an outdated model version')
        policy = _validate_execution_policy(result.get('execution_policy'))
        if not policy.get('allowed'):
            raise InputError('agent context is blocked by execution_policy')
        context = result['agent_context']
        cycle = run_agent_cycle(context)
        if not cycle.get('can_execute'):
            raise InputError('agent context is blocked')
        return cycle


REQUIRED_CONTEXT_FIELDS = (
    "compilationId",
    "goal",
    "available_actions",
    "applicable_rules",
    "status",
    "execution_policy",
)


def load_agent_context(path: str | Path) -> dict:
    source = str(path)
    if source == "-":
        raw = sys.stdin.read()
        source = "<stdin>"
    else:
        file_path = Path(path)
        try:
            raw = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise InputError(f"context is not valid UTF-8: {file_path}") from exc
        except OSError as exc:
            raise InputError(f"cannot read context: {file_path}") from exc
    try:
        context = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InputError(f"context is not valid JSON: {source}") from exc
    return validate_agent_context(context)


def validate_agent_context(context: object) -> dict[str, Any]:
    if not isinstance(context, dict):
        raise InputError("agent context must be a JSON object")
    missing = [field for field in REQUIRED_CONTEXT_FIELDS if field not in context]
    if missing:
        raise InputError(f"agent context is missing fields: {', '.join(missing)}")

    policy = context.get("execution_policy")
    if not isinstance(policy, dict):
        raise InputError("execution_policy must be an object")
    if not isinstance(policy.get("allowed"), bool):
        raise InputError("execution_policy.allowed must be boolean")
    if policy.get("mode") not in {"execute", "review"}:
        raise InputError("execution_policy.mode must be execute or review")
    blockers = policy.get("blockers", [])
    if not isinstance(blockers, list) or not all(isinstance(item, str) for item in blockers):
        raise InputError("execution_policy.blockers must be an array of strings")

    guidance = context.get("user_guidance")
    if not isinstance(guidance, dict):
        raise InputError("user_guidance must be an object")
    if guidance.get("mode") not in {"NO_ACTION_REQUIRED", "REVIEW_REQUIRED", "HUMAN_DECISION_REQUIRED"}:
        raise InputError("user_guidance.mode is unsupported")
    if not isinstance(guidance.get("summary"), str) or not guidance.get("summary").strip():
        raise InputError("user_guidance.summary must be a non-empty string")
    required_actions = guidance.get("required_actions")
    if not isinstance(required_actions, list) or not all(isinstance(item, dict) for item in required_actions):
        raise InputError("user_guidance.required_actions must be an array of objects")
    if guidance.get("mode") == "NO_ACTION_REQUIRED" and required_actions:
        raise InputError("NO_ACTION_REQUIRED must not include required actions")
    if guidance.get("observations_are_context_only") is not True:
        raise InputError("user_guidance must keep observations as context only")
    for action in required_actions:
        if action.get("kind") not in {"finding", "gap"}:
            raise InputError("user_guidance action must originate from a finding or GAP")
    for field in ("available_actions", "applicable_rules", "unresolved_gaps"):
        if not isinstance(context.get(field), list):
            raise InputError(f"{field} must be an array")
    if "observations" in context and not isinstance(context["observations"], list):
        raise InputError("observations must be an array")
    proof_result = context.get("proof_result")
    if proof_result is not None:
        if not isinstance(proof_result, dict):
            raise InputError("proof_result must be an object when supplied")
        if proof_result.get("status") not in PROOF_STATUSES:
            raise InputError("proof_result.status is unsupported")
        if validate_formal_claim(proof_result.get("formal_claim")):
            raise InputError("proof_result.formal_claim is invalid")
        if proof_result.get("explanation") is not None and validate_proof_explanation(proof_result.get("explanation"), proof_result.get("status")):
            raise InputError("proof_result.explanation is invalid")
        if proof_result.get("status") not in {"PROVED", "REFUTED"} and (policy.get("allowed") or policy.get("mode") != "review"):
            raise InputError("incomplete proof_result must keep execution_policy in review mode")
    if not isinstance(context.get("status"), str):
        raise InputError("context status must be a string")
    return dict(context)


def _review_blockers(context: dict) -> list[str]:
    policy = context["execution_policy"]
    blockers = [item for item in policy.get("blockers", []) if isinstance(item, str)]
    if not blockers:
        blockers = [
            item.get("id")
            for item in context.get("unresolved_gaps", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]
    if not blockers and not policy.get("allowed"):
        blockers = ["execution_policy.allowed=false"]
    if not blockers and context.get("status") != "confirmed":
        blockers = [f"status={context.get('status')}"]
    return [blocker for blocker in blockers if isinstance(blocker, str)]


def run_agent_cycle(context: dict, *, action_limit: int | None = None) -> dict:
    """Возвращает директиву ASIR, не превращая observation в действие."""
    validate_agent_context(context)
    guidance = context["user_guidance"]
    mode = guidance["mode"]
    policy = context["execution_policy"]
    allowed = (
        policy.get("allowed") is True
        and policy.get("mode") == "execute"
        and context.get("status") == "confirmed"
        and not policy.get("blockers")
        and not context.get("unresolved_gaps")
    )
    rules = [item for item in context.get("applicable_rules", []) if isinstance(item, str) and item.strip()]
    if mode == "NO_ACTION_REQUIRED" and allowed:
        actions = [item for item in context.get("available_actions", []) if isinstance(item, str) and item.strip()]
        selected_actions = actions if action_limit is None else actions[:action_limit]
        return {
            "status": "READY", "decision": "NO_ACTION_REQUIRED", "can_execute": True,
            "compilationId": context.get("compilationId"), "goal": context.get("goal"), "user_guidance": guidance,
            "plan": [{"step": index, "action": action} for index, action in enumerate(selected_actions, start=1)],
            "total_actions": len(actions), "rules": rules, "blockers": [], "review_items": [],
        }
    actions = [item.get("next_step") for item in guidance.get("required_actions", []) if isinstance(item, dict) and isinstance(item.get("next_step"), str) and item.get("next_step").strip()]
    selected_actions = actions if action_limit is None else actions[:action_limit]
    blockers = _review_blockers(context)
    question = guidance.get("human_question")
    if mode == "HUMAN_DECISION_REQUIRED" and isinstance(question, str) and question:
        blockers.append("human_question=" + question)
    return {
        "status": "REVIEW_REQUIRED", "decision": mode, "can_execute": False,
        "compilationId": context.get("compilationId"), "goal": context.get("goal"), "user_guidance": guidance,
        "plan": [{"step": index, "action": action} for index, action in enumerate(selected_actions, start=1)],
        "rules": rules, "blockers": blockers, "review_items": context.get("unresolved_gaps", []),
    }

def format_agent_result(result: dict, output_format: str) -> str:
    if output_format == "json":
        return json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    lines = [
        f"status: {result.get('status', 'REVIEW_REQUIRED')}",
        f"decision: {result.get('decision', 'REVIEW_REQUIRED')}",
        f"can_execute: {str(result.get('can_execute', False)).lower()}",
        f"goal: {result.get('goal') or ''}",
        "user_guidance_mode: " + str(result.get("user_guidance", {}).get("mode", "REVIEW_REQUIRED")) if isinstance(result.get("user_guidance"), dict) else "user_guidance_mode: REVIEW_REQUIRED",
        "user_guidance: " + str(result.get("user_guidance", {}).get("summary", "")) if isinstance(result.get("user_guidance"), dict) else "user_guidance: ",
    ]
    blockers = result.get("blockers", [])
    if blockers:
        lines.append("blockers:")
        lines.extend(f"- {item}" for item in blockers)
    plan = result.get("plan", [])
    if plan:
        lines.append("plan:")
        lines.extend(f"{item['step']}. {item['action']}" for item in plan)
    else:
        lines.append("plan: empty")
    return "\n".join(lines) + "\n"
