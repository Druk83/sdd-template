
'''Детерминированные предложения для свободных Markdown-фрагментов.'''
from __future__ import annotations

import re
from collections.abc import Mapping

# scope: src/agent_logic/markdown_classification.py, src/agent_logic/decisions.py, tests/
# type: feature
# prio: P1
# accept: предложения не становятся подтверждёнными без решения человека; карточки группируют одинаковые типы

_LIST_PREFIX_RE = re.compile(r'^\s*(?:[-*+]\s+|\d+[.)]\s+)')
_GOAL_RE = re.compile(r'^\s*(?:цель|назначение)\b', re.IGNORECASE)
_CONSTRAINT_RE = re.compile(
    r'\b(?:должен|должны|следует|необходимо|запрещено|только)\b|^\s*не\s+[а-яё]+(?:ть|ться)\b',
    re.IGNORECASE,
)
_CONDITION_RE = re.compile(r'\b(?:если|когда|при условии|в случае)\b', re.IGNORECASE)
_DEPENDENCY_RE = re.compile(r'(?:->|=>|\b(?:зависит|после|перед)\b)', re.IGNORECASE)
_ACTION_RE = re.compile(
    r'\b(?:выполнить|проверить|создать|обработать|отправить|получить|сформировать|'
    r'зарегистрировать|обновить|изменить|переименовать|перенести|удалить|добавить)\w*\b',
    re.IGNORECASE,
)
_ENTITY_RE = re.compile(
    r'^(?:(?:роль|пользователь|оператор|система|документ|заказ|файл|артефакт)'
    r'(?:\s+[A-Za-zА-Яа-яЁё0-9_-]+){0,3})$',
    re.IGNORECASE,
)
_ENTITY_CONTEXT_RE = re.compile(
    r'\b(?:должен|должны|следует|необходимо|запрещено|только|если|когда|не)\b',
    re.IGNORECASE,
)


def _clean_fragment(fragment: str) -> str:
    return _LIST_PREFIX_RE.sub('', fragment.strip())


def _proposal(target: str, text: str, match: re.Match[str], confidence: float = 0.65) -> dict:
    return {
        'target': target,
        'text': text,
        'confidence': confidence,
        'rationale': f'Явный языковой признак: {match.group(0)}',
    }


def classify_fragment(fragment: str) -> dict | None:
    """Возвращает предложение только при достаточно специфичном признаке."""
    text = _clean_fragment(fragment)
    if not text:
        return None
    for target, pattern in (
        ('goals', _GOAL_RE),
        ('constraints', _CONSTRAINT_RE),
        ('conditions', _CONDITION_RE),
        ('actions', _ACTION_RE),
        ('dependencies', _DEPENDENCY_RE),
    ):
        match = pattern.search(text)
        if match:
            return _proposal(target, text, match)
    entity_match = _ENTITY_RE.fullmatch(text)
    if entity_match and not _ENTITY_CONTEXT_RE.search(text):
        return _proposal('entities', text, entity_match)
    return None


def build_classification_proposals(gaps: object) -> list[dict]:
    if not isinstance(gaps, list):
        return []
    proposals: list[dict] = []
    for gap in gaps:
        if not isinstance(gap, Mapping) or gap.get('extraction_method') != 'unclassified_gap':
            continue
        source_ref = gap.get('source_ref')
        if not isinstance(source_ref, Mapping):
            continue
        classification = classify_fragment(str(source_ref.get('fragment', '')))
        if classification is None:
            continue
        proposal = {
            'id': f'classification-{len(proposals) + 1:03d}',
            'gap_id': gap.get('id'),
            'target': classification['target'],
            'text': classification['text'],
            'status': 'proposed',
            'confidence': classification['confidence'],
            'rationale': classification['rationale'],
            'source_ref': dict(source_ref),
            'evidence': [dict(source_ref)],
        }
        proposals.append(proposal)
    return proposals