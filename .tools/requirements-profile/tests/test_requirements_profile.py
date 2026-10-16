"""Проверки выбора профилей требований и выходного документа."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / ".tools" / "requirements-profile" / "requirements_profile.py"
SPEC = importlib.util.spec_from_file_location("requirements_profile", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class RequirementsProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = module.load_registry(ROOT)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name)
        self.decision = self.project / module.DECISION_PATH
        self.decision.parent.mkdir(parents=True)

    def test_catalog_has_four_unique_valid_profiles(self) -> None:
        self.assertEqual({p["id"] for p in self.registry["profiles"]},
                         {"gost-19", "gost-34", "sdd", "iso-29148"})
        self.assertEqual(self.registry["default_profile"], "gost-19")

    def test_each_explicit_profile_resolves_to_own_instruction(self) -> None:
        for identifier in ("gost-19", "gost-34", "sdd", "iso-29148"):
            with self.subTest(identifier=identifier):
                self.decision.write_text(
                    f"**Профиль требований:** {identifier}\n", encoding="utf-8"
                )
                profile, origin = module.select_profile(self.project, self.registry)
                self.assertEqual((profile["id"], origin), (identifier, "explicit"))
                self.assertTrue((ROOT / profile["instruction"]).is_file())

    def test_legacy_and_absent_choices_preserve_behaviour(self) -> None:
        self.decision.write_text("**Выбранный стандарт:** ГОСТ 34\n", encoding="utf-8")
        self.assertEqual(module.select_profile(self.project, self.registry)[0]["id"], "gost-34")
        self.decision.unlink()
        self.assertEqual(module.select_profile(self.project, self.registry)[0]["id"], "gost-19")

    def test_conflicting_or_unknown_choice_is_rejected(self) -> None:
        for value in (
            "**Профиль требований:** sdd\n**Выбранный стандарт:** ГОСТ 34\n",
            "**Профиль требований:** unknown\n",
            "**Выбранный стандарт:** Без стандарта\n",
        ):
            with self.subTest(value=value):
                self.decision.write_text(value, encoding="utf-8")
                with self.assertRaises(module.ProfileError):
                    module.select_profile(self.project, self.registry)

    def test_explicit_sdd_can_use_legacy_no_standard_choice(self) -> None:
        self.decision.write_text(
            "**Выбранный стандарт:** Без стандарта\n**Профиль требований:** sdd\n",
            encoding="utf-8",
        )
        self.assertEqual(module.select_profile(self.project, self.registry)[0]["id"], "sdd")

    def test_examples_inside_code_fences_are_not_selected(self) -> None:
        self.decision.write_text(
            "**Профиль требований:** gost-19\n\n"
            "```text\n**Профиль требований:** iso-29148\n```\n",
            encoding="utf-8",
        )
        self.assertEqual(module.select_profile(self.project, self.registry)[0]["id"], "gost-19")

    def test_duplicate_id_and_missing_instruction_are_rejected(self) -> None:
        registry_path = self.project / ".requirements" / "требования" / "профили.json"
        registry_path.parent.mkdir(parents=True)
        data = json.loads((ROOT / ".requirements" / "требования" / "профили.json").read_text(encoding="utf-8"))
        data["profiles"][1]["id"] = "gost-19"
        registry_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(module.ProfileError):
            module.load_registry(self.project)

    def test_iso_profile_requires_pdf_source(self) -> None:
        registry_path = self.project / ".requirements" / "требования" / "профили.json"
        registry_path.parent.mkdir(parents=True)
        data = json.loads((ROOT / ".requirements" / "требования" / "профили.json").read_text(encoding="utf-8"))
        data["profiles"][-1].pop("source_document_url")
        registry_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(module.ProfileError):
            module.load_registry(self.project)

    def test_result_metadata_and_headings_are_checked(self) -> None:
        for profile in self.registry["profiles"]:
            with self.subTest(profile=profile["id"]):
                output = self.project / profile["output"]
                output.parent.mkdir(parents=True, exist_ok=True)
                metadata = (
                    f"**requirements_profile:** {profile['id']}\n"
                    f"**profile_version:** {module.read_version(ROOT)}\n"
                    f"**profile_source:** {profile['source']}\n"
                    f"**scope:** {profile['scope'][0]}\n"
                )
                if profile["id"] == "iso-29148":
                    scope = profile["scope"][0]
                    headings = (
                        "\n".join(f"## {heading} [ISO]" for heading in module.h8_required_headings(scope))
                    )
                else:
                    headings = "\n".join(f"## {section}" for section in profile["required_sections"])
                source_url = profile.get("source_document_url", "")
                iso_details = ""
                if profile["id"] == "iso-29148":
                    scope = profile["scope"][0]
                    iso_details = (
                        "**information_item:** SRS\n"
                        "**conformance_claim:** not_claimed\n"
                        "**document_readiness:** ready_for_review\n"
                        "| ID | Требование | Тип | Информационный объект/уровень | Родительские ID | Источник | Приоритет | Риск | Обоснование | Владелец | Сложность | Версия | Критерий | Метод | Статус |\n"
                        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
                        + "".join(
                            f"| {clause} | covered | раздел {clause} | решение разработчика |\n"
                            for clause in module.iso_required_clauses(scope)
                        )
                    )
                output.write_text(metadata + headings + "\n" + source_url + "\n" + iso_details,
                                  encoding="utf-8")
                module.check_result(self.project, profile, module.read_version(ROOT))
                if source_url:
                    output.write_text(metadata + headings + "\n" + iso_details, encoding="utf-8")
                    with self.assertRaises(module.ProfileError):
                        module.check_result(self.project, profile, module.read_version(ROOT))
                output.write_text(metadata.replace("**scope:**", "**wrong_scope:**") + headings + "\n" +
                                  source_url + "\n" + iso_details,
                                  encoding="utf-8")
                with self.assertRaises(module.ProfileError):
                    module.check_result(self.project, profile, module.read_version(ROOT))

    def test_iso_requires_correct_item_and_complete_clause_coverage(self) -> None:
        profile = next(p for p in self.registry["profiles"] if p["id"] == "iso-29148")
        output = self.project / profile["output"]
        output.parent.mkdir(parents=True, exist_ok=True)
        headings = (
            "\n".join(f"## {heading} [ISO]" for heading in module.h8_required_headings("system"))
        )
        base = (
            f"**requirements_profile:** iso-29148\n"
            f"**profile_version:** {module.read_version(ROOT)}\n"
            f"**profile_source:** {profile['source']}\n"
            f"{profile['source_document_url']}\n{headings}\n"
        )
        rows = "".join(f"| {clause} | covered | раздел {clause} | решение |\n"
                       for clause in module.iso_required_clauses("system"))
        valid = base + "**scope:** system\n**information_item:** SyRS\n" + \
                "**conformance_claim:** not_claimed\n" + \
                "**document_readiness:** ready_for_review\n" + \
                "| ID | Требование | Тип | Информационный объект/уровень | Родительские ID | Источник | Приоритет | Риск | Обоснование | Владелец | Сложность | Версия | Критерий | Метод | Статус |\n" + \
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n" + rows
        output.write_text(valid, encoding="utf-8")
        module.check_result(self.project, profile, module.read_version(ROOT))
        draft = valid.replace("**document_readiness:** ready_for_review",
                             "**document_readiness:** draft").replace(
                                 "| 9.5.19 | covered", "| 9.5.19 | gap")
        output.write_text(draft, encoding="utf-8")
        module.check_result(self.project, profile, module.read_version(ROOT))
        for invalid in (
            valid.replace("**information_item:** SyRS", "**information_item:** SRS"),
            valid.replace("| 9.5.19 | covered | раздел 9.5.19 | решение |\n", ""),
            valid.replace("| 9.5.19 | covered", "| 9.5.19 | gap"),
        ):
            with self.subTest(invalid=invalid[-120:]):
                output.write_text(invalid, encoding="utf-8")
                with self.assertRaises(module.ProfileError):
                    module.check_result(self.project, profile, module.read_version(ROOT))

    def test_release_package_runs_profile_selection(self) -> None:
        builder_path = ROOT / ".tools" / "sdd-template-release" / "build_release.py"
        builder_spec = importlib.util.spec_from_file_location("build_release", builder_path)
        assert builder_spec is not None and builder_spec.loader is not None
        builder = importlib.util.module_from_spec(builder_spec)
        builder_spec.loader.exec_module(builder)
        stage = self.project / "package"
        builder.build_stage(ROOT, module.read_version(ROOT), stage)
        self.decision.write_text("**Профиль требований:** iso-29148\n", encoding="utf-8")
        command = [sys.executable, "-B", str(stage / ".tools" / "requirements-profile" /
                    "requirements_profile.py"), "resolve", "--project-root", str(self.project)]
        completed = subprocess.run(command, capture_output=True, text=True, check=True)
        result = json.loads(completed.stdout)
        self.assertEqual(result["profile"], "iso-29148")
        self.assertEqual(result["profile_version"], module.read_version(ROOT))
        self.assertEqual(result["source_document_url"],
                         self.registry["profiles"][-1]["source_document_url"])
        self.assertFalse((stage / ".tools" / "requirements-profile" / "tests").exists())
        self.assertFalse((stage / ".source" / "29148-2018-ISOIECIEEE.pdf").exists())


if __name__ == "__main__":
    unittest.main()
