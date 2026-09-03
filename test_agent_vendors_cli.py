import unittest
import io
import json
from pathlib import Path
from unittest import mock

import agent_vendors_cli as cli


class AgentVendorsCliTests(unittest.TestCase):
    def test_proposed_preserves_provider_registry_and_agent_bindings(self):
        data = {"providers": {"gpt": {"baseURL": "http://gpt"}, "opencode-go": {"baseURL": "http://oc"}, "deepseek": {}}, "agents": {"codex": {"defaultProvider": "deepseek", "defaultModel": "gpt-x", "providers": {"deepseek": {}}}, "pi": {"provider": "deepseek", "defaultModel": "oc-x", "providers": ["deepseek"]}, "dsh": {"defaultProvider": "deepseek"}, "zcode": {"providers": {"deepseek": {}}}, "claude": {"provider": "deepseek", "defaultModel": "oc-x", "flashModel": "oc-x"}}}
        selected = {"gpt": {"gpt-x": {"name": "GPT X"}}, "opencode-go": {"oc-x": {"name": "OC X"}}}
        out = cli.proposed(data, selected, {"gpt": "new-gpt", "opencode-go": "new-oc"})
        self.assertEqual(set(out["providers"]), {"gpt", "opencode-go", "deepseek"})
        self.assertEqual(out["agents"]["codex"]["defaultProvider"], "deepseek")
        self.assertEqual(out["agents"]["pi"]["providers"], ["deepseek"])
        self.assertEqual(out["agents"]["zcode"]["providers"], {"deepseek": {}})
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
        self.assertEqual(out["providers"]["gpt"]["wireApi"], "responses")

    def test_compact_agents_records_anthropic_endpoint(self):
        data = {"providers": {"gpt": {}, "opencode-go": {"baseURL": "https://oc/zen/go/v1"}}, "agents": {"claude": {"provider": "opencode-go"}}}
        out = cli.proposed(
            data,
            {"gpt": {"gpt-x": {}}, "opencode-go": {"oc-x": {}}},
            {},
            choices={"claude.defaultModel": "oc-x", "claude.flashModel": "oc-x", "claude.haikuModel": "oc-x", "claude.sonnetModel": "oc-x", "claude.opusModel": "oc-x"},
        )
        self.assertEqual(out["providers"]["opencode-go"]["anthropicBaseURL"], "https://oc/zen/go")
        self.assertEqual(out["agents"]["claude"]["provider"], "opencode-go")

    def test_gpt_defaults_to_custom_url(self):
        answers = iter(["", "https://my-gateway.example/v1", ""])
        result = cli.choose_provider_settings({}, "gpt", input_fn=lambda _: next(answers))
        self.assertEqual(result, {"baseURL": "https://my-gateway.example/v1", "api": "openai-completions"})

    def test_gpt_does_not_offer_foreign_vendor_presets(self):
        answers = iter(["", "https://gateway.example/v1", ""])
        with mock.patch("sys.stdout", new_callable=io.StringIO) as output:
            cli.choose_provider_settings({}, "gpt", input_fn=lambda _: next(answers))
        self.assertNotIn("DeepSeek", output.getvalue())
        self.assertNotIn("OpenRouter", output.getvalue())

    def test_vendor_preset_matches_provider_id(self):
        result = cli.choose_provider_settings({}, "deepseek", input_fn=lambda _: "1")
        self.assertEqual(result["baseURL"], "https://api.deepseek.com")

    def test_model_catalog_stays_scoped_to_provider(self):
        data = {
            "providers": {
                "gpt": {"models": {"gpt-5.5": {"name": "GPT 5.5"}}},
                "deepseek": {"models": {"deepseek-chat": {"name": "DeepSeek Chat"}}},
            }
        }
        catalog = cli.model_catalog(data, "gpt")
        self.assertIn("gpt-5.5", catalog)
        self.assertNotIn("deepseek-chat", catalog)

    def test_provider_add_creates_custom_provider(self):
        data = {"providers": {}}
        answers = iter(["My Gateway", "https://gateway.example/v1", "openai-responses", "MY_KEY", "manual", "model-a, model-b"])
        pid = cli.provider_add(data, "my-gateway", input_fn=lambda _: next(answers), secret_fn=lambda _: "secret")
        self.assertEqual(pid, "my-gateway")
        self.assertEqual(data["providers"][pid]["api"], "openai-responses")
        self.assertEqual(data["providers"][pid]["apiKey"], "secret")
        self.assertEqual(set(data["providers"][pid]["models"]), {"model-a", "model-b"})

    def test_discover_provider_models_reads_openai_shape(self):
        payload = json.dumps({"data": [{"id": "model-a"}, {"id": "model-b", "name": "Model B"}]}).encode()

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

        seen = {}

        def opener(request, timeout):
            seen["url"] = request.full_url
            seen["auth"] = request.headers.get("Authorization")
            return Response(payload)

        result = cli.discover_provider_models("https://gateway.example/v1/", "secret", opener)
        self.assertEqual(set(result), {"model-a", "model-b"})
        self.assertEqual(seen, {"url": "https://gateway.example/v1/models", "auth": "Bearer secret"})

    def test_provider_remove_refuses_bound_provider(self):
        data = {"providers": {"custom": {}}, "agents": {"pi": {"provider": "custom"}}}
        with self.assertRaises(ValueError):
            cli.provider_remove(data, "custom")
        cli.provider_remove(data, "custom", force=True)
        self.assertNotIn("custom", data["providers"])


if __name__ == "__main__":
    unittest.main()
