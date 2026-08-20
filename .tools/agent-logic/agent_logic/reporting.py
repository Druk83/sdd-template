"""Построение контекстных отчётов и выходных форматов."""

from __future__ import annotations



import json
from collections import defaultdict
from collections.abc import Iterable, Mapping

from .decisions import decision_envelope

ARRAYS = (
    "goals", "entities", "attributes", "facts", "states", "events", "actions",
    "transitions", "conditions", "constraints", "invariants", "dependencies",
    "decisions", "exceptions", "assumptions", "gaps",
)
GAP_SAMPLE_LIMIT = 3
STRUCTURAL_CHECKS = ('STR-001', 'STR-002')
BOOLEAN_CHECKS = ('LGC-001', 'LGC-002', 'LGC-003')
DEONTIC_CHECKS = ('DNT-001', 'DNT-002', 'DNT-003', 'DNT-004')
ARGUMENT_CHECKS = ('ARG-001',)
DEFINITION_CHECKS = ('DEF-001', 'DEF-002')
LOGICAL_CHECKS = tuple(f"LOG-{number:03d}" for number in range(1, 9))
POLICY_CHECKS = tuple(f"POL-{number:03d}" for number in range(1, 5))
DEVELOPER_ACTION_LIMIT = 5


def _items(model: Mapping, names: Iterable[str]) -> list[dict]:
    result: list[dict] = []
    for name in names:
        values = model.get(name, [])
        if isinstance(values, list):
            result.extend(item for item in values if isinstance(item, dict))
    return result


def _unresolved(model: Mapping) -> list[dict]:
    result = []
    for item in _items(model, ARRAYS):
        if item.get("status") in {"gap", "REVIEW_REQUIRED", "assumed", "BLOCKED"}:
            result.append({
                "id": item.get("id"),
                "type": item.get("type"),
                "status": item.get("status"),
                "text": item.get("text"),
                "confidence": item.get("confidence"),
                "source_ref": item.get("source_ref"),
                "evidence": item.get("evidence"),
                "extraction_method": item.get("extraction_method"),
            })
    return result


def _observations(model: Mapping) -> list[dict]:
    return [
        {
            "id": item.get("id"),
            "type": item.get("type"),
            "status": item.get("status"),
            "text": item.get("text"),
            "confidence": item.get("confidence"),
            "source_ref": item.get("source_ref"),
            "evidence": item.get("evidence"),
            "extraction_method": item.get("extraction_method"),
        }
        for item in _items(model, ARRAYS)
        if item.get("status") == "observed"
    ]

def _findings(model: Mapping) -> list[dict]:
    values = model.get("findings", [])
    return [item for item in values if isinstance(item, dict)] if isinstance(values, list) else []


def _unresolved_findings(model: Mapping) -> list[dict]:
    return [
        item for item in _findings(model)
        if item.get("status") not in {"approved", "rejected", "auto_decided"}
        and (item.get("status") == "REVIEW_REQUIRED" or item.get("severity") in {"warning", "error"})
    ]


def _profiles(model: Mapping) -> list[dict]:
    values = model.get("artifact_profiles", [])
    return [item for item in values if isinstance(item, dict)] if isinstance(values, list) else []


def _reference_blocks(model: Mapping) -> list[dict]:
    values = model.get("reference_blocks", [])
    return [item for item in values if isinstance(item, dict)] if isinstance(values, list) else []


def _confidence(model: Mapping) -> str:
    value = model.get("confidence")
    return f"{value:.2f}" if isinstance(value, (int, float)) else "n/a"


def _gap_groups(unresolved: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for item in unresolved:
        if item.get("type") == "gap":
            groups[str(item.get("extraction_method") or "unknown")].append(item)
    return groups


def _source_label(item: Mapping) -> str:
    source_ref = item.get("source_ref")
    if not isinstance(source_ref, Mapping):
        return "unknown"
    path = str(source_ref.get("relative_path", "unknown"))
    line_range = source_ref.get("line_range")
    if isinstance(line_range, Mapping) and isinstance(line_range.get("start"), int):
        return f"{path}:{line_range['start']}"
    return path


def _display_text(item: Mapping) -> str:
    source_ref = item.get("source_ref")
    fragment = source_ref.get("fragment") if isinstance(source_ref, Mapping) else None
    text = str(fragment or item.get("text", "")).replace("\n", " ").strip()
    return text if len(text) <= 180 else text[:177].rstrip() + "..."


def _section_roles(profile: Mapping) -> dict[str, int]:
    sections = profile.get("section_profiles", [])
    counts: dict[str, int] = defaultdict(int)
    if isinstance(sections, list):
        for section in sections:
            if isinstance(section, Mapping):
                counts[str(section.get("role", "unknown"))] += 1
    return dict(sorted(counts.items()))


def _checks_for_profile(profile: Mapping) -> list[str]:
    checks = list(LOGICAL_CHECKS + STRUCTURAL_CHECKS + BOOLEAN_CHECKS + DEONTIC_CHECKS + ARGUMENT_CHECKS + DEFINITION_CHECKS)
    if profile.get("artifact_kind") == "normative_manifest":
        checks.extend(POLICY_CHECKS)
    return checks



def _norm_label(value: object) -> str:
    labels = {
        'PROHIBITION': 'запрет',
        'OBLIGATION': 'обязанность',
        'PERMISSION': 'разрешение',
    }
    return labels.get(str(value), 'норма')


def _norm_text(item: Mapping) -> str:
    source_ref = item.get('source_ref')
    fragment = source_ref.get('fragment') if isinstance(source_ref, Mapping) else None
    if isinstance(fragment, str) and fragment.strip():
        return fragment.replace('\n', ' ').strip()

    def role(name: str) -> str | None:
        value = item.get(name)
        text = value.get('text') if isinstance(value, Mapping) else None
        return str(text) if isinstance(text, str) and text.strip() else None

    parts = [role('subject'), role('predicate'), role('object')]
    return ' '.join(value for value in parts if value) or 'Исходная формулировка нормы недоступна.'


def _structural_summary(model: Mapping) -> dict:
    propositions = model.get('propositions', [])
    expressions = model.get('logical_expressions', [])
    typed: dict[str, int] = defaultdict(int)
    norms: list[dict] = []
    if isinstance(propositions, list):
        for proposition in propositions:
            if not isinstance(proposition, Mapping):
                continue
            proposition_type = str(proposition.get('type', 'unknown'))
            typed[proposition_type] += 1
            if proposition_type == 'norm':
                norms.append({
                    'id': proposition.get('id'),
                    'label': _norm_label(proposition.get('modality')),
                    'text': _norm_text(proposition),
                    'source_ref': proposition.get('source_ref'),
                })
    connectors: dict[str, int] = defaultdict(int)
    review_required = 0
    if isinstance(expressions, list):
        for expression in expressions:
            if isinstance(expression, Mapping):
                connectors[str(expression.get('operator', 'unknown'))] += 1
                if expression.get('status') == 'review_required':
                    review_required += 1
    return {
        'propositions': {'total': sum(typed.values()), 'by_type': dict(sorted(typed.items()))},
        'norms': norms,
        'logical_expressions': {
            'total': sum(connectors.values()),
            'by_operator': dict(sorted(connectors.items())),
            'review_required': review_required,
        },
    }


def _append_structural_summary_markdown(lines: list[str], summary: Mapping) -> None:
    propositions = summary.get('propositions', {}) if isinstance(summary, Mapping) else {}
    expressions = summary.get('logical_expressions', {}) if isinstance(summary, Mapping) else {}
    by_type = propositions.get('by_type', {}) if isinstance(propositions, Mapping) else {}
    by_operator = expressions.get('by_operator', {}) if isinstance(expressions, Mapping) else {}
    type_text = ', '.join(f'{name}: {count}' for name, count in by_type.items()) if isinstance(by_type, Mapping) and by_type else 'нет'
    operator_text = ', '.join(f'{name}: {count}' for name, count in by_operator.items()) if isinstance(by_operator, Mapping) and by_operator else 'нет'
    lines.extend(['', '## Структурно-нормативная сводка', ''])
    lines.append(f"- Высказывания: {propositions.get('total', 0) if isinstance(propositions, Mapping) else 0} ({type_text}).")
    lines.append(f"- Логические выражения: {expressions.get('total', 0) if isinstance(expressions, Mapping) else 0} ({operator_text}); требуют review: {expressions.get('review_required', 0) if isinstance(expressions, Mapping) else 0}.")
    norms = summary.get('norms', []) if isinstance(summary, Mapping) else []
    if isinstance(norms, list) and norms:
        lines.append('- Нормы:')
        for norm in norms[:5]:
            if isinstance(norm, Mapping):
                lines.append(f"  - {norm.get('id')} [{norm.get('label', 'норма')}]: {norm.get('text', '')} ({_source_label(norm)}).")
def _report_summary(model: Mapping) -> dict:
    profiles = _profiles(model)
    reference_blocks = _reference_blocks(model)
    profile_summary = []
    for profile in profiles:
        profile_summary.append({
            "relative_path": str(profile.get("relative_path", "unknown")),
            "artifact_kind": str(profile.get("artifact_kind", "unknown")),
            "narrative_style": str(profile.get("narrative_style", "unknown")),
            "confidence": profile.get("confidence"),
            "section_roles": _section_roles(profile),
            "rule_ids": list(profile.get("rule_ids", [])) if isinstance(profile.get("rule_ids"), list) else [],
            "formalization_profile": dict(profile.get("formalization_profile", {})) if isinstance(profile.get("formalization_profile"), Mapping) else {},
            "applied_checks": _checks_for_profile(profile),
        })
    reference_types: dict[str, int] = defaultdict(int)
    for block in reference_blocks:
        reference_types[str(block.get("type", "reference"))] += 1
    findings = _findings(model)
    return {
        "artifact_profiles": profile_summary,
        "reference_blocks": {
            "count": len(reference_blocks),
            "by_type": dict(sorted(reference_types.items())),
        },
        "findings": {
            "confirmed_problems": sum(item.get("severity") == "error" for item in findings),
            "warnings": sum(item.get("severity") == "warning" for item in findings),
            "information": sum(item.get("severity") not in {"error", "warning"} for item in findings),
        },
        "structural_analysis": _structural_summary(model),
    }


def _request_details(request_text: str | None, requested_at: str | None) -> dict[str, str | None]:
    """Возвращает только переданные вызывающим агентом реквизиты запроса."""
    return {
        "text": request_text if isinstance(request_text, str) and request_text else None,
        "requested_at": requested_at if isinstance(requested_at, str) and requested_at else None,
    }


def _developer_action(finding: Mapping, order: int) -> dict:
    rule_id = str(finding.get("rule_id", "unknown"))
    message = str(finding.get("message", ""))
    severity = str(finding.get("severity", "warning"))
    category = "manual_review"
    title = "Проверить предупреждение"
    next_step = "Сверить фрагмент с источником и правилами проекта; не менять документ автоматически."
    priority = 3
    if severity == "error":
        category = "confirmed_problem"
        title = "Устранить подтверждённую проблему"
        next_step = "Исправить только подтверждённое нарушение, затем повторить проверку этого входа."
        priority = 0
    elif rule_id == "POL-004" and "identifier is duplicated" in message:
        category = "structural_fix"
        title = "Устранить дубликат идентификатора правила"
        next_step = "Выбрать уникальный идентификатор для дублирующего раздела, проверить ссылки на него и повторить проверку."
        priority = 0
    elif rule_id == "POL-003":
        category = "reference_check"
        title = "Проверить неразрешённую ссылку на правило"
        next_step = "Сверить целевой идентификатор среди входных материалов; исправить или удалить ссылку только если цели действительно нет."
        priority = 1
    elif rule_id == "POL-001":
        category = "policy_review"
        title = "Проверить связь политики со стандартом"
        next_step = "Проверить, нужен ли для политики отдельный H4-стандарт; добавлять его только при необходимости формального способа выполнения."
        priority = 2
    elif rule_id == "POL-002":
        category = "policy_review"
        title = "Проверить действие для нормативного условия"
        next_step = "Убедиться, что условие задаёт исполнителя и действие; уточнять формулировку только после ручной проверки контекста."
        priority = 2
    return {
        "order": order,
        "priority": priority,
        "category": category,
        "title": title,
        "rule_id": rule_id,
        "severity": severity,
        "finding_id": str(finding.get("id", "")),
        "source": _source_label(finding),
        "message": message,
        "next_step": next_step,
        "confidence": finding.get("confidence"),
    }


def _developer_action_plan(model: Mapping) -> dict:
    findings = _unresolved_findings(model)
    ranked = [_developer_action(item, index) for index, item in enumerate(findings, start=1)]
    ranked.sort(key=lambda item: (item["priority"], item["rule_id"], item["source"], item["finding_id"]))
    selected = ranked[:DEVELOPER_ACTION_LIMIT]
    for index, item in enumerate(selected, start=1):
        item["order"] = index
    unresolved = _unresolved(model)
    return {
        "items": selected,
        "total_findings": len(findings),
        "deferred_findings": max(0, len(findings) - len(selected)),
        "unresolved_gaps": len([item for item in unresolved if item.get("type") == "gap"]),
        "unresolved_non_gaps": len([item for item in unresolved if item.get("type") != "gap"]),
        "classification_proposals": len(model.get("classification_proposals", [])) if isinstance(model.get("classification_proposals", []), list) else 0,
        "automatic_changes_allowed": False,
    }

def _user_guidance(
    model: Mapping,
    status: str,
    unresolved: list[dict],
    developer_action_plan: Mapping,
    decisions: Mapping,
) -> dict:
    """Формирует только подтверждённую директиву для человека и агента."""
    required_actions: list[dict[str, object]] = []
    plan_items = developer_action_plan.get("items", []) if isinstance(developer_action_plan, Mapping) else []
    if isinstance(plan_items, list):
        for item in plan_items:
            if isinstance(item, Mapping):
                required_actions.append({"id": item.get("finding_id"), "kind": "finding", "rule_id": item.get("rule_id"), "source": item.get("source"), "next_step": item.get("next_step")})
    cards = decisions.get("cards", []) if isinstance(decisions, Mapping) else []
    review_cards = [item for item in cards if isinstance(item, Mapping) and item.get("status") == "review_required"] if isinstance(cards, list) else []
    prohibited_actions = [
        "Не предлагать изменение исходного документа только по неблокирующему наблюдению.",
        "Не считать observation ошибкой, GAP, вопросом человеку или основанием для действия.",
        "Не изменять исходный документ автоматически.",
    ]
    if review_cards:
        question = review_cards[0].get("question")
        return {"mode": "HUMAN_DECISION_REQUIRED", "summary": "Проверка требует решения человека по подтверждённой неоднозначности или карточке решения.", "required_actions": required_actions, "human_question": question if isinstance(question, str) else "Требуется решение человека по карточке анализа.", "prohibited_actions": prohibited_actions, "observations_are_context_only": True}
    gap_count = len([item for item in unresolved if item.get("type") == "gap"])
    if gap_count:
        required_actions.append({"id": "gap-review", "kind": "gap", "rule_id": None, "source": "полный раздел GAP отчёта", "next_step": f"Рассмотреть {gap_count} GAP по группам в полном отчёте; не добавлять содержание автоматически."})
    if required_actions or status != "confirmed":
        return {"mode": "REVIEW_REQUIRED", "summary": "Проверка выявила подтверждённые элементы для ручной проверки; до решения источники не изменять.", "required_actions": required_actions, "human_question": None, "prohibited_actions": prohibited_actions, "observations_are_context_only": True}
    return {"mode": "NO_ACTION_REQUIRED", "summary": "Проверка завершена: подтверждённых проблем, предупреждений, GAP и решений человека нет. Действия по результату проверки не требуются.", "required_actions": [], "human_question": None, "prohibited_actions": prohibited_actions, "observations_are_context_only": True}

def _append_user_guidance_markdown(lines: list[str], guidance: Mapping) -> None:
    lines.extend(["", "## Итог для пользователя", ""])
    lines.append(str(guidance.get("summary", "Итог проверки не сформирован.")))
    if guidance.get("mode") == "NO_ACTION_REQUIRED":
        lines.append("- Обязательные действия: отсутствуют.")
    else:
        lines.append("- Обязательные действия:")
        actions = guidance.get("required_actions", [])
        if isinstance(actions, list) and actions:
            for item in actions:
                if isinstance(item, Mapping):
                    lines.append(f"  - {item.get('id', 'unknown')} [{item.get('kind', 'review')}]: {item.get('next_step', '')} ({item.get('source', 'unknown')}).")
        else:
            lines.append("  - Рассмотреть подтверждённый статус модели и связанные карточки решения.")
    question = guidance.get("human_question")
    if isinstance(question, str) and question:
        lines.append(f"- Вопрос человеку: {question}")
    lines.append("- Неблокирующие наблюдения приведены ниже только для контекста и не являются рекомендацией изменения.")

def _file_stem(path: str) -> str:
    normalized = path.replace("\\", "/").rstrip("/")
    name = normalized.rsplit("/", 1)[-1] or "asir"
    stem = name.rsplit(".", 1)[0] if "." in name else name
    return stem or "asir"


def _quote_command_argument(value: str) -> str:
    return '"' + value.replace('"', '\\"') + '"'


def recommended_report_path(model: Mapping, input_path: str | None = None) -> str:
    compilation_id = str(model.get("compilationId") or "<compilationId>")
    source = input_path or ".source"
    return (
        ".tools/agent-logic/.runtime/exports/"
        f"{compilation_id}/{_file_stem(source)}.agent-logic.md"
    )


def recommended_report_command(
    model: Mapping,
    input_path: str | None = None,
    *,
    request_text: str | None = None,
    requested_at: str | None = None,
) -> str:
    source = input_path or ".source"
    output = recommended_report_path(model, source)
    arguments = [
        "python .tools/agent-logic/agent-logic.py compile",
        _quote_command_argument(source),
        "--format md",
    ]
    if requested_at:
        arguments.append("--requested-at " + _quote_command_argument(requested_at))
    if request_text:
        arguments.append("--request " + _quote_command_argument(request_text))
    arguments.extend(("--output " + _quote_command_argument(output), "--write"))
    return " ".join(arguments)


def _append_gap_summary_markdown(lines: list[str], gaps: dict[str, list[dict]]) -> None:
    if not gaps:
        return
    lines.extend(["", "### Сводка GAP", ""])
    for method in sorted(gaps):
        lines.append(f"- {method}: {len(gaps[method])}")
    lines.extend(["", f"### Примеры GAP (не более {GAP_SAMPLE_LIMIT} на группу)", ""])
    for method in sorted(gaps):
        values = gaps[method]
        for item in values[:GAP_SAMPLE_LIMIT]:
            lines.append(f"- {method} — {_source_label(item)}: {_display_text(item)}")
        remaining = len(values) - GAP_SAMPLE_LIMIT
        if remaining > 0:
            lines.append(f"- {method}: ещё {remaining} фрагм. доступны в JSON-модели и agent_context.")


def _append_findings_markdown(lines: list[str], findings: list[dict]) -> None:
    confirmed = [item for item in findings if item.get("severity") == "error"]
    warnings = [item for item in findings if item.get("severity") == "warning"]
    information = [item for item in findings if item.get("severity") not in {"error", "warning"}]
    categories = (
        ("Подтверждённые проблемы", confirmed, "Подтверждённых проблем нет."),
        ("Предупреждения", warnings, "Предупреждений нет."),
        ("Информационные сообщения", information, "Информационных сообщений нет."),
    )
    for title, values, empty in categories:
        lines.extend(["", f"## {title}", ""])
        if not values:
            lines.append(empty)
            continue
        for item in values:
            lines.append(
                "- "
                f"{item.get('id')} [{item.get('rule_id')}] "
                f"{item.get('severity')}: {item.get('message', '')} "
                f"({_source_label(item)})"
            )
            _append_deontic_scope_markdown(lines, item)



def _append_deontic_scope_markdown(lines: list[str], finding: Mapping) -> None:
    if finding.get('rule_id') != 'DNT-004':
        return
    evidence = finding.get('evidence', [])
    if not isinstance(evidence, list) or len(evidence) < 2:
        return
    heading, item = evidence[0], evidence[1]
    if not isinstance(heading, Mapping) or not isinstance(item, Mapping):
        return
    lines.append(f"  - Контекст области: «{heading.get('fragment', '')}» → «{item.get('fragment', '')}».")
    lines.append('  - Область действия: до следующего заголовка того же или более высокого уровня либо до следующей отдельной нормативной метки.')

def _append_developer_action_plan(lines: list[str], plan: Mapping) -> None:
    lines.extend(["", "## Первые действия разработчика", ""])
    items = plan.get("items", []) if isinstance(plan, Mapping) else []
    if not isinstance(items, list) or not items:
        lines.append("Подтверждённых действий нет; при необходимости рассмотрите полный список предупреждений и карточек решений.")
        return
    lines.append("Это очередь ручной проверки, а не разрешение на автоматическое изменение исходных материалов.")
    for item in items:
        if not isinstance(item, Mapping):
            continue
        lines.append(
            f"{item.get('order')}. **{item.get('title')}** "
            f"[{item.get('rule_id')}] — {item.get('source')}."
        )
        lines.append(f"   - Основание: {item.get('message')}")
        lines.append(f"   - Следующий шаг: {item.get('next_step')}")
    deferred = plan.get("deferred_findings", 0)
    gaps = plan.get("unresolved_gaps", 0)
    proposals = plan.get("classification_proposals", 0)
    lines.append(
        f"- Не менять автоматически: ещё {deferred} предупрежд. для ручного рассмотрения; "
        f"GAP: {gaps}; предложений классификации: {proposals}."
    )

def _append_proof_markdown(lines: list[str], model: Mapping) -> None:
    hypothesis = model.get("hypothesis")
    proof_result = model.get("proof_result")
    if not isinstance(hypothesis, Mapping) and not isinstance(proof_result, Mapping):
        return
    lines.extend(["", "## Формальное исследование гипотезы", ""])
    if isinstance(hypothesis, Mapping):
        lines.append(f"- Гипотеза: {hypothesis.get('id', 'unknown')}: {hypothesis.get('text', '')}")
        lines.append(f"- Режим: {hypothesis.get('mode', 'unknown')}; статус формализации: {hypothesis.get('formalization_status', 'unknown')}.")
    if not isinstance(proof_result, Mapping):
        lines.append("- Результат доказательства не сформирован.")
        return
    lines.append(f"- Статус исследования: {proof_result.get('status', 'NOT_EVALUATED')}.")
    lines.append(f"- Версия движка: {proof_result.get('engine_version', 'unknown')}; контрольная сумма формальной модели: {proof_result.get('formal_model_checksum', 'unknown')}.")
    proof_graph = proof_result.get("proof_graph", [])
    if isinstance(proof_graph, list) and proof_graph:
        lines.append("- Цепочка доказательства:")
        for node in proof_graph:
            if isinstance(node, Mapping):
                source = _source_label(node)
                if node.get("kind") == "rule":
                    lines.append(f"  - правило {node.get('rule_id', 'unknown')} ({source})")
                else:
                    lines.append(f"  - {node.get('id', 'unknown')} [{node.get('kind', 'node')}]: {node.get('claim', '')} ({source})")
    explanation = proof_result.get("explanation")
    if isinstance(explanation, Mapping):
        alternatives = explanation.get("alternatives", [])
        if isinstance(alternatives, list) and alternatives:
            lines.append("- Недостающие основания по существующим путям:")
            for alternative in alternatives:
                if not isinstance(alternative, Mapping):
                    continue
                atoms = alternative.get("missing_atoms", [])
                atom_text = "; ".join(str(item) for item in atoms) if isinstance(atoms, list) else ""
                rules = ", ".join(str(item) for item in alternative.get("rule_ids", []) if isinstance(item, str))
                source_refs = alternative.get("source_refs", [])
                sources = ", ".join(_source_label({"source_ref": item}) for item in source_refs if isinstance(item, Mapping)) if isinstance(source_refs, list) else ""
                lines.append(f"  - {alternative.get('id', 'unknown')} ({alternative.get('polarity', 'unknown')}): {atom_text}; правила: {rules or 'нет'}; источники: {sources or 'нет'}." )
        traces = explanation.get("derivation_traces", [])
        if isinstance(traces, list) and len(traces) > 1:
            lines.append("- Независимые цепочки конфликта:")
            for trace in traces:
                if isinstance(trace, Mapping):
                    rules = ", ".join(str(item) for item in trace.get("rule_ids", []) if isinstance(item, str))
                    source_refs = trace.get("source_refs", [])
                    sources = ", ".join(_source_label({"source_ref": item}) for item in source_refs if isinstance(item, Mapping)) if isinstance(source_refs, list) else ""
                    lines.append(f"  - {trace.get('polarity', 'unknown')}: правила {rules or 'нет'}; источники: {sources or 'нет'}." )
        next_step = explanation.get("safe_next_step")
        if isinstance(next_step, Mapping):
            lines.append(f"- Безопасный следующий шаг: {next_step.get('code', 'unknown')} — {next_step.get('message', '')}")
    blockers = proof_result.get("blocking_reasons", [])
    if isinstance(blockers, list) and blockers:
        lines.append("- Основания статуса:")
        for blocker in blockers:
            if isinstance(blocker, Mapping):
                lines.append(f"  - {blocker.get('code', 'unknown')}: {blocker.get('message', '')}")
    lines.append("- Результат исследования не изменяет execution_policy и не разрешает действия сам по себе.")

def markdown_report(
    model: Mapping,
    issues: list[dict],
    *,
    report_summary: Mapping | None = None,
    report_command: str | None = None,
    request: Mapping | None = None,
    developer_action_plan: Mapping | None = None,
    decision_cards: list[dict] | None = None,
    user_guidance: Mapping | None = None,
) -> str:
    unresolved = _unresolved(model)
    observations = _observations(model)
    source_count = len(model.get("sources", [])) if isinstance(model.get("sources", []), list) else 0
    semantic_count = sum(
        len(model.get(key, [])) if isinstance(model.get(key, []), list) else 0
        for key in ARRAYS if key != "gaps"
    )
    gap_count = len(model.get("gaps", [])) if isinstance(model.get("gaps", []), list) else 0
    proposal_count = len(model.get("classification_proposals", [])) if isinstance(model.get("classification_proposals", []), list) else 0
    summary = report_summary or _report_summary(model)
    lines = [
        f"# Отчёт компиляции ASIR: {model.get('compilationId', '')}",
        "",
        f"- Статус модели: {model.get('status', 'BLOCKED')}",
        f"- Рекомендуемая модель: {model.get('recommended_model', 'unknown')}",
        f"- Уверенность: {_confidence(model)}",
        f"- Источников: {source_count}",
        f"- Семантических элементов: {semantic_count}",
        f"- GAP: {gap_count}",
        f"- Предложений классификации: {proposal_count}",
        f"- Неблокирующих наблюдений: {len(observations)}",
        "",
        "## Запрос проверки",
        "",
    ]
    request_details = request if isinstance(request, Mapping) else {}
    requested_at = request_details.get("requested_at")
    request_text = request_details.get("text")
    lines.append("- Время регистрации: " + str(requested_at) if requested_at else "- Время регистрации: не передано вызывающим агентом.")
    if request_text:
        lines.extend(["- Исходный запрос:", "```text", str(request_text), "```"])
    else:
        lines.append("- Исходный запрос: не передан вызывающим агентом.")
    lines.extend(["", "## Проверенный артефакт", ""])
    profiles = summary.get("artifact_profiles", []) if isinstance(summary, Mapping) else []
    if isinstance(profiles, list) and profiles:
        for profile in profiles:
            if not isinstance(profile, Mapping):
                continue
            roles = profile.get("section_roles", {})
            role_text = ", ".join(f"{role}: {count}" for role, count in roles.items()) if isinstance(roles, Mapping) and roles else "нет заголовков"
            lines.append(
                f"- {profile.get('relative_path')} — {profile.get('artifact_kind')}; "
                f"стиль: {profile.get('narrative_style')}; разделы: {role_text}."
            )
            formalization_profile = profile.get("formalization_profile", {})
            if isinstance(formalization_profile, Mapping):
                profile_id = formalization_profile.get("id", "unknown")
                profile_version = formalization_profile.get("version", "unknown")
                if formalization_profile.get("deductive_premises") is True:
                    lines.append(f"  - Профиль формализации: {profile_id}@{profile_version}; формальные основания допускаются только после явного утверждения.")
                else:
                    reason = formalization_profile.get("reason") or "дедуктивные основания для этого вида источника не поддерживаются"
                    lines.append(f"  - Профиль формализации: {profile_id}@{profile_version}; {reason}.")
            checks = profile.get("applied_checks", [])
            if isinstance(checks, list) and checks:
                lines.append("  - Применённые проверки: " + ", ".join(str(value) for value in checks) + ".")
    else:
        lines.append("- Профиль не определён: применены общие проверки входного текста.")
    references = summary.get("reference_blocks", {}) if isinstance(summary, Mapping) else {}
    if isinstance(references, Mapping):
        reference_types = references.get("by_type", {})
        type_text = ", ".join(f"{kind}: {count}" for kind, count in reference_types.items()) if isinstance(reference_types, Mapping) and reference_types else "нет"
        lines.append(f"- Справочные блоки: {references.get('count', 0)} ({type_text}); они не являются GAP сами по себе.")

    lines.extend(["", "## Диагностика формата модели", ""])
    if issues:
        lines.extend(f"- {item.get('issue_type', 'validation_error')}: {item.get('message', '')}" for item in issues)
    else:
        lines.append("Ошибок валидации нет.")
    _append_structural_summary_markdown(lines, summary.get('structural_analysis', {}))
    _append_proof_markdown(lines, model)
    _append_findings_markdown(lines, _findings(model))
    _append_user_guidance_markdown(lines, user_guidance or _user_guidance(model, str(model.get("status", "BLOCKED")), unresolved, developer_action_plan or _developer_action_plan(model), {"cards": decision_cards or []}))
    _append_developer_action_plan(lines, developer_action_plan or _developer_action_plan(model))

    cards = decision_cards if decision_cards is not None else decision_envelope(model)["cards"]
    lines.extend(["", "## Требующие решения элементы", ""])
    if cards:
        for card in cards:
            lines.append("- " + str(card.get("id")) + " [" + str(card.get("status")) + "]: " + str(card.get("question", "")))
            context = card.get("context")
            if isinstance(context, Mapping):
                heading = context.get("heading", {})
                item = context.get("item", {})
                if isinstance(heading, Mapping) and isinstance(item, Mapping):
                    lines.append("  - Исходный контекст: «" + str(heading.get("fragment", "")) + "» → «" + str(item.get("fragment", "")) + "».")
                    lines.append("  - Область действия: " + str(context.get("scope_boundary", "не определена")) + ".")
            for variant in card.get("variants", []):
                lines.append("  - " + str(variant.get("id")) + ": " + str(variant.get("interpretation", "")))
    elif unresolved:
        lines.append("Карточек решений нет; см. неразрешённые элементы ниже.")
    else:
        lines.append("Решение человека не требуется.")

    unresolved_non_gaps = [item for item in unresolved if item.get('type') != 'gap']
    gap_groups = _gap_groups(unresolved)
    if unresolved_non_gaps:
        lines.extend(['', '## Неразрешённые элементы (не GAP)', ''])
        for item in unresolved_non_gaps:
            lines.append(
                '- '
                f"{item.get('id')} [{item.get('status', 'unknown')}] "
                f"(confidence={item.get('confidence', 'n/a')}): {_display_text(item)}"
            )
    if gap_groups:
        lines.extend(['', '## GAP', ''])
        _append_gap_summary_markdown(lines, gap_groups)

    if observations:
        lines.extend(["", "## Неблокирующие наблюдения", ""])
        lines.append("Эти элементы сохранены для контекста, но не являются GAP, находками или блокерами выполнения.")
        for item in observations:
            lines.append(
                "- "
                f"{item.get('id')} [observed] (confidence={item.get('confidence', 'n/a')}): {_display_text(item)}"
            )

    if report_command:
        lines.extend([
            "",
            "## Сохранение отчёта",
            "",
            "Команда только показана: она создаст новый Markdown-файл и не перезапишет существующий результат.",
            "Если путь уже занят, команда завершится ошибкой; сравните существующий файл и явно выберите другое имя либо `--replace`.",
            "```cmd",
            report_command,
            "```",
        ])
    return "\n".join(lines) + "\n"


def text_diagnostics(
    model: Mapping,
    issues: list[dict],
    *,
    report_summary: Mapping | None = None,
    report_command: str | None = None,
    request: Mapping | None = None,
    developer_action_plan: Mapping | None = None,
    decision_cards: list[dict] | None = None,
    user_guidance: Mapping | None = None,
) -> str:
    summary = report_summary or _report_summary(model)
    lines = [
        f"compilationId: {model.get('compilationId', '')}",
        f"status: {model.get('status', 'BLOCKED')}",
    ]
    proof_result = model.get("proof_result")
    if isinstance(proof_result, Mapping):
        lines.append("proof_status: " + str(proof_result.get("status", "NOT_EVALUATED")))
        lines.append("proof_hypothesis_id: " + str(proof_result.get("hypothesis_id", "")))
        lines.append("proof_checksum: " + str(proof_result.get("formal_model_checksum", "")))
        explanation = proof_result.get("explanation")
        if isinstance(explanation, Mapping):
            next_step = explanation.get("safe_next_step")
            if isinstance(next_step, Mapping):
                lines.append("proof_safe_next_step: " + str(next_step.get("code", "")))
            alternatives = explanation.get("alternatives", [])
            if isinstance(alternatives, list):
                for alternative in alternatives:
                    if isinstance(alternative, Mapping):
                        lines.append("proof_missing_premises: " + str(alternative.get("id", "")) + "=" + json.dumps(alternative.get("missing_atoms", []), ensure_ascii=False, sort_keys=True))

    request_details = request if isinstance(request, Mapping) else {}
    requested_at = request_details.get("requested_at")
    request_text = request_details.get("text")
    lines.append("request_requested_at: " + str(requested_at) if requested_at else "request_requested_at: not_provided")
    lines.append("request_text: " + str(request_text).replace("\n", "\\n") if request_text else "request_text: not_provided")
    profiles = summary.get("artifact_profiles", []) if isinstance(summary, Mapping) else []
    if isinstance(profiles, list):
        for profile in profiles:
            if isinstance(profile, Mapping):
                lines.append(
                    "profile: "
                    f"path={profile.get('relative_path')} "
                    f"kind={profile.get('artifact_kind')} "
                    f"style={profile.get('narrative_style')}"
                )
                formalization_profile = profile.get("formalization_profile", {})
                if isinstance(formalization_profile, Mapping):
                    profile_id = formalization_profile.get("id", "unknown")
                    profile_version = formalization_profile.get("version", "unknown")
                    if formalization_profile.get("deductive_premises") is True:
                        lines.append(f"  - Профиль формализации: {profile_id}@{profile_version}; формальные основания допускаются только после явного утверждения.")
                    else:
                        reason = formalization_profile.get("reason") or "дедуктивные основания для этого вида источника не поддерживаются"
                        lines.append(f"  - Профиль формализации: {profile_id}@{profile_version}; {reason}.")
                checks = profile.get("applied_checks", [])
                if isinstance(checks, list):
                    lines.append("checks: " + ",".join(str(value) for value in checks))
    references = summary.get("reference_blocks", {}) if isinstance(summary, Mapping) else {}
    if isinstance(references, Mapping):
        lines.append(f"reference_blocks: {references.get('count', 0)}")
    if issues:
        lines.extend(
            f"{item.get('issue_type', 'validation_error')}: {item.get('message', '')}"
            for item in issues
        )
    for item in _findings(model):
        category = "problem" if item.get("severity") == "error" else "warning" if item.get("severity") == "warning" else "info"
        lines.append(
            category + ": " + str(item.get("id")) + " [" + str(item.get("rule_id")) + "] "
            + str(item.get("severity")) + ": " + str(item.get("message", ""))
        )
    action_plan = developer_action_plan or _developer_action_plan(model)
    guidance = user_guidance or _user_guidance(model, str(model.get("status", "BLOCKED")), _unresolved(model), action_plan, {"cards": decision_cards or []})
    lines.append("user_guidance: mode=" + str(guidance.get("mode", "REVIEW_REQUIRED")) + " summary=" + str(guidance.get("summary", "")))
    for item in action_plan.get("items", []):
        if isinstance(item, Mapping):
            lines.append(
                "developer_action: "
                + str(item.get("order")) + " [" + str(item.get("rule_id")) + "] "
                + str(item.get("source")) + ": " + str(item.get("next_step"))
            )
    for card in (decision_cards if decision_cards is not None else decision_envelope(model)["cards"]):
        lines.append("decision: " + str(card.get("id")) + " [" + str(card.get("status")) + "] question=" + str(card.get("question", "")))
    unresolved = _unresolved(model)
    for item in _observations(model):
        lines.append(
            f"info: observation {item.get('id')} [observed] "
            f"confidence={item.get('confidence', 'n/a')} source={_source_label(item)}: {_display_text(item)}"
        )
    for item in unresolved:
        if item.get("type") != "gap":
            lines.append(
                f"warning: unresolved {item.get('id')} [{item.get('status', 'unknown')}] "
                f"confidence={item.get('confidence', 'n/a')} source={_source_label(item)}: {_display_text(item)}"
            )
    for method, values in sorted(_gap_groups(unresolved).items()):
        examples = "; ".join(f"{_source_label(item)}: {_display_text(item)}" for item in values[:GAP_SAMPLE_LIMIT])
        lines.append(f"warning: unresolved_group method={method} count={len(values)} examples={examples}")
    if report_command:
        lines.append("report_write_command: " + report_command)
    if not issues and len(lines) == 3:
        lines.append("diagnostics: none")
    return "\n".join(lines) + "\n"


def _first_text(model: Mapping, name: str) -> str | None:
    values = model.get(name, [])
    if isinstance(values, list):
        for item in values:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                return item["text"]
    return None


def _texts(model: Mapping, names: Iterable[str]) -> list[str]:
    return [
        item["text"]
        for item in _items(model, names)
        if isinstance(item.get("text"), str) and item.get("status") != "observed"
    ]


def _proof_blockers(model: Mapping) -> list[str]:
    proof_result = model.get("proof_result")
    if not isinstance(proof_result, Mapping):
        return []
    status = proof_result.get("status")
    if status in {"PROVED", "REFUTED"}:
        return []
    if isinstance(status, str):
        return ["proof_result.status=" + status]
    return ["proof_result.status=invalid"]


def _execution_policy(status: str, unresolved: list[dict], model: Mapping) -> dict:
    blockers = [str(item.get("id")) for item in unresolved if item.get("id")]
    blockers.extend(_proof_blockers(model))
    allowed = status == "confirmed" and not blockers
    return {
        "allowed": allowed,
        "mode": "execute" if allowed else "review",
        "blockers": blockers,
    }
def _agent_context(
    model: Mapping,
    status: str,
    unresolved: list[dict],
    report_summary: Mapping,
    report_command: str,
    request: Mapping,
    developer_action_plan: Mapping,
    decisions: Mapping,
) -> dict:
    logical_findings = _findings(model)
    unresolved_findings = _unresolved_findings(model)
    metadata = model.get("metadata", {})
    current_context = metadata.get("context") if isinstance(metadata, dict) else None
    policy = _execution_policy(status, unresolved, model)
    user_guidance = _user_guidance(model, status, unresolved, developer_action_plan, decisions)
    return {
        "hypothesis": model.get("hypothesis"),
        "proof_result": model.get("proof_result"),
        "propositions": model.get("propositions", []),
        "logical_expressions": model.get("logical_expressions", []),
        "structural_analysis": report_summary.get("structural_analysis", {}),
        "analysis_summary": dict(report_summary),
        "logical_findings": [item for item in logical_findings if str(item.get("rule_id", "")).startswith(("STR-", "LGC-", "DNT-", "ARG-", "DEF-"))],
        "interpretation_requests": [item for item in decisions["cards"] if item.get("status") == "review_required"],
        "agent_brief_basis": {
            "checked_sources": len(model.get("sources", [])) if isinstance(model.get("sources", []), list) else 0,
            "findings": logical_findings,
            "execution_policy": dict(policy),
            "user_guidance": user_guidance,
        },        "findings": logical_findings,
        "unresolved_findings": unresolved_findings,
        "decision_cards": decisions["cards"],
        "model_version": decisions["model_version"],
        "compilationId": model.get("compilationId", ""),
        "sources": model.get("sources", []),
        "artifact_profiles": _profiles(model),
        "reference_blocks": _reference_blocks(model),
        "report_summary": dict(report_summary),
        "report_request": dict(request),
        "developer_action_plan": dict(developer_action_plan),
        "user_guidance": user_guidance,
        "report_write_command": report_command,
        "goal": _first_text(model, "goals"),
        "current_context": current_context,
        "current_state": _first_text(model, "states"),
        "relevant_facts": _texts(model, ("facts",)),
        "available_actions": _texts(model, ("actions",)),
        "applicable_rules": _texts(model, ("conditions", "constraints", "invariants")),
        "assumptions": _texts(model, ("assumptions",)),
        "blocked_actions": [
            item.get("text")
            for item in _items(model, ("actions",))
            if item.get("status") in {"BLOCKED", "rejected"}
        ],
        "expected_result": _first_text(model, "goals"),
        "recommended_model": model.get("recommended_model"),
        "status": status,
        "execution_policy": dict(policy),
        "unresolved_gaps": unresolved,
        "observations": _observations(model),
    }


def build_report(
    model: object,
    issues: list[dict],
    *,
    input_path: str | None = None,
    request_text: str | None = None,
    requested_at: str | None = None,
) -> dict:
    safe_model: Mapping = model if isinstance(model, Mapping) else {}
    errors = [item for item in issues if item.get("severity", "error") == "error"]
    warnings = [item for item in issues if item.get("severity") == "warning"]
    unresolved = _unresolved(safe_model)
    if errors:
        status = "BLOCKED"
        exit_code = 1
    elif safe_model.get("status") in {"REVIEW_REQUIRED", "BLOCKED"} or warnings or unresolved:
        status = "REVIEW_REQUIRED"
        exit_code = 2
    else:
        status = "confirmed"
        exit_code = 0
    summary = _report_summary(safe_model)
    request = _request_details(request_text, requested_at)
    developer_action_plan = _developer_action_plan(safe_model)
    known_version = safe_model.get("model_version") if isinstance(safe_model.get("model_version"), str) else None
    decisions = decision_envelope(safe_model, base_version=known_version)
    user_guidance = _user_guidance(safe_model, status, unresolved, developer_action_plan, decisions)
    if isinstance(safe_model, dict):
        safe_model["decision_cards"] = decisions["cards"]
        safe_model["model_version"] = decisions["model_version"]
    command = recommended_report_command(
        safe_model,
        input_path,
        request_text=request["text"],
        requested_at=request["requested_at"],
    )
    markdown = markdown_report(
        safe_model,
        issues,
        report_summary=summary,
        report_command=command,
        request=request,
        developer_action_plan=developer_action_plan,
        decision_cards=decisions["cards"],
        user_guidance=user_guidance,
    )
    text = text_diagnostics(
        safe_model,
        issues,
        report_summary=summary,
        report_command=command,
        request=request,
        developer_action_plan=developer_action_plan,
        decision_cards=decisions["cards"],
        user_guidance=user_guidance,
    )
    return {
        "compilationId": safe_model.get("compilationId", ""),
        "issues": issues,
        "status": status,
        "json_model": dict(safe_model),
        "markdown_report": markdown,
        "text_diagnostics": text,
        "agent_context": _agent_context(safe_model, status, unresolved, summary, command, request, developer_action_plan, decisions),
        "report_summary": summary,
        "report_request": request,
        "developer_action_plan": developer_action_plan,
        "user_guidance": user_guidance,
        "report_write_command": command,
        "exit_code": exit_code,
    }


def output_content(report: Mapping, output_format: str) -> str:
    if output_format == "json":
        return json.dumps(report.get("json_model", {}), ensure_ascii=False, indent=2) + "\n"
    if output_format == "context":
        return json.dumps(report.get("agent_context", {}), ensure_ascii=False, indent=2) + "\n"
    if output_format == "md":
        return str(report.get("markdown_report", ""))
    return str(report.get("text_diagnostics", ""))
