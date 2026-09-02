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
            }
            changes = []
            sync.sync_zcode(vendors, False, changes)
            result = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(set(result["provider"]), {"gpt"})


if __name__ == "__main__":
    unittest.main()
