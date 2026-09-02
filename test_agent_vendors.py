import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import agent_vendors as sync


class ProviderResolutionTests(unittest.TestCase):
    def test_opencode_anthropic_endpoint_is_parent_of_v1(self):
        p = {"baseURL": "https://opencode.ai/zen/go/v1"}
        self.assertEqual(
            sync.provider_endpoint(p, "opencode-go", "anthropic-messages"),
            "https://opencode.ai/zen/go",
        )

    def test_explicit_endpoint_wins(self):
        p = {
            "baseURL": "https://gateway/v1",
            "anthropicBaseURL": "https://gateway/anthropic",
        }
        self.assertEqual(
            sync.provider_endpoint(p, "custom", "anthropic-messages"),
            "https://gateway/anthropic",
        )

    def test_api_key_reference_can_be_chained(self):
        providers = {
            "alias": {"apiKeyRef": "shared"},
            "shared": {"apiKeyRef": "env"},
            "env": {"apiKeyEnv": "TEST_PROVIDER_KEY"},
        }
        with mock.patch.dict("os.environ", {"TEST_PROVIDER_KEY": "secret"}):
            _, key = sync.resolve_provider(providers, "alias")
        self.assertEqual(key, "secret")

    def test_deepseek_init_prefers_majority_key(self):
        claude = {"apiKey": "old"}
        codex = {"top": {"providers": {"deepseek": {"apiKey": "new"}}}}
        pi = {"providers": {"deepseek": {"apiKey": "new"}}}
        dsh = {"credentials": {"DEEPSEEK_API_KEY": "other"}}
        result = sync.resolve_deepseek_provider(claude, codex, pi, dsh)
        self.assertEqual(result["apiKey"], "new")

    def test_zcode_sync_removes_stale_providers(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "config.json"
            path.write_text(json.dumps({"provider": {"old": {"name": "old"}}}), encoding="utf-8")
            vendors = {
                "paths": {"windows": {"zcode_config": str(path)}},
                "providers": {"gpt": {"baseURL": "https://gpt", "apiKey": "k"}},
                "agents": {
                    "zcode": {
                        "enabled": True,
                        "providers": {"gpt": {"provider": "gpt", "name": "GPT"}},
                    }
                },
                "_prune": True,
            }
            changes = []
            sync.sync_zcode(vendors, False, changes)
            result = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(set(result["provider"]), {"gpt"})

    def test_zcode_sync_keeps_stale_providers_without_prune(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "config.json"
            path.write_text(json.dumps({"provider": {"old": {"name": "old"}}}), encoding="utf-8")
            vendors = {
                "paths": {"windows": {"zcode_config": str(path)}},
                "providers": {"gpt": {"baseURL": "https://gpt", "apiKey": "k"}},
                "agents": {"zcode": {"enabled": True, "providers": {"gpt": {"provider": "gpt", "name": "GPT"}}}},
            }
            sync.sync_zcode(vendors, False, [])
            result = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(set(result["provider"]), {"old", "gpt"})

    def test_codex_uses_env_key_and_keeps_unmanaged_provider_by_default(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "config.toml"
            path.write_text(
                '[model_providers.gpt]\nbase_url = "https://old"\nexperimental_bearer_token = "secret"\n'
                '\n[model_providers.other]\nbase_url = "https://other"\n',
                encoding="utf-8",
            )
            vendors = {
                "paths": {"windows": {"codex_config": str(path), "codex_models": str(Path(td) / "models.json")}},
                "providers": {"gpt": {"baseURL": "https://gateway/v1", "apiKeyEnv": "GPT_KEY", "api": "openai-completions", "models": {"m": {}}}},
                "agents": {"codex": {"enabled": True, "defaultProvider": "gpt", "defaultModel": "m"}},
            }
            changes = []
            sync.sync_codex(vendors, False, changes)
            text = path.read_text(encoding="utf-8")
            self.assertIn('env_key = "GPT_KEY"', text)
            self.assertNotIn("experimental_bearer_token", text)
            self.assertIn("[model_providers.other]", text)
            self.assertIn('wire_api = "responses"', text)

    def test_claude_env_key_does_not_materialize_secret(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "settings.json"
            path.write_text(json.dumps({"env": {}}), encoding="utf-8")
            vendors = {
                "paths": {"windows": {"claude_settings": str(path)}},
                "providers": {"deepseek": {"apiKeyEnv": "DEEPSEEK_API_KEY", "baseURL": "https://api.deepseek.com", "models": {"m": {}}}},
                "agents": {"claude": {"enabled": True, "provider": "deepseek", "defaultModel": "m"}},
            }
            sync.sync_claude(vendors, False, [])
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("ANTHROPIC_AUTH_TOKEN", data["env"])
            self.assertNotIn("ANTHROPIC_API_KEY", data["env"])


if __name__ == "__main__":
    unittest.main()
