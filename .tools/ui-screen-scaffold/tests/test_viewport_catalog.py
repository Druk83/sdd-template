import json
import unittest
from datetime import date
from pathlib import Path


CATALOG_DIR = Path(__file__).resolve().parents[1] / "catalog"
CATALOG_PATH = CATALOG_DIR / "viewport-profiles.json"
SCHEMA_PATH = CATALOG_DIR / "viewport-profiles.schema.json"
SHELLS_DIR = CATALOG_DIR.parent / "shells"
SHELL_LIBRARY_PATH = SHELLS_DIR / "shell-library.json"
SHELL_LIBRARY_SCHEMA_PATH = SHELLS_DIR / "shell-library.schema.json"


class ViewportCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.shell_library = json.loads(SHELL_LIBRARY_PATH.read_text(encoding="utf-8"))
        cls.shell_library_schema = json.loads(SHELL_LIBRARY_SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_catalog_and_schema_are_valid_json(self) -> None:
        self.assertEqual(self.schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertEqual(self.catalog["schema_version"], "1.0")
        self.assertEqual(self.catalog["status"], "confirmed")
        self.assertEqual(self.shell_library_schema["$schema"], self.schema["$schema"])

    def test_local_schema_references_resolve(self) -> None:
        refs: list[str] = []

        def collect(value: object) -> None:
            if isinstance(value, dict):
                ref = value.get("$ref")
                if isinstance(ref, str):
                    refs.append(ref)
                for child in value.values():
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)

        collect(self.schema)
        for ref in refs:
            self.assertTrue(ref.startswith("#/"), ref)
            node: object = self.schema
            for part in ref.removeprefix("#/").split("/"):
                if not isinstance(node, dict):
                    raise AssertionError(f"Ссылка JSON Schema указывает не на объект: {ref}")
                key = part.replace("~1", "/").replace("~0", "~")
                if key not in node:
                    raise AssertionError(f"В ссылке JSON Schema отсутствует ключ: {ref}")
                node = node[key]

    def test_source_ids_and_profile_ids_are_unique(self) -> None:
        source_ids = [source["source_id"] for source in self.catalog["sources"]]
        profile_ids = [profile["profile_id"] for profile in self.catalog["profiles"]]
        self.assertEqual(len(source_ids), len(set(source_ids)))
        self.assertEqual(len(profile_ids), len(set(profile_ids)))

    def test_every_profile_and_variant_references_known_sources(self) -> None:
        source_ids = {source["source_id"] for source in self.catalog["sources"]}
        for profile in self.catalog["profiles"]:
            self.assertTrue(profile["source_refs"])
            self.assertLessEqual(set(profile["source_refs"]), source_ids)
            for variant in profile["variants"]:
                self.assertTrue(variant["source_refs"])
                self.assertLessEqual(set(variant["source_refs"]), source_ids)

    def test_viewport_and_shell_candidate_ids_are_unique(self) -> None:
        variants = [variant for profile in self.catalog["profiles"] for variant in profile["variants"]]
        viewport_ids = [variant["viewport_id"] for variant in variants]
        shell_ids = [variant["shell_id_candidate"] for variant in variants]
        self.assertEqual(len(viewport_ids), len(set(viewport_ids)))
        self.assertEqual(len(shell_ids), len(set(shell_ids)))

    def test_viewport_geometry_matches_declared_orientation(self) -> None:
        for profile in self.catalog["profiles"]:
            for variant in profile["variants"]:
                self.assertGreater(variant["width"], 0)
                self.assertGreater(variant["height"], 0)
                self.assertEqual(variant["unit"], "css-px")
                if variant["orientation"] == "portrait":
                    self.assertLess(variant["width"], variant["height"], variant["viewport_id"])
                else:
                    self.assertGreater(variant["width"], variant["height"], variant["viewport_id"])
                expected_status = "implemented" if profile["status"] == "confirmed" else "not_implemented"
                self.assertEqual(variant["implementation_status"], expected_status)

    def test_sources_have_review_dates_and_complete_provenance(self) -> None:
        for source in self.catalog["sources"]:
            date.fromisoformat(source["retrieved_at"])
            self.assertTrue(source["revision"])
            self.assertTrue(source["limitations"])
            if source["url"] is None:
                self.assertEqual(source["kind"], "developer-provided-example")
            else:
                self.assertTrue(source["url"].startswith("https://"))

    def test_physical_screen_is_separate_from_css_viewport(self) -> None:
        for profile in self.catalog["profiles"]:
            for variant in profile["variants"]:
                physical = variant.get("physical_screen")
                if physical is not None:
                    self.assertEqual(physical["unit"], "emulated-screen-px")
                    self.assertNotEqual(
                        (physical["width"], physical["height"]),
                        (variant["width"], variant["height"]),
                    )
                if "device_scale_factor" in variant:
                    self.assertGreater(variant["device_scale_factor"], 0)

    def test_recorded_profile_decision_matches_catalog_statuses(self) -> None:
        decision = self.catalog["developer_decision"]
        self.assertEqual(decision["status"], "recorded")
        confirmed = set(decision["confirmed_profile_ids"])
        rejected = set(decision["rejected_profile_ids"])
        profile_statuses = {profile["profile_id"]: profile["status"] for profile in self.catalog["profiles"]}
        self.assertEqual(confirmed, {key for key, value in profile_statuses.items() if value == "confirmed"})
        self.assertEqual(rejected, {key for key, value in profile_statuses.items() if value == "rejected"})
        self.assertEqual(self.catalog["status"], "confirmed")

    def test_deviceatlas_mobile_profiles_keep_measured_and_transposed_sizes_distinct(self) -> None:
        source = next(
            item
            for item in self.catalog["sources"]
            if item["source_id"] == "deviceatlas-mobile-viewport-study-2026-05"
        )
        self.assertIn("DeviceAtlas service traffic", source["limitations"])
        self.assertIn("no measured landscape", source["limitations"])

        profile = next(
            item
            for item in self.catalog["profiles"]
            if item["profile_id"] == "gui-mobile-common-pixel-412"
        )
        self.assertEqual(profile["status"], "confirmed")
        dimensions = {(item["width"], item["height"]) for item in profile["variants"]}
        self.assertEqual(dimensions, {(412, 915), (915, 412)})
        self.assertIn("412×914", profile["rationale"])

    def test_device_frame_is_excluded(self) -> None:
        self.assertEqual(self.catalog["shell_contract"]["device_frame"]["status"], "excluded")

    def test_wide_desktop_remains_gap_without_an_exact_css_viewport(self) -> None:
        profile = next(item for item in self.catalog["profiles"] if item["category"] == "wide-desktop")
        self.assertEqual(profile["status"], "gap")
        self.assertEqual(profile["variants"], [])
        self.assertTrue(profile["decision_needed"])

    def test_shell_library_covers_every_confirmed_profile_variant_once(self) -> None:
        catalog_variants = {
            variant["shell_id_candidate"]: (profile, variant)
            for profile in self.catalog["profiles"]
            if profile["status"] == "confirmed"
            for variant in profile["variants"]
        }
        library_shells = self.shell_library["shells"]
        shell_ids = [shell["shell_id"] for shell in library_shells]
        self.assertEqual(len(shell_ids), len(set(shell_ids)))
        self.assertEqual(set(shell_ids), set(catalog_variants))
        self.assertEqual(self.shell_library["profile_catalog_revision"], self.catalog["catalog_revision"])
        self.assertEqual(self.shell_library["external_contract"], self.catalog["external_contract"])
        self.assertEqual(self.shell_library["rendering"]["device_frame"], "excluded")
        shell_css = (SHELLS_DIR / "shell.css").read_text(encoding="utf-8")
        self.assertNotIn("border:", shell_css)
        shell_schema = self.shell_library_schema["properties"]["shells"]["items"]
        self.assertTrue(set(shell_schema["required"]) <= set(shell_schema["properties"]))

        for shell in library_shells:
            self.assertTrue(set(shell_schema["required"]) <= set(shell))
            profile, variant = catalog_variants[shell["shell_id"]]
            self.assertEqual(shell["profile_id"], profile["profile_id"])
            self.assertEqual(shell["viewport_id"], variant["viewport_id"])
            self.assertEqual((shell["width"], shell["height"]), (variant["width"], variant["height"]))
            self.assertEqual(shell["orientation"], variant["orientation"])
            self.assertEqual(shell["unit"], "css-px")
            self.assertEqual(shell["shell_version"], "1.0.0")
            self.assertEqual(len(shell["shell_version"].split(".")), 3)
            self.assertEqual(shell["safe_area_status"], variant["safe_area_status"])
            self.assertEqual(variant["implementation_status"], "implemented")

            html_path = SHELLS_DIR / shell["path"]
            stylesheet_path = (html_path.parent / shell["stylesheet"]).resolve()
            self.assertTrue(html_path.is_file(), shell["path"])
            self.assertEqual(stylesheet_path, (SHELLS_DIR / "shell.css").resolve())
            html = html_path.read_text(encoding="utf-8")
            self.assertIn('name="viewport"', html)
            self.assertIn(f'--viewport-width: {shell["width"]}px', html)
            self.assertIn(f'--viewport-height: {shell["height"]}px', html)
            self.assertIn('data-slot-id="screen-content"', html)
            self.assertNotIn("https://", html)

    def test_shell_index_links_to_every_library_entry(self) -> None:
        index = (SHELLS_DIR / "index.html").read_text(encoding="utf-8")
        for shell in self.shell_library["shells"]:
            self.assertIn(f'href="{shell["path"]}"', index)


if __name__ == "__main__":
    unittest.main()
