import unittest

import tempfile
from pathlib import Path
import zipfile

from scripts.compare_comics_alt_pipelines_local import (
    parse_pipeline,
    parse_bool,
    preset_pipelines,
    build_subset_cbz,
    select_central_page_slice,
    provider_env_key,
    huggingface_token_env_keys,
    resolve_huggingface_token,
    huggingface_cache_dir,
)


class CompareComicsAltPipelinesLocalTest(unittest.TestCase):
    def test_parse_pipeline_simple_name(self):
        spec = parse_pipeline("heuristic-ocr")
        self.assertEqual(spec.name, "heuristic-ocr")
        self.assertEqual(spec.options, {})

    def test_parse_pipeline_with_options(self):
        spec = parse_pipeline("vlm:provider=openai,model=gpt-4o-mini,track=true")
        self.assertEqual(spec.name, "vlm")
        self.assertEqual(spec.options["provider"], "openai")
        self.assertEqual(spec.options["model"], "gpt-4o-mini")
        self.assertEqual(spec.options["track"], "true")

    def test_parse_pipeline_hf_detector_name(self):
        spec = parse_pipeline(
            "hf-rtdetr-bubble-ocr:model_repo=ogkalu/comic-text-and-bubble-detector,model_file=best.pt"
        )
        self.assertEqual(spec.name, "hf-rtdetr-bubble-ocr")
        self.assertEqual(spec.options["model_repo"], "ogkalu/comic-text-and-bubble-detector")
        self.assertEqual(spec.options["model_file"], "best.pt")

    def test_parse_bool_variants(self):
        self.assertTrue(parse_bool("true"))
        self.assertTrue(parse_bool("YES"))
        self.assertFalse(parse_bool("false"))
        self.assertFalse(parse_bool("0"))

    def test_parse_bool_invalid(self):
        with self.assertRaises(ValueError):
            parse_bool("maybe")

    def test_preset_pipelines_extended_contains_expected_vlm(self):
        items = preset_pipelines("extended")
        self.assertTrue(any("provider=openai" in x for x in items))
        self.assertTrue(any("provider=gemini" in x for x in items))
        self.assertTrue(any("provider=deepseek" in x for x in items))

    def test_preset_pipelines_hf_core_contains_expected_items(self):
        items = preset_pipelines("hf-core")
        self.assertTrue(any(x.startswith("hf-rtdetr-bubble-ocr") for x in items))
        self.assertTrue(any(x.startswith("hf-panel-seg-plus-bubble-ocr") for x in items))

    def test_preset_pipelines_hf_all_contains_all_hf_variants(self):
        items = preset_pipelines("hf-all")
        self.assertTrue(any(x.startswith("hf-rtdetr-bubble-ocr") for x in items))
        self.assertTrue(any(x.startswith("hf-panel-seg-plus-bubble-ocr") for x in items))
        self.assertTrue(any(x.startswith("hf-panel-seg-plus-bubble-mask-ocr") for x in items))
        self.assertTrue(any(x.startswith("hf-local-vlm") for x in items))

    def test_build_subset_cbz_limits_pages(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            imgs = []
            for i in range(3):
                p = tmp / f"{i+1:04d}.jpg"
                p.write_bytes(b"fake")
                imgs.append(str(p))

            out = build_subset_cbz(imgs, tmp, 2)
            self.assertIsNotNone(out)
            self.assertTrue(out.exists())
            with zipfile.ZipFile(out, "r") as zf:
                self.assertEqual(len(zf.namelist()), 2)

    def test_build_subset_cbz_creates_when_limit_equals_length(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            imgs = []
            for i in range(2):
                p = tmp / f"{i+1:04d}.jpg"
                p.write_bytes(b"fake")
                imgs.append(str(p))

            out = build_subset_cbz(imgs, tmp, 2)
            self.assertIsNotNone(out)
            self.assertTrue(out.exists())
            with zipfile.ZipFile(out, "r") as zf:
                self.assertEqual(len(zf.namelist()), 2)

    def test_select_central_page_slice(self):
        arr = list(range(1, 11))
        subset, start = select_central_page_slice(arr, 4)
        self.assertEqual(subset, [4, 5, 6, 7])
        self.assertEqual(start, 3)

    def test_provider_env_key_mapping(self):
        self.assertEqual(provider_env_key("openai"), "OPENAI_API_KEY")
        self.assertEqual(provider_env_key("gemini"), "GEMINI_API_KEY")
        self.assertEqual(provider_env_key("deepseek"), "DEEPSEEK_API_KEY")
        self.assertEqual(provider_env_key("anthropic"), "ANTHROPIC_API_KEY")
        self.assertEqual(provider_env_key("qwen"), "QWEN_API_KEY")
        self.assertEqual(provider_env_key("fireworks"), "FIREWORKS_API_KEY")
        self.assertEqual(provider_env_key("fal"), "FAL_API_KEY")

    def test_huggingface_token_env_keys_priority_is_stable(self):
        self.assertEqual(
            huggingface_token_env_keys(),
            ["HF_TOKEN", "HUGGINGFACE_HUB_TOKEN", "HUGGINGFACE_TOKEN"],
        )

    def test_resolve_huggingface_token_uses_first_available_key(self):
        original_hf_token = __import__("os").environ.get("HF_TOKEN")
        original_hf_hub = __import__("os").environ.get("HUGGINGFACE_HUB_TOKEN")
        original_hf_generic = __import__("os").environ.get("HUGGINGFACE_TOKEN")
        try:
            __import__("os").environ.pop("HF_TOKEN", None)
            __import__("os").environ["HUGGINGFACE_HUB_TOKEN"] = "hub-token"
            __import__("os").environ["HUGGINGFACE_TOKEN"] = "generic-token"
            self.assertEqual(resolve_huggingface_token(), "hub-token")
        finally:
            if original_hf_token is None:
                __import__("os").environ.pop("HF_TOKEN", None)
            else:
                __import__("os").environ["HF_TOKEN"] = original_hf_token
            if original_hf_hub is None:
                __import__("os").environ.pop("HUGGINGFACE_HUB_TOKEN", None)
            else:
                __import__("os").environ["HUGGINGFACE_HUB_TOKEN"] = original_hf_hub
            if original_hf_generic is None:
                __import__("os").environ.pop("HUGGINGFACE_TOKEN", None)
            else:
                __import__("os").environ["HUGGINGFACE_TOKEN"] = original_hf_generic

    def test_huggingface_cache_dir_prefers_local_tmp_path(self):
        cache_dir = huggingface_cache_dir()
        self.assertIn("/tmp", cache_dir)

    def test_hf_core_preset_uses_real_default_filenames(self):
        items = preset_pipelines("hf-core")
        self.assertTrue(any("detector.onnx" in x for x in items))
        self.assertTrue(any("comic-speech-bubble-detector.pt" in x for x in items))


if __name__ == "__main__":
    unittest.main()
