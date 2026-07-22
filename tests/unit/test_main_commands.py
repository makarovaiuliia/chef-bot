"""Флаг-условные анонсы: /plan в командах и /help только при включенном флаге."""
from bot.handlers.start import help_text
from bot.main import bot_commands
from config import get_settings


def test_bot_commands_with_flag():
    cmds = [c.command for c in bot_commands(planning_enabled=True)]
    assert "plan" in cmds


def test_bot_commands_without_flag():
    cmds = [c.command for c in bot_commands(planning_enabled=False)]
    assert "plan" not in cmds


def test_help_text_follows_flag(monkeypatch):
    monkeypatch.setattr(get_settings(), "planning_enabled", True)
    assert "/plan" in help_text()
    monkeypatch.setattr(get_settings(), "planning_enabled", False)
    assert "/plan" not in help_text()
