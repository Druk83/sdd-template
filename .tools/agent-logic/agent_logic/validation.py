"""ASIR schema and provenance validation."""

from __future__ import annotations

import re
from collections.abc import Mapping

from .proof_contract import PROOF_STATUSES, validate_evidence_record, validate_formal_claim, validate_formal_model, validate_hypothesis, validate_proof_explanation
from functools import lru_cache

ARRAYS = (
    "goals", "entities", "attributes", "facts", "states", "events", "actions",
    "transitions", "conditions", "constraints", "invariants", "dependencies",
    "decisions", "exceptions", "assumptions", "gaps",
)
SINGULAR = {
    "goals": "goal", "entities": "entity", "attributes": "attribute", "facts": "fact",
    "states": "state", "events": "event", "actions": "action", "transitions": "transition",
    "conditions": "condition", "constraints": "constraint", "invariants": "invariant",
    "dependencies": "dependency", "decisions": "decision", "exceptions": "exception",
    "assumptions": "assumption", "gaps": "gap",
}
ALLOWED_STATUS = {
    "confirmed", "inferred", "assumed", "observed", "approved", "rejected",
    "deprecated", "gap", "REVIEW_REQUIRED", "BLOCKED",
}
PROPOSITION_TYPES = {
    'norm', 'fact', 'causal', 'argument', 'definition', 'question', 'example',
    'narrative', 'opinion_or_hypothesis', 'forecast', 'unclassified',
}
STRUCTURAL_STATUS = {'confirmed', 'review_required', 'gap'}
DEONTIC_MODALITIES = {'OBLIGATION', 'PERMISSION', 'PROHIBITION'}
LOGICAL_OPERATORS = {'AND', 'OR', 'XOR', 'NOT', 'IMPLIES', 'IFF', 'ALL', 'EXISTS'}
PROPOSITION_ROLE_FIELDS = ('subject', 'predicate', 'object', 'constraint', 'consequence', 'violation', 'sanction', 'priority')
PROPOSITION_FIELDS = (
    'id', 'type', 'subject', 'predicate', 'object', 'constraint', 'modality', 'condition',
    'exceptions', 'consequence', 'violation', 'sanction', 'priority',
    'logical_expression', 'source_ref', 'evidence', 'extraction_method',
    'confidence', 'status',
)
ALLOWED_MODELS = {
    "state_machine", "decision_table", "dependency_graph",
    "constraint_model", "policy_model", "hybrid",
}
AMBIGUITY_RE = re.compile(
    r"(?:неоднознач\w*|неясн\w*|неопредел\w*|не указ\w*|непол\w*|"
    r"требует уточ\w*|нужно уточ\w*|\bвозможно\b|"
    r"\bвозможн(?:ое|ый|ая|ые)\b|\bambiguous\b|"
    r"\bunclear\b|\buncertain\b|\bunspecified\b|\bincomplete\b|"
    r"\bpossibly\b|\btbd\b|\?\?\?|\[\?\])",
    re.IGNORECASE,
)
REFERENCE_AMBIGUITY_PHRASES = (
    "неразрешенная неоднозначность", "неразрешенная неоднозначность",
    "состояние неопределенности", "состояние неопределенности",
    "и неоднозначности", "для неоднозначных фрагментов",
    "неподтвержденная неоднозначность",
)


@lru_cache(maxsize=4096)
def _contains_ambiguity(text: str) -> bool:
    normalized = text.casefold().replace("ё", "е")
    if any(phrase in normalized for phrase in REFERENCE_AMBIGUITY_PHRASES):
        return False
    return bool(AMBIGUITY_RE.search(text))


def _issue(
    issue_type: str,
    message: str,
    *,
    evidence=None,
    source_ref=None,
    confidence=None,
    severity: str = "error",
) -> dict:
    return {
        "issue_type": issue_type,
        "message": message,
        "evidence": evidence or [],
        "source_ref": source_ref or [],
        "confidence": confidence,
        "severity": severity,
    }


def _number_in_range(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1


def _validate_line_range(value: object, location: str) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, dict):
        return [_issue("invalid_line_range", f"{location} line_range must be an object or null")]
    start = value.get("start")
    end = value.get("end")
    if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start:
        return [_issue("invalid_line_range", f"{location} line_range must contain valid start/end values")]
    return []


def _validate_source(source: object, index: int) -> list[dict]:
    location = f"sources[{index}]"
    if not isinstance(source, dict):
        return [_issue("invalid_source", f"{location} must be an object")]
    issues: list[dict] = []
    relative_path = source.get("relative_path")
    if not isinstance(relative_path, str) or not relative_path:
        issues.append(_issue("missing_source_path", f"{location} has no relative_path"))
    if source.get("encoding") != "UTF-8":
        issues.append(_issue("invalid_encoding", f"{location} encoding must be UTF-8"))
    issues.extend(_validate_line_range(source.get("line_range"), location))
    if not isinstance(source.get("fragment"), str):
        issues.append(_issue("missing_source_fragment", f"{location} fragment must be a string"))
    if not isinstance(source.get("extraction_method"), str) or not source.get("extraction_method"):
        issues.append(_issue("missing_extraction_method", f"{location} has no extraction_method"))
    if not _number_in_range(source.get("confidence")):
        issues.append(_issue("invalid_confidence", f"{location} confidence must be between 0 and 1"))
    return issues


def _validate_ref(ref: object, location: str, source_paths: set[str]) -> list[dict]:
    if not isinstance(ref, dict):
        return [_issue("missing_provenance", f"{location} must be an object")]
    issues: list[dict] = []
    relative_path = ref.get("relative_path")
    if not isinstance(relative_path, str) or not relative_path:
        issues.append(_issue("missing_provenance", f"{location} has no relative_path"))
    elif relative_path not in source_paths:
        issues.append(_issue("broken_provenance", f"{location} references an unknown source"))
    issues.extend(_validate_line_range(ref.get("line_range"), location))
    if not isinstance(ref.get("fragment"), str):
        issues.append(_issue("invalid_provenance", f"{location} fragment must be a string"))
    section_path = ref.get('section_path')
    if section_path is not None and (
        not isinstance(section_path, list)
        or not section_path
        or any(not isinstance(value, str) or not value.strip() for value in section_path)
    ):
        issues.append(_issue('invalid_provenance', f'{location} section_path must be a non-empty array of strings'))
    return issues

def _validate_findings(model: Mapping, source_paths: set[str]) -> list[dict]:
    findings = model.get('findings', [])
    if not isinstance(findings, list):
        return [_issue('invalid_collection', 'findings must be an array')]
    issues = []
    seen = set()
    allowed_severity = {'info', 'warning', 'error'}
    allowed_status = {'diagnostic', 'REVIEW_REQUIRED', 'auto_decided', 'approved', 'rejected', 'BLOCKED'}
    for index, finding in enumerate(findings):
        location = f'findings[{index}]'
        if not isinstance(finding, dict):
            issues.append(_issue('invalid_finding', f'{location} must be an object'))
            continue
        finding_id = finding.get('id')
        if not isinstance(finding_id, str) or not finding_id:
            issues.append(_issue('missing_finding_id', f'{location} has no id'))
        elif finding_id in seen:
            issues.append(_issue('duplicate_finding_id', f'duplicate finding id: {finding_id}'))
        else:
            seen.add(finding_id)
        if not isinstance(finding.get('rule_id'), str) or not finding.get('rule_id'):
            issues.append(_issue('missing_rule_id', f'{location} has no rule_id'))
        if not isinstance(finding.get('message'), str) or not finding.get('message'):
            issues.append(_issue('invalid_finding_message', f'{location} message must be non-empty'))
        if finding.get('severity') not in allowed_severity:
            issues.append(_issue('invalid_finding_severity', f'{location} has unsupported severity'))
        if finding.get('status') not in allowed_status:
            issues.append(_issue('invalid_finding_status', f'{location} has unsupported status'))
        if not _number_in_range(finding.get('confidence')):
            issues.append(_issue('invalid_confidence', f'{location} confidence must be between 0 and 1'))
        issues.extend(_validate_ref(finding.get('source_ref'), f'{location}.source_ref', source_paths))
        evidence = finding.get('evidence')
        if not isinstance(evidence, list) or not evidence:
            issues.append(_issue('missing_finding_evidence', f'{location} evidence must be non-empty'))
        else:
            for evidence_index, ref in enumerate(evidence):
                issues.extend(_validate_ref(ref, f'{location}.evidence[{evidence_index}]', source_paths))
    checks = model.get('checks', [])
    if not isinstance(checks, list):
        issues.append(_issue('invalid_collection', 'checks must be an array'))
    else:
        for index, check in enumerate(checks):
            if not isinstance(check, dict) or not isinstance(check.get('rule_id'), str) or check.get('status') not in {'passed', 'findings'} or not isinstance(check.get('finding_ids'), list):
                issues.append(_issue('invalid_check', f'checks[{index}] has invalid structure'))
    return issues


def _validate_classification_proposals(model: Mapping, source_paths: set[str]) -> list[dict]:
    values = model.get('classification_proposals', [])
    if not isinstance(values, list):
        return [_issue('invalid_collection', 'classification_proposals must be an array')]
    issues = []
    seen_ids = set()
    for index, proposal in enumerate(values):
        location = f'classification_proposals[{index}]'
        if not isinstance(proposal, dict):
            issues.append(_issue('invalid_classification_proposal', f'{location} must be an object'))
            continue
        proposal_id = proposal.get('id')
        if not isinstance(proposal_id, str) or not proposal_id:
            issues.append(_issue('missing_classification_id', f'{location} has no id'))
        elif proposal_id in seen_ids:
            issues.append(_issue('duplicate_classification_id', f'duplicate classification id: {proposal_id}'))
        else:
            seen_ids.add(proposal_id)
        if proposal.get('target') not in ARRAYS or proposal.get('target') == 'gaps':
            issues.append(_issue('invalid_classification_target', f'{location} has unsupported target'))
        if proposal.get('status') not in {'proposed', 'approved', 'rejected'}:
            issues.append(_issue('invalid_classification_status', f'{location} has unsupported status'))
        if not isinstance(proposal.get('text'), str) or not proposal.get('text'):
            issues.append(_issue('invalid_classification_text', f'{location} text must be non-empty'))
        if not _number_in_range(proposal.get('confidence')):
            issues.append(_issue('invalid_confidence', f'{location} confidence must be between 0 and 1'))
        issues.extend(_validate_ref(proposal.get('source_ref'), f'{location}.source_ref', source_paths))
    return issues

def _validate_artifact_profiles(model: Mapping, source_paths: set[str]) -> list[dict]:
    profiles = model.get('artifact_profiles')
    if profiles is None:
        return []
    if not isinstance(profiles, list):
        return [_issue('invalid_collection', 'artifact_profiles must be an array')]
    issues: list[dict] = []
    for index, profile in enumerate(profiles):
        location = f'artifact_profiles[{index}]'
        if not isinstance(profile, Mapping):
            issues.append(_issue('invalid_artifact_profile', f'{location} must be an object'))
            continue
        for field in ('relative_path', 'artifact_kind', 'narrative_style', 'rationale'):
            if not isinstance(profile.get(field), str) or not str(profile.get(field)).strip():
                issues.append(_issue('invalid_artifact_profile', f'{location}.{field} must be a non-empty string'))
        if not _number_in_range(profile.get('confidence')):
            issues.append(_issue('invalid_confidence', f'{location}.confidence must be between 0 and 1'))
        issues.extend(_validate_ref(profile.get('source_ref'), f'{location}.source_ref', source_paths))
        sections = profile.get('section_profiles')
        if not isinstance(sections, list):
            issues.append(_issue('invalid_artifact_profile', f'{location}.section_profiles must be an array'))
        else:
            for section_index, section in enumerate(sections):
                section_location = f'{location}.section_profiles[{section_index}]'
                if not isinstance(section, Mapping):
                    issues.append(_issue('invalid_section_profile', f'{section_location} must be an object'))
                    continue
                if not isinstance(section.get('role'), str) or not section.get('role'):
                    issues.append(_issue('invalid_section_profile', f'{section_location}.role must be a non-empty string'))
                if not isinstance(section.get('level'), int) or not 1 <= section['level'] <= 6:
                    issues.append(_issue('invalid_section_profile', f'{section_location}.level must be in 1..6'))
                if not isinstance(section.get('heading'), str) or not section.get('heading'):
                    issues.append(_issue('invalid_section_profile', f'{section_location}.heading must be a non-empty string'))
                issues.extend(_validate_ref(section.get('source_ref'), f'{section_location}.source_ref', source_paths))
        if not isinstance(profile.get('rule_ids'), list) or not all(isinstance(item, str) and item for item in profile.get('rule_ids', [])):
            issues.append(_issue('invalid_artifact_profile', f'{location}.rule_ids must be an array of strings'))
        formalization_profile = profile.get('formalization_profile')
        if not isinstance(formalization_profile, Mapping):
            issues.append(_issue('invalid_artifact_profile', f'{location}.formalization_profile must be an object'))
        else:
            for field in ('id', 'version', 'provenance'):
                if not isinstance(formalization_profile.get(field), str) or not formalization_profile.get(field):
                    issues.append(_issue('invalid_artifact_profile', f'{location}.formalization_profile.{field} must be a non-empty string'))
            if not isinstance(formalization_profile.get('deductive_premises'), bool):
                issues.append(_issue('invalid_artifact_profile', f'{location}.formalization_profile.deductive_premises must be boolean'))
            if formalization_profile.get('reason') is not None and not isinstance(formalization_profile.get('reason'), str):
                issues.append(_issue('invalid_artifact_profile', f'{location}.formalization_profile.reason must be string or null'))
        references = profile.get('rule_references')
        if not isinstance(references, list):
            issues.append(_issue('invalid_artifact_profile', f'{location}.rule_references must be an array'))
        else:
            for reference_index, reference in enumerate(references):
                reference_location = f'{location}.rule_references[{reference_index}]'
                if not isinstance(reference, Mapping) or not isinstance(reference.get('rule_id'), str) or not reference.get('rule_id'):
                    issues.append(_issue('invalid_artifact_profile', f'{reference_location}.rule_id must be a non-empty string'))
                elif isinstance(reference, Mapping):
                    issues.extend(_validate_ref(reference.get('source_ref'), f'{reference_location}.source_ref', source_paths))
    blocks = model.get('reference_blocks')
    if blocks is None:
        return issues
    if not isinstance(blocks, list):
        issues.append(_issue('invalid_collection', 'reference_blocks must be an array'))
        return issues
    seen_ids: set[str] = set()
    for index, block in enumerate(blocks):
        location = f'reference_blocks[{index}]'
        if not isinstance(block, Mapping):
            issues.append(_issue('invalid_reference_block', f'{location} must be an object'))
            continue
        block_id = block.get('id')
        if not isinstance(block_id, str) or not block_id:
            issues.append(_issue('invalid_reference_block', f'{location}.id must be a non-empty string'))
        elif block_id in seen_ids:
            issues.append(_issue('duplicate_reference_block_id', f'duplicate reference block id: {block_id}'))
        else:
            seen_ids.add(block_id)
        if not isinstance(block.get('type'), str) or not block.get('type'):
            issues.append(_issue('invalid_reference_block', f'{location}.type must be a non-empty string'))
        issues.extend(_validate_ref(block.get('source_ref'), f'{location}.source_ref', source_paths))
        evidence = block.get('evidence')
        if not isinstance(evidence, list) or not evidence:
            issues.append(_issue('missing_evidence', f'{location}.evidence must be a non-empty array'))
        else:
            for evidence_index, ref in enumerate(evidence):
                issues.extend(_validate_ref(ref, f'{location}.evidence[{evidence_index}]', source_paths))
    return issues

def _validate_evidence(value: object, location: str, source_paths: set[str]) -> list[dict]:
    if not isinstance(value, list) or not value:
        return [_issue('missing_evidence', f'{location} must be a non-empty array')]
    issues: list[dict] = []
    for index, ref in enumerate(value):
        issues.extend(_validate_ref(ref, f'{location}[{index}]', source_paths))
    return issues


def _validate_role(value: object, location: str, source_paths: set[str]) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, Mapping):
        return [_issue('invalid_proposition_role', f'{location} must be an object or null')]
    issues: list[dict] = []
    if not isinstance(value.get('text'), str) or not str(value.get('text')).strip():
        issues.append(_issue('invalid_proposition_role', f'{location}.text must be a non-empty string'))
    issues.extend(_validate_ref(value.get('source_ref'), f'{location}.source_ref', source_paths))
    issues.extend(_validate_evidence(value.get('evidence'), f'{location}.evidence', source_paths))
    return issues


def _expression_reference_id(value: object, location: str, issues: list[dict]) -> str | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        issues.append(_issue('invalid_expression_reference', f'{location} must be an object or null'))
        return None
    expression_id = value.get('expression_id')
    if not isinstance(expression_id, str) or not expression_id:
        issues.append(_issue('invalid_expression_reference', f'{location}.expression_id must be a non-empty string'))
        return None
    return expression_id


def _validate_structural_contract(model: Mapping, source_paths: set[str], seen_ids: set[str]) -> list[dict]:
    propositions = model.get('propositions', [])
    expressions = model.get('logical_expressions', [])
    issues: list[dict] = []
    if not isinstance(propositions, list):
        issues.append(_issue('invalid_collection', 'propositions must be an array'))
        propositions = []
    if not isinstance(expressions, list):
        issues.append(_issue('invalid_collection', 'logical_expressions must be an array'))
        expressions = []

    proposition_ids = {
        item.get('id')
        for item in propositions
        if isinstance(item, Mapping) and isinstance(item.get('id'), str) and item.get('id')
    }
    expression_ids = {
        item.get('id')
        for item in expressions
        if isinstance(item, Mapping) and isinstance(item.get('id'), str) and item.get('id')
    }

    for index, proposition in enumerate(propositions):
        location = f'propositions[{index}]'
        if not isinstance(proposition, Mapping):
            issues.append(_issue('invalid_proposition', f'{location} must be an object'))
            continue
        for field in PROPOSITION_FIELDS:
            if field not in proposition:
                issues.append(_issue('missing_proposition_field', f'{location} is missing {field}'))
        proposition_id = proposition.get('id')
        if not isinstance(proposition_id, str) or not proposition_id:
            issues.append(_issue('missing_proposition_id', f'{location}.id must be a non-empty string'))
        elif proposition_id in seen_ids:
            issues.append(_issue('duplicate_id', f'duplicate ASIR element id: {proposition_id}'))
        else:
            seen_ids.add(proposition_id)
        proposition_type = proposition.get('type')
        if proposition_type not in PROPOSITION_TYPES:
            issues.append(_issue('invalid_proposition_type', f'{location}.type is unsupported'))
        modality = proposition.get('modality')
        if modality is not None and modality not in DEONTIC_MODALITIES:
            issues.append(_issue('invalid_proposition_modality', f'{location}.modality is unsupported'))
        if proposition_type != 'norm' and modality is not None:
            issues.append(_issue('invalid_proposition_modality', f'{location}.modality is allowed only for norm'))
        if proposition_type == 'norm' and modality is not None and not isinstance(proposition.get('predicate'), Mapping):
            issues.append(_issue('missing_proposition_role', f'{location}.predicate is required for a modal norm'))
        for field in PROPOSITION_ROLE_FIELDS:
            issues.extend(_validate_role(proposition.get(field), f'{location}.{field}', source_paths))
        exceptions = proposition.get('exceptions')
        if not isinstance(exceptions, list):
            issues.append(_issue('invalid_proposition_exceptions', f'{location}.exceptions must be an array'))
        else:
            for exception_index, exception in enumerate(exceptions):
                issues.extend(_validate_role(exception, f'{location}.exceptions[{exception_index}]', source_paths))
        for field in ('condition', 'logical_expression'):
            expression_id = _expression_reference_id(proposition.get(field), f'{location}.{field}', issues)
            if expression_id is not None and expression_id not in expression_ids:
                issues.append(_issue('broken_expression_reference', f'{location}.{field} references an unknown logical expression'))
        if not isinstance(proposition.get('extraction_method'), str) or not str(proposition.get('extraction_method')).strip():
            issues.append(_issue('missing_extraction_method', f'{location}.extraction_method must be a non-empty string'))
        if not _number_in_range(proposition.get('confidence')):
            issues.append(_issue('invalid_confidence', f'{location}.confidence must be between 0 and 1'))
        if proposition.get('status') not in STRUCTURAL_STATUS:
            issues.append(_issue('invalid_proposition_status', f'{location}.status is unsupported'))
        issues.extend(_validate_ref(proposition.get('source_ref'), f'{location}.source_ref', source_paths))
        issues.extend(_validate_evidence(proposition.get('evidence'), f'{location}.evidence', source_paths))

    for index, expression in enumerate(expressions):
        location = f'logical_expressions[{index}]'
        if not isinstance(expression, Mapping):
            issues.append(_issue('invalid_logical_expression', f'{location} must be an object'))
            continue
        expression_id = expression.get('id')
        if not isinstance(expression_id, str) or not expression_id:
            issues.append(_issue('missing_logical_expression_id', f'{location}.id must be a non-empty string'))
        elif expression_id in seen_ids:
            issues.append(_issue('duplicate_id', f'duplicate ASIR element id: {expression_id}'))
        else:
            seen_ids.add(expression_id)
        operator = expression.get('operator')
        if operator not in LOGICAL_OPERATORS:
            issues.append(_issue('invalid_logical_operator', f'{location}.operator is unsupported'))
        operands = expression.get('operands')
        if not isinstance(operands, list) or not operands:
            issues.append(_issue('invalid_logical_operands', f'{location}.operands must be a non-empty array'))
            operands = []
        elif operator == 'NOT' and len(operands) != 1:
            issues.append(_issue('invalid_logical_operands', f'{location}.operator NOT requires exactly one operand'))
        elif operator in {'AND', 'OR', 'XOR', 'IMPLIES', 'IFF'} and len(operands) < 2:
            issues.append(_issue('invalid_logical_operands', f'{location}.operator {operator} requires at least two operands'))
        for operand_index, operand in enumerate(operands):
            operand_location = f'{location}.operands[{operand_index}]'
            if not isinstance(operand, Mapping):
                issues.append(_issue('invalid_logical_operand', f'{operand_location} must be an object'))
                continue
            kind = operand.get('kind')
            if kind not in {'proposition', 'expression', 'atom'}:
                issues.append(_issue('invalid_logical_operand', f'{operand_location}.kind is unsupported'))
            elif kind == 'proposition':
                proposition_id = operand.get('proposition_id')
                if not isinstance(proposition_id, str) or proposition_id not in proposition_ids:
                    issues.append(_issue('broken_proposition_reference', f'{operand_location}.proposition_id references an unknown proposition'))
            elif kind == 'expression':
                nested_id = operand.get('expression_id')
                if not isinstance(nested_id, str) or nested_id not in expression_ids or nested_id == expression_id:
                    issues.append(_issue('broken_expression_reference', f'{operand_location}.expression_id references an unknown or current expression'))
            elif kind == 'atom' and (not isinstance(operand.get('text'), str) or not str(operand.get('text')).strip()):
                issues.append(_issue('invalid_logical_operand', f'{operand_location}.text must be a non-empty string for atom'))
            issues.extend(_validate_ref(operand.get('source_ref'), f'{operand_location}.source_ref', source_paths))
            issues.extend(_validate_evidence(operand.get('evidence'), f'{operand_location}.evidence', source_paths))
        if not _number_in_range(expression.get('confidence')):
            issues.append(_issue('invalid_confidence', f'{location}.confidence must be between 0 and 1'))
        expression_status = expression.get('status')
        if expression_status not in STRUCTURAL_STATUS:
            issues.append(_issue('invalid_logical_expression_status', f'{location}.status is unsupported'))
        alternatives = expression.get('alternatives', [])
        if not isinstance(alternatives, list) or any(value not in LOGICAL_OPERATORS for value in alternatives):
            issues.append(_issue('invalid_logical_alternatives', f'{location}.alternatives must contain supported operators'))
        elif alternatives and (len(alternatives) < 2 or expression_status != 'review_required'):
            issues.append(_issue('invalid_logical_alternatives', f'{location}.alternatives require review_required and at least two variants'))
        issues.extend(_validate_ref(expression.get('source_ref'), f'{location}.source_ref', source_paths))
        issues.extend(_validate_evidence(expression.get('evidence'), f'{location}.evidence', source_paths))
    return issues

def validate_model(model: object) -> list[dict]:
    if not isinstance(model, Mapping):
        return [_issue("invalid_model", "SemanticModel must be an object")]

    issues: list[dict] = []
    required = {"compilationId", "metadata", "sources", "recommended_model", "alternatives", "confidence", "status"}
    for key in sorted(required - model.keys()):
        issues.append(_issue("missing_field", f"required model field is missing: {key}"))

    compilation_id = model.get("compilationId")
    if not isinstance(compilation_id, str) or not compilation_id:
        issues.append(_issue("invalid_compilation_id", "compilationId must be a non-empty string"))
    if not isinstance(model.get("metadata"), dict):
        issues.append(_issue("invalid_metadata", "metadata must be an object"))

    sources = model.get("sources")
    source_paths: set[str] = set()
    if not isinstance(sources, list):
        issues.append(_issue("invalid_collection", "sources must be an array"))
        sources = []
    else:
        for index, source in enumerate(sources):
            issues.extend(_validate_source(source, index))
            if isinstance(source, dict) and isinstance(source.get("relative_path"), str):
                source_paths.add(source["relative_path"])

    recommended = model.get("recommended_model")
    if recommended not in ALLOWED_MODELS:
        issues.append(_issue("invalid_model_type", "recommended_model is not a supported ASIR model type"))

    alternatives = model.get("alternatives")
    if not isinstance(alternatives, list):
        issues.append(_issue("invalid_collection", "alternatives must be an array"))
    else:
        for value in alternatives:
            if value not in ALLOWED_MODELS:
                issues.append(_issue("invalid_model_type", f"unsupported alternative model type: {value}"))
        if recommended in alternatives:
            issues.append(_issue("invalid_model_type", "recommended_model must not be listed among alternatives"))

    if not _number_in_range(model.get("confidence")):
        issues.append(_issue("invalid_confidence", "model confidence must be between 0 and 1"))
    if 'classification_proposals' in model:
        issues.extend(_validate_classification_proposals(model, source_paths))
    issues.extend(_validate_artifact_profiles(model, source_paths))

    seen_ids: set[str] = set()
    for array_name in ARRAYS:
        values = model.get(array_name, [])
        if not isinstance(values, list):
            issues.append(_issue("invalid_collection", f"{array_name} must be an array"))
            continue
        expected_type = SINGULAR[array_name]
        for index, item in enumerate(values):
            location = f"{array_name}[{index}]"
            if not isinstance(item, dict):
                issues.append(_issue("invalid_element", f"{location} must be an object"))
                continue
            item_id = item.get("id")
            if not isinstance(item_id, str) or not item_id:
                issues.append(_issue("missing_element_id", f"{location} has no id"))
            elif item_id in seen_ids:
                issues.append(_issue("duplicate_id", f"duplicate ASIR element id: {item_id}"))
            else:
                seen_ids.add(item_id)
            if item.get("type") != expected_type:
                issues.append(_issue("invalid_element_type", f"{location} type must be {expected_type}"))
            if not isinstance(item.get("text"), str) or not item.get("text"):
                issues.append(_issue("invalid_element_text", f"{location} text must be a non-empty string"))
            status = item.get("status")
            if status not in ALLOWED_STATUS:
                issues.append(_issue("invalid_status", f"unsupported status in {location}: {status}"))
            if not _number_in_range(item.get("confidence")):
                issues.append(_issue("invalid_confidence", f"{location} confidence must be between 0 and 1"))
            issues.extend(_validate_ref(item.get("source_ref"), f"{location}.source_ref", source_paths))
            evidence = item.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                issues.append(_issue("missing_evidence", f"{location} evidence must be a non-empty array"))
            elif not (len(evidence) == 1 and evidence[0] is item.get("source_ref")):
                for evidence_index, ref in enumerate(evidence):
                    issues.extend(_validate_ref(ref, f"{location}.evidence[{evidence_index}]", source_paths))
            text = str(item.get("text", "")).lower()
            if status == "confirmed" and _contains_ambiguity(text):
                issues.append(_issue(
                    "ambiguous_confirmed",
                    f"{location} contains unresolved ambiguity but is confirmed",
                    evidence=item.get("evidence"),
                    source_ref=item.get("source_ref"),
                    confidence=item.get("confidence"),
                ))
            if status == "assumed" and item.get("confidence") == 1.0:
                issues.append(_issue(
                    "assumption_confidence",
                    f"{location} is assumed but has confidence 1.0",
                    evidence=item.get("evidence"),
                    source_ref=item.get("source_ref"),
                    confidence=item.get("confidence"),
                ))

    issues.extend(_validate_structural_contract(model, source_paths, seen_ids))

    model_evidence = model.get("evidence", [])
    if not isinstance(model_evidence, list):
        issues.append(_issue("invalid_collection", "evidence must be an array"))
    else:
        for index, ref in enumerate(model_evidence):
            issues.extend(_validate_ref(ref, f"evidence[{index}]", source_paths))

    model_status = model.get("status")
    if model_status not in ALLOWED_STATUS:
        issues.append(_issue("invalid_status", f"unsupported model status: {model_status}"))
    if 'findings' in model or 'checks' in model:
        issues.extend(_validate_findings(model, source_paths))
    unresolved_items = [
        item
        for name in ARRAYS
        for item in (model.get(name, []) if isinstance(model.get(name, []), list) else [])
        if isinstance(item, dict) and item.get("status") in {"gap", "REVIEW_REQUIRED", "assumed", "BLOCKED"}
    ]
    unresolved_items.extend(
        dict(item)
        for item in (model.get('propositions', []) if isinstance(model.get('propositions', []), list) else [])
        if isinstance(item, Mapping) and item.get('status') in {'review_required', 'gap'}
    )
    if model_status == "confirmed" and unresolved_items:
        issues.append(_issue("status_conflict", "model cannot be confirmed while unresolved elements exist"))

    if "formal_model" in model:
        formal_model = model.get("formal_model")
        artifact_kinds = {
            profile.get("relative_path"): profile.get("artifact_kind")
            for profile in model.get("artifact_profiles", [])
            if isinstance(profile, Mapping) and isinstance(profile.get("relative_path"), str) and isinstance(profile.get("artifact_kind"), str)
        } if isinstance(model.get("artifact_profiles", []), list) else {}
        source_context = {
            source.get("relative_path"): {
                "input_kind": source.get("input_kind"),
                "artifact_kind": artifact_kinds.get(source.get("relative_path")),
            }
            for source in sources
            if isinstance(source, Mapping) and isinstance(source.get("relative_path"), str) and isinstance(source.get("input_kind"), str)
        }
        for error in validate_formal_model(formal_model, source_context):
            issues.append(_issue("invalid_formal_model", error))
        if isinstance(formal_model, Mapping):
            for group in ("facts", "rules"):
                values = formal_model.get(group, [])
                if isinstance(values, list):
                    for index, item in enumerate(values):
                        if isinstance(item, Mapping):
                            issues.extend(_validate_ref(item.get("source_ref"), f"formal_model.{group}[{index}].source_ref", source_paths))

    evidence_records = model.get("evidence_records")
    if evidence_records is not None:
        if not isinstance(evidence_records, list):
            issues.append(_issue("invalid_evidence_record", "evidence_records must be an array"))
        else:
            for index, evidence_record in enumerate(evidence_records):
                for error in validate_evidence_record(evidence_record, source_paths):
                    issues.append(_issue("invalid_evidence_record", f"evidence_records[{index}].{error}"))
    hypothesis = model.get("hypothesis")
    if hypothesis is not None:
        for error in validate_hypothesis(hypothesis, source_paths):
            issues.append(_issue("invalid_hypothesis", error))
        if isinstance(hypothesis, Mapping):
            issues.extend(_validate_ref(hypothesis.get("source_ref"), "hypothesis.source_ref", source_paths))
            issues.extend(_validate_evidence(hypothesis.get("evidence"), "hypothesis.evidence", source_paths))

    proof_result = model.get("proof_result")
    if proof_result is not None:
        if not isinstance(proof_result, Mapping):
            issues.append(_issue("invalid_proof_result", "proof_result must be an object"))
        else:
            proof_status = proof_result.get("status")
            if proof_status not in PROOF_STATUSES:
                issues.append(_issue("invalid_proof_result", "proof_result.status is unsupported"))
            if not isinstance(proof_result.get("hypothesis_id"), str) or not proof_result.get("hypothesis_id"):
                issues.append(_issue("invalid_proof_result", "proof_result.hypothesis_id must be a non-empty string"))
            elif isinstance(hypothesis, Mapping) and proof_result.get("hypothesis_id") != hypothesis.get("id"):
                issues.append(_issue("invalid_proof_result", "proof_result.hypothesis_id must match hypothesis.id"))
            for error in validate_formal_claim(proof_result.get("formal_claim")):
                issues.append(_issue("invalid_proof_result", error))
            checksum = proof_result.get("formal_model_checksum")
            if not isinstance(checksum, str) or len(checksum) != 64 or any(character not in "0123456789abcdef" for character in checksum.lower()):
                issues.append(_issue("invalid_proof_result", "proof_result.formal_model_checksum must be a SHA-256 string"))
            proof_graph = proof_result.get("proof_graph")
            used_premises = proof_result.get("used_premises")
            if not isinstance(proof_graph, list) or not isinstance(used_premises, list):
                issues.append(_issue("invalid_proof_result", "proof_result proof_graph and used_premises must be arrays"))
            elif proof_status in {"PROVED", "REFUTED"} and (not proof_graph or not used_premises):
                issues.append(_issue("invalid_proof_result", "PROVED and REFUTED require a proof graph and used premises"))
            if proof_result.get("explanation") is not None:
                for error in validate_proof_explanation(proof_result.get("explanation"), proof_status):
                    issues.append(_issue("invalid_proof_result", error))
    return issues
