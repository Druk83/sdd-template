"""Явная логическая проверка ASIR по локальному методическому пакету.

Модуль передаёт агенту зафиксированный методический пакет ASIR, проверяет
расширенный ответ и сохраняет экспертное заключение отдельным слоем. Адаптер
никогда не превращает его в факт, доказательство, разрешение действия или
показатель риска.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from typing import Mapping

from .errors import InputError
from .method_pack import load_method_pack, method_fingerprint


LOGIC_REVIEW_CONTRACT_VERSION = "0.2"
LOCAL_LOGIC_SKILL = "asir.local.logic_review"
REVIEW_STATUSES = {"NO_FINDINGS", "REVIEW_REQUIRED", "INVALID_RESULT"}
SEVERITIES = {"info", "low", "medium", "high", "critical"}
CONFIDENCE_LEVELS = {"low", "medium", "high"}
TRUTH_SCOPES = {"formal", "material", "both", "unknown"}
FORBIDDEN_RESULT_FIELDS = {
    "facts",
    "proved",
    "proof_result",
    "actions",
    "execution_policy",
    "ai_risk_score",
    "risk_score",
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _text(value: object, field: str, *, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"поле logic-review {field} должно быть непустой строкой")
    return value.strip()


def _source_refs(model: Mapping) -> dict[str, dict]:
    sources = model.get("sources", [])
    if not isinstance(sources, list):
        return {}
    return {
        source["relative_path"]: source
        for source in sources
        if isinstance(source, dict) and isinstance(source.get("relative_path"), str)
    }


def _fragment_id(item: Mapping, prefix: str, index: int) -> str:
    value = item.get("id")
    return value if isinstance(value, str) and value else f"{prefix}-{index + 1:04d}"


def _fragment(item: Mapping, fragment_id: str, source_refs: Mapping[str, dict], kind: str) -> dict | None:
    source_ref = item.get("source_ref")
    if not isinstance(source_ref, dict):
        return None
    relative_path = source_ref.get("relative_path")
    if relative_path not in source_refs:
        return None
    return {
        "id": fragment_id,
        "kind": kind,
        "text": item.get("text", ""),
        "source_ref": source_ref,
    }


def build_logic_review_request(
    model: Mapping,
    *,
    input_path: str | None = None,
    request_text: str | None = None,
    requested_at: str | None = None,
) -> dict:
    """Сформировать provenance-bound запрос вместе с методиками для агента."""
    compilation_id = _text(model.get("compilationId"), "compilationId")
    method_pack = load_method_pack()
    sources = _source_refs(model)
    fragments: list[dict] = []
    for key, kind in (("propositions", "proposition"), ("logical_expressions", "logical_expression"), ("fragment_analyses", "fragment_analysis")):
        values = model.get(key, [])
        if not isinstance(values, list):
            continue
        for index, value in enumerate(values):
            if isinstance(value, dict):
                item = _fragment(value, _fragment_id(value, kind, index), sources, kind)
                if item is not None:
                    fragments.append(item)
    if not fragments:
        for key, kind in (("goals", "goal"), ("constraints", "constraint"), ("assumptions", "assumption")):
            values = model.get(key, [])
            if isinstance(values, list):
                for index, value in enumerate(values):
                    if isinstance(value, dict):
                        item = _fragment(value, _fragment_id(value, kind, index), sources, kind)
                        if item is not None:
                            fragments.append(item)

    request_id = "lr-" + sha256(
        f"{compilation_id}:{len(fragments)}:{method_pack['manifest']['pack_sha256']}".encode("utf-8")
    ).hexdigest()[:16]
    return {
        "contract": "asir.logic_review_request",
        "contract_version": LOGIC_REVIEW_CONTRACT_VERSION,
        "request_id": request_id,
        "compilationId": compilation_id,
        "model_version": model.get("model_version"),
        "created_at": requested_at or _now(),
        "input_path": input_path,
        "source_provenance": list(sources.values()),
        "fragments": fragments,
        "method_pack": method_pack,
        "deterministic_context": {
            "logical_findings": model.get("logical_findings", model.get("findings", [])),
            "review_hypotheses": model.get("review_hypotheses", []),
        },
        "instructions": {
            "mode": "review_only",
            "skill": LOCAL_LOGIC_SKILL,
            "user_request": request_text or "Провести логический анализ фрагментов ASIR.",
            "check": [
                "понятия и согласованность терминов",
                "суждения и структура аргумента",
                "силлогизмы и корректность вывода",
                "индукция и необоснованные обобщения",
                "формальные и содержательные логические ошибки",
            ],
            "algorithm": method_pack["algorithm"],
            "required_sections": method_pack["required_sections"],
            "method_manifest": method_fingerprint(method_pack),
            "constraints": [
                "Не изменять источник в режиме проверки.",
                "Не выдумывать факты и ссылки.",
                "Каждая находка должна ссылаться на переданный фрагмент.",
                "Возвращать только наблюдения; ASIR определяет, разрешено ли действие человека.",
                "Для каждого этапа алгоритма вернуть результат или not_applicable с причиной.",
                "Не ограничиваться кодами ASIR: использовать локальный каталог ошибок и точное описание.",
            ],
        },
    }


def _validate_source_ref(value: object, refs: Mapping[str, dict], field: str) -> dict:
    if not isinstance(value, dict):
        raise InputError(f"поле logic-review {field} должно быть объектом")
    path = value.get("relative_path")
    if not isinstance(path, str) or path not in refs:
        raise InputError(f"поле logic-review {field} ссылается на неизвестный источник")
    return value


def _validate_string_list(value: object, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise InputError(f"поле logic-review {field} должно быть массивом непустых строк")
    return [item.strip() for item in value]


def _reject_forbidden(value: object) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in FORBIDDEN_RESULT_FIELDS:
                raise InputError(f"результат logic-review не может устанавливать поле {key}")
            _reject_forbidden(child)
    elif isinstance(value, list):
        for child in value:
            _reject_forbidden(child)


def _validate_argument_structure(value: object, fragment_ids: set[str]) -> dict:
    if not isinstance(value, Mapping):
        raise InputError("expert_review.argument_structure должен быть объектом")
    normalized: dict[str, list] = {}
    for key in ("theses", "premises", "conclusions", "inferences"):
        items = value.get(key, [])
        if not isinstance(items, list):
            raise InputError(f"expert_review.argument_structure.{key} должен быть массивом")
        normalized_items = []
        for index, item in enumerate(items):
            if not isinstance(item, Mapping):
                raise InputError(f"элемент {key}[{index}] должен быть объектом")
            item_copy = dict(item)
            refs = item_copy.get("fragment_ids", [])
            if refs:
                refs = _validate_string_list(refs, f"argument_structure.{key}[{index}].fragment_ids")
                unknown = set(refs) - fragment_ids
                if unknown:
                    raise InputError(f"структура аргумента ссылается на неизвестные фрагменты: {sorted(unknown)}")
                item_copy["fragment_ids"] = refs
            normalized_items.append(item_copy)
        normalized[key] = normalized_items
    return normalized


def validate_logic_review_result(result: Mapping, request: Mapping) -> dict:
    """Проверить расширенный ответ агента и вернуть нейтральную копию."""
    if not isinstance(result, Mapping):
        raise InputError("корень результата logic-review должен быть объектом")
    if result.get("contract") != "asir.logic_review_result":
        raise InputError("результат logic-review содержит неподдерживаемый контракт")
    if result.get("contract_version") != LOGIC_REVIEW_CONTRACT_VERSION:
        raise InputError("результат logic-review содержит неподдерживаемую версию контракта")
    if result.get("request_id") != request.get("request_id"):
        raise InputError("request_id результата logic-review не совпадает с запросом")
    if result.get("skill") != LOCAL_LOGIC_SKILL:
        raise InputError("результат logic-review должен указывать локальный метод ASIR")
    status = result.get("status")
    if status not in REVIEW_STATUSES:
        raise InputError(f"результат logic-review содержит неподдерживаемый статус: {status}")
    _reject_forbidden(result)
    expected_manifest = request.get("instructions", {}).get("method_manifest")
    if result.get("method_manifest") != expected_manifest:
        raise InputError("результат logic-review не подтверждает использованный пакет методик")
    refs = {item["relative_path"]: item for item in request.get("source_provenance", []) if isinstance(item, dict) and isinstance(item.get("relative_path"), str)}
    fragment_ids: set[str] = set()
    for item in request.get("fragments", []):
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        if isinstance(item_id, str) and item_id:
            fragment_ids.add(item_id)
    expert = result.get("expert_review")
    if not isinstance(expert, Mapping):
        raise InputError("результат logic-review должен содержать блок expert_review")
    verdict = expert.get("verdict", status)
    if verdict not in REVIEW_STATUSES | {"INCONCLUSIVE"}:
        raise InputError(f"expert_review содержит неподдерживаемый вердикт: {verdict}")
    findings = expert.get("findings", result.get("findings", []))
    if not isinstance(findings, list):
        raise InputError("expert_review.findings должен быть массивом")
    normalized: list[dict] = []
    for index, finding in enumerate(findings):
        if not isinstance(finding, Mapping):
            raise InputError(f"находка logic-review {index + 1} должна быть объектом")
        finding_id = _text(finding.get("id"), f"finding {index + 1}.id")
        raw_fragment_ids = finding.get("fragment_ids")
        if raw_fragment_ids is None:
            raw_fragment_ids = [finding.get("fragment_id")]
        fragment_refs = _validate_string_list(raw_fragment_ids, f"finding {finding_id}.fragment_ids")
        unknown = set(fragment_refs) - fragment_ids
        if not fragment_refs or unknown:
            raise InputError(f"находка logic-review {finding_id} ссылается на неизвестный фрагмент")
        raw_source_refs = finding.get("source_refs")
        if raw_source_refs is None:
            raw_source_refs = [finding.get("source_ref")]
        if not isinstance(raw_source_refs, list) or not raw_source_refs:
            raise InputError(f"finding {finding_id}.source_refs должен быть непустым массивом")
        source_refs = [_validate_source_ref(item, refs, f"finding {finding_id}.source_refs") for item in raw_source_refs]
        severity = finding.get("severity", "medium")
        confidence = finding.get("confidence", "medium")
        if severity not in SEVERITIES:
            raise InputError(f"находка logic-review {finding_id} содержит недопустимую серьёзность")
        if confidence not in CONFIDENCE_LEVELS:
            raise InputError(f"находка logic-review {finding_id} содержит недопустимую уверенность")
        truth_scope = finding.get("truth_scope", "unknown")
        if truth_scope not in TRUTH_SCOPES:
            raise InputError(f"находка logic-review {finding_id} содержит недопустимую область истины")
        normalized.append({
            "id": finding_id,
            "code": _text(finding.get("code"), f"finding {finding_id}.code"),
            "family": _text(finding.get("family"), f"finding {finding_id}.family"),
            "name_ru": _text(finding.get("name_ru"), f"finding {finding_id}.name_ru"),
            "name_latin": _text(finding.get("name_latin"), f"finding {finding_id}.name_latin"),
            "title": _text(finding.get("title") or finding.get("name_ru"), f"finding {finding_id}.title"),
            "message": _text(finding.get("message") or finding.get("why"), f"finding {finding_id}.message"),
            "explanation": _text(finding.get("explanation") or finding.get("why"), f"finding {finding_id}.explanation"),
            "truth_scope": truth_scope,
            "severity": severity,
            "confidence": confidence,
            "fragment_ids": fragment_refs,
            "fragment_id": fragment_refs[0],
            "source_refs": source_refs,
            "source_ref": source_refs[0],
            "hidden_premises": _validate_string_list(finding.get("hidden_premises"), f"finding {finding_id}.hidden_premises"),
            "consequences": _validate_string_list(finding.get("consequences"), f"finding {finding_id}.consequences"),
            "suggested_fix": _text(finding.get("suggested_fix"), f"finding {finding_id}.suggested_fix", required=False),
        })
    if status == "NO_FINDINGS" and normalized:
        raise InputError("результат logic-review со статусом NO_FINDINGS не может содержать находки")
    if status == "REVIEW_REQUIRED" and not normalized:
        raise InputError("результат logic-review со статусом REVIEW_REQUIRED должен содержать находки")
    normalized_expert = {
        "provider": expert.get("provider", "asir-local-logic"),
        "verdict": verdict,
        "argument_structure": _validate_argument_structure(expert.get("argument_structure", {}), fragment_ids),
        "findings": normalized,
        "hidden_premises": _validate_string_list(expert.get("hidden_premises"), "expert_review.hidden_premises"),
        "non_deductive_strength": expert.get("non_deductive_strength", []),
        "limitations": _validate_string_list(expert.get("limitations"), "expert_review.limitations"),
    }
    if not isinstance(normalized_expert["non_deductive_strength"], list):
        raise InputError("expert_review.non_deductive_strength должен быть массивом")
    return {
        "contract": "asir.logic_review_result",
        "contract_version": LOGIC_REVIEW_CONTRACT_VERSION,
        "request_id": request["request_id"],
        "compilationId": request["compilationId"],
        "skill": LOCAL_LOGIC_SKILL,
        "method_manifest": expected_manifest,
        "status": status,
        "completed_at": result.get("completed_at") or _now(),
        "expert_review": normalized_expert,
        "findings": normalized,
        "notes": _text(result.get("notes"), "notes", required=False),
    }


def build_logic_review_report(request: Mapping, result: Mapping | None = None) -> dict:
    """Сформировать слоистый отчёт без права разрешить выполнение."""
    findings = list(result.get("findings", [])) if isinstance(result, Mapping) else []
    status = result.get("status") if isinstance(result, Mapping) else "REVIEW_REQUIRED"
    expert_review = result.get("expert_review") if isinstance(result, Mapping) else None
    deterministic = request.get("deterministic_context", {})
    cards = [
        {
            "id": f"logic-card-{finding['id']}",
            "kind": "logic_review_observation",
            "status": "HUMAN_DECISION_REQUIRED",
            "question": f"Принять ли во внимание логическое замечание {finding['id']}?",
            "finding_id": finding["id"],
            "source_ref": finding["source_ref"],
            "fragment_ids": finding.get("fragment_ids", [finding.get("fragment_id")]),
            "variants": ["A: принять как замечание для редакции", "B: отклонить замечание"],
        }
        for finding in findings
    ]
    return {
        "contract": "asir.logic_review_report",
        "contract_version": LOGIC_REVIEW_CONTRACT_VERSION,
        "request": request,
        "result": result,
        "status": status,
        "layers": {
            "deterministic_asir": {
                "findings": deterministic.get("logical_findings", []),
                "role": "локальные детерминированные наблюдения ASIR",
            },
            "expert_logic": {
                "review": expert_review,
                "role": "агентное экспертное заключение по локальной методике ASIR",
            },
        },
        "expert_review": expert_review,
        "findings": findings,
        "decision_cards": cards,
        "user_guidance": {
            "mode": "HUMAN_DECISION_REQUIRED" if findings else "NO_ACTION_REQUIRED",
            "observations_are_context_only": True,
            "message": "Логические замечания не изменяют ASIR-модель автоматически.",
        },
        "execution_policy": {
            "allowed": False,
            "mode": "review",
            "reason": "наблюдения logic-review требуют решения человека",
        },
        "exit_code": 2 if status == "REVIEW_REQUIRED" else 0,
    }


def logic_review_output(report: Mapping, output_format: str) -> str:
    if output_format == "json":
        import json
        return json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if output_format == "context":
        import json
        return json.dumps({"logic_review": report}, ensure_ascii=False, indent=2) + "\n"
    if output_format == "text":
        expert = report.get("expert_review") or {}
        lines = [f"статус={report['status']}", f"экспертных_находок={len(report['findings'])}"]
        if expert:
            lines.append(f"вердикт_expert_review={expert.get('verdict', 'REVIEW_REQUIRED')}")
        lines.extend(f"{item['id']} [{item['severity']}] {item['message']}" for item in report["findings"])
        return "\n".join(lines) + "\n"
    lines = ["# Логическая проверка ASIR", "", f"Статус: `{report['status']}`", ""]
    deterministic = report.get("layers", {}).get("deterministic_asir", {})
    lines.extend(["## 1. Детерминированный анализ ASIR", "", f"Наблюдений: {len(deterministic.get('findings', []))}", ""])
    expert = report.get("expert_review")
    if expert:
        structure = expert.get("argument_structure", {})
        lines.extend([
            "## 2. Экспертный логический review ASIR", "",
            f"Вердикт: `{expert.get('verdict', report['status'])}`", "",
            "### Структура аргумента", "",
            f"Тезисов: {len(structure.get('theses', []))}; посылок: {len(structure.get('premises', []))}; "
            f"выводов: {len(structure.get('conclusions', []))}; переходов: {len(structure.get('inferences', []))}", "",
            f"Скрытых посылок: {len(expert.get('hidden_premises', []))}", "",
            "### Экспертные замечания", "",
        ])
    for item in report["findings"]:
        lines.extend([
            f"### {item['id']}: {item['name_ru']} ({item['name_latin']})", "",
            f"{item['message']} Область: `{item['truth_scope']}`.", "",
            f"Источник: `{item['source_ref']['relative_path']}`", "",
            f"Исправление: {item['suggested_fix'] or 'не предложено'}", "",
        ])
    lines.extend(["## 3. Карточки решений", "", f"Карточек: {len(report['decision_cards'])}", ""])
    return "\n".join(lines)
