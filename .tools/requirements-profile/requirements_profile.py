#!/usr/bin/env python3
"""Выбор и проверка профиля требований SDD Framework."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


REQUIRED_FIELDS = {
    "id", "title", "scope", "source", "instruction", "output",
    "requirement_id", "required_sections",
}
DECISION_PATH = Path("docs/requirements/обоснование выбора.md")
ALLOWED_SCOPE = {"software", "system"}
H8_REQUIRED_HEADINGS = {
    "software": (
        "1. Общие сведения", "1.1 Идентификация", "1.2 Начальные сведения",
        "1.3 Определения", "1.4 Нормативные и справочные ссылки", "1.5 Сокращения",
        "2. Назначение и область ПО", "3. Перспектива продукта", "3.1 Системные интерфейсы",
        "3.2 Пользовательские интерфейсы", "3.3 Аппаратные интерфейсы",
        "3.4 Программные интерфейсы", "3.5 Коммуникационные интерфейсы",
        "3.6 Ограничения памяти", "3.7 Эксплуатация", "3.8 Адаптация к месту установки",
        "3.9 Интерфейсы с сервисами", "4. Функции продукта", "5. Характеристики пользователей",
        "6. Ограничения", "7. Допущения и зависимости", "8. Распределение требований",
        "9. Внешние интерфейсы", "10. Удобство использования", "11. Производительность",
        "12. Логическая база данных", "13. Ограничения проектирования",
        "14. Соответствие стандартам", "15. Атрибуты программной системы",
        "16. Заданные требования — индекс", "17. Проверка выполнения требований",
        "18. Вспомогательная информация",
        "Приложение Г. Проверка и прослеживаемость",
    ),
    "system": (
        "1. Общие сведения", "1.1 Идентификация", "1.2 Начальные сведения",
        "1.3 Определения", "1.4 Нормативные и справочные ссылки", "1.5 Сокращения",
        "2. Назначение и область системы", "3. Обзор системы", "3.1 Контекст системы",
        "3.2 Функции системы", "3.3 Характеристики пользователей",
        "4. Функциональные требования", "5. Удобство использования", "6. Производительность",
        "7. Интерфейсы системы", "7.1 Перечень интерфейсов", "7.2 Контракты интерфейсов",
        "8. Эксплуатация системы",
        "8.1 Интеграция человека и системы", "8.2 Сопровождаемость", "8.3 Надёжность",
        "8.4 Другие требования к качеству", "9. Режимы и состояния",
        "10. Физические характеристики", "10.1 Физические требования", "10.2 Адаптируемость",
        "11. Условия среды", "12. Защита системы", "13. Управление информацией",
        "14. Политики и нормативы", "15. Поддержка жизненного цикла",
        "16. Упаковка, обращение, перевозка и хранение",
        "17. Заданные требования — индекс", "18. Проверка выполнения требований",
        "19. Допущения и зависимости",
        "Приложение Г. Проверка и прослеживаемость",
    ),
}
REQUIREMENT_REGISTRY_COLUMNS = (
    "ID", "Требование", "Тип", "Информационный объект/уровень",
    "Родительские ID", "Источник", "Приоритет", "Риск", "Обоснование",
    "Владелец", "Сложность", "Версия", "Критерий", "Метод", "Статус",
)


def h8_required_headings(scope: str) -> tuple[str, ...]:
    return H8_REQUIRED_HEADINGS[scope]


def has_table_header(content: str, required_columns: tuple[str, ...]) -> bool:
    required = {column.casefold() for column in required_columns}
    for line in content.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        columns = {column.strip().casefold() for column in line.strip().strip("|").split("|")}
        if required.issubset(columns):
            return True
    return False


def iso_required_clauses(scope: str) -> list[str]:
    if scope == "software":
        return ([f"9.6.{number}" for number in range(1, 21)] +
                [f"9.6.4.{number}" for number in range(1, 10)])
    return ([f"9.5.{number}" for number in range(1, 20)] +
            [f"9.5.4.{number}" for number in range(1, 4)] +
            [f"9.5.9.{number}" for number in range(1, 5)] +
            [f"9.5.11.{number}" for number in range(1, 3)])


class ProfileError(ValueError):
    """Некорректный каталог, выбор или результат профиля."""


def framework_root() -> Path:
    return Path(__file__).resolve().parents[2]


def read_version(root: Path) -> str:
    text = (root / "README.md").read_text(encoding="utf-8")
    matches = re.findall(r"^>\s*\*\*Версия:\*\*\s*`?([0-9]+\.[0-9]+\.[0-9]+)`?\s*$", text, re.MULTILINE)
    if len(matches) != 1:
        raise ProfileError("Не найдена единственная версия Framework в README.md.")
    return matches[0]


def load_registry(root: Path) -> dict[str, Any]:
    path = root / ".requirements" / "требования" / "профили.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProfileError(f"Невозможно прочитать каталог профилей: {error}") from error
    if not isinstance(data, dict) or data.get("schema_version") != "1.0":
        raise ProfileError("Некорректная версия схемы каталога профилей.")
    profiles = data.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        raise ProfileError("Каталог профилей должен содержать непустой список profiles.")
    seen: set[str] = set()
    for profile in profiles:
        if not isinstance(profile, dict) or not REQUIRED_FIELDS.issubset(profile):
            raise ProfileError("Профиль не содержит обязательных полей.")
        identifier = profile["id"]
        if (not isinstance(identifier, str) or
            not re.fullmatch(r"[a-z][a-z0-9-]*", identifier) or identifier in seen):
            raise ProfileError(f"Некорректный или повторный ID профиля: {identifier}")
        seen.add(identifier)
        if not all(isinstance(profile[key], str) and profile[key] for key in
                   ("title", "source", "instruction", "output", "requirement_id")):
            raise ProfileError(f"Профиль {identifier} содержит пустые текстовые поля.")
        scope = profile["scope"]
        if not isinstance(scope, list) or not scope or any(value not in ALLOWED_SCOPE for value in scope):
            raise ProfileError(f"Некорректный scope профиля {identifier}.")
        sections = profile["required_sections"]
        if not isinstance(sections, list) or not sections or any(not isinstance(x, str) or not x for x in sections):
            raise ProfileError(f"Некорректные разделы профиля {identifier}.")
        instruction = Path(profile["instruction"])
        output = Path(profile["output"])
        if (instruction.is_absolute() or ".." in instruction.parts or
            instruction.parts[:2] != (".requirements", "требования") or
            not (root / instruction).is_file()):
            raise ProfileError(f"Не найдена инструкция профиля {identifier}: {instruction}")
        if (output.is_absolute() or ".." in output.parts or
            output.parts[:3] != ("docs", "requirements", "требования") or
            output.suffix != ".md"):
            raise ProfileError(f"Некорректный выходной путь профиля {identifier}: {output}")
        instruction_text = (root / instruction).read_text(encoding="utf-8")
        if any(section not in instruction_text for section in sections):
            raise ProfileError(f"Инструкция {identifier} не описывает обязательные разделы.")
        if identifier == "iso-29148":
            source_url = profile.get("source_document_url")
            parsed = urlparse(source_url) if isinstance(source_url, str) else None
            if parsed is None or parsed.scheme != "https" or not parsed.netloc or not parsed.path.endswith(".pdf"):
                raise ProfileError("Профиль iso-29148 должен ссылаться на PDF полного источника.")
    if data.get("default_profile") not in seen:
        raise ProfileError("default_profile должен ссылаться на существующий профиль.")
    return data


def _decision_values(text: str, field: str) -> list[str]:
    # Примеры внутри кодовых блоков не являются решениями проекта.
    without_examples = re.sub(r"^```[^\n]*\n.*?^```\s*$", "", text, flags=re.MULTILINE | re.DOTALL)
    return [value.strip() for value in re.findall(
        rf"^\*\*{re.escape(field)}:\*\*\s*(.+)$", without_examples, re.MULTILINE
    )]


def select_profile(project_root: Path, registry: dict[str, Any]) -> tuple[dict[str, Any], str]:
    decision = project_root / DECISION_PATH
    default = registry["default_profile"]
    if not decision.is_file():
        identifier, origin = default, "default"
    else:
        content = decision.read_text(encoding="utf-8")
        explicit = _decision_values(content, "Профиль требований")
        legacy = _decision_values(content, "Выбранный стандарт")
        if len(explicit) > 1 or len(legacy) > 1:
            raise ProfileError("В решении этапа [2] указано несколько профилей или стандартов.")
        mapped: str | None = None
        if legacy:
            normalized = re.sub(r"\s+", " ", legacy[0]).strip().casefold()
            mapped = {"гост 19": "gost-19", "гост 19 (еспд)": "gost-19",
                      "гост 34": "gost-34", "гост 34 (ас)": "gost-34",
                      "sdd framework": "sdd",
                      "iso/iec/ieee 29148:2018": "iso-29148"}.get(normalized)
            if mapped is None and not (explicit and normalized in
                                       {"внутренний", "внутренний стандарт", "без стандарта"}
                                       and explicit[0].strip("` ") == "sdd"):
                raise ProfileError("Невозможно сопоставить выбранный стандарт с профилем.")
        if explicit:
            identifier, origin = explicit[0].strip("` "), "explicit"
            if mapped and mapped != identifier:
                raise ProfileError("Профиль требований противоречит выбранному стандарту.")
        elif mapped:
            identifier, origin = mapped, "legacy"
        else:
            identifier, origin = default, "default"
    matching = [p for p in registry["profiles"] if p["id"] == identifier]
    if len(matching) != 1:
        raise ProfileError(f"Неизвестный профиль требований: {identifier}")
    return matching[0], origin


def check_result(project_root: Path, profile: dict[str, Any], version: str) -> None:
    path = project_root / profile["output"]
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ProfileError(f"Не найден результат профиля: {path}") from error
    expected = {"requirements_profile": profile["id"], "profile_version": version,
                "profile_source": profile["source"]}
    for key, value in expected.items():
        if not re.search(rf"^\*\*{key}:\*\*\s*`?{re.escape(value)}`?\s*$", content, re.MULTILINE):
            raise ProfileError(f"Результат содержит неверное или отсутствующее поле {key}.")
    scope_values = _decision_values(content, "scope")
    if len(scope_values) != 1 or scope_values[0].strip("` ") not in profile["scope"]:
        raise ProfileError("Результат содержит неверный scope.")
    scope = scope_values[0].strip("` ")
    source_url = profile.get("source_document_url")
    if source_url and source_url not in content:
        raise ProfileError("Результат не содержит ссылку на полный источник профиля.")
    if profile["id"] == "iso-29148":
        item = "SRS" if scope == "software" else "SyRS"
        if _decision_values(content, "information_item") != [item]:
            raise ProfileError(f"Для scope {scope} требуется информационный объект {item}.")
        if _decision_values(content, "conformance_claim") != ["not_claimed"]:
            raise ProfileError("Нельзя автоматически заявлять полное соответствие ISO.")
        readiness_values = _decision_values(content, "document_readiness")
        if len(readiness_values) != 1 or readiness_values[0] not in {"draft", "ready_for_review"}:
            raise ProfileError("Результат должен содержать document_readiness: draft или ready_for_review.")
        readiness = readiness_values[0]
        headings = re.findall(r"^#{1,6}\s+(.+)$", content, re.MULTILINE)
        for required_heading in h8_required_headings(scope):
            if not any(heading.startswith(required_heading) for heading in headings):
                raise ProfileError(f"Результат не содержит раздел H8: {required_heading}.")
        if not has_table_header(content, REQUIREMENT_REGISTRY_COLUMNS):
            raise ProfileError("Реестр требований Г.1 не содержит все обязательные атрибуты.")
        for reference in iso_required_clauses(scope):
            rows = re.findall(
                rf"^\|\s*{re.escape(reference)}\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*$",
                content, re.MULTILINE,
            )
            allowed_statuses = {"covered", "not_applicable"}
            if readiness == "draft":
                allowed_statuses.add("gap")
            if len(rows) != 1 or rows[0][0].strip() not in allowed_statuses:
                raise ProfileError(f"Не закрыт пункт стандарта {reference}.")
            if not all(value.strip() for value in rows[0][1:]):
                raise ProfileError(f"Пункт {reference} не содержит основания покрытия.")
        if readiness == "ready_for_review" and re.search(r"\b(?:TBD|TBS|TBR)\b", content):
            raise ProfileError("ready_for_review не допускает нерешённые TBD/TBS/TBR.")
    else:
        headings = re.findall(r"^#{1,4}\s+(.+)$", content, re.MULTILINE)
        if any(not any(section.casefold() in heading.casefold() for heading in headings)
               for section in profile["required_sections"]):
            raise ProfileError("Результат не содержит обязательные разделы выбранного профиля.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Выбрать и проверить профиль требований.")
    parser.add_argument("action", choices=("registry", "resolve", "check-result"))
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = framework_root()
    registry = load_registry(root)
    if args.action == "registry":
        result: object = {"status": "pass", "profiles": [p["id"] for p in registry["profiles"]]}
    else:
        profile, origin = select_profile(args.project_root.resolve(), registry)
        result = {"profile": profile["id"], "origin": origin,
                  "instruction": profile["instruction"], "output": profile["output"],
                  "source": profile["source"], "scope": profile["scope"],
                  "profile_version": read_version(root)}
        if profile.get("source_document_url"):
            result["source_document_url"] = profile["source_document_url"]
        if args.action == "check-result":
            check_result(args.project_root.resolve(), profile, read_version(root))
            result["status"] = "pass"
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ProfileError, OSError) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        raise SystemExit(1)
