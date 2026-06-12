import unittest

from ollama_librarian.hardware import (
    HardwareProfile,
    classify_resource_pressure,
    recommend_model,
    safety_policy_for_pressure,
)


def _profile(total_gb: int) -> HardwareProfile:
    return HardwareProfile(
        os_name="test-os",
        machine="test-machine",
        processor="test-processor",
        cpu_count=8,
        total_memory_bytes=total_gb * 1024 ** 3,
        available_memory_bytes=(total_gb // 2) * 1024 ** 3,
        load_average_1m=1.0,
        notes=[],
    )


class ModelRecommendationTests(unittest.TestCase):
    def test_recommendation_prefers_best_safe_model(self):
        result = recommend_model(
            [
                {"name": "nomic-embed-text", "size": 1000},
                {"name": "qwen2.5:14b", "size": 9 * 1024 ** 3},
                {"name": "llama3.1:8b", "size": 5 * 1024 ** 3},
            ],
            _profile(16),
        )

        self.assertEqual(result.get("recommended_model"), "llama3.1:8b")
        self.assertEqual(result.get("reason"), "best_safe_installed_model")
        names = [item.get("name") for item in result.get("models", [])]
        self.assertNotIn("nomic-embed-text", names)

    def test_recommendation_falls_back_to_smallest_when_no_safe_model_exists(self):
        result = recommend_model(
            [
                {"name": "qwen2.5:14b", "size": 9 * 1024 ** 3},
                {"name": "llama3.1:8b", "size": 5 * 1024 ** 3},
            ],
            _profile(8),
        )

        self.assertEqual(result.get("recommended_model"), "llama3.1:8b")
        self.assertIn("no_safe_model_installed", result.get("reason", ""))

    def test_recommendation_uses_ollama_show_metadata(self):
        result = recommend_model(
            [
                {
                    "name": "custom-local:latest",
                    "details": {
                        "parameter_size": "7.6B",
                        "quantization_level": "Q4_K_M",
                        "family": "llama",
                    },
                    "model_info": {
                        "llama.context_length": 8192,
                    },
                },
            ],
            _profile(16),
        )

        model = result.get("models", [])[0]
        self.assertEqual(result.get("recommended_model"),
                         "custom-local:latest")
        self.assertEqual(model.get("parameter_size_b"), 7.6)
        self.assertEqual(model.get("quantization"), "q4_k_m")
        self.assertEqual(model.get("family"), "llama")
        self.assertEqual(model.get("context_length"), 8192)
        self.assertLess(model.get("estimated_memory_gb"), 8.0)

    def test_resource_pressure_classifies_low_memory_as_critical(self):
        profile = HardwareProfile(
            os_name="test-os",
            machine="test-machine",
            processor="test-processor",
            cpu_count=8,
            total_memory_bytes=16 * 1024 ** 3,
            available_memory_bytes=1 * 1024 ** 3,
            load_average_1m=1.0,
            notes=[],
        )

        self.assertEqual(classify_resource_pressure(profile), "critical")

    def test_safety_policy_for_critical_blocks_new_work(self):
        policy = safety_policy_for_pressure("critical")

        self.assertFalse(policy.get("allow_new_work"))
        self.assertFalse(policy.get("allow_index_start"))
        self.assertTrue(policy.get("pause_index"))
        self.assertEqual(policy.get("embed_num_thread"), 1)


if __name__ == "__main__":
    unittest.main()
