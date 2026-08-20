'''Decision cards and human decision application for ASIR models.'''
from __future__ import annotations

import copy
import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping

from .errors import InputError

CARD_STATUSES = {'proposed', 'auto_decided', 'review_required', 'approved', 'rejected', 'blocked'}
DECISION_STATUSES = {'approved', 'rejected'}
SINGULAR = {
    'goals': 'goal', 'entities': 'entity', 'attributes': 'attribute', 'facts': 'fact',
    'states': 'state', 'events': 'event', 'actions': 'action', 'transitions': 'transition',
    'conditions': 'condition', 'constraints': 'constraint', 'invariants': 'invariant',
    'dependencies': 'dependency', 'decisions': 'decision', 'exceptions': 'exception',
    'assumptions': 'assumption', 'gaps': 'gap',
}


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _resolved_state(model: Mapping, collection: str) -> list[dict]:
    values = model.get(collection, [])
    if not isinstance(values, list):
        return []
    result: list[dict] = []
    for item in values:
        if not isinstance(item, Mapping):
            continue
        status = item.get('status')
        if status not in {'approved', 'rejected', 'BLOCKED', 'auto_decided'} and 'decision_record' not in item:
            continue
        result.append({
            'id': item.get('id'),
            'status': status,
            'decision_card_id': item.get('decision_card_id'),
            'decision_record': item.get('decision_record'),
        })
    return result


def model_version(model: Mapping) -> str:
    """Возвращает версию, зависящую от входов, компилятора и решений без копии полной ASIR."""
    metadata = model.get('metadata')
    compiler_version = metadata.get('compiler_version') if isinstance(metadata, Mapping) else None
    payload = {
        'compilationId': model.get('compilationId'),
        'compiler_version': compiler_version,
        'decision_records': model.get('decision_records', []),
        'findings': _resolved_state(model, 'findings'),
        'classification_proposals': _resolved_state(model, 'classification_proposals'),
        'gaps': _resolved_state(model, 'gaps'),
    }
    return hashlib.sha256(_canonical(payload).encode('utf-8')).hexdigest()[:16]


def _refs(finding: Mapping) -> list[dict]:
    values = finding.get('evidence', [])
    return [value for value in values if isinstance(value, dict)] if isinstance(values, list) else []




def _explicit_expression_variants(finding: Mapping) -> list[dict] | None:
    participants = finding.get('participants', [])
    if not isinstance(participants, list):
        return None
    alternatives: list[str] = []
    for participant in participants:
        values = participant.get('alternatives', []) if isinstance(participant, Mapping) else []
        if isinstance(values, list):
            for value in values:
                if isinstance(value, str) and value not in alternatives:
                    alternatives.append(value)
    if len(alternatives) < 2:
        return None
    meanings = {
        'OR': ('Прочитать связку как «или».', 'Достаточно выполнения хотя бы одного варианта.'),
        'XOR': ('Прочитать связку как «либо, но не оба».', 'Допустим ровно один вариант; совместное выполнение исключено.'),
    }
    variants = []
    for index, operator in enumerate(alternatives, start=1):
        interpretation, consequences = meanings.get(operator, (f'Выбрать трактовку {operator}.', 'Последствия должны быть подтверждены человеком.'))
        variants.append({'id': chr(64 + index), 'interpretation': interpretation, 'difference': f'Логический оператор: {operator}.', 'consequences': consequences})
    return variants
def _deontic_scope_variants(finding: Mapping) -> list[dict] | None:
    if finding.get('rule_id') != 'DNT-004':
        return None
    evidence = _refs(finding)
    if len(evidence) < 2:
        return None
    heading = str(evidence[0].get('fragment', '')).strip()
    item = str(evidence[1].get('fragment', '')).strip()
    if not heading or not item:
        return None
    return [
        {
            'id': 'A',
            'interpretation': 'Считать пункт самостоятельным запретом действия, описанного после «Не».',
            'difference': 'Отрицание в пункте не инвертирует модальность заголовка.',
            'consequences': 'Документ должен быть переписан вручную так, чтобы запрещённое действие было выражено утвердительно.',
        },
        {
            'id': 'B',
            'interpretation': 'Считать заголовок запретом не выполнять действие из пункта.',
            'difference': 'Модальность применяется к отрицательному действию: PROHIBITION(NOT action).',
            'consequences': 'Действие без «Не» может оказаться разрешённым; требуется явное подтверждение человека.',
        },
    ]


def _deontic_scope_context(finding: Mapping) -> dict | None:
    if finding.get('rule_id') != 'DNT-004':
        return None
    evidence = _refs(finding)
    if len(evidence) < 2:
        return None
    heading, item = evidence[0], evidence[1]
    if not heading.get('fragment') or not item.get('fragment'):
        return None
    return {
        'heading': heading,
        'item': item,
        'scope_boundary': 'до следующего заголовка того же или более высокого уровня либо до следующей отдельной нормативной метки',
    }
def _variants(finding: Mapping) -> list[dict]:
    deontic = _deontic_scope_variants(finding)
    if deontic is not None:
        return deontic
    explicit = _explicit_expression_variants(finding)
    if explicit is not None:
        return explicit
    evidence = _refs(finding)
    fragments = [str(value.get('fragment', '')).strip() for value in evidence if value.get('fragment')]
    if len(fragments) >= 2:
        return [
            {'id': 'A', 'interpretation': fragments[0], 'difference': 'Первый источник или вариант трактовки.', 'consequences': 'Смысл и связанные действия определяются первым фрагментом.'},
            {'id': 'B', 'interpretation': fragments[1], 'difference': 'Второй источник или вариант трактовки.', 'consequences': 'Смысл и связанные действия определяются вторым фрагментом.'},
        ]
    return [
        {'id': 'A', 'interpretation': 'Переформулировать или дополнить исходный фрагмент после проверки контекста.', 'difference': 'Устранить причину находки в источнике без автоматического изменения.', 'consequences': 'После ручного изменения требуется повторная проверка; текущая модель не утверждает новую трактовку.'},
        {'id': 'B', 'interpretation': 'Зафиксировать фрагмент как осознанное исключение без семантического вывода.', 'difference': 'Не менять источник и не считать находку автоматически разрешённой.', 'consequences': 'Ограничение или неопределённость сохраняется в журнале решения человека.'},
    ]

MAX_CLASSIFICATION_CARD_SIZE = 10


def _proposal_sort_key(proposal: Mapping) -> tuple[int, str]:
    source_ref = proposal.get('source_ref')
    line_range = source_ref.get('line_range') if isinstance(source_ref, Mapping) else None
    line = line_range.get('start') if isinstance(line_range, Mapping) else None
    return (line if isinstance(line, int) else 0, str(proposal.get('id', '')))


def _full_section_path(proposal: Mapping) -> tuple[str, ...]:
    source_ref = proposal.get('source_ref')
    if not isinstance(source_ref, Mapping):
        return ()
    section_path = source_ref.get('section_path')
    if not isinstance(section_path, list) or any(not isinstance(value, str) for value in section_path):
        return ()
    return tuple(section_path)


def _proposal_group_key(proposal: Mapping) -> tuple[str, tuple[str, ...]]:
    source_ref = proposal.get('source_ref')
    source_path = str(source_ref.get('relative_path') or 'unknown') if isinstance(source_ref, Mapping) else 'unknown'
    section_path = _full_section_path(proposal)
    # Соседние вложенные подразделы образуют единый смысловой блок.
    parent_path = section_path[:-1] if len(section_path) >= 3 else section_path
    return (source_path, parent_path)


def _section_paths(proposals: list[dict]) -> list[list[str]]:
    values: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for proposal in proposals:
        section_path = _full_section_path(proposal)
        if section_path and section_path not in seen:
            seen.add(section_path)
            values.append(list(section_path))
    return values


def _classification_card_id(target: str, proposals: list[dict], has_single_card: bool) -> str:
    if has_single_card:
        return f'classification-{target}'
    proposal_id = str(proposals[0].get('id', ''))
    suffix = proposal_id.removeprefix('classification-')
    return f'classification-{target}-{suffix}'


def _classification_cards(model: Mapping, base_version: str) -> list[dict]:
    values = model.get('classification_proposals', [])
    if not isinstance(values, list):
        return []
    by_target: dict[str, list[dict]] = defaultdict(list)
    for proposal in values:
        if isinstance(proposal, dict) and proposal.get('status') == 'proposed' and proposal.get('target') in SINGULAR:
            by_target[str(proposal['target'])].append(proposal)
    cards = []
    for target in sorted(by_target):
        by_section: dict[tuple[str, tuple[str, ...]], list[dict]] = defaultdict(list)
        for proposal in by_target[target]:
            by_section[_proposal_group_key(proposal)].append(proposal)
        chunks: list[tuple[tuple[str, tuple[str, ...]], list[dict]]] = []
        ordered_groups = sorted(
            by_section.items(),
            key=lambda item: (_proposal_sort_key(min(item[1], key=_proposal_sort_key)), item[0]),
        )
        for group_key, proposals in ordered_groups:
            ordered = sorted(proposals, key=_proposal_sort_key)
            for index in range(0, len(ordered), MAX_CLASSIFICATION_CARD_SIZE):
                chunks.append((group_key, ordered[index:index + MAX_CLASSIFICATION_CARD_SIZE]))
        has_single_card = len(chunks) == 1
        for (source_path, section_path), proposals in chunks:
            sources = [item['source_ref'] for item in proposals if isinstance(item.get('source_ref'), dict)]
            section_name = ' / '.join(section_path) if section_path else 'без заголовка'
            cards.append({
                'id': _classification_card_id(target, proposals, has_single_card),
                'finding_id': f'classification-{target}',
                'rule_id': 'CLS-001',
                'status': 'review_required',
                'kind': 'classification_group',
                'question': f'Подтвердить классификацию {len(proposals)} фрагм. как {SINGULAR[target]} в разделе «{section_name}»?',
                'variants': [
                    {'id': 'A', 'interpretation': f'Добавить предложенные фрагменты в {target}.', 'difference': 'Принять эвристическое предложение.', 'consequences': 'В ASIR появятся одобренные элементы с исходными ссылками.'},
                    {'id': 'B', 'interpretation': 'Оставить фрагменты без классификации.', 'difference': 'Отклонить эвристическое предложение.', 'consequences': 'Подтверждённые элементы ASIR не создаются.'},
                ],
                'recommendation': None,
                'sources': sources,
                'base_model_version': base_version,
                'classification_target': target,
                'source_path': source_path,
                'section_path': list(section_path),
                'section_paths': _section_paths(proposals),
                'proposal_ids': [item['id'] for item in proposals],
                'gap_ids': [item['gap_id'] for item in proposals if isinstance(item.get('gap_id'), str)],
            })
    return cards

def _gap_group_cards(model: Mapping, base_version: str, proposed_gap_ids: set[str]) -> list[dict]:
    """Собирает нераспознанные GAP в компактные карточки ручной трактовки."""
    groups: dict[str, list[dict]] = defaultdict(list)
    gaps = model.get('gaps', [])
    if not isinstance(gaps, list):
        return []
    unresolved_statuses = {'gap', 'REVIEW_REQUIRED', 'assumed', 'BLOCKED'}
    for gap in gaps:
        if not isinstance(gap, dict) or gap.get('id') in proposed_gap_ids:
            continue
        if gap.get('status') not in unresolved_statuses:
            continue
        method = str(gap.get('extraction_method') or 'unclassified_gap')
        groups[method].append(gap)
    cards = []
    for method in sorted(groups):
        values = sorted(groups[method], key=lambda item: str(item.get('id', '')))
        sources = [item['source_ref'] for item in values if isinstance(item.get('source_ref'), dict)]
        cards.append({
            'id': f'gap-group-{method}',
            'finding_id': f'gap-group-{method}',
            'rule_id': 'GAP-001',
            'status': 'review_required',
            'kind': 'gap_group',
            'question': f'Как трактовать {len(values)} фрагм. без достаточного признака классификации?',
            'variants': [
                {'id': 'A', 'interpretation': 'Признать фрагменты справочными и не включать в семантическую модель.', 'difference': 'Закрыть вопрос без создания элемента ASIR.', 'consequences': 'Фрагменты сохраняются с provenance как рассмотренные человеком.'},
                {'id': 'B', 'interpretation': 'Отклонить текущую трактовку и оставить исходный текст для доработки.', 'difference': 'Не делать семантический вывод из фрагментов.', 'consequences': 'Элементы ASIR не создаются; в журнале остаётся решение человека.'},
            ],
            'recommendation': None,
            'sources': sources,
            'base_model_version': base_version,
            'gap_ids': [item['id'] for item in values if isinstance(item.get('id'), str)],
            'extraction_method': method,
        })
    return cards

def build_decision_cards(model: Mapping, *, base_version: str | None = None) -> list[dict]:
    if base_version is None:
        base_version = model_version(model)
    proposals = model.get('classification_proposals', [])
    proposed_gap_ids: set[str] = set()
    if isinstance(proposals, list):
        for proposal in proposals:
            if not isinstance(proposal, dict) or proposal.get('status') != 'proposed':
                continue
            gap_id = proposal.get('gap_id')
            if isinstance(gap_id, str):
                proposed_gap_ids.add(gap_id)
    findings = list(model.get('findings', [])) if isinstance(model.get('findings', []), list) else []

    cards = []
    for index, finding in enumerate(findings, 1):
        if not isinstance(finding, dict):
            continue
        status = finding.get('status')
        if status == 'auto_decided':
            card_status = 'auto_decided'
        elif status == 'BLOCKED':
            card_status = 'blocked'
        elif status in {'approved', 'rejected'}:
            card_status = status
        elif finding.get('severity') in {'warning', 'error'}:
            card_status = 'review_required'
        else:
            card_status = 'proposed'
        cards.append({
            'id': f'decision-{index:03d}',
            'finding_id': finding.get('id'),
            'rule_id': finding.get('rule_id'),
            'status': card_status,
            'kind': 'finding',
            'question': finding.get('message', 'Что следует принять?'),
            'variants': _variants(finding),
            'recommendation': None if card_status == 'review_required' else 'A',
            'sources': _refs(finding),
            'context': _deontic_scope_context(finding),
            'base_model_version': base_version,
        })
    return cards + _classification_cards(model, base_version) + _gap_group_cards(model, base_version, proposed_gap_ids)


def decision_envelope(model: Mapping, *, base_version: str | None = None) -> dict:
    version = base_version if isinstance(base_version, str) and base_version else model_version(model)
    cards = build_decision_cards(model, base_version=version)
    return {'compilationId': model.get('compilationId'), 'model_version': version, 'cards': cards}


def _find_card(model: Mapping, card_id: str) -> dict:
    for card in build_decision_cards(model):
        if card.get('id') == card_id:
            return card
    raise InputError(f'unknown decision card: {card_id}')


def _apply_classification(updated: dict, card: Mapping, status: str, record: dict) -> None:
    proposal_ids = set(card.get('proposal_ids', []))
    proposals = updated.get('classification_proposals', [])
    if not isinstance(proposals, list):
        raise InputError('classification proposals are missing')
    target = card.get('classification_target')
    if target not in SINGULAR:
        raise InputError('classification target is unsupported')
    gaps = updated.get('gaps', [])
    if not isinstance(gaps, list):
        raise InputError('gaps collection is invalid')
    gap_by_id = {gap.get('id'): gap for gap in gaps if isinstance(gap, dict)}
    target_items = updated.setdefault(target, [])
    if not isinstance(target_items, list):
        raise InputError(f'{target} collection is invalid')
    for proposal in proposals:
        if not isinstance(proposal, dict) or proposal.get('id') not in proposal_ids:
            continue
        proposal['status'] = status
        gap = gap_by_id.get(proposal.get('gap_id'))
        if isinstance(gap, dict):
            gap['status'] = status
            gap['decision_card_id'] = card['id']
            gap['decision_record'] = record
        if status != 'approved':
            continue
        source_ref = proposal.get('source_ref')
        if not isinstance(source_ref, dict):
            continue
        target_items.append({
            'id': f'{SINGULAR[target]}-{len(target_items) + 1:03d}',
            'type': SINGULAR[target],
            'text': proposal.get('text', ''),
            'status': 'approved',
            'confidence': proposal.get('confidence', 0.65),
            'source_ref': dict(source_ref),
            'evidence': [dict(source_ref)],
            'extraction_method': 'heuristic_classification_approved',
            'inferred_from_gap': proposal.get('gap_id'),
            'classification_rationale': proposal.get('rationale'),
        })


def _apply_gap_group(updated: dict, card: Mapping, status: str, record: dict) -> None:
    """Фиксирует решение по группе фрагментов без семантического вывода."""
    gap_ids = set(card.get('gap_ids', []))
    for gap in updated.get('gaps', []):
        if isinstance(gap, dict) and gap.get('id') in gap_ids:
            gap['status'] = status
            gap['decision_card_id'] = card['id']
            gap['decision_record'] = record

def apply_human_decision(model: Mapping, response: Mapping) -> dict:
    if not isinstance(response, Mapping):
        raise InputError('decision response must be a JSON object')
    card_id = response.get('decision_card_id')
    if not isinstance(card_id, str) or not card_id:
        raise InputError('decision_card_id is required')
    current_version = model_version(model)
    expected_version = response.get('base_model_version')
    if expected_version != current_version:
        raise InputError('decision response targets an outdated model version')
    card = _find_card(model, card_id)
    if card.get('status') in {'auto_decided', 'blocked'}:
        raise InputError('decision card is not available for human approval')
    status = response.get('status')
    if status not in DECISION_STATUSES:
        raise InputError('decision status must be approved or rejected')
    variant = response.get('selected_variant')
    if status == 'approved' and not isinstance(variant, str):
        raise InputError('selected_variant is required for approved decision')
    if variant is not None and variant not in {item.get('id') for item in card.get('variants', [])}:
        raise InputError('selected_variant is not present in the decision card')
    updated = copy.deepcopy(dict(model))
    records = updated.setdefault('decision_records', [])
    if not isinstance(records, list):
        records = []
        updated['decision_records'] = records
    record = {'decision_card_id': card_id, 'finding_id': card.get('finding_id'), 'status': status, 'selected_variant': variant, 'base_model_version': current_version}
    for field in ('decided_by', 'decided_at', 'comment'):
        if field in response:
            record[field] = response[field]
    records.append(record)
    if card.get('kind') == 'classification_group':
        _apply_classification(updated, card, status, record)
    elif card.get('kind') == 'gap_group':
        _apply_gap_group(updated, card, status, record)
    else:
        finding_id = card.get('finding_id')
        for finding in updated.get('findings', []):
            if isinstance(finding, dict) and finding.get('id') == finding_id:
                finding['status'] = status
                finding['decision_card_id'] = card_id
                finding['decision_record'] = record
        for gap in updated.get('gaps', []):
            if isinstance(gap, dict) and gap.get('id') == finding_id:
                gap['status'] = status
                gap['decision_card_id'] = card_id
    updated['decision_cards'] = build_decision_cards(updated)
    updated['model_version'] = model_version(updated)
    updated['versions'] = list(updated.get('versions', [])) if isinstance(updated.get('versions', []), list) else []
    updated['versions'].append({'component': 'human-decision', 'version': updated['model_version'], 'base_model_version': current_version})
    unresolved = [item for item in updated.get('findings', []) if isinstance(item, dict) and item.get('status') not in {'approved', 'rejected', 'auto_decided'} and item.get('severity') in {'warning', 'error'}]
    for name in SINGULAR:
        unresolved += [item for item in updated.get(name, []) if isinstance(item, dict) and item.get('status') in {'gap', 'REVIEW_REQUIRED', 'assumed', 'BLOCKED'}]
    if not unresolved:
        updated['status'] = 'confirmed'
    return updated
