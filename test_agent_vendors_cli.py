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


if __name__ == "__main__":
    unittest.main()
