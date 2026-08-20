"""Контракт явной гипотезы и результата формального исследования."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from .errors import OutputError
from .formalization_profiles import validate_formalization

HYPOTHESIS_MODES = {"deductive", "empirical"}
FORMALIZATION_STATUSES = {"confirmed", "approved", "review_required", "ambiguous"}
PROOF_STATUSES = {
    "PROVED",
    "REFUTED",
    "NOT_DERIVABLE",
    "INCONSISTENT",
    "AMBIGUOUS",
    "MISSING_PREMISES",
    "EMPIRICAL_VALIDATION_REQUIRED",
    "NOT_EVALUATED",
}


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_formal_claim(value: object) -> list[str]:
    """Проверяет минимальный DSL утверждений до запуска движка вывода."""
    if not isinstance(value, Mapping):
        return ["formal_claim must be an object"]
    kind = value.get("kind")
    if kind == "atom":
        errors: list[str] = []
        if not _is_non_empty_string(value.get("predicate")):
            errors.append("formal_claim.predicate must be a non-empty string")
        terms = value.get("terms", [])
        if not isinstance(terms, list) or any(not isinstance(term, (str, int, float)) or isinstance(term, bool) for term in terms):
            errors.append("formal_claim.terms must be an array of scalar values")
        return errors
    if kind == "comparison":
        if value.get("operator") not in {"=", "!=", "<", "<=", ">", ">="}:
            return ["formal_claim.operator is unsupported"]
        if any(not isinstance(value.get(field), (str, int, float)) or isinstance(value.get(field), bool) for field in ("left", "right")):
            return ["formal_claim comparison literals must be strings or numbers"]
        return []
    if kind == "not":
        nested = validate_formal_claim(value.get("claim"))
        return [f"formal_claim.claim: {error}" for error in nested]
    return ["formal_claim.kind must be atom, not or comparison"]


def validate_hypothesis(value: object, source_paths: set[str] | None = None) -> list[str]:
    """Возвращает ошибки контракта без неявной нормализации входных данных."""
    if not isinstance(value, Mapping):
        return ["hypothesis must be an object"]
    errors: list[str] = []
    for field in ("id", "text"):
        if not _is_non_empty_string(value.get(field)):
            errors.append(f"hypothesis.{field} must be a non-empty string")
    if value.get("mode") not in HYPOTHESIS_MODES:
        errors.append("hypothesis.mode must be deductive or empirical")
    if value.get("formalization_status") not in FORMALIZATION_STATUSES:
        errors.append("hypothesis.formalization_status is unsupported")
    errors.extend(validate_formal_claim(value.get("formal_claim")))
    confidence = value.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        errors.append("hypothesis.confidence must be between 0 and 1")
    source_ref = value.get("source_ref")
    if not isinstance(source_ref, Mapping):
        errors.append("hypothesis.source_ref must be an object")
    else:
        relative_path = source_ref.get("relative_path")
        if not _is_non_empty_string(relative_path):
            errors.append("hypothesis.source_ref.relative_path must be a non-empty string")
        elif source_paths is not None and relative_path not in source_paths:
            errors.append("hypothesis.source_ref references an unknown source")
    evidence = value.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        errors.append("hypothesis.evidence must be a non-empty array")
    return errors


def _claim_kinds(value: object) -> set[str]:
    if not isinstance(value, Mapping):
        return set()
    kind = value.get("kind")
    if kind == "not":
        return {"not"} | _claim_kinds(value.get("claim"))
    return {kind} if isinstance(kind, str) else set()


def validate_formal_model(value: object, source_context: Mapping[str, object] | None = None) -> list[str]:
    """Проверяет конечный DSL фактов и правил до передачи движку."""
    if not isinstance(value, Mapping):
        return ["formal_model must be an object"]
    errors: list[str] = []
    facts = value.get("facts")
    rules = value.get("rules")
    if not isinstance(facts, list) or not isinstance(rules, list):
        return ["formal_model.facts and formal_model.rules must be arrays"]
    identifiers: set[str] = set()
    for group, items in (("facts", facts), ("rules", rules)):
        for index, item in enumerate(items):
            location = f"formal_model.{group}[{index}]"
            if not isinstance(item, Mapping):
                errors.append(f"{location} must be an object")
                continue
            item_id = item.get("id")
            if not isinstance(item_id, str) or not item_id.strip():
                errors.append(f"{location}.id must be a non-empty string")
            elif item_id in identifiers:
                errors.append(f"duplicate formal item id: {item_id}")
            else:
                identifiers.add(item_id)
            if item.get("status") not in {"confirmed", "assumed", "observed", "review_required", "gap"}:
                errors.append(f"{location}.status is unsupported")
            source_ref = item.get("source_ref")
            if not isinstance(source_ref, Mapping):
                errors.append(f"{location}.source_ref must be an object")
                source_kind = None
                artifact_kind = None
            else:
                relative_path = source_ref.get("relative_path")
                context = source_context.get(relative_path) if isinstance(source_context, Mapping) and isinstance(relative_path, str) else None
                if isinstance(context, Mapping):
                    source_kind = context.get("input_kind") if isinstance(context.get("input_kind"), str) else None
                    artifact_kind = context.get("artifact_kind") if isinstance(context.get("artifact_kind"), str) else None
                elif isinstance(context, str):
                    source_kind = context
                    artifact_kind = None
                else:
                    source_kind = None
                    artifact_kind = None
            claim_values: list[object] = [item.get("claim")] if group == "facts" else [item.get("conclusion")]
            if group == "rules":
                premises_value = item.get("premises")
                if isinstance(premises_value, list):
                    claim_values.extend(premises_value)
            claim_kinds: set[str] = set()
            for claim_value in claim_values:
                claim_kinds.update(_claim_kinds(claim_value))
            for error in validate_formalization(item.get("formalization"), item_kind="fact" if group == "facts" else "rule", claim_kinds=claim_kinds, source_kind=source_kind, artifact_kind=artifact_kind):
                errors.append(f"{location}.{error}")
            if group == "facts":
                errors.extend(f"{location}.{error}" for error in validate_formal_claim(item.get("claim")))
                continue
            premises = item.get("premises")
            if not isinstance(premises, list) or not premises:
                errors.append(f"{location}.premises must be a non-empty AND array")
            else:
                for premise_index, premise in enumerate(premises):
                    errors.extend(f"{location}.premises[{premise_index}].{error}" for error in validate_formal_claim(premise))
            errors.extend(f"{location}.conclusion.{error}" for error in validate_formal_claim(item.get("conclusion")))
            exceptions = item.get("exceptions", [])
            if not isinstance(exceptions, list):
                errors.append(f"{location}.exceptions must be an array")
            else:
                for exception_index, exception in enumerate(exceptions):
                    errors.extend(f"{location}.exceptions[{exception_index}].{error}" for error in validate_formal_claim(exception))
    return errors
def validate_proof_explanation(value: object, proof_status: object) -> list[str]:
    """Проверяет объяснение результата, не превращая его в новые основания."""
    if not isinstance(value, Mapping):
        return ["proof_result.explanation must be an object"]
    errors: list[str] = []
    if value.get("classification") != proof_status:
        errors.append("proof_result.explanation.classification must match proof_result.status")
    traces = value.get("derivation_traces")
    alternatives = value.get("alternatives")
    safe_next_step = value.get("safe_next_step")
    if not isinstance(traces, list):
        errors.append("proof_result.explanation.derivation_traces must be an array")
    if not isinstance(alternatives, list):
        errors.append("proof_result.explanation.alternatives must be an array")
    if not isinstance(safe_next_step, Mapping):
        errors.append("proof_result.explanation.safe_next_step must be an object")
    elif not _is_non_empty_string(safe_next_step.get("code")) or not _is_non_empty_string(safe_next_step.get("message")):
        errors.append("proof_result.explanation.safe_next_step requires code and message")
    if isinstance(alternatives, list):
        for index, alternative in enumerate(alternatives):
            location = f"proof_result.explanation.alternatives[{index}]"
            if not isinstance(alternative, Mapping):
                errors.append(f"{location} must be an object")
                continue
            if not _is_non_empty_string(alternative.get("id")):
                errors.append(f"{location}.id must be a non-empty string")
            if alternative.get("polarity") not in {"hypothesis", "negation"}:
                errors.append(f"{location}.polarity is unsupported")
            errors.extend(f"{location}.target_claim.{error}" for error in validate_formal_claim(alternative.get("target_claim")))
            for field in ("rule_ids", "source_refs"):
                if not isinstance(alternative.get(field), list):
                    errors.append(f"{location}.{field} must be an array")
            missing_atoms = alternative.get("missing_atoms")
            if not isinstance(missing_atoms, list) or not missing_atoms:
                errors.append(f"{location}.missing_atoms must be a non-empty array")
            elif any(validate_formal_claim(item) for item in missing_atoms):
                errors.append(f"{location}.missing_atoms contains an invalid claim")
    return errors
def validate_evidence_record(value: object, source_paths: set[str] | None = None) -> list[str]:
    """Проверяет запись наблюдения без статистического или дедуктивного вывода."""
    if not isinstance(value, Mapping):
        return ["evidence_record must be an object"]
    errors: list[str] = []
    for field in ("id", "method", "recorded_at", "schema_version", "quality"):
        if not _is_non_empty_string(value.get(field)):
            errors.append(f"evidence_record.{field} must be a non-empty string")
    errors.extend("evidence_record.claim." + error for error in validate_formal_claim(value.get("claim")))
    source_ref = value.get("source_ref")
    if not isinstance(source_ref, Mapping):
        errors.append("evidence_record.source_ref must be an object")
    elif source_paths is not None and source_ref.get("relative_path") not in source_paths:
        errors.append("evidence_record.source_ref references an unknown source")
    if not isinstance(value.get("data_schema"), Mapping):
        errors.append("evidence_record.data_schema must be an object")
    return errors
def formal_model_checksum(model: Mapping, hypothesis: Mapping) -> str:
    """Фиксирует только формальную часть входа, а не изменяемый отчёт."""
    formal_model = {
        "formal_claim": hypothesis.get("formal_claim"),
        "formal_model": model.get("formal_model", {}),
        "propositions": model.get("propositions", []),
        "logical_expressions": model.get("logical_expressions", []),
    }
    encoded = json.dumps(formal_model, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def load_explicit_hypothesis(value: object, source_paths: set[str]) -> dict:
    """Принимает только явную валидную гипотезу, переданную пользователем или моделью."""
    candidate = value.get("hypothesis") if isinstance(value, Mapping) and isinstance(value.get("hypothesis"), Mapping) else value
    errors = validate_hypothesis(candidate, source_paths)
    if errors:
        raise OutputError("invalid hypothesis: " + "; ".join(errors))
    return dict(candidate)  # type: ignore[arg-type]


def build_proof_result(model: Mapping, hypothesis: Mapping) -> dict:
    """Создаёт честный результат контракта, пока движок вывода не подключён."""
    checksum = formal_model_checksum(model, hypothesis)
    status = "NOT_EVALUATED"
    blockers: list[dict[str, str]] = [{
        "code": "PROOF_ENGINE_NOT_INSTALLED",
        "message": "Движок формального вывода будет добавлен следующей задачей; утверждение не доказано и не опровергнуто.",
    }]
    if hypothesis.get("formalization_status") in {"review_required", "ambiguous"}:
        status = "AMBIGUOUS"
        blockers = [{
            "code": "FORMALIZATION_REVIEW_REQUIRED",
            "message": "Формализация гипотезы требует проверки человеком; вывод не запускался.",
        }]
    elif hypothesis.get("mode") == "empirical":
        status = "EMPIRICAL_VALIDATION_REQUIRED"
        blockers = [{
            "code": "EMPIRICAL_EVIDENCE_REQUIRED",
            "message": "Эмпирическая гипотеза требует внешних наблюдений или измерений; дедуктивный вывод не запускался.",
        }]
    elif model.get("status") in {"REVIEW_REQUIRED", "BLOCKED"}:
        status = "AMBIGUOUS"
        blockers = [{
            "code": "ASIR_REVIEW_REQUIRED",
            "message": "Исходная ASIR-модель содержит неразрешённые элементы; вывод не запускался.",
        }]
    safe_steps = {
        "AMBIGUOUS": ("CLARIFY_FORMALIZATION", "Уточнить формализацию с человеком; новые предпосылки не добавлять."),
        "EMPIRICAL_VALIDATION_REQUIRED": ("OBTAIN_EMPIRICAL_EVIDENCE", "Получить наблюдение или измерение; дедуктивное доказательство не заявлять."),
        "NOT_EVALUATED": ("COMPLETE_FORMAL_EVALUATION", "Передать человеку причину, по которой исследование не выполнено."),
    }
    step_code, step_message = safe_steps[status]
    return {
        "hypothesis_id": hypothesis["id"],
        "formal_claim": hypothesis["formal_claim"],
        "mode": hypothesis["mode"],
        "engine_version": "not-installed",
        "formal_model_checksum": checksum,
        "status": status,
        "proof_graph": [],
        "used_premises": [],
        "missing_premises": [],
        "blocking_reasons": blockers,
        "explanation": {
            "classification": status,
            "derivation_traces": [],
            "alternatives": [],
            "safe_next_step": {"code": step_code, "message": step_message},
        },
        "explanation_basis": ["explicit_hypothesis", "formal_model_checksum", "no_implicit_inference"],
    }