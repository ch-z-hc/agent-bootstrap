import unittest
from pathlib import Path

import agent_vendors_cli as cli


class AgentVendorsCliTests(unittest.TestCase):
    def test_compact_agents_and_providers(self):
        data = {"providers": {"gpt": {"baseURL": "http://gpt"}, "opencode-go": {"baseURL": "http://oc"}, "deepseek": {}}, "agents": {"codex": {"defaultProvider": "deepseek", "defaultModel": "gpt-x", "providers": {"deepseek": {}}}, "pi": {"provider": "deepseek", "defaultModel": "oc-x", "providers": ["deepseek"]}, "dsh": {"defaultProvider": "deepseek"}, "zcode": {"providers": {"deepseek": {}}}, "claude": {"provider": "deepseek", "defaultModel": "oc-x", "flashModel": "oc-x"}}}
        selected = {"gpt": {"gpt-x": {"name": "GPT X"}}, "opencode-go": {"oc-x": {"name": "OC X"}}}
        out = cli.proposed(data, selected, {"gpt": "new-gpt", "opencode-go": "new-oc"})
        self.assertEqual(set(out["providers"]), set(cli.KEEP))
        self.assertEqual(out["agents"]["codex"]["defaultProvider"], "gpt")
        self.assertEqual(out["agents"]["pi"]["providers"], list(cli.KEEP))
        self.assertEqual(out["agents"]["pi"]["defaultModel"], "oc-x")
        self.assertEqual(set(out["agents"]["zcode"]["providers"]), set(cli.KEEP))
        self.assertEqual(out["providers"]["gpt"]["apiKey"], "new-gpt")

    def test_choose_models_numbers(self):
        catalog = {"a": {"name": "A"}, "b": {"name": "B"}, "c": {"name": "C"}}
        result = cli.choose_models("demo", catalog, input_fn=lambda _: "1,3")
        self.assertEqual(list(result), ["a", "c"])

    def test_choose_path_accepts_explicit_path(self):
        result = cli.choose_path({}, "codex_config", input_fn=lambda _: "~/custom/codex.toml")
        self.assertTrue(str(result).endswith("custom\\codex.toml") or str(result).endswith("custom/codex.toml"))

    def test_paths_are_stored_per_platform(self):
        paths = cli.choose_paths({}, input_fn=lambda _: "~/x/config")
        self.assertIn(cli.PLATFORM, paths)
        self.assertEqual(Path(paths[cli.PLATFORM]["codex_models"]).name, "models.json")

    def test_provider_api_change_updates_codex_wire_api(self):
        data = {"providers": {"gpt": {"wireApi": "responses"}, "opencode-go": {}}, "agents": {}}
        out = cli.proposed(
            data,
            {"gpt": {"gpt-x": {"name": "GPT X"}}, "opencode-go": {"oc-x": {"name": "OC X"}}},
            {},
            provider_settings={
                "gpt": {"baseURL": "https://gateway/v1", "api": "openai-completions"},
                "opencode-go": {"baseURL": "https://oc/v1", "api": "openai-completions"},
            },
        )
        self.assertEqual(out["providers"]["gpt"]["wireApi"], "chat")

    def test_compact_agents_records_anthropic_endpoint(self):
        data = {"providers": {"gpt": {}, "opencode-go": {"baseURL": "https://oc/zen/go/v1"}}, "agents": {"claude": {}}}
        out = cli.proposed(
            data,
            {"gpt": {"gpt-x": {}}, "opencode-go": {"oc-x": {}}},
            {},
            choices={"claude.defaultModel": "oc-x", "claude.flashModel": "oc-x", "claude.haikuModel": "oc-x", "claude.sonnetModel": "oc-x", "claude.opusModel": "oc-x"},
        )
        self.assertEqual(out["providers"]["opencode-go"]["anthropicBaseURL"], "https://oc/zen/go")
        self.assertEqual(out["agents"]["claude"]["anthropicBaseURL"], "https://oc/zen/go")

    def test_gpt_defaults_to_custom_url(self):
        answers = iter(["", "https://my-gateway.example/v1", ""])
        result = cli.choose_provider_settings({}, "gpt", input_fn=lambda _: next(answers))
        self.assertEqual(result, {"baseURL": "https://my-gateway.example/v1", "api": "openai-completions"})

    def test_common_vendor_preset_is_available(self):
        # Common presets are offered for the generic GPT gateway; OpenCode Go
        # keeps only endpoints known to support its dual-protocol use case.
        result = cli.choose_provider_settings({}, "gpt", input_fn=lambda _: "3")
        self.assertEqual(result["baseURL"], "https://api.deepseek.com")


if __name__ == "__main__":
    unittest.main()
