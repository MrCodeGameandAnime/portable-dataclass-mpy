import sys
import unittest
from pathlib import Path


EXTRACTION_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EXTRACTION_ROOT / "src"))

from portable_dataclass_metadata.generator import build_manifest  # noqa: E402


class ManifestValidationTests(unittest.TestCase):
    def test_field_names_must_be_an_ordered_sequence_of_unique_nonempty_strings(self):
        invalid_field_lists = (
            "name",
            ("name", "name"),
            ("",),
            (1,),
            None,
        )
        for field_names in invalid_field_lists:
            with self.subTest(field_names=field_names):
                with self.assertRaises(ValueError):
                    build_manifest(((("models", "Record"), field_names),))


if __name__ == "__main__":
    unittest.main()
