from core.tools import TOOL_SCHEMAS


def test_tool_schemas_have_required_fields():
    for tool in TOOL_SCHEMAS:
        assert "name" in tool
        assert "description" in tool
        assert "input_schema" in tool
        assert tool["input_schema"]["type"] == "object"


def test_tool_names_are_unique():
    names = [t["name"] for t in TOOL_SCHEMAS]
    assert len(names) == len(set(names))
