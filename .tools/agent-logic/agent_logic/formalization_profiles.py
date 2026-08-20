"""Версионируемый реестр границ формализации входных источников."""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

REGISTRY_PATH = Path(__file__).with_name("formalization_profiles.json")
APPROVAL_BASES = {"explicit_json_dsl", "human_approved"}


@lru_cache(maxsize=1)
def load_profile_registry() -> dict[str, dict]:
    """Загружает локальный статический реестр без сетевых зависимостей."""
    raw = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    profiles = raw.get("profiles") if isinstance(raw, Mapping) else None
    if not isinstance(profiles, list):
        raise ValueError("formalization profile registry must contain profiles")
    result: dict[str, dict] = {}
    for profile in profiles:
        if not isinstance(profile, Mapping):
            raise ValueError("formalization profile must be an object")
        profile_id = profile.get("id")
        if not isinstance(profile_id, str) or not profile_id:
            raise ValueError("formalization profile id must be a non-empty string")
        if profile_id in result:
            raise ValueError("formalization profile ids must be unique")
        result[profile_id] = dict(profile)
    return result


def profile_for_source(*, input_kind: str, artifact_kind: str) -> dict:
    """Выбирает профиль источника только по детерминированным признакам."""
    for profile in load_profile_registry().values():
        if input_kind in profile.get("source_kinds", []) and artifact_kind in profile.get("artifact_kinds", []):
            return dict(profile)
    return {
        "id": "unrecognized_source",
        "version": "0",
        "deductive_premises": False,
        "provenance": "none",
        "reason": "Для вида источника нет профиля формализации.",
    }


def profile_summary(profile: Mapping) -> dict:
    """Возвращает только данные, допустимые для ASIR-отчёта."""
    return {
        "id": profile.get("id"),
        "version": profile.get("version"),
        "deductive_premises": profile.get("deductive_premises") is True,
        "provenance": profile.get("provenance"),
        "reason": profile.get("reason"),
    }


def validate_formalization(
    value: object,
    *,
    item_kind: str,
    claim_kinds: set[str],
    source_kind: str | None,
    artifact_kind: str | None,
) -> list[str]:
    """Проверяет, что формальное основание разрешено профилем и принято явно."""
    if not isinstance(value, Mapping):
        return ["formalization must be an object"]
    profile_id = value.get("profile_id")
    profile_version = value.get("profile_version")
    approval_basis = value.get("approval_basis")
    if not isinstance(profile_id, str) or not profile_id:
        return ["formalization.profile_id must be a non-empty string"]
    profile = load_profile_registry().get(profile_id)
    if profile is None:
        return ["formalization.profile_id is unknown"]
    errors: list[str] = []
    if profile_version != profile.get("version"):
        errors.append("formalization.profile_version does not match registry")
    if approval_basis not in APPROVAL_BASES:
        errors.append("formalization.approval_basis is unsupported")
    if source_kind not in profile.get("source_kinds", []):
        errors.append("formalization profile is incompatible with source kind")
    if artifact_kind is not None and artifact_kind not in profile.get("artifact_kinds", []):
        errors.append("formalization profile is incompatible with artifact kind")
    if not profile.get("deductive_premises", False):
        errors.append("formalization profile cannot supply deductive premises")
    if item_kind not in profile.get("supported_items", []):
        errors.append("formalization profile does not support this formal item")
    unsupported = sorted(claim_kinds - set(profile.get("supported_claim_kinds", [])))
    if unsupported:
        errors.append("formalization profile does not support claim kinds: " + ", ".join(unsupported))
    if approval_basis == "human_approved" and not isinstance(value.get("approved_by"), str):
        errors.append("human-approved formalization requires approved_by")
    return errors