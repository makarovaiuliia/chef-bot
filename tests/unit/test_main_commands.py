"""/plan всегда в списке команд и в /help — планирование базовая функция."""
from bot.handlers.start import help_text
from bot.main import bot_commands


def test_bot_commands_always_include_plan():
    cmds = [c.command for c in bot_commands()]
    assert "plan" in cmds


def test_help_text_always_includes_plan():
    assert "/plan" in help_text()
