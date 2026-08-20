"""Детерминированное профилирование вида входного артефакта и его разделов."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .formalization_profiles import profile_for_source, profile_summary

_HEADING_RE = re.compile(r"^\s{0,3}(?P<marks>#{1,6})\s+(?P<heading>.+?)\s*#*\s*$")
_RULE_ID_RE = re.compile(r"\b(?P<id>[A-Za-z][A-Za-z0-9_-]*\.H[34]\.\d+)\b")
_FENCE_RE = re.compile(r'^\s*(?:```|~~~)')


def _source_ref(document: Any, line: int, fragment: str, section_path: list[str] | None = None) -> dict:
    ref = {
        'relative_path': str(document.relative_path),
        'line_range': {'start': line, 'end': line},
        'fragment': fragment,
    }
    if section_path:
        ref['section_path'] = list(section_path)
    return ref


def _artifact_kind(document: Any) -> tuple[str, str, float, str]:
    path = Path(document.path)
    parts = {part.casefold() for part in path.parts}
    name = path.name.casefold()
    if getattr(document, 'input_kind', 'text') == 'code':
        return 'source_code', 'source_code', 1.0, 'input_kind:code'
    if name == 'agents.md' or '.claude' in parts or '.github' in parts and 'agents' in parts:
        return 'governance', 'constitutional_rules', 1.0, 'path:governance'
    if name == 'readme.md':
        return 'readme', 'navigation_or_usage', 1.0, 'filename:README.md'
    if '.manifest' in parts:
        return 'normative_manifest', 'normative_policy', 1.0, 'path:.manifest'
    if '.requirements' in parts:
        return 'specification', 'procedure_template', 1.0, 'path:.requirements'
    if '.approach' in parts:
        return 'methodology', 'methodology_or_pattern', 1.0, 'path:.approach'
    if '.tasks' in parts:
        return 'task', 'work_plan', 1.0, 'path:.tasks'
    if '.issues' in parts:
        return 'issue', 'problem_record', 1.0, 'path:.issues'
    if 'docs' in parts:
        return 'project_result', 'project_facts_and_decisions', 0.9, 'path:docs'
    if '.source' in parts:
        return 'unstructured_source', 'unstructured_material', 1.0, 'path:.source'
    return 'unstructured_source', 'unstructured_material', 0.5, 'fallback:unknown_path'


def _section_role(artifact_kind: str, heading: str, level: int) -> tuple[str, str | None]:
    match = _RULE_ID_RE.search(heading)
    rule_id = match.group('id') if match else None
    if artifact_kind == 'normative_manifest':
        if rule_id and '.H3.' in rule_id:
            return 'policy', rule_id
        if rule_id and '.H4.' in rule_id:
            return 'standard', rule_id
        return 'manifest_title' if level == 1 else 'manifest_context', rule_id
    if artifact_kind == 'specification':
        if level == 1:
            return 'specification', rule_id
        if level == 2:
            return 'procedure', rule_id
        return 'procedure_description', rule_id
    if artifact_kind == 'task':
        return 'task_section', rule_id
    if artifact_kind == 'issue':
        return 'issue_section', rule_id
    if artifact_kind == 'methodology':
        return 'methodology_section', rule_id
    if artifact_kind == 'readme':
        return 'readme_section', rule_id
    if artifact_kind == 'governance':
        return 'governance_rule', rule_id
    return 'content_section', rule_id


def build_artifact_profile(document: Any) -> dict:
    """Возвращает профиль артефакта без извлечения семантических утверждений."""
    artifact_kind, narrative_style, confidence, rationale = _artifact_kind(document)
    profile = {
        'relative_path': str(document.relative_path),
        'artifact_kind': artifact_kind,
        'narrative_style': narrative_style,
        'confidence': confidence,
        'rationale': rationale,
        'source_ref': _source_ref(document, 1, str(document.title or document.relative_path)),
        'section_profiles': [],
        'rule_ids': [],
        'rule_references': [],
    }
    source_text = str(document.text)
    formalization_profile = profile_for_source(
        input_kind=str(getattr(document, 'input_kind', 'text')),
        artifact_kind=artifact_kind,
    )
    profile['formalization_profile'] = profile_summary(formalization_profile)
    if artifact_kind == 'unstructured_source' and '#' not in source_text:
        return profile
    stack: list[tuple[int, str]] = []
    in_fence = False
    for line_number, line in enumerate(source_text.splitlines(), start=1):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _HEADING_RE.match(line)
        if not match:
            continue
        level = len(match.group('marks'))
        heading = match.group('heading').strip()
        while stack and stack[-1][0] >= level:
            stack.pop()
        section_path = [value for _, value in stack] + [heading]
        role, rule_id = _section_role(artifact_kind, heading, level)
        section = {
            'role': role,
            'level': level,
            'heading': heading,
            'section_path': section_path,
            'source_ref': _source_ref(document, line_number, line, section_path),
        }
        if rule_id:
            section['rule_id'] = rule_id
            profile['rule_ids'].append(rule_id)
        profile['section_profiles'].append(section)
        stack.append((level, heading))
    known = set(profile['rule_ids'])
    in_fence = False
    for line_number, line in enumerate(source_text.splitlines(), start=1):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for match in _RULE_ID_RE.finditer(line):
            rule_id = match.group('id')
            if rule_id not in known:
                profile['rule_references'].append({
                    'rule_id': rule_id,
                    'source_ref': _source_ref(document, line_number, line),
                })
    return profile


def is_normative_manifest(profile: dict) -> bool:
    return profile.get('artifact_kind') == 'normative_manifest'
