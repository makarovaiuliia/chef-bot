import pytest

from core.exceptions import LLMInvalidResponse
from core.llm import parse_json_response


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
