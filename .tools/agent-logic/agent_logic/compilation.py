
from __future__ import annotations

import re
from collections import defaultdict
from functools import lru_cache

from .ingestion import SourceDocument
from .logic_checks import run_logical_checks
from .decisions import build_decision_cards, model_version
from .markdown_classification import build_classification_proposals
from .artifact_profiles import build_artifact_profile, is_normative_manifest
from .structural_analysis import analyze_document

LABELS = {
    "goal": "goals", "цель": "goals",
    "entity": "entities", "сущность": "entities",
    "attribute": "attributes", "атрибут": "attributes",
    "fact": "facts", "факт": "facts",
    "state": "states", "состояние": "states",
    "event": "events", "событие": "events",
    "action": "actions", "действие": "actions",
    "transition": "transitions", "переход": "transitions",
    "condition": "conditions", "условие": "conditions",
    "constraint": "constraints", "ограничение": "constraints",
    "invariant": "invariants", "инвариант": "invariants",
    "dependency": "dependencies", "зависимость": "dependencies",
    "decision": "decisions", "решение": "decisions",
    "exception": "exceptions", "исключение": "exceptions",
    "assumption": "assumptions", "допущение": "assumptions",
    "gap": "gaps", "пробел": "gaps",
}
ARRAYS = tuple(dict.fromkeys(LABELS.values()))
SINGULAR = {
    "goals": "goal", "entities": "entity", "attributes": "attribute", "facts": "fact",
    "states": "state", "events": "event", "actions": "action", "transitions": "transition",
    "conditions": "condition", "constraints": "constraint", "invariants": "invariant",
    "dependencies": "dependency", "decisions": "decision", "exceptions": "exception",
    "assumptions": "assumption", "gaps": "gap",
}
MODEL_TYPES = ("state_machine", "decision_table", "dependency_graph", "constraint_model", "policy_model", "hybrid")

ENTRY_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:[-*+]\s*|\d+[.)]\s*)?"
    r"(?P<label>[A-Za-zА-Яа-яЁё_]+)\s*[:\-]\s*(?P<text>.+?)\s*$",
    re.IGNORECASE,
)
HEADING_RE = re.compile(r"^\s{0,3}(?P<marks>#{1,6})\s+(?P<heading>.+?)\s*#*\s*$")
LIST_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)(?P<text>.+?)\s*$")
FENCE_RE = re.compile(r"^\s*(?:\x60\x60\x60|~~~)")
TABLE_RE = re.compile(r"^\s*\|")
BOLD_NORMATIVE_LABEL_RE = re.compile(r"^\s*\*\*(?P<label>.+?)\*\*\s*:?\s*$")
NORMATIVE_SCOPE_MARKERS = {
    "\u0437\u0430\u043f\u0440\u0435\u0449\u0435\u043d\u043e": "PROHIBITION",
    "\u043d\u0435\u043b\u044c\u0437\u044f": "PROHIBITION",
    "prohibited": "PROHIBITION", "forbidden": "PROHIBITION",
    "\u043e\u0431\u044f\u0437\u0430\u0442\u0435\u043b\u044c\u043d\u043e": "OBLIGATION",
    "\u0442\u0440\u0435\u0431\u0443\u0435\u0442\u0441\u044f": "OBLIGATION",
    "required": "OBLIGATION", "mandatory": "OBLIGATION",
    "\u0440\u0430\u0437\u0440\u0435\u0448\u0435\u043d\u043e": "PERMISSION",
    "\u0434\u043e\u043f\u0443\u0441\u043a\u0430\u0435\u0442\u0441\u044f": "PERMISSION",
    "allowed": "PERMISSION", "permitted": "PERMISSION",
}
NORMATIVE_NEGATION_RE = re.compile(r"^\s*(?:\u043d\u0435|not)\b", re.IGNORECASE)

SECTION_ALIASES = {
    "goals": (
        "goal", "goals", "цель", "цели", "назначение", "purpose",
    ),
    "entities": (
        "entity", "entities", "сущность", "сущности", "объект", "объекты",
    ),
    "facts": (
        "fact", "facts", "факт", "факты", "контекст", "context",
        "наблюдение", "наблюдения",
    ),
    "states": (
        "state", "states", "состояние", "состояния",
    ),
    "events": (
        "event", "events", "событие", "события",
    ),
    "actions": (
        "action", "actions", "действие", "действия", "состав работ",
        "work items", "план разбиения", "реализовать", "ожидаемые артефакты",
        "тестирование", "testing", "tests", "приёмочный сценарий",
        "acceptance scenario",
    ),
    "transitions": (
        "transition", "transitions", "переход", "переходы",
    ),
    "conditions": (
        "condition", "conditions", "условие", "условия", "критерий", "критерии",
        "чек лист готовности", "критерии готовности", "acceptance criteria",
    ),
    "constraints": (
        "constraint", "constraints", "ограничение", "ограничения",
        "граница", "границы", "лимит", "лимиты", "конфигурация правил",
        "поддерживаемые платформы", "нефункциональные требования",
    ),
    "invariants": (
        "invariant", "invariants", "инвариант", "инварианты",
    ),
    "dependencies": (
        "dependency", "dependencies", "зависимость", "зависимости",
        "входы и ссылки", "inputs and references",
    ),
    "decisions": (
        "decision", "decisions", "решение", "решения",
        "подтвержденные решения", "название промежуточного представления",
    ),
    "exceptions": (
        "exception", "exceptions", "исключение", "исключения", "риски", "risk", "risks",
    ),
    "assumptions": (
        "assumption", "assumptions", "допущение", "допущения", "предположение", "предположения",
    ),
    "gaps": (
        "gap", "gaps", "пробел", "пробелы", "открытые вопросы", "open questions",
    ),
}

NOISE_RE = re.compile(
    r"^(?:note|status|pr|commit|дата|версия|ветка|ответственный|дата выполнения|"
    r"version|generated)\b",
    re.IGNORECASE,
)
AMBIGUITY_RE = re.compile(
    r"(?:неоднознач\w*|неясн\w*|неопредел\w*|не указ\w*|непол\w*|"
    r"требует уточ\w*|нужно уточ\w*|\bвозможно\b|"
    r"\bвозможн(?:ое|ый|ая|ые)\b|\bambiguous\b|"
    r"\bunclear\b|\buncertain\b|\bunspecified\b|\bincomplete\b|"
    r"\bpossibly\b|\btbd\b|\?\?\?|\[\?\])",
    re.IGNORECASE,
)
ASSUMPTION_RE = re.compile(
    r"(?:\bпредполагается\b|\bпредполагаем\b|\bпредположено\b|"
    r"\bдопущение\b|\bдопущено\b|\bassume(?:d)?\s+that\b|"
    r"\bassumption\s*:|\bpresume(?:d)?\s+that\b)",
    re.IGNORECASE,
)
REFERENCE_AMBIGUITY_PHRASES = (
    "неразрешенная неоднозначность", "неразрешенная неоднозначность",
    "состояние неопределенности", "состояние неопределенности",
    "и неоднозначности", "для неоднозначных фрагментов",
    "неподтвержденная неоднозначность",
)


def _normalize_heading(value: str) -> str:
    value = value.casefold().replace("ё", "е")
    value = value.replace(chr(96), "")
    value = re.sub(r"^\s*\d+(?:[.)-])\s*", "", value)
    value = re.sub(r"[^a-zа-я0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _section_target(heading: str) -> str | None:
    normalized = _normalize_heading(heading)
    for target, aliases in SECTION_ALIASES.items():
        for alias in sorted(aliases, key=len, reverse=True):
            alias_normalized = _normalize_heading(alias)
            if normalized == alias_normalized:
                return target
    return None


def _source_ref(
    document: SourceDocument,
    start_line: int,
    fragment: str,
    end_line: int | None = None,
    section_path: list[str] | None = None,
) -> dict:
    ref = {
        "relative_path": document.relative_path,
        "line_range": {"start": start_line, "end": end_line or start_line},
        "fragment": fragment,
    }
    if section_path:
        ref['section_path'] = list(section_path)
    return ref


@lru_cache(maxsize=4096)
def _text_flags(value: str) -> tuple[bool, bool]:
    normalized = value.casefold().replace("ё", "е")
    is_reference = any(phrase in normalized for phrase in REFERENCE_AMBIGUITY_PHRASES)
    uncertain = bool(AMBIGUITY_RE.search(value)) and not is_reference
    assumed = bool(ASSUMPTION_RE.search(value))
    return uncertain, assumed


def _element(
    kind: str, index: int, value: str, ref: dict, *, extraction_method: str = "label", nonblocking_observation: bool = False,
) -> dict:
    uncertain, assumed_by_text = _text_flags(value)
    assumed = kind == "assumptions" or assumed_by_text
    if kind == "gaps":
        status, confidence = "gap", 0.5
    elif uncertain:
        status, confidence = ("observed", 0.5) if nonblocking_observation else ("REVIEW_REQUIRED", 0.5)
    elif assumed:
        status, confidence = "assumed", 0.7
    else:
        status, confidence = "confirmed", 1.0
    return {
        "id": f"{SINGULAR[kind]}-{index:03d}",
        "type": SINGULAR[kind],
        "text": value,
        "status": status,
        "confidence": confidence,
        "source_ref": ref,
        "evidence": [ref],
        "extraction_method": extraction_method,
    }


def _empty_gap_statement(value: str) -> bool:
    normalized = value.casefold().replace("ё", "е")
    return bool(re.search(r"(?:открытых вопросов нет|нет открытых вопросов|no open questions)", normalized))


def _candidate_text(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith((">", "|", "<!--", "![", "<")):
        return None
    if stripped in {"---", "***", "___"}:
        return None
    list_match = LIST_RE.match(line)
    text = list_match.group("text").strip() if list_match else stripped
    if not text or NOISE_RE.match(text):
        return None
    return text


def _recommended(model: dict) -> str:
    profiles = model.get("artifact_profiles", [])
    has_normative_profile = any(
        isinstance(profile, dict) and profile.get("artifact_kind") == "normative_manifest"
        for profile in profiles
    )
    if has_normative_profile and not model["dependencies"]:
        return "policy_model"
    if model["transitions"] or model["states"]:
        return "state_machine"
    if model["decisions"]:
        return "decision_table"
    if model["dependencies"]:
        return "dependency_graph"
    if model["constraints"] or model["invariants"]:
        return "constraint_model"
    all_items = [item for name in ARRAYS for item in model[name]]
    if any("политик" in item["text"].casefold() or "policy" in item["text"].casefold() for item in all_items):
        return "policy_model"
    return "hybrid"




def compile_model(compilation_id: str, documents: list[SourceDocument]) -> dict:
    model: dict = {
        "compilationId": compilation_id,
        "metadata": {"schema_version": "1.0", "compiler": "agent-logic", "compiler_version": "0.4.0"},
        **{name: [] for name in ARRAYS},
        "sources": [document.as_dict() for document in documents],
        "versions": [{"component": "agent-logic", "version": "0.4.0"}],
        "recommended_model": "hybrid",
        "alternatives": [name for name in MODEL_TYPES if name != "hybrid"],
        "confidence": 1.0,
        "evidence": [],
        "status": "confirmed",
    }
    model['findings'] = []
    model['checks'] = []
    model['classification_proposals'] = []
    model['artifact_profiles'] = []
    model['reference_blocks'] = []
    # Структуры IMPL-027 заполняются только при явном детерминированном распознавании.
    model['propositions'] = []
    model['logical_expressions'] = []
    model['normative_scopes'] = []
    counters = defaultdict(int)
    semantic_index: dict[tuple[str, str], dict] = {}
    for document_index, document in enumerate(documents, start=1):
        document_profile = build_artifact_profile(document)
        model['artifact_profiles'].append(document_profile)
        profile_ref = document_profile.get('source_ref')
        if isinstance(profile_ref, dict):
            model['evidence'].append(profile_ref)
        profile_sections = {
            item['source_ref']['line_range']['start']: item
            for item in document_profile['section_profiles']
        }
        is_normative = is_normative_manifest(document_profile)
        is_reference_artifact = document_profile.get('artifact_kind') == 'readme'
        recognized_structural_lines: frozenset[int] = frozenset()
        if document.analysis is None and not is_reference_artifact:
            structural_analysis = analyze_document(document, document_index)
            model['propositions'].extend(structural_analysis.propositions)
            model['logical_expressions'].extend(structural_analysis.logical_expressions)
            recognized_structural_lines = structural_analysis.recognized_lines
            if any(item.get('status') in {'review_required', 'gap'} for item in structural_analysis.propositions):
                model['status'] = 'REVIEW_REQUIRED'
                model['confidence'] = min(model['confidence'], 0.5)
        if document.analysis is not None:
            for contribution in document.analysis.elements:
                kind = contribution['kind']
                counters[kind] += 1
                line = contribution['line']
                fragment = contribution['fragment']
                ref = _source_ref(document, line, fragment)
                item = _element(kind, counters[kind], contribution['text'], ref, extraction_method='code_ast')
                item['code_kind'] = contribution['code_kind']
                item['language'] = document.analysis.language
                model[kind].append(item)
            for gap in document.analysis.gaps:
                counters['gaps'] += 1
                line = gap['line']
                ref = _source_ref(document, line, gap['fragment'])
                item = _element('gaps', counters['gaps'], gap['text'], ref, extraction_method='code_analysis_gap')
                item['language'] = document.analysis.language
                model['gaps'].append(item)
                model['status'] = 'REVIEW_REQUIRED'
                model['confidence'] = min(model['confidence'], item['confidence'])
            continue

        section_stack: list[tuple[int, str | None, str, dict]] = []
        in_fence = False
        special_kind: str | None = None
        special_block: list[tuple[int, str]] = []
        unclassified_blocks: list[list[tuple[int, str, list[str]]]] = []
        current_block: list[tuple[int, str, list[str]]] = []
        active_normative_scope: dict | None = None

        def normalized_scope_marker(value: str) -> str | None:
            plain = re.sub(r'[*_`:#]', '', value).strip().rstrip(':').casefold().replace('\u0451', '\u0435')
            return NORMATIVE_SCOPE_MARKERS.get(plain)

        def start_normative_scope(modality: str, heading_text: str, line_number: int, line: str, level: int | None) -> None:
            nonlocal active_normative_scope
            active_normative_scope = {
                'id': f'normative-scope-{document_index:03d}-{len(model["normative_scopes"]) + 1:03d}',
                'modality': modality,
                'heading': heading_text,
                'heading_level': level,
                'source_ref': _source_ref(document, line_number, line, section_path=current_section_path()),
                'items': [],
            }

        def close_normative_scope() -> None:
            nonlocal active_normative_scope
            if active_normative_scope is not None and active_normative_scope['items']:
                model['normative_scopes'].append(active_normative_scope)
            active_normative_scope = None

        def add_normative_scope_item(line_number: int, line: str, text: str) -> None:
            if active_normative_scope is None or LIST_RE.match(line) is None:
                return
            ref = _source_ref(document, line_number, line, section_path=current_section_path())
            active_normative_scope['items'].append({
                'text': text,
                'negated': NORMATIVE_NEGATION_RE.search(text) is not None,
                'source_ref': ref,
                'evidence': [ref],
            })

        def current_section_path() -> list[str]:
            return [heading for _, _, heading, _ in section_stack]

        def current_section_role() -> str:
            return str(section_stack[-1][3].get('role', '')) if section_stack else ''

        def add_reference_block(kind: str, entries: list[tuple[int, str, list[str]]]) -> None:
            if not entries:
                return
            start_line = entries[0][0]
            end_line = entries[-1][0]
            fragment = '\n'.join(value for _, value, _ in entries)
            ref = _source_ref(document, start_line, fragment, end_line, entries[0][2])
            model['reference_blocks'].append({
                'id': f'reference-{len(model["reference_blocks"]) + 1:03d}',
                'type': kind,
                'section_role': current_section_role() or 'content_section',
                'source_ref': ref,
                'evidence': [ref],
            })

        def flush_block() -> None:
            nonlocal current_block
            if not current_block:
                return
            if is_reference_artifact:
                add_reference_block('reference_narrative', current_block)
                current_block = []
                return
            if not is_normative:
                unclassified_blocks.append(current_block)
                current_block = []
                return
            references: list[tuple[int, str, list[str]]] = []
            for line_number, line, section_path in current_block:
                fragment = _candidate_text(line)
                if not fragment:
                    continue
                plain = re.sub(r'[*_`]', '', fragment).strip().casefold()
                target: str | None = None
                if plain.startswith(('если ', 'при ', 'после ', 'в случае ')) and plain.endswith(':'):
                    target = 'conditions'
                elif plain.startswith(('запрещено', 'нельзя', 'не ')) or 'требуется' in plain:
                    target = 'constraints'
                elif current_section_role() in {'policy', 'standard'} and (
                    LIST_RE.match(line) is not None
                    or re.search(r'\b(?:сообщи|проверь|выполни|обнови|создай|добавь|убеди|найди|прочитай|дождись|используй|применяй|показывай|указывай|разделяй|выведи|формируй|зафиксируй|не\s+создавай|не\s+добавляй)\w*\b', plain)
                ):
                    target = 'actions'
                if target:
                    method = 'normative_list' if LIST_RE.match(line) else 'normative_paragraph'
                    add_item(target, fragment, line_number, line, method)
                else:
                    references.append((line_number, line, section_path))
            add_reference_block('reference_narrative', references)
            current_block = []

        def flush_special() -> None:
            nonlocal special_kind, special_block
            if not special_block or not special_kind:
                return
            if is_normative or is_reference_artifact:
                entries = [(line_number, line, current_section_path()) for line_number, line in special_block]
                add_reference_block('reference_' + special_kind.removeprefix('markdown_'), entries)
                special_kind = None
                special_block = []
                return
            start_line = special_block[0][0]
            end_line = special_block[-1][0]
            fragment = '\n'.join(value for _, value in special_block)
            counters['gaps'] += 1
            ref = _source_ref(document, start_line, fragment, end_line, current_section_path())
            item = _element('gaps', counters['gaps'], 'Unparsed Markdown fragment: ' + document.relative_path, ref, extraction_method=special_kind + '_gap')
            model['gaps'].append(item)
            model['status'] = 'REVIEW_REQUIRED'
            model['confidence'] = min(model['confidence'], item['confidence'])
            special_kind = None
            special_block = []

        def add_item(target: str, text: str, line_number: int, line: str, method: str) -> None:
            if target == "gaps" and _empty_gap_statement(text):
                return
            value = text.strip()
            ref = _source_ref(document, line_number, line, section_path=current_section_path())
            key = (target, value)
            existing = semantic_index.get(key)
            if existing is not None:
                evidence = existing.get("evidence")
                if isinstance(evidence, list):
                    evidence.append(ref)
                existing["occurrences"] = int(existing.get("occurrences", 1)) + 1
                methods = existing.get("extraction_methods")
                if isinstance(methods, list) and method not in methods:
                    methods.append(method)
                return
            counters[target] += 1
            item = _element(
                target, counters[target], value, ref, extraction_method=method,
                nonblocking_observation=is_normative and method.startswith("normative_"),
            )
            item["occurrences"] = 1
            item["extraction_methods"] = [method]
            semantic_index[key] = item
            model[target].append(item)
            if item["status"] in {"REVIEW_REQUIRED", "gap", "assumed"}:
                model["status"] = "REVIEW_REQUIRED"
                model["confidence"] = min(model["confidence"], item["confidence"])

        for line_number, line in enumerate(document.text.splitlines(), start=1):
            if in_fence:
                special_block.append((line_number, line))
                if FENCE_RE.match(line):
                    in_fence = False
                    flush_special()
                continue
            if FENCE_RE.match(line):
                flush_block()
                in_fence = True
                special_kind = 'markdown_code'
                special_block = [(line_number, line)]
                continue

            is_table = TABLE_RE.match(line) is not None
            is_quote = line.strip().startswith(chr(62))
            if is_table or is_quote:
                flush_block()
                kind = 'markdown_table' if is_table else 'markdown_quote'
                if special_kind and special_kind != kind:
                    flush_special()
                if not special_kind:
                    special_kind = kind
                special_block.append((line_number, line))
                continue
            flush_special()

            heading = HEADING_RE.match(line)
            if heading:
                flush_block()
                level = len(heading.group("marks"))
                if active_normative_scope is not None and (
                    active_normative_scope['heading_level'] is None or level <= active_normative_scope['heading_level']
                ):
                    close_normative_scope()
                while section_stack and section_stack[-1][0] >= level:
                    section_stack.pop()
                inherited = section_stack[-1][1] if section_stack else None
                heading_text = heading.group("heading").strip()
                section_profile = profile_sections.get(line_number, {
                    'role': 'content_section',
                    'source_ref': _source_ref(document, line_number, line, section_path=current_section_path()),
                })
                target = None if is_normative else _section_target(heading_text) or inherited
                section_stack.append((level, target, heading_text, section_profile))
                if is_normative and section_profile.get('role') == 'policy':
                    add_item('constraints', heading_text, line_number, line, 'normative_policy_heading')
                scope_modality = normalized_scope_marker(heading_text)
                if scope_modality is not None:
                    start_normative_scope(scope_modality, heading_text, line_number, line, level)
                continue

            if TABLE_RE.match(line) or line.strip().startswith(">"):
                flush_block()
                continue

            current_target = section_stack[-1][1] if section_stack else None
            explicit = ENTRY_RE.match(line)
            explicit_target = LABELS.get(explicit.group("label").casefold()) if explicit else None
            if explicit is not None and explicit_target:
                flush_block()
                candidate = _candidate_text(line)
                if candidate is not None:
                    add_normative_scope_item(line_number, line, candidate)
                add_item(explicit_target, explicit.group("text"), line_number, line, "explicit_label")
                continue

            bold_label = BOLD_NORMATIVE_LABEL_RE.match(line)
            if bold_label is not None:
                scope_modality = normalized_scope_marker(bold_label.group('label'))
                if scope_modality is not None:
                    flush_block()
                    close_normative_scope()
                    start_normative_scope(scope_modality, bold_label.group('label').strip(), line_number, line, None)
                    continue

            candidate = _candidate_text(line)
            if not candidate:
                flush_block()
                continue
            add_normative_scope_item(line_number, line, candidate)

            if current_target:
                flush_block()
                list_match = LIST_RE.match(line)
                method = "markdown_list" if list_match else "markdown_paragraph"
                add_item(current_target, candidate, line_number, line, method)
            else:
                current_block.append((line_number, line, current_section_path()))

        flush_special()
        flush_block()
        close_normative_scope()
        for block in unclassified_blocks:
            for line_number, line, section_path in block:
                if line_number in recognized_structural_lines:
                    continue
                fragment = _candidate_text(line)
                if not fragment:
                    continue
                ref = _source_ref(document, line_number, fragment, section_path=section_path)
                counters["gaps"] += 1
                item = _element(
                    "gaps",
                    counters["gaps"],
                    f"Неклассифицированный фрагмент: {document.relative_path}",
                    ref,
                    extraction_method="unclassified_gap",
                )
                model["gaps"].append(item)
                model["status"] = "REVIEW_REQUIRED"
                model["confidence"] = min(model["confidence"], item["confidence"])

    model['classification_proposals'] = build_classification_proposals(model['gaps'])
    model["recommended_model"] = _recommended(model)
    model["alternatives"] = [name for name in MODEL_TYPES if name != model["recommended_model"]]
    if not model["evidence"]:
        model["confidence"] = 0.5
        model["status"] = "REVIEW_REQUIRED"
    findings, checks = run_logical_checks(model)
    model['findings'] = findings
    model['checks'] = checks
    if any(item.get('severity') in {'warning', 'error'} for item in findings):
        model['status'] = 'REVIEW_REQUIRED'
        model['confidence'] = min(model['confidence'], 0.5)
    model['model_version'] = model_version(model)
    model['decision_cards'] = build_decision_cards(model, base_version=model['model_version'])
    return model
