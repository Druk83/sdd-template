"""Загрузка локального методического пакета логической проверки ASIR."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path


METHOD_PACK_ROOT = Path(__file__).with_name("logic_specs")
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _digest(value: bytes) -> str:
    return sha256(value).hexdigest()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _reference_path(relative: str) -> Path:
    packaged = METHOD_PACK_ROOT / relative
    if packaged.is_file():
        return packaged
    source_reference = PROJECT_ROOT / "docs" / "requirements" / relative
    if source_reference.is_file():
        return source_reference
    raise FileNotFoundError(f"методический справочник не найден: {relative}")


def load_method_pack(*, include_content: bool = True) -> dict:
    """Возвращает manifest и содержание методик для агентного запроса."""
    manifest_path = METHOD_PACK_ROOT / "manifest.json"
    manifest = json.loads(_read(manifest_path))
    specs: list[dict] = []
    fingerprints: list[str] = []
    for item in manifest.get("specifications", []):
        relative = item["path"]
        path = METHOD_PACK_ROOT / relative
        content = _read(path)
        digest = _digest(content.encode("utf-8"))
        specs.append({
            "id": item["id"],
            "title": item["title"],
            "path": relative,
            "sha256": digest,
            **({"content": content} if include_content else {}),
        })
        fingerprints.append(f"{relative}:{digest}")
    reference_materials: list[dict] = []
    reference_fingerprints: list[str] = []
    for item in manifest.get("reference_materials", []):
        relative = item["path"]
        path = _reference_path(relative)
        content = _read(path)
        digest = _digest(content.encode("utf-8"))
        reference_materials.append({
            "id": item["id"],
            "title": item["title"],
            "path": relative,
            "sha256": digest,
        })
        reference_fingerprints.append(f"{relative}:{digest}")
    pack_sha256 = _digest("\n".join(fingerprints + reference_fingerprints).encode("utf-8"))
    compact = {
        "provider": manifest["provider"],
        "methodology": manifest["methodology"],
        "adaptation_version": manifest["adaptation_version"],
        "pack_sha256": pack_sha256,
        "specifications": [
            {key: value for key, value in spec.items() if key != "content"}
            for spec in specs
        ],
    }
    return {
        "manifest": compact,
        "algorithm": list(manifest["algorithm"]),
        "required_sections": list(manifest["required_sections"]),
        "reference_materials": reference_materials,
        "system_prompt": _read(METHOD_PACK_ROOT / manifest["prompt"]),
        "specifications": specs,
    }


def method_fingerprint(method_pack: dict) -> dict:
    """Короткая подпись методик, которую агент обязан вернуть."""
    return dict(method_pack["manifest"])
