"""Детерминированный движок ограниченного вывода по правилам Хорна."""

from __future__ import annotations

from collections.abc import Mapping

from .proof_contract import formal_model_checksum

ENGINE_VERSION = "0.4.0"
MAX_DERIVATIONS = 1000
MAX_BACKWARD_PATHS = 8
MAX_BACKWARD_DEPTH = 16


def _key(claim: Mapping) -> str:
    kind = claim.get("kind")
    if kind == "atom":
        return "atom:" + str(claim.get("predicate")) + ":" + repr(claim.get("terms", []))
    if kind == "not":
        nested = claim.get("claim")
        return "not:" + _key(nested) if isinstance(nested, Mapping) else "not:invalid"
    return "comparison:" + str(claim.get("operator")) + ":" + repr([claim.get("left"), claim.get("right")])


def _negate(claim: Mapping) -> dict:
    nested = claim.get("claim")
    if claim.get("kind") == "not" and isinstance(nested, Mapping):
        return dict(nested)
    return {"kind": "not", "claim": dict(claim)}


def _comparison_holds(claim: Mapping) -> bool:
    left = claim.get("left")
    right = claim.get("right")
    operator = claim.get("operator")
    if not isinstance(operator, str):
        return False

    if isinstance(left, str) and isinstance(right, str):
        if operator == "=":
            return left == right
        if operator == "!=":
            return left != right
        if operator == "<":
            return left < right
        if operator == "<=":
            return left <= right
        if operator == ">":
            return left > right
        if operator == ">=":
            return left >= right
        return False

    if isinstance(left, int) and not isinstance(left, bool) and isinstance(right, int) and not isinstance(right, bool):
        if operator == "=":
            return left == right
        if operator == "!=":
            return left != right
        if operator == "<":
            return left < right
        if operator == "<=":
            return left <= right
        if operator == ">":
            return left > right
        if operator == ">=":
            return left >= right
        return False

    if isinstance(left, float) and isinstance(right, float):
        if operator == "=":
            return left == right
        if operator == "!=":
            return left != right
        if operator == "<":
            return left < right
        if operator == "<=":
            return left <= right
        if operator == ">":
            return left > right
        if operator == ">=":
            return left >= right
    return False


def _trace(selected: list[dict], known: Mapping[str, dict], rules: Mapping[str, Mapping]) -> tuple[list[dict], list[dict]]:
    """Возвращает только основания выбранной цепочки в детерминированном порядке."""
    by_id = {str(value["id"]): value for value in known.values()}
    required: set[str] = set()
    required_rules: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in required or node_id not in by_id:
            return
        required.add(node_id)
        node = by_id[node_id]
        if node.get("kind") == "derived":
            rule_id = str(node.get("rule_id"))
            required_rules.add(rule_id)
            for premise_id in node.get("premise_ids", []):
                if isinstance(premise_id, str):
                    visit(premise_id)

    for node in selected:
        visit(str(node["id"]))
    graph = [by_id[node_id] for node_id in sorted(required, key=lambda value: (int(by_id[value].get("step", 0)), value))]
    rule_nodes = [
        {"id": "rule-" + rule_id, "kind": "rule", "rule_id": rule_id, "source_ref": rules[rule_id].get("source_ref")}
        for rule_id in sorted(required_rules)
        if rule_id in rules
    ]
    graph.extend(rule_nodes)
    premises = [node for node in graph if node.get("kind") == "premise"]
    return graph, premises


def _source_refs(rules: Mapping[str, Mapping], rule_ids: list[str]) -> list[object]:
    result: list[object] = []
    seen: set[str] = set()
    for rule_id in rule_ids:
        rule = rules.get(rule_id)
        source_ref = rule.get("source_ref") if isinstance(rule, Mapping) else None
        marker = repr(source_ref)
        if source_ref is not None and marker not in seen:
            seen.add(marker)
            result.append(source_ref)
    return result


def _merge_paths(left: list[dict], right: list[dict]) -> list[dict]:
    merged: list[dict] = []
    for first in left:
        for second in right:
            missing = {item["key"]: item for item in first["missing"]}
            missing.update({item["key"]: item for item in second["missing"]})
            merged.append({
                "rule_ids": sorted(set(first["rule_ids"] + second["rule_ids"])),
                "missing": [missing[key] for key in sorted(missing)],
            })
            if len(merged) >= MAX_BACKWARD_PATHS:
                return merged
    return merged


def _backward_paths(
    claim: Mapping,
    *,
    known: Mapping[str, dict],
    rules_by_conclusion: Mapping[str, list[tuple[str, Mapping]]],
    rules: Mapping[str, Mapping],
    visiting: frozenset[str] = frozenset(),
    depth: int = 0,
) -> list[dict]:
    """Ищет только конечные наборы отсутствующих атомов по существующим правилам."""
    claim_key = _key(claim)
    if claim_key in known:
        return [{"rule_ids": [], "missing": []}]
    if depth >= MAX_BACKWARD_DEPTH or claim_key in visiting:
        return []
    candidates = rules_by_conclusion.get(claim_key, [])
    if not candidates:
        if claim.get("kind") != "atom":
            return []
        return [{"rule_ids": [], "missing": [{"key": claim_key, "claim": dict(claim)}]}]

    result: list[dict] = []
    for rule_id, rule in candidates:
        exceptions = rule.get("exceptions", [])
        if not isinstance(exceptions, list) or any(
            isinstance(exception, Mapping) and _key(exception) in known
            for exception in exceptions
        ):
            continue
        premises = rule.get("premises", [])
        if not isinstance(premises, list):
            continue
        paths = [{"rule_ids": [rule_id], "missing": []}]
        for premise in premises:
            if not isinstance(premise, Mapping):
                paths = []
                break
            premise_paths = _backward_paths(
                premise,
                known=known,
                rules_by_conclusion=rules_by_conclusion,
                rules=rules,
                visiting=visiting | {claim_key},
                depth=depth + 1,
            )
            if not premise_paths:
                paths = []
                break
            paths = _merge_paths(paths, premise_paths)
            if not paths:
                break
        result.extend(paths)
        if len(result) >= MAX_BACKWARD_PATHS:
            break
    return result[:MAX_BACKWARD_PATHS]


def _missing_analysis(
    claim: Mapping,
    *,
    known: Mapping[str, dict],
    rules: Mapping[str, Mapping],
) -> tuple[list[dict], list[dict]]:
    rules_by_conclusion: dict[str, list[tuple[str, Mapping]]] = {}
    for rule_id, rule in sorted(rules.items()):
        conclusion = rule.get("conclusion")
        if isinstance(conclusion, Mapping):
            rules_by_conclusion.setdefault(_key(conclusion), []).append((rule_id, rule))

    alternatives: list[dict] = []
    for polarity, target in (("hypothesis", claim),):
        for path in _backward_paths(target, known=known, rules_by_conclusion=rules_by_conclusion, rules=rules):
            if not path["missing"]:
                continue
            rule_ids = [rule_id for rule_id in path["rule_ids"] if isinstance(rule_id, str)]
            missing_atoms = [dict(item["claim"]) for item in path["missing"] if isinstance(item.get("claim"), Mapping)]
            alternatives.append({
                "polarity": polarity,
                "target_claim": dict(target),
                "rule_ids": rule_ids,
                "missing_atoms": missing_atoms,
                "source_refs": _source_refs(rules, rule_ids),
            })
    alternatives.sort(key=lambda item: (str(item["polarity"]), tuple(item["rule_ids"]), repr(item["missing_atoms"])))
    alternatives = alternatives[:MAX_BACKWARD_PATHS]
    graph: list[dict] = []
    for index, item in enumerate(alternatives, start=1):
        alternative_id = "alternative-" + str(index).zfill(3)
        item["id"] = alternative_id
        for missing_index, missing_atom in enumerate(item["missing_atoms"], start=1):
            graph.append({
                "id": "missing-" + alternative_id + "-" + str(missing_index).zfill(3),
                "kind": "missing_premise",
                "claim": dict(missing_atom),
                "status": "unverified_requirement",
                "alternative_id": alternative_id,
            })
    return alternatives, graph


def _trace_summary(
    selected: list[dict], known: Mapping[str, dict], rules: Mapping[str, Mapping], claim: Mapping) -> list[dict]:
    result: list[dict] = []
    for node in selected:
        graph, premises = _trace([node], known, rules)
        rule_ids = sorted(
            str(item.get("rule_id"))
            for item in graph
            if item.get("kind") == "rule" and isinstance(item.get("rule_id"), str)
        )
        result.append({
            "polarity": "negation" if _key(node["claim"]) == _key(_negate(claim)) else "hypothesis",
            "conclusion_node_id": node["id"],
            "node_ids": [str(item.get("id")) for item in graph if isinstance(item.get("id"), str)],
            "rule_ids": rule_ids,
            "premise_ids": [str(item.get("id")) for item in premises if isinstance(item.get("id"), str)],
            "source_refs": _source_refs(rules, rule_ids),
        })
    return result


def _explanation(status: str, *, traces: list[dict], alternatives: list[dict]) -> dict:
    next_steps = {
        "PROVED": ("PRESERVE_EXISTING_POLICY", "Сохранить действующую policy исполнения; доказательство само не разрешает действие."),
        "REFUTED": ("REVIEW_REFUTED_HYPOTHESIS", "Передать опровергнутую гипотезу человеку и не выполнять действие по ней."),
        "INCONSISTENT": ("RESOLVE_CONFLICT", "Передать конфликт двух цепочек человеку; действия по гипотезе запрещены."),
        "MISSING_PREMISES": ("CONFIRM_MISSING_PREMISES", "Подтвердить или опровергнуть указанные отсутствующие основания, не добавляя их автоматически."),
        "NOT_DERIVABLE": ("REVIEW_FORMAL_MODEL", "Уточнить формальную модель или гипотезу; подходящее подтверждённое правило не найдено."),
        "NOT_EVALUATED": ("REVIEW_ENGINE_LIMIT", "Передать человеку причину, по которой исследование не завершено."),
    }
    code, message = next_steps.get(status, ("REQUEST_HUMAN_REVIEW", "Передать результат проверки человеку."))
    return {
        "classification": status,
        "derivation_traces": traces,
        "alternatives": alternatives,
        "safe_next_step": {"code": code, "message": message},
    }


def evaluate(model: Mapping, hypothesis: Mapping) -> dict:
    """Строит конечное замыкание подтверждённых правил без новых констант."""
    formal = model.get("formal_model", {})
    if not isinstance(formal, Mapping):
        formal = {}
    facts = formal.get("facts", []) if isinstance(formal.get("facts", []), list) else []
    raw_rules = formal.get("rules", []) if isinstance(formal.get("rules", []), list) else []
    rules = {str(item.get("id")): item for item in raw_rules if isinstance(item, Mapping) and item.get("status") == "confirmed"}
    known: dict[str, dict] = {}
    for item in sorted((item for item in facts if isinstance(item, Mapping) and item.get("status") == "confirmed"), key=lambda item: str(item.get("id"))):
        claim = item.get("claim")
        if not isinstance(claim, Mapping) or (claim.get("kind") == "comparison" and not _comparison_holds(claim)):
            continue
        key = _key(claim)
        known.setdefault(key, {"id": str(item.get("id")), "claim": dict(claim), "source_ref": item.get("source_ref"), "kind": "premise", "step": 0})
    step = 0
    changed = True
    while changed and step < MAX_DERIVATIONS:
        changed = False
        for rule_id, rule in sorted(rules.items()):
            premises = rule.get("premises", [])
            conclusion = rule.get("conclusion")
            exceptions = rule.get("exceptions", [])
            if not isinstance(premises, list) or not isinstance(exceptions, list) or not isinstance(conclusion, Mapping):
                continue
            premise_keys = [_key(item) for item in premises if isinstance(item, Mapping)]
            exception_keys = [_key(item) for item in exceptions if isinstance(item, Mapping)]
            if len(premise_keys) != len(premises) or any(key not in known for key in premise_keys) or any(key in known for key in exception_keys):
                continue
            if conclusion.get("kind") == "comparison" and not _comparison_holds(conclusion):
                continue
            result_key = _key(conclusion)
            if result_key in known:
                continue
            step += 1
            known[result_key] = {
                "id": "derived-" + str(step).zfill(4), "claim": dict(conclusion), "source_ref": rule.get("source_ref"),
                "kind": "derived", "rule_id": rule_id, "premise_ids": [known[key]["id"] for key in premise_keys], "step": step,
            }
            changed = True
            if step >= MAX_DERIVATIONS:
                break
    claim = hypothesis["formal_claim"]
    positive, negative = _key(claim), _key(_negate(claim))
    selected = [known[key] for key in (positive, negative) if key in known]
    has_positive, has_negative = positive in known, negative in known
    alternatives: list[dict] = []
    missing_graph: list[dict] = []
    if has_positive and has_negative:
        status = "INCONSISTENT"
    elif has_positive:
        status = "PROVED"
    elif has_negative:
        status = "REFUTED"
    elif step >= MAX_DERIVATIONS:
        status = "NOT_EVALUATED"
    else:
        alternatives, missing_graph = _missing_analysis(claim, known=known, rules=rules)
        status = "MISSING_PREMISES" if alternatives else "NOT_DERIVABLE"
    proof_graph, used_premises = _trace(selected, known, rules) if selected else (missing_graph, [])
    traces = _trace_summary(selected, known, rules, claim) if selected else []
    if status == "MISSING_PREMISES":
        blockers = [{"code": "MISSING_PREMISES", "message": "Для существующих путей к гипотезе отсутствуют подтверждённые атомы."}]
    elif status == "NOT_EVALUATED":
        blockers = [{"code": "DERIVATION_LIMIT", "message": "Достигнут лимит производных фактов; утверждение не доказано и не опровергнуто."}]
    elif status == "NOT_DERIVABLE":
        blockers = [{"code": "NO_DERIVATION", "message": "В конечной формальной модели нет применимого пути для гипотезы или её отрицания."}]
    elif status == "INCONSISTENT":
        blockers = [{"code": "CONFLICTING_DERIVATIONS", "message": "Выведены гипотеза и её отрицание; действие по результату запрещено."}]
    else:
        blockers = []
    return {
        "hypothesis_id": hypothesis["id"], "formal_claim": claim, "mode": hypothesis["mode"], "engine_version": ENGINE_VERSION,
        "formal_model_checksum": formal_model_checksum(model, hypothesis), "status": status, "proof_graph": proof_graph,
        "used_premises": used_premises, "missing_premises": alternatives, "blocking_reasons": blockers,
        "explanation": _explanation(status, traces=traces, alternatives=alternatives),
        "explanation_basis": ["confirmed_formal_facts", "confirmed_horn_rules", "deterministic_forward_chaining", "bounded_backward_analysis"], "conclusion_nodes": selected,
    }