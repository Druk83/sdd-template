
"""Детерминированные логические и контекстные диагностики ASIR."""
from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence

ARRAYS = ('goals', 'entities', 'attributes', 'facts', 'states', 'events', 'actions', 'transitions', 'conditions', 'constraints', 'invariants', 'dependencies', 'decisions', 'exceptions', 'assumptions', 'gaps')
STRUCTURAL_RULES = ('STR-001', 'STR-002')
LOGIC_RULES = ('LGC-001', 'LGC-002', 'LGC-003')
DEONTIC_RULES = ('DNT-001', 'DNT-002', 'DNT-003', 'DNT-004')
ARGUMENT_RULES = ('ARG-001',)
DEFINITION_RULES = ('DEF-001', 'DEF-002')
LEGACY_RULES = ('LOG-001', 'LOG-002', 'LOG-003', 'LOG-004', 'LOG-005', 'LOG-006', 'LOG-007', 'LOG-008', 'POL-001', 'POL-002', 'POL-003', 'POL-004')
RULE_ORDER = STRUCTURAL_RULES + LOGIC_RULES + DEONTIC_RULES + ARGUMENT_RULES + DEFINITION_RULES + LEGACY_RULES
NEGATION_RE = re.compile(r'\b(?:не|not|forbidden|cannot)\b', re.IGNORECASE)
ARROW_RE = re.compile(r'(?P<left>[A-Za-z\u0400-\u04ff][\w\u0400-\u04ff ._-]{0,80}?)\s*(?:->|=>)\s*(?P<right>[A-Za-z\u0400-\u04ff][\w\u0400-\u04ff ._-]{0,80})')
UNDEFINED_MARKER_RE = re.compile(r'(?<!@)\b(?:TBD|TODO|FIXME)\b|\?\?\?|\[\?\]', re.IGNORECASE)
MARKER_PROHIBITION_RE = re.compile(r'\b(?:не\s+(?:оставляй|оставлять|используй|использовать|допускай|допускать)|(?:do\s+not|must\s+not)\s+(?:leave|use))\b', re.IGNORECASE)
POLICY_ACTION_RE = re.compile(
    r'\b(?:сообщи|проверь|выполни|обнови|создай|добавь|убеди|найди|прочитай|дождись|'
    r'используй|применяй|показывай|указывай|разделяй|выведи|формируй|зафиксируй)\w*\b',
    re.IGNORECASE,
)
EXPLICIT_DEFINITION_RE = re.compile(
    r'^\s*(?!(?:найти|создать|проверить|используй|примени|добавь|удали|сформируй|'
    r'find|create|check|use|apply|add|delete|generate)\b)'
    r'(?P<term>[A-Za-zА-Яа-яЁё][\wА-Яа-яЁё _-]{0,80}?)'
    r'(?:\s*(?:—|-|:)\s*(?:это|означает|называется|определяется\s+как)\s+'
    r'|\s+(?:means|is\s+defined\s+as)\s+)'
    r'(?P<body>.+?)\s*[.!]?$',
    re.IGNORECASE,
)


def _normalize(value: str) -> str:
    return re.sub(r'\s+', ' ', value.casefold()).strip(' .;:-')


def _without_negation(value: str) -> str:
    return _normalize(NEGATION_RE.sub(' ', value))


def _is_negative(value: str) -> bool:
    return bool(NEGATION_RE.search(value))


def _items(model: Mapping) -> list[dict]:
    result = []
    for name in ARRAYS:
        values = model.get(name, [])
        if isinstance(values, list):
            result.extend(item for item in values if isinstance(item, dict) and item.get('text'))
    return result


def _refs(items: list[dict]) -> list[dict]:
    return [item.get('source_ref', {}) for item in items if item.get('source_ref')]


def _finding(index: int, rule_id: str, message: str, refs: list[dict], severity: str = 'warning', status: str = 'REVIEW_REQUIRED') -> dict:
    evidence = []
    seen = set()
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        line_range = ref.get('line_range') or {}
        key = (ref.get('relative_path'), line_range.get('start'), line_range.get('end'))
        if key not in seen:
            seen.add(key)
            evidence.append(ref)
    return {'id': f'finding-{index:03d}', 'rule_id': rule_id, 'message': message, 'severity': severity, 'status': status, 'confidence': 1.0, 'source_ref': evidence[0] if evidence else {}, 'evidence': evidence}


def _contradictions(items, add):
    grouped = defaultdict(list)
    for item in items:
        grouped[_without_negation(item.get('text', ''))].append(item)
    for base, values in sorted(grouped.items()):
        if base and len(values) > 1 and any(_is_negative(x.get('text', '')) for x in values) and any(not _is_negative(x.get('text', '')) for x in values):
            add('LOG-001', 'Contradictory statements detected for: ' + base, values)


def _incompatible_conditions(items, add):
    grouped = defaultdict(list)
    pattern = re.compile(r'(.+?)\s+(?:only|только)\s+([^.;]+)', re.IGNORECASE)
    for item in items:
        match = pattern.search(_normalize(item.get('text', '')))
        if match:
            grouped[match.group(1).strip()].append((match.group(2).strip(), item))
    for subject, values in sorted(grouped.items()):
        choices = {choice for choice, _ in values}
        if len(choices) > 1:
            add('LOG-002', 'Incompatible conditions for ' + subject + ': ' + ', '.join(sorted(choices)), [item for _, item in values])


def _dependency_cycles(items, add):
    graph = defaultdict(set)
    owners = defaultdict(list)
    for item in items:
        match = ARROW_RE.search(item.get('text', ''))
        if match:
            left, right = _normalize(match.group('left')), _normalize(match.group('right'))
            graph[left].add(right)
            owners[(left, right)].append(item)
    visiting, visited = set(), set()

    def visit(node, path):
        if node in visiting:
            cycle = path[path.index(node):] + [node]
            refs = [ref for edge, values in owners.items() if edge[0] in cycle and edge[1] in cycle for ref in _refs(values)]
            add('LOG-004', 'Dependency cycle detected: ' + ' -> '.join(cycle), refs)
            return
        if node in visited:
            return
        visiting.add(node)
        for child in sorted(graph.get(node, ())):
            visit(child, path + [node])
        visiting.remove(node)
        visited.add(node)

    for node in sorted(graph):
        visit(node, [])


def _dependency_shape(items, add):
    for item in items:
        text = item.get('text', '')
        if '->' not in text and '=>' not in text:
            add('LOG-003', 'Dependency has no explicit relation: ' + text, [item])


def _undefined_markers(items, add):
    for item in items:
        text = item.get('text', '')
        if UNDEFINED_MARKER_RE.search(text) and not MARKER_PROHIBITION_RE.search(text):
            add('LOG-007', 'Undefined marker requires review: ' + text, [item])


_CLARIFICATION_MARKERS = {'требует уточнения'}


def _undefined_terms(items, add):
    defined = {_normalize(item.get('text', '')) for item in items if item.get('type') in {'entity', 'attribute'}}
    for item in items:
        text = item.get('text', '')
        for match in re.finditer(r'\[\[([^\]]+)\]\]', text):
            term = _normalize(match.group(1))
            if term and term not in defined and term not in _CLARIFICATION_MARKERS:
                add('LOG-005', 'Undefined term referenced: ' + match.group(1), [item])


def _duplicates(items, add):
    grouped = defaultdict(list)
    for item in items:
        if item.get('type') == 'gap':
            continue
        grouped[_normalize(item.get('text', ''))].append(item)
    for text, values in sorted(grouped.items()):
        if text and len(values) > 1:
            add('LOG-008', 'Duplicate statements detected: ' + text, values, severity='info', status='auto_decided')


def _normative_profiles(model: Mapping) -> list[dict]:
    profiles = model.get('artifact_profiles', [])
    if not isinstance(profiles, list):
        return []
    return [item for item in profiles if isinstance(item, dict) and item.get('artifact_kind') == 'normative_manifest']


def _policy_has_standard(policy: Mapping, standards: Sequence[Mapping], next_policy_line: int | None) -> bool:
    policy_line = ((policy.get('source_ref') or {}).get('line_range') or {}).get('start', 0)
    for standard in standards:
        standard_line = ((standard.get('source_ref') or {}).get('line_range') or {}).get('start', 0)
        if standard_line > policy_line and (next_policy_line is None or standard_line < next_policy_line):
            return True
    return False


def _policy_structure(model: Mapping, add) -> None:
    actions = model.get('actions', [])
    action_items = [item for item in actions if isinstance(item, Mapping) and str(item.get('extraction_method', '')).startswith('normative_')] if isinstance(actions, list) else []

    def has_explicit_action(policy: Mapping) -> bool:
        policy_ref = policy.get('source_ref')
        policy_path = policy_ref.get('relative_path') if isinstance(policy_ref, Mapping) else None
        policy_section = tuple(policy_ref.get('section_path', [])) if isinstance(policy_ref, Mapping) and isinstance(policy_ref.get('section_path'), list) else ()
        for action in action_items:
            action_ref = action.get('source_ref')
            if not isinstance(action_ref, Mapping) or action_ref.get('relative_path') != policy_path:
                continue
            action_section = action_ref.get('section_path')
            if isinstance(action_section, list) and tuple(action_section)[:len(policy_section)] == policy_section:
                return True
        return False

    for profile in _normative_profiles(model):
        sections = profile.get('section_profiles', [])
        if not isinstance(sections, list):
            continue
        policies = [item for item in sections if isinstance(item, dict) and item.get('role') == 'policy']
        standards = [item for item in sections if isinstance(item, dict) and item.get('role') == 'standard']
        policies.sort(key=lambda item: ((item.get('source_ref') or {}).get('line_range') or {}).get('start', 0))
        for index, policy in enumerate(policies):
            next_line = None
            if index + 1 < len(policies):
                next_line = ((policies[index + 1].get('source_ref') or {}).get('line_range') or {}).get('start')
            if not _policy_has_standard(policy, standards, next_line) and not has_explicit_action(policy):
                add('POL-001', 'Policy has no linked standard or explicit action: ' + str(policy.get('heading', '')), [policy])


def _policy_structure_format(model: Mapping, add) -> None:
    for profile in _normative_profiles(model):
        sections = profile.get('section_profiles', [])
        if not isinstance(sections, list):
            continue
        titles = [item for item in sections if isinstance(item, dict) and item.get('role') == 'manifest_title']
        if not titles or not re.search(r'\(\s*H2\s*\)\s*$', str(titles[0].get('heading', '')), re.IGNORECASE):
            add('POL-004', 'Manifest title must declare hierarchy level H2.', [profile])
        seen_rule_ids: set[str] = set()
        for section in sections:
            if not isinstance(section, dict):
                continue
            if section.get('role') == 'manifest_context' and int(section.get('level', 0)) >= 3:
                add('POL-004', 'Manifest H3/H4 section must use a policy or standard identifier: ' + str(section.get('heading', '')), [section])
            rule_id = section.get('rule_id')
            if isinstance(rule_id, str) and rule_id:
                if rule_id in seen_rule_ids:
                    add('POL-004', 'Manifest rule identifier is duplicated: ' + rule_id, [section])
                seen_rule_ids.add(rule_id)

def _policy_conditions(model: Mapping, add) -> None:
    actions = [item for item in model.get('actions', []) if isinstance(item, dict) and str(item.get('extraction_method', '')).startswith('normative_')] if isinstance(model.get('actions', []), list) else []
    reference_blocks = model.get('reference_blocks', [])
    references = [item for item in reference_blocks if isinstance(item, Mapping)] if isinstance(reference_blocks, list) else []
    for condition in model.get('conditions', []):
        if not isinstance(condition, dict) or not str(condition.get('extraction_method', '')).startswith('normative_'):
            continue
        ref = condition.get('source_ref') or {}
        path = ref.get('relative_path')
        section_path = ref.get('section_path')
        has_action = any((action.get('source_ref') or {}).get('relative_path') == path and (action.get('source_ref') or {}).get('section_path') == section_path for action in actions)
        has_template = any((block.get('source_ref') or {}).get('relative_path') == path and (block.get('source_ref') or {}).get('section_path') == section_path for block in references)
        if not has_action and not has_template and not POLICY_ACTION_RE.search(str(condition.get('text', ''))):
            add('POL-002', 'Normative condition has no prescribed action: ' + str(condition.get('text', '')), [condition])


def _policy_references(model: Mapping, add) -> None:
    known_rule_ids = {
        rule_id
        for profile in _normative_profiles(model)
        for rule_id in profile.get('rule_ids', [])
        if isinstance(rule_id, str) and rule_id
    }
    for profile in _normative_profiles(model):
        for reference in profile.get('rule_references', []):
            if isinstance(reference, dict):
                rule_id = str(reference.get('rule_id', ''))
                if rule_id and rule_id not in known_rule_ids:
                    add('POL-003', 'Reference to an unavailable manifest rule: ' + rule_id, [reference])



def _role_text(proposition: Mapping, name: str) -> str | None:
    value = proposition.get(name)
    text = value.get('text') if isinstance(value, Mapping) else None
    return _normalize(text) if isinstance(text, str) and text.strip() else None


def _expression_index(model: Mapping) -> dict[str, dict]:
    values = model.get('logical_expressions', [])
    return {str(item['id']): item for item in values if isinstance(item, dict) and isinstance(item.get('id'), str)} if isinstance(values, list) else {}


def _operand_signature(operand: Mapping, expressions: Mapping[str, Mapping], seen: set[str] | None = None) -> str:
    if operand.get('kind') == 'atom':
        return _normalize(str(operand.get('text', '')))
    expression_id = operand.get('expression_id')
    if operand.get('kind') != 'expression' or not isinstance(expression_id, str) or expression_id in (seen or set()):
        return ''
    expression = expressions.get(expression_id)
    if not isinstance(expression, Mapping):
        return ''
    return _expression_signature(expression, expressions, (seen or set()) | {expression_id})


def _expression_signature(expression: Mapping, expressions: Mapping[str, Mapping], seen: set[str] | None = None) -> str:
    operands = expression.get('operands', [])
    values = [_operand_signature(item, expressions, seen) for item in operands if isinstance(item, Mapping)] if isinstance(operands, list) else []
    return str(expression.get('operator', '')) + '(' + ','.join(values) + ')'


def _expression_atoms(operand: Mapping, expressions: Mapping[str, Mapping]) -> list[str]:
    if operand.get('kind') == 'atom':
        text = operand.get('text')
        return [str(text)] if isinstance(text, str) and text.strip() else []
    expression = expressions.get(str(operand.get('expression_id'))) if operand.get('kind') == 'expression' else None
    if not isinstance(expression, Mapping):
        return []
    operands = expression.get('operands', [])
    atoms = [atom for child in operands if isinstance(child, Mapping) for atom in _expression_atoms(child, expressions)] if isinstance(operands, list) else []
    return ['не ' + atom for atom in atoms] if expression.get('operator') == 'NOT' and atoms else atoms


def _structural_checks(model: Mapping, add) -> None:
    normative_paths = {str(profile.get('relative_path')) for profile in _normative_profiles(model) if isinstance(profile.get('relative_path'), str)}
    propositions = model.get('propositions', [])
    if isinstance(propositions, list):
        for proposition in propositions:
            if not isinstance(proposition, Mapping) or proposition.get('type') != 'norm':
                continue
            missing = [name for name in ('subject', 'predicate') if _role_text(proposition, name) is None]
            ref = proposition.get('source_ref')
            path = ref.get('relative_path') if isinstance(ref, Mapping) else None
            if missing == ['subject'] and path in normative_paths:
                continue
            if missing:
                add('STR-001', 'Norm has no explicit ' + ' and '.join(missing) + '.', [proposition])
    for expression in _expression_index(model).values():
        alternatives = expression.get('alternatives')
        if expression.get('status') == 'review_required' or isinstance(alternatives, list) and alternatives:
            add('STR-002', 'Logical connector requires human choice: ' + str(expression.get('operator', 'unknown')) + '.', [expression])


def _logical_expression_checks(model: Mapping, add) -> None:
    expressions = _expression_index(model)
    for expression in expressions.values():
        operator = expression.get('operator')
        operands = expression.get('operands', [])
        if operator in {'IMPLIES', 'IFF'} and (not isinstance(operands, list) or len(operands) != 2):
            add('LGC-003', 'Logical relation requires exactly two operands: ' + str(operator) + '.', [expression], severity='error')
            continue
        if not isinstance(operands, list):
            continue
        signatures = [_operand_signature(item, expressions) for item in operands if isinstance(item, Mapping)]
        if operator == 'XOR' and len(signatures) == 2 and signatures[0] and signatures[0] == signatures[1]:
            add('LGC-002', 'XOR contains two identical branches.', [expression], severity='error')
        if operator == 'AND':
            atoms = [atom for operand in operands if isinstance(operand, Mapping) for atom in _expression_atoms(operand, expressions)]
            normalize_atom = lambda value: re.sub(r'^(?:both|одновременно)\s+', '', _without_negation(value), flags=re.IGNORECASE)
            positive = {normalize_atom(value) for value in atoms if not _is_negative(value)}
            negative = {normalize_atom(value) for value in atoms if _is_negative(value)}
            overlap = sorted(value for value in positive & negative if value)
            if overlap:
                add('LGC-001', 'AND contains incompatible branches: ' + ', '.join(overlap) + '.', [expression], severity='error')


def _normative_scope_checks(model: Mapping, add) -> None:
    scopes = model.get('normative_scopes', [])
    if not isinstance(scopes, list):
        return
    for scope in scopes:
        if not isinstance(scope, Mapping) or scope.get('modality') != 'PROHIBITION':
            continue
        heading_ref = scope.get('source_ref')
        items = scope.get('items', [])
        if not isinstance(heading_ref, dict) or not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, Mapping) or item.get('negated') is not True:
                continue
            item_ref = item.get('source_ref')
            text = str(item.get('text', '')).strip()
            if not isinstance(item_ref, dict) or not text:
                continue
            action = re.sub(r'^\s*(?:\u043d\u0435|not)\s+', '', text, flags=re.IGNORECASE).strip(' .;:')
            message = (
                'Normative heading PROHIBITION combined with a negated list item is ambiguous: '
                + 'PROHIBITION(NOT ' + action + ') may permit ' + action + '.'
            )
            add('DNT-004', message, [
                {'id': str(scope.get('id', 'normative-scope')), 'type': 'normative_scope', 'source_ref': heading_ref},
                {'id': str(scope.get('id', 'normative-scope')) + '-item', 'type': 'normative_item', 'source_ref': item_ref},
            ])


def _deontic_checks(model: Mapping, add) -> None:
    propositions = model.get('propositions', [])
    if not isinstance(propositions, list):
        return
    expressions = _expression_index(model)
    norms = [item for item in propositions if isinstance(item, Mapping) and item.get('type') == 'norm']
    for proposition in norms:
        if proposition.get('violation') is not None and proposition.get('sanction') is None and proposition.get('consequence') is None:
            add('DNT-003', 'Violation has no explicit consequence or sanction.', [proposition])
    grouped: dict[tuple[str, str, str, str], list[Mapping]] = defaultdict(list)
    for proposition in norms:
        subject, predicate = _role_text(proposition, 'subject'), _role_text(proposition, 'predicate')
        obj = _role_text(proposition, 'object') or ''
        condition = proposition.get('condition')
        expression_id = condition.get('expression_id') if isinstance(condition, Mapping) else None
        signature = _expression_signature(expressions[expression_id], expressions) if isinstance(expression_id, str) and expression_id in expressions else ''
        if subject and predicate:
            grouped[(subject, predicate, obj, signature)].append(proposition)
    for values in grouped.values():
        modalities = {str(item.get('modality')) for item in values}
        if 'PROHIBITION' not in modalities or not ({'OBLIGATION', 'PERMISSION'} & modalities):
            continue
        rule = 'DNT-001' if 'OBLIGATION' in modalities else 'DNT-002'
        add(rule, 'Deontic conflict for subject/action/object under the same explicit condition.', list(values), severity='error')
        priorities = {_role_text(item, 'priority') for item in values if _role_text(item, 'priority')}
        if len(priorities) > 1:
            add('DNT-003', 'Conflicting rules declare different explicit priorities; human review is required.', list(values))


def _argument_checks(model: Mapping, add) -> None:
    values = model.get('propositions', [])
    if not isinstance(values, list):
        return
    for proposition in values:
        if not isinstance(proposition, Mapping) or proposition.get('type') != 'argument':
            continue
        ref = proposition.get('source_ref')
        text = str(ref.get('fragment', '')) if isinstance(ref, Mapping) else ''
        if re.search(r'\b(?:следовательно|therefore|thus|hence)\b', text, re.IGNORECASE) and not re.search(r'\b(?:так как|поскольку|because|since)\b', text, re.IGNORECASE):
            add('ARG-001', 'Argument conclusion has no explicit premise in the same statement.', [proposition])


def _definition_parts(text: str) -> tuple[str, str] | None:
    match = EXPLICIT_DEFINITION_RE.match(text)
    if match is None:
        return None
    term, body = _normalize(match.group('term')), _normalize(match.group('body'))
    return (term, body) if term and body else None


def _definition_checks(model: Mapping, add) -> None:
    values = model.get('propositions', [])
    if not isinstance(values, list):
        return
    definitions: dict[str, list[tuple[str, Mapping]]] = defaultdict(list)
    for proposition in values:
        if not isinstance(proposition, Mapping) or proposition.get('type') != 'definition':
            continue
        ref = proposition.get('source_ref')
        parts = _definition_parts(str(ref.get('fragment', ''))) if isinstance(ref, Mapping) else None
        if parts is None:
            add('DEF-001', 'Definition has no explicit defined term and body.', [proposition])
        else:
            definitions[parts[0]].append((parts[1], proposition))
    for term, entries in sorted(definitions.items()):
        if len({body for body, _ in entries}) > 1:
            add('DEF-002', 'Definition has conflicting explicit bodies: ' + term + '.', [item for _, item in entries])
def run_logical_checks(model: Mapping) -> tuple[list[dict], list[dict]]:
    items = _items(model)
    findings = []

    def add(rule_id, message, values, severity='warning', status='REVIEW_REQUIRED'):
        refs = []
        for value in values:
            if isinstance(value, dict) and value.get('source_ref'):
                refs.append(value['source_ref'])
            elif isinstance(value, dict) and value.get('relative_path'):
                refs.append(value)
        finding = _finding(len(findings) + 1, rule_id, message, refs, severity, status)
        participants = []
        for value in values:
            if not isinstance(value, Mapping) or not isinstance(value.get('id'), str):
                continue
            if value.get('type') == 'norm':
                participants.append({
                    'id': value['id'], 'kind': 'proposition', 'type': 'norm',
                    'subject': _role_text(value, 'subject'), 'predicate': _role_text(value, 'predicate'),
                    'object': _role_text(value, 'object'), 'modality': value.get('modality'),
                    'condition': value.get('condition'), 'priority': _role_text(value, 'priority'),
                })
            elif 'operator' in value:
                participants.append({'id': value['id'], 'kind': 'logical_expression', 'operator': value.get('operator'), 'status': value.get('status'), 'alternatives': value.get('alternatives', [])})
            else:
                participants.append({'id': value['id'], 'kind': 'proposition', 'type': value.get('type')})
        if participants:
            finding['participants'] = participants
        findings.append(finding)

    _contradictions(items, add)
    _incompatible_conditions([x for x in items if x.get('type') in ('condition', 'constraint')], add)
    _dependency_cycles([x for x in items if x.get('type') == 'dependency'], add)
    _dependency_shape([x for x in items if x.get('type') == 'dependency'], add)
    _undefined_markers(items, add)
    _undefined_terms(items, add)
    _duplicates(items, add)
    _structural_checks(model, add)
    _logical_expression_checks(model, add)
    _deontic_checks(model, add)
    _normative_scope_checks(model, add)
    _argument_checks(model, add)
    _definition_checks(model, add)
    _policy_structure(model, add)
    _policy_structure_format(model, add)
    _policy_conditions(model, add)
    _policy_references(model, add)
    findings.sort(key=lambda x: (RULE_ORDER.index(x['rule_id']), x['message']))
    for index, finding in enumerate(findings, 1):
        finding['id'] = f'finding-{index:03d}'
    by_rule = defaultdict(list)
    for finding in findings:
        by_rule[finding['rule_id']].append(finding['id'])
    checks = [{'rule_id': rule, 'status': 'findings' if rule in by_rule else 'passed', 'finding_ids': by_rule.get(rule, [])} for rule in RULE_ORDER]
    return findings, checks
