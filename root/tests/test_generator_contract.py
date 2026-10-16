import sys
import tempfile
import unittest
from pathlib import Path


EXTRACTION_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = EXTRACTION_ROOT / "src"
sys.path.insert(0, str(SOURCE_ROOT))

from portable_dataclass_metadata.generator import (  # noqa: E402
    UnsafeImportError,
    build_manifest,
    discover_native_dataclasses,
    render_manifest,
)


class GeneratorContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=str(Path(__file__).resolve().parent))
        self.fixture_root = Path(self.temp.name)
        self.source_root = self.fixture_root / "src"
        self.source_root.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def write_module(self, package_name, module_text, relative_path="models.py"):
        package_root = self.source_root / package_name
        package_root.mkdir(parents=True, exist_ok=True)
        (package_root / "__init__.py").write_text("", encoding="utf-8")
        current = package_root
        for part in Path(relative_path).parts[:-1]:
            current = current / part
            current.mkdir(parents=True, exist_ok=True)
            init_file = current / "__init__.py"
            if not init_file.exists():
                init_file.write_text("", encoding="utf-8")
        module_path = self.source_root / package_name / relative_path
        module_path.parent.mkdir(parents=True, exist_ok=True)
        module_path.write_text(module_text, encoding="utf-8")
        return module_path

    def test_explicit_scan_root_excludes_valid_out_of_scope_dataclass(self):
        package_name = "fixture_nested"
        module_path = self.write_module(
            package_name,
            """
from dataclasses import dataclass

@dataclass
class Outer:
    value: int

""",
        )
        other_path = self.source_root / "ignored.py"
        other_path.write_text(
            "from dataclasses import dataclass\n@dataclass\nclass Ignored:\n    x: int\n",
            encoding="utf-8",
        )

        records = discover_native_dataclasses(
            self.source_root, [module_path.parent]
        )

        self.assertEqual(
            records,
            (
                ((package_name + ".models", "Outer"), ("value",)),
            ),
        )

    def test_rendering_is_deterministic_and_manifest_rejects_duplicates(self):
        records = (
            (("pkg.models", "Second"), ("b",)),
            (("pkg.models", "First"), ("a",)),
        )
        self.assertEqual(render_manifest(records), render_manifest(reversed(records)))
        self.assertIn("('pkg.models', 'First')", render_manifest(records))
        with self.assertRaisesRegex(ValueError, "duplicate dataclass manifest key"):
            build_manifest((records[0], records[0]))

    def test_write_helper_creates_real_nested_packages(self):
        path = self.write_module(
            'fixture_deep',
            'from dataclasses import dataclass\n@dataclass\nclass R:\n    x: int\n',
            relative_path='sub/deeper/models.py',
        )
        self.assertTrue((self.source_root / 'fixture_deep' / '__init__.py').is_file())
        self.assertTrue((path.parent / '__init__.py').is_file())
        self.assertTrue((path.parent.parent / '__init__.py').is_file())
        self.assertEqual(discover_native_dataclasses(self.source_root, [path]),
                         ((('fixture_deep.sub.deeper.models', 'R'), ('x',)),))

    def test_terminal_input_is_rejected_during_import(self):
        module_path = self.write_module(
            "fixture_input",
            """
from dataclasses import dataclass

@dataclass
class Record:
    value: int

def ask():
    return input("unsafe")

ask()
""",
        )
        with self.assertRaises(UnsafeImportError):
            discover_native_dataclasses(self.source_root, [module_path.parent])

    def test_scan_root_outside_source_root_is_rejected(self):
        outside = self.fixture_root / "outside"
        outside.mkdir()
        with self.assertRaisesRegex(ValueError, "scan root must be inside source root"):
            discover_native_dataclasses(self.source_root, [outside])

    def test_scan_root_symlink_is_rejected(self):
        target = self.source_root / "linked_package"
        target.mkdir()
        (target / "__init__.py").write_text("", encoding="utf-8")
        (target / "models.py").write_text(
            "from dataclasses import dataclass\n"
            "@dataclass\n"
            "class Sample:\n"
            "    value: int\n",
            encoding="utf-8",
        )
        alias = self.source_root / "scan_alias"
        try:
            alias.symlink_to(target, target_is_directory=True)
        except OSError as error:
            self.skipTest("directory symlinks unavailable: %s" % error)

        with self.assertRaisesRegex(ValueError, "scan root must not be a symlink"):
            discover_native_dataclasses(self.source_root, [alias])

    def test_repeated_discovery_uses_the_requested_source_tree(self):
        package_name = "fixture_reused_module_name"
        roots = []
        for dirname, field_name in (("first", "first_value"), ("second", "second_value")):
            source_root = self.fixture_root / dirname
            package_root = source_root / package_name
            package_root.mkdir(parents=True)
            (source_root / "fixture_reused_helper.py").write_text(
                "from dataclasses import dataclass\n"
                "@dataclass\n"
                "class Base:\n"
                "    %s: int\n" % field_name,
                encoding="utf-8",
            )
            (package_root / "__init__.py").write_text("", encoding="utf-8")
            (package_root / "models.py").write_text(
                "from dataclasses import dataclass\n"
                "from fixture_reused_helper import Base\n"
                "@dataclass\n"
                "class Record(Base):\n"
                "    pass\n",
                encoding="utf-8",
            )
            roots.append((source_root, package_root))

        first = discover_native_dataclasses(roots[0][0], [roots[0][1]])
        second = discover_native_dataclasses(roots[1][0], [roots[1][1]])

        self.assertEqual(first[0][1], ("first_value",))
        self.assertEqual(second[0][1], ("second_value",))

    def test_parent_package_imports_are_isolated_between_source_roots(self):
        package_name = "fixture_reused_parent_package"
        helper_package = "fixture_reused_dotted_helper"
        roots = []
        for dirname, field_name in (("first", "first_value"), ("second", "second_value")):
            source_root = self.fixture_root / dirname
            package_root = source_root / package_name
            helper_root = source_root / helper_package
            package_root.mkdir(parents=True)
            helper_root.mkdir()
            (source_root / "fixture_reused_config.py").write_text(
                "from dataclasses import dataclass\n"
                "@dataclass\n"
                "class Base:\n"
                "    %s: int\n" % field_name,
                encoding="utf-8",
            )
            (helper_root / "__init__.py").write_text(
                "from fixture_reused_config import Base\n", encoding="utf-8"
            )
            (helper_root / "sub.py").write_text("", encoding="utf-8")
            (package_root / "__init__.py").write_text("", encoding="utf-8")
            (package_root / "models.py").write_text(
                "from dataclasses import dataclass\n"
                "import fixture_reused_dotted_helper.sub\n"
                "@dataclass\n"
                "class Record(fixture_reused_dotted_helper.Base):\n"
                "    pass\n",
                encoding="utf-8",
            )
            roots.append((source_root, package_root))

        discover_native_dataclasses(roots[0][0], [roots[0][1]])
        second = discover_native_dataclasses(roots[1][0], [roots[1][1]])

        self.assertEqual(second[0][1], ("second_value",))

    def test_candidate_package_initializers_are_isolated_between_source_roots(self):
        package_name = "fixture_reused_candidate_package"
        roots = []
        for dirname, field_name in (("first", "first_value"), ("second", "second_value")):
            source_root = self.fixture_root / dirname
            package_root = source_root / package_name
            package_root.mkdir(parents=True)
            (source_root / "fixture_candidate_config.py").write_text(
                "from dataclasses import dataclass\n"
                "@dataclass\n"
                "class Base:\n"
                "    %s: int\n" % field_name,
                encoding="utf-8",
            )
            (package_root / "__init__.py").write_text(
                "from fixture_candidate_config import Base\n", encoding="utf-8"
            )
            (package_root / "models.py").write_text(
                "from dataclasses import dataclass\n"
                "from . import Base\n"
                "@dataclass\n"
                "class Record(Base):\n"
                "    pass\n",
                encoding="utf-8",
            )
            roots.append((source_root, package_root))

        discover_native_dataclasses(roots[0][0], [roots[0][1]])
        second = discover_native_dataclasses(roots[1][0], [roots[1][1]])

        self.assertEqual(second[0][1], ("second_value",))

    def test_classvar_metadata_is_rejected(self):
        module_path = self.write_module(
            "fixture_classvar",
            """
from dataclasses import dataclass
from typing import ClassVar

@dataclass
class Record:
    category: ClassVar[str] = "shared"
    value: int = 1
""",
        )
        with self.assertRaisesRegex(ValueError, "ClassVar and InitVar are unsupported"):
            discover_native_dataclasses(self.source_root, [module_path.parent])

    def test_initvar_metadata_is_rejected(self):
        module_path = self.write_module(
            "fixture_initvar",
            """
from dataclasses import InitVar, dataclass

@dataclass
class Record:
    supplied: InitVar[int]
    value: int

    def __post_init__(self, supplied):
        self.value += supplied
""",
        )
        with self.assertRaisesRegex(ValueError, "ClassVar and InitVar are unsupported"):
            discover_native_dataclasses(self.source_root, [module_path.parent])

    def test_unrepresentable_field_modes_and_equality_options_are_rejected(self):
        cases = (
            (
                "init_false",
                "from dataclasses import dataclass, field\n"
                "@dataclass\nclass Record:\n    value: int = field(init=False, default=1)\n",
            ),
            (
                "keyword_only",
                "from dataclasses import dataclass\n"
                "@dataclass(kw_only=True)\nclass Record:\n    value: int\n",
            ),
            (
                "compare_false",
                "from dataclasses import dataclass, field\n"
                "@dataclass\nclass Record:\n    value: int = field(compare=False, default=1)\n",
            ),
            (
                "eq_false",
                "from dataclasses import dataclass\n"
                "@dataclass(eq=False)\nclass Record:\n    value: int\n",
            ),
            (
                "ordered",
                "from dataclasses import dataclass\n"
                "@dataclass(order=True)\nclass Record:\n    value: int\n",
            ),
        )
        for package_name, module_text in cases:
            with self.subTest(package_name=package_name):
                module_path = self.write_module(package_name, module_text)
                with self.assertRaisesRegex(ValueError, "unsupported (dataclass|field)"):
                    discover_native_dataclasses(
                        self.source_root, [module_path.parent]
                    )


if __name__ == "__main__":
    unittest.main()
