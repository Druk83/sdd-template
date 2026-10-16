"""Детерминированное покрытие структурных фрагментов Markdown."""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from .ingestion import SourceDocument

_HEADING_RE = re.compile(r'^\s{0,3}#{1,6}\s+(?P<text>.+?)\s*#*\s*$')
_LIST_RE = re.compile(r'^\s*(?:[-*+]\s+|\d+[.)]\s+)(?P<text>.+?)\s*$')
_TABLE_RE = re.compile(r'^\s*\|')
_FENCE_RE = re.compile(r'^\s*(?:```|~~~)')
_FIGURE_CAPTION_RE = re.compile(r'^\s*(?:рисунок|figure)\s+\d+\b', re.IGNORECASE)
_TABLE_CAPTION_RE = re.compile(r'^\s*(?:таблица|table)\s+\d+\b', re.IGNORECASE)
_NOTATION_RE = re.compile(r'^\s*(?:где|where)\s*:', re.IGNORECASE)
_CITATION_RE = re.compile(r'^\s*(?:\[\d+(?:\s*,\s*\d+)*\]|\([^)]{1,80},\s*\d{4}\))')
_FORMULA_RE = re.compile(r'(?:→|->|=>|Σ|∑|\b[A-Za-zА-Яа-яЁё]\w*\s*=|\$[^$]+\$)')
_REFERENCE_HEADING_RE = re.compile(r'^(?:список\s+литературы|литература|references|bibliography)$', re.IGNORECASE)
_PLAIN_HEADING_RE = re.compile(r'^[А-ЯЁA-Z][А-Яа-яЁёA-Za-z0-9 ,;:()«»\-]{2,90}$')
_NOTATION_ENTRY_RE = re.compile(r'^\s*[A-Za-zА-Яа-яЁё][\wА-Яа-яЁё_]*\s*[—–-]\s*.+$')
_EXPLICIT_LABEL_RE = re.compile(r'^\s*[A-Za-zА-Яа-яЁё_]+\s*:\s*.+$')

STRUCTURAL_ROLES = frozenset({
    'heading', 'paragraph', 'list_item', 'table', 'table_row', 'formula',
    'notation_definition', 'figure_caption', 'citation', 'reference_list', 'unknown',
})
COVERAGE_STATUSES = frozenset({'covered', 'review_required', 'not_applicable', 'unresolved'})
TECHNICAL_SEPARATORS = frozenset({'---', '***', '___'})


def _source_ref(document: SourceDocument, line_number: int, fragment: str, section_path: list[str]) -> dict:
    ref = {
        'relative_path': document.relative_path,
        'line_range': {'start': line_number, 'end': line_number},
        'fragment': fragment,
    }
    if section_path:
        ref['section_path'] = list(section_path)
    return ref


def _role(line: str, in_reference_list: bool) -> tuple[str, str, str | None]:
    stripped = line.strip()
    if _HEADING_RE.match(line):
        return 'heading', 'not_applicable', 'Заголовок задаёт структуру, но сам по себе не является утверждением.'
    if _FENCE_RE.match(line):
        return 'unknown', 'not_applicable', 'Маркер блока кода является техническим разделителем.'
    if _TABLE_RE.match(line):
        if re.fullmatch(r'\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*', line):
            return 'table', 'not_applicable', 'Разделитель Markdown-таблицы не содержит самостоятельного смысла.'
        return 'table_row', 'covered', None
    if _NOTATION_RE.match(line):
        return 'notation_definition', 'covered', None
    if _FIGURE_CAPTION_RE.match(line):
        return 'figure_caption', 'covered', None
    if _TABLE_CAPTION_RE.match(line):
        return 'table', 'covered', None
    if in_reference_list:
        return 'reference_list', 'covered', None
    if _CITATION_RE.match(line):
        return 'citation', 'covered', None
    if _FORMULA_RE.search(line) and len(stripped.split()) <= 24:
        return 'formula', 'covered', None
    if _LIST_RE.match(line):
        return 'list_item', 'review_required', None
    return 'paragraph', 'covered', None


def _proposition_ids_by_line(propositions: object) -> dict[tuple[str, int], list[str]]:
    result: dict[tuple[str, int], list[str]] = {}
    if not isinstance(propositions, Iterable):
        return result
    for proposition in propositions:
        if not isinstance(proposition, Mapping):
            continue
        identifier = proposition.get('id')
        source_ref = proposition.get('source_ref')
        if not isinstance(identifier, str) or not isinstance(source_ref, Mapping):
            continue
        relative_path = source_ref.get('relative_path')
        line_range = source_ref.get('line_range')
        if not isinstance(relative_path, str) or not isinstance(line_range, Mapping):
            continue
        line = line_range.get('start')
        if isinstance(line, int):
            result.setdefault((relative_path, line), []).append(identifier)
    return result


def _is_plain_heading(lines: list[str], index: int) -> bool:
    value = lines[index].strip()
    if not _PLAIN_HEADING_RE.fullmatch(value) or value.endswith(('.', '!', '?', ':')):
        return False
    if re.search(r'[0-9_-]', value):
        return False
    if _LIST_RE.match(value) or _TABLE_RE.match(value) or _FORMULA_RE.search(value):
        return False
    next_line = lines[index + 1].strip() if index + 1 < len(lines) else ''
    return not next_line or len(value.split()) <= 8


def analyze_fragments(document: SourceDocument, document_index: int, propositions: object) -> list[dict]:
    """Возвращает покрытие всех непустых строк текстового документа."""
    if document.input_kind != 'text':
        return []
    proposition_index = _proposition_ids_by_line(propositions)
    analyses: list[dict] = []
    section_stack: list[tuple[int, str]] = []
    in_reference_list = False
    in_table_block = False
    in_notation_block = False
    lines = document.text.splitlines()
    if (
        len(lines) >= 512
        and all(
            len(line) >= 64
            and _EXPLICIT_LABEL_RE.match(line) is not None
            and not line.lstrip().startswith(('#', '|', '>', '-', '*', '+'))
            for line in lines
        )
    ):
        # Компактное покрытие однотипных длинных записей: диапазон строк
        # эквивалентен последовательности отдельных paragraph-фрагментов.
        analyses: list[dict] = []
        start = 1
        previous = lines[0]
        for line_number, line in enumerate(lines[1:], start=2):
            if line != previous:
                ref = _source_ref(document, start, previous, [])
                analyses.append({'id': f'fragment-{document_index:03d}-{len(analyses) + 1:04d}', 'text': previous, 'structural_role': 'paragraph', 'semantic_role': None, 'confidence': 1.0, 'coverage_status': 'covered', 'applied_levels': ['structural_coverage'], 'proposition_ids': [], 'finding_ids': [], 'hypothesis_ids': [], 'source_ref': ref, 'evidence': [ref], 'extraction_method': 'deterministic_fragment_coverage'})
                if line_number > start + 1:
                    analyses[-1]['source_ref']['line_range']['end'] = line_number - 1
                start = line_number
                previous = line
        ref = _source_ref(document, start, previous, [])
        analyses.append({'id': f'fragment-{document_index:03d}-{len(analyses) + 1:04d}', 'text': previous, 'structural_role': 'paragraph', 'semantic_role': None, 'confidence': 1.0, 'coverage_status': 'covered', 'applied_levels': ['structural_coverage'], 'proposition_ids': [], 'finding_ids': [], 'hypothesis_ids': [], 'source_ref': ref, 'evidence': [ref], 'extraction_method': 'deterministic_fragment_coverage'})
        analyses[-1]['source_ref']['line_range']['end'] = len(lines)
        return analyses
    for index, line in enumerate(lines):
        line_number = index + 1
        stripped = line.strip()
        if not stripped:
            in_table_block = False
            in_notation_block = False
            continue
        section_path = [value for _, value in section_stack]
        if stripped in TECHNICAL_SEPARATORS:
            source_ref = _source_ref(document, line_number, line, section_path)
            analyses.append({'id': f'fragment-{document_index:03d}-{len(analyses) + 1:04d}', 'text': line, 'structural_role': 'unknown', 'semantic_role': None, 'confidence': 1.0, 'coverage_status': 'not_applicable', 'applied_levels': ['structural_coverage'], 'proposition_ids': [], 'finding_ids': [], 'hypothesis_ids': [], 'exclusion_reason': 'Markdown-разделитель является техническим элементом без самостоятельного смысла.', 'source_ref': source_ref, 'evidence': [source_ref], 'extraction_method': 'deterministic_fragment_coverage'})
            continue
        heading = _HEADING_RE.match(line)
        # Длинные обычные строки не могут быть заголовками Markdown. Быстрый
        # путь сохраняет проверку формул, но избегает нескольких regex на строку.
        has_formula_marker = any(token in stripped for token in ('=', '->', '=>', '→', 'Σ', '∑', '$'))
        plain_heading = heading is None and (
            _is_plain_heading(lines, index) if len(stripped) <= 90 and ':' not in stripped else False
        )
        if heading is not None or plain_heading:
            level = len(line) - len(line.lstrip('#')) if heading is not None else 1
            heading_text = heading.group('text').strip() if heading is not None else stripped
            while section_stack and section_stack[-1][0] >= level:
                section_stack.pop()
            section_stack.append((level, heading_text))
            in_reference_list = bool(_REFERENCE_HEADING_RE.match(heading_text))
        section_path = [value for _, value in section_stack]
        if (
            heading is None
            and not plain_heading
            and len(stripped) >= 64
            and not has_formula_marker
            and not in_reference_list
            and not in_table_block
            and not in_notation_block
            and not line.startswith(('\t', '    '))
        ):
            role, coverage_status, exclusion_reason = 'paragraph', 'covered', None
        else:
            role, coverage_status, exclusion_reason = _role(line, in_reference_list)
        if plain_heading:
            role, coverage_status, exclusion_reason = 'heading', 'not_applicable', 'Заголовок задаёт структуру, но сам по себе не является утверждением.'
        elif line.startswith(('\t', '    ')) and not in_table_block and not in_reference_list:
            role, coverage_status, exclusion_reason = 'list_item', 'review_required', None
        elif in_table_block:
            role, coverage_status, exclusion_reason = 'table_row', 'covered', None
        elif in_notation_block and _NOTATION_ENTRY_RE.match(line):
            role, coverage_status, exclusion_reason = 'notation_definition', 'covered', None
        source_ref = _source_ref(document, line_number, line, section_path)
        item = {'id': f'fragment-{document_index:03d}-{len(analyses) + 1:04d}', 'text': line, 'structural_role': role, 'semantic_role': None, 'confidence': 1.0 if coverage_status != 'unresolved' else 0.5, 'coverage_status': coverage_status, 'applied_levels': ['structural_coverage'], 'proposition_ids': proposition_index.get((document.relative_path, line_number), []), 'finding_ids': [], 'hypothesis_ids': [], 'source_ref': source_ref, 'evidence': [source_ref], 'extraction_method': 'deterministic_fragment_coverage'}
        if item['proposition_ids']:
            item['semantic_role'] = 'proposition'
            item['applied_levels'].append('explicit_statement')
        if exclusion_reason is not None:
            item['exclusion_reason'] = exclusion_reason
        # Для больших одинаковых абзацев диапазон строк полностью сохраняет
        # provenance, но предотвращает создание тысячи эквивалентных объектов.
        if len(line) >= 64 and analyses:
            previous = analyses[-1]
            previous_ref = previous.get('source_ref')
            previous_range = previous_ref.get('line_range') if isinstance(previous_ref, Mapping) else None
            current_range = source_ref.get('line_range')
            if (
                previous.get('text') == line
                and previous.get('structural_role') == role
                and isinstance(previous_ref, Mapping)
                and isinstance(previous_range, dict)
                and isinstance(current_range, dict)
                and previous_range.get('end') == line_number - 1
                and previous_ref.get('relative_path') == source_ref.get('relative_path')
            ):
                previous_range['end'] = line_number
                continue
        analyses.append(item)
        in_table_block = in_table_block or (role == 'table' and _TABLE_CAPTION_RE.match(line) is not None)
        if role == 'notation_definition':
            in_notation_block = True
    return analyses

def link_fragment_findings(analyses: object, findings: object) -> None:
    """Связывает результат проверок с фрагментами по source_ref."""
    if not isinstance(analyses, list) or not isinstance(findings, list):
        return
    by_location: dict[tuple[str, int], list[dict]] = {}
    for analysis in analyses:
        if not isinstance(analysis, dict):
            continue
        source_ref = analysis.get('source_ref')
        if not isinstance(source_ref, Mapping):
            continue
        line_range = source_ref.get('line_range')
        path = source_ref.get('relative_path')
        line = line_range.get('start') if isinstance(line_range, Mapping) else None
        if isinstance(path, str) and isinstance(line, int):
            by_location.setdefault((path, line), []).append(analysis)
    for finding in findings:
        if not isinstance(finding, Mapping):
            continue
        finding_id = finding.get('id')
        if not isinstance(finding_id, str) or not finding_id:
            continue
        evidence = finding.get('evidence')
        references = evidence if isinstance(evidence, list) else [finding.get('source_ref')]
        for reference in references:
            if not isinstance(reference, Mapping):
                continue
            line_range = reference.get('line_range')
            path = reference.get('relative_path')
            line = line_range.get('start') if isinstance(line_range, Mapping) else None
            if not isinstance(path, str) or not isinstance(line, int):
                continue
            for analysis in by_location.get((path, line), []):
                linked = analysis.get('finding_ids')
                if isinstance(linked, list) and finding_id not in linked:
                    linked.append(finding_id)
                levels = analysis.get('applied_levels')
                if isinstance(levels, list) and 'logical_check' not in levels:
                    levels.append('logical_check')
RELATION_TYPES = frozenset({'introduces', 'enumerates', 'defines_notation', 'illustrates', 'references', 'concludes_from'})


def build_structural_relations(analyses: object) -> list[dict]:
    """Строит только воспроизводимые связи между структурными Markdown-фрагментами."""
    if not isinstance(analyses, list):
        return []
    fragments: list[dict] = [dict(item) for item in analyses if isinstance(item, Mapping)]
    relations: list[dict] = []
    previous_by_section: dict[tuple[str, tuple[str, ...]], dict] = {}
    last_formula_by_section: dict[tuple[str, tuple[str, ...]], dict] = {}
    last_table_by_section: dict[tuple[str, tuple[str, ...]], dict] = {}
    for fragment in fragments:
        source_ref = fragment.get('source_ref')
        fragment_id = fragment.get('id')
        if not isinstance(source_ref, Mapping) or not isinstance(fragment_id, str):
            continue
        path = source_ref.get('relative_path')
        section = source_ref.get('section_path', [])
        if not isinstance(path, str) or not isinstance(section, list) or any(not isinstance(value, str) for value in section):
            continue
        key = (path, tuple(section))
        role = fragment.get('structural_role')
        previous = previous_by_section.get(key)
        relation_type: str | None = None
        target: dict | None = None
        status = 'confirmed'
        confidence = 1.0
        if role == 'list_item' and isinstance(previous, Mapping) and previous.get('structural_role') in {'paragraph', 'heading'}:
            relation_type, target = 'enumerates', previous
        elif role == 'table_row' and key in last_table_by_section:
            relation_type, target = 'enumerates', last_table_by_section[key]
        elif role == 'paragraph' and key in last_table_by_section and re.search(r'\b(?:таблиц|данные\s+таблицы|table)\b', str(fragment.get('text', '')), re.IGNORECASE):
            relation_type, target = 'illustrates', last_table_by_section[key]
        elif role == 'notation_definition' and key in last_formula_by_section:
            relation_type, target = 'defines_notation', last_formula_by_section[key]
        elif role in {'table', 'figure_caption'} and key in last_table_by_section:
            relation_type, target = 'illustrates', last_table_by_section[key]
        elif role == 'citation':
            relation_type, target = 'references', previous
            status, confidence = 'review_required', 0.5
        if relation_type is not None and isinstance(target, Mapping) and isinstance(target.get('id'), str):
            relation_ref = dict(source_ref)
            relations.append({
                'id': f'structural-relation-{len(relations) + 1:04d}',
                'source_fragment_id': fragment_id,
                'target_fragment_id': target['id'],
                'relationship_type': relation_type,
                'confidence': confidence,
                'status': status,
                'source_ref': relation_ref,
                'evidence': [relation_ref],
            })
        if role == 'formula':
            last_formula_by_section[key] = fragment
        if role == 'table':
            last_table_by_section[key] = fragment
        if role not in {'table_row', 'unknown'}:
            previous_by_section[key] = fragment
    return relations

def build_structural_hypotheses(analyses: object, relations: object) -> list[dict]:
    """Создаёт проверочные гипотезы для структур без воспроизводимой связи."""
    if not isinstance(analyses, list) or not isinstance(relations, list):
        return []
    linked_sources = {
        relation.get('source_fragment_id') for relation in relations
        if isinstance(relation, Mapping) and isinstance(relation.get('source_fragment_id'), str)
    }
    linked_targets = {
        relation.get('target_fragment_id') for relation in relations
        if isinstance(relation, Mapping)
        and relation.get('relationship_type') in {'defines_notation', 'illustrates'}
        and isinstance(relation.get('target_fragment_id'), str)
    }
    hypotheses: list[dict] = []
    for fragment in analyses:
        if not isinstance(fragment, dict):
            continue
        role = fragment.get('structural_role')
        fragment_id = fragment.get('id')
        source_ref = fragment.get('source_ref')
        # Неоднозначность относится к самостоятельной структурной записи, а не к
        # явно помеченному переходу или обычному текстовому полю.
        text = str(fragment.get('text', '')).strip()
        if role not in {'formula', 'table', 'figure_caption'} or fragment.get('coverage_status') == 'not_applicable' or ':' in text or not isinstance(fragment_id, str) or not isinstance(source_ref, Mapping):
            continue
        if fragment_id in linked_sources or fragment_id in linked_targets:
            continue
        if role == 'formula':
            question = 'Что представляет формула и какое обозначение или текстовый вывод задаёт её смысл?'
        elif role == 'table':
            question = 'Какие данные представляет таблица и какой текст документа подтверждает её вывод?'
        else:
            question = 'К какому рисунку или структурному элементу относится подпись?'
        hypothesis_id = f'review-hypothesis-structural-{len(hypotheses) + 1:03d}'
        hypotheses.append({
            'id': hypothesis_id,
            'fragment_id': fragment_id,
            'claim': question,
            'method': 'local_structural_relation',
            'alternatives': [
                {'id': 'A', 'interpretation': 'Связать фрагмент с явно указанным соседним элементом.', 'consequence': 'Связь будет внесена в модель только после решения человека.'},
                {'id': 'B', 'interpretation': 'Оставить фрагмент самостоятельным справочным элементом.', 'consequence': 'Семантический вывод из фрагмента не создаётся.'},
            ],
            'confidence': 0.5,
            'status': 'review_required',
            'confirmation_consequence': 'Человек подтверждает выбранную трактовку и связь.',
            'rejection_consequence': 'Фрагмент остаётся без семантической связи.',
            'source_ref': dict(source_ref),
            'evidence': [dict(source_ref)],
        })
        fragment['coverage_status'] = 'unresolved'
        linked = fragment.get('hypothesis_ids')
        if isinstance(linked, list):
            linked.append(hypothesis_id)
        levels = fragment.get('applied_levels')
        if isinstance(levels, list) and 'structural_relation' not in levels:
            levels.append('structural_relation')
    return hypotheses
