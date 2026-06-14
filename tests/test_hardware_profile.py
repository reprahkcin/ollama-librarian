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

    def test_vram_constrained_budget_overrides_ram(self):
        # Machine with 32 GB RAM but only 8 GB VRAM: VRAM is the binding constraint.
        # qwen2.5:7b estimated ~6.71 GB > VRAM safe budget (8 * 0.75 = 6.0 GB) -> caution/unsafe
        # qwen2.5:3b estimated ~3.92 GB <= 6.0 GB -> safe
        result = recommend_model(
            [
                {"name": "qwen2.5:7b", "details": {
                    "parameter_size": "7.6B", "quantization_level": "Q4_K_M"}},
                {"name": "qwen2.5:3b", "details": {
                    "parameter_size": "3.1B", "quantization_level": "Q4_K_M"}},
            ],
            {"total_memory_gb": 32.0, "gpu_vram_total_gb": 8.0},
        )
        self.assertEqual(result.get("recommended_model"), "qwen2.5:3b")
        models_by_name = {m["name"]: m for m in result.get("models", [])}
        self.assertEqual(models_by_name["qwen2.5:3b"]["safety"], "safe")
        self.assertNotEqual(models_by_name["qwen2.5:7b"]["safety"], "safe")
        # Effective safe budget should be VRAM-constrained, not RAM-constrained.
        self.assertLess(result.get("safe_budget_gb", 99.0), 10.0)

    def test_apple_silicon_unified_memory_ignores_vram(self):
        # On Apple Silicon, unified memory means RAM budget applies, not VRAM.
        # Even if gpu_vram_total_gb were somehow populated, notes gate should prevent reduction.
        result = recommend_model(
            [
                {"name": "qwen2.5:14b", "details": {
                    "parameter_size": "14.8B", "quantization_level": "Q4_K_M"}},
                {"name": "qwen2.5:7b", "details": {
                    "parameter_size": "7.6B", "quantization_level": "Q4_K_M"}},
            ],
            {"total_memory_gb": 64.0, "gpu_vram_total_gb": 8.0,
                "notes": ["apple_silicon_unified_memory"]},
        )
        # RAM budget (64 * 0.55 = 35.2 GB) should dominate; both models are safe.
        models_by_name = {m["name"]: m for m in result.get("models", [])}
        self.assertEqual(models_by_name["qwen2.5:14b"]["safety"], "safe")
        self.assertEqual(models_by_name["qwen2.5:7b"]["safety"], "safe")
        self.assertGreater(result.get("safe_budget_gb", 0.0), 10.0)


if __name__ == "__main__":
    unittest.main()
