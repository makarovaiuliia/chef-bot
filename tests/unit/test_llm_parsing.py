import pytest

from core.exceptions import LLMInvalidResponse
from core.llm import build_system_blocks, parse_json_response


def test_build_system_blocks_uses_profile():
    blocks = build_system_blocks("recipe", profile_md="# Семья\nБез лука.")
    assert len(blocks) == 2
    assert "Без лука" in blocks[1]["text"]
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert blocks[1]["cache_control"] == {"type": "ephemeral"}


def test_build_system_blocks_empty_profile_placeholder():
    blocks = build_system_blocks("recipe", profile_md="")
    assert "не заполнен" in blocks[1]["text"]


def test_plain_json():
    assert parse_json_response('{"a": 1}') == {"a": 1}


def test_fenced_json():
    text = '```json\n{"a": 1}\n```'
    assert parse_json_response(text) == {"a": 1}


def test_fenced_without_lang():
    text = '```\n{"a": 1}\n```'
    assert parse_json_response(text) == {"a": 1}


def test_invalid_json_raises():
    with pytest.raises(LLMInvalidResponse):
        parse_json_response("not json at all")
