"""Локальный контракт внешнего решателя без запуска реальных провайдеров."""

from __future__ import annotations

from collections.abc import Mapping

from .proof_contract import validate_formal_claim

ALLOWED_PARAMETERS = {"timeout_ms", "memory_mib", "max_trace_nodes"}
REQUEST_FIELDS = {"request_id", "solver_id", "solver_version", "formal_model_checksum", "goal", "parameters", "capabilities"}
RESPONSE_FIELDS = {"request_id", "solver_id", "solver_version", "formal_model_checksum", "status", "trace", "diagnostics"}
RESPONSE_STATUSES = {"PROVED", "REFUTED", "NOT_EVALUATED", "AMBIGUOUS", "TIMEOUT", "UNAVAILABLE", "INCOMPATIBLE", "ERROR"}


def available_adapters() -> list[dict]:
    """Возвращает только отключённые локальные адаптеры; сеть не используется."""
    return [{
        "id": "fake-local",
        "version": "1.0",
        "enabled": False,
        "network": False,
        "capabilities": {"claim_kinds": ["atom", "not", "comparison"], "verifiable_trace": True},
    }]


def _unknown_fields(value: Mapping, allowed: set[str], location: str) -> list[str]:
    unknown = sorted(str(key) for key in value if key not in allowed)
    return [f"{location} contains unsupported fields: " + ", ".join(unknown)] if unknown else []


def _is_trace_node(value: object) -> bool:
    if not isinstance(value, Mapping) or not isinstance(value.get("id"), str) or not value.get("id"):
        return False
    source_ref = value.get("source_ref")
    return isinstance(source_ref, Mapping) and isinstance(source_ref.get("relative_path"), str) and bool(source_ref.get("relative_path"))


def validate_solver_request(value: object) -> list[str]:
    if not isinstance(value, Mapping):
        return ["solver_request must be an object"]
    errors = _unknown_fields(value, REQUEST_FIELDS, "solver_request")
    for field in ("request_id", "solver_id", "solver_version", "formal_model_checksum"):
        if not isinstance(value.get(field), str) or not value.get(field):
            errors.append(f"solver_request.{field} must be a non-empty string")
    checksum = value.get("formal_model_checksum")
    if isinstance(checksum, str) and (len(checksum) != 64 or any(char not in "0123456789abcdef" for char in checksum.lower())):
        errors.append("solver_request.formal_model_checksum must be a SHA-256 string")
    errors.extend("solver_request.goal." + error for error in validate_formal_claim(value.get("goal")))
    parameters = value.get("parameters")
    if not isinstance(parameters, Mapping):
        errors.append("solver_request.parameters must be an object")
    else:
        unknown = sorted(str(key) for key in parameters if key not in ALLOWED_PARAMETERS)
        if unknown:
            errors.append("solver_request.parameters contains unsupported keys: " + ", ".join(unknown))
        if any(not isinstance(item, int) or isinstance(item, bool) or item <= 0 for item in parameters.values()):
            errors.append("solver_request.parameters values must be positive integers")
    capabilities = value.get("capabilities")
    if not isinstance(capabilities, Mapping):
        errors.append("solver_request.capabilities must be an object")
    else:
        errors.extend(_unknown_fields(capabilities, {"verifiable_trace", "claim_kinds"}, "solver_request.capabilities"))
        if capabilities.get("verifiable_trace") is not True:
            errors.append("solver_request.capabilities.verifiable_trace must be true")
        claim_kinds = capabilities.get("claim_kinds")
        if claim_kinds is not None and (not isinstance(claim_kinds, list) or any(item not in {"atom", "not", "comparison"} for item in claim_kinds)):
            errors.append("solver_request.capabilities.claim_kinds is unsupported")
    return errors


def validate_solver_response(value: object, request: Mapping) -> list[str]:
    errors = validate_solver_request(request)
    if not isinstance(value, Mapping):
        return errors + ["solver_response must be an object"]
    errors.extend(_unknown_fields(value, RESPONSE_FIELDS, "solver_response"))
    if value.get("request_id") != request.get("request_id"):
        errors.append("solver_response.request_id must match request")
    if value.get("formal_model_checksum") != request.get("formal_model_checksum"):
        errors.append("solver_response.formal_model_checksum must match request")
    if value.get("solver_id") != request.get("solver_id") or value.get("solver_version") != request.get("solver_version"):
        errors.append("solver_response solver identity must match request")
    status = value.get("status")
    if status not in RESPONSE_STATUSES:
        errors.append("solver_response.status is unsupported")
    trace = value.get("trace")
    if status in {"PROVED", "REFUTED"}:
        if not isinstance(trace, list) or not trace or not all(_is_trace_node(item) for item in trace):
            errors.append("positive solver response requires a verifiable trace with source_ref")
    elif trace is not None and not isinstance(trace, list):
        errors.append("solver_response.trace must be an array")
    diagnostics = value.get("diagnostics", [])
    if not isinstance(diagnostics, list) or not all(isinstance(item, Mapping) for item in diagnostics):
        errors.append("solver_response.diagnostics must be an array of objects")
    return errors


def _diagnostics(response: Mapping, status: object) -> list[dict]:
    diagnostics = response.get("diagnostics")
    values = [dict(item) for item in diagnostics] if isinstance(diagnostics, list) and all(isinstance(item, Mapping) for item in diagnostics) else []
    return [{"origin": "solver_adapter", "status": str(status)}] + values


def result_from_response(value: object, request: Mapping) -> dict:
    """Нормализует ответ, не повышая непроверенный внешний результат до доказательства."""
    errors = validate_solver_response(value, request)
    response = value if isinstance(value, Mapping) else {}
    status = response.get("status")
    if errors:
        return {
            "status": "AMBIGUOUS",
            "blocking_reasons": [{"code": "UNVERIFIABLE_SOLVER_RESPONSE", "message": error} for error in errors],
            "trace": [],
            "diagnostics": _diagnostics(response, "AMBIGUOUS"),
        }
    if status in {"PROVED", "REFUTED"}:
        return {"status": status, "blocking_reasons": [], "trace": list(response.get("trace", [])), "diagnostics": _diagnostics(response, status)}
    code = "SOLVER_" + str(status)
    return {
        "status": "NOT_EVALUATED",
        "blocking_reasons": [{"code": code, "message": "Внешний решатель не предоставил проверяемый положительный результат."}],
        "trace": [],
        "diagnostics": _diagnostics(response, status),
    }


class FakeSolverAdapter:
    """Тестовый локальный адаптер без сети, процессов и файловой записи."""
    adapter_id = "fake-local"
    version = "1.0"

    def respond(self, request: Mapping, response: Mapping) -> dict:
        return result_from_response(response, request)