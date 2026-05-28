import json
import unittest
from pathlib import Path


class QualityFixtureSchemaTests(unittest.TestCase):
    def test_benchmark_v1_schema_and_seed_requirements(self):
        fixture_path = (
            Path(__file__).resolve().parent
            / "quality"
            / "fixtures"
            / "benchmark_v1.json"
        )
        self.assertTrue(fixture_path.exists(),
                        f"Missing fixture: {fixture_path}")

        data = json.loads(fixture_path.read_text(encoding="utf-8"))
        self.assertIsInstance(data, dict)
        self.assertEqual(data.get("version"), "1.0")

        prompts = data.get("prompts")
        self.assertIsInstance(prompts, list)
        self.assertGreaterEqual(len(prompts), 40)
        self.assertLessEqual(len(prompts), 60)

        required_keys = {
            "id",
            "category",
            "prompt",
            "expected_intent",
            "expected_signals",
            "requires_citation",
        }
        seen_ids = set()
        category_counts = {}

        for idx, item in enumerate(prompts):
            self.assertIsInstance(
                item, dict, f"Prompt at index {idx} must be object")
            missing = required_keys - set(item.keys())
            self.assertFalse(missing, f"Prompt {idx} missing keys: {missing}")

            prompt_id = item["id"]
            self.assertIsInstance(prompt_id, str)
            self.assertNotIn(prompt_id, seen_ids,
                             f"Duplicate prompt id: {prompt_id}")
            seen_ids.add(prompt_id)

            category = item["category"]
            self.assertIsInstance(category, str)
            self.assertNotEqual(category.strip(), "")
            category_counts[category] = category_counts.get(category, 0) + 1

            self.assertIsInstance(item["prompt"], str)
            self.assertNotEqual(item["prompt"].strip(), "")

            self.assertIsInstance(item["expected_intent"], str)
            self.assertNotEqual(item["expected_intent"].strip(), "")

            signals = item["expected_signals"]
            self.assertIsInstance(signals, list)
            self.assertGreaterEqual(len(signals), 1)
            for signal in signals:
                self.assertIsInstance(signal, str)
                self.assertNotEqual(signal.strip(), "")

            self.assertIsInstance(item["requires_citation"], bool)

        expected_categories = {
            "broad_factual",
            "narrow_entity",
            "ambiguous_multi_doc",
            "insufficient_evidence",
        }
        self.assertTrue(
            expected_categories.issubset(set(category_counts.keys())),
            f"Missing expected categories: {expected_categories - set(category_counts.keys())}",
        )

        self.assertGreaterEqual(category_counts.get("broad_factual", 0), 10)
        self.assertGreaterEqual(category_counts.get("narrow_entity", 0), 10)
        self.assertGreaterEqual(
            category_counts.get("ambiguous_multi_doc", 0), 10)


if __name__ == "__main__":
    unittest.main()
