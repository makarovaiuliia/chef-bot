from config import Settings


def test_settings_load_from_env(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "abc")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("ALLOWLIST_TELEGRAM_IDS", "111,222")

    s = Settings(_env_file=None)
    assert s.bot_token.get_secret_value() == "abc"
    assert s.anthropic_api_key.get_secret_value() == "sk-test"
    assert s.allowlist_telegram_ids == [111, 222]
    assert s.timezone == "Asia/Bangkok"
    assert s.claude_model == "claude-sonnet-4-6"
