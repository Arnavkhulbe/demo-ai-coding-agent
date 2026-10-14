"""Tests for parsing and validating the model's JSON replies."""

from __future__ import annotations

import json

import pytest

from agent.protocol import (
    DONE,
    PROPOSE_FIX,
    TOOL_ACTION,
    ProtocolError,
    build_system_prompt,
    extract_json_object,
    parse_action,
)


# -- extract_json_object -----------------------------------------------------

def test_extracts_a_plain_json_object():
    assert extract_json_object('{"a": 1}') == {"a": 1}


def test_extracts_json_from_a_markdown_fence():
    reply = 'Here you go:\n```json\n{"tool": "read_file"}\n```\nHope that helps!'
    assert extract_json_object(reply) == {"tool": "read_file"}


def test_handles_braces_inside_strings():
    reply = '{"new": "def f(): return {1: 2}", "path": "a.py"}'
    assert extract_json_object(reply)["path"] == "a.py"


def test_rejects_a_reply_without_json():
    with pytest.raises(ProtocolError, match="no JSON object"):
        extract_json_object("I could not find the bug.")


def test_rejects_an_unbalanced_object():
    with pytest.raises(ProtocolError, match="Unbalanced|no JSON object"):
        extract_json_object('{"tool": "read_file"')


def test_rejects_an_empty_reply():
    with pytest.raises(ProtocolError, match="empty reply"):
        extract_json_object("   ")


# -- parse_action: tool calls ------------------------------------------------

def test_parses_a_tool_call():
    action = parse_action('{"thought": "look", "tool": "search_code", "args": {"query": "x"}}')
    assert action.kind == TOOL_ACTION
    assert action.tool == "search_code"
    assert action.args == {"query": "x"}
    assert action.thought == "look"


def test_tool_call_without_arguments_defaults_to_empty():
    assert parse_action('{"tool": "list_files"}').args == {}


def test_tool_call_without_a_name_is_rejected():
    with pytest.raises(ProtocolError, match='"tool" field'):
        parse_action('{"action": "tool", "args": {}}')


def test_tool_arguments_must_be_an_object():
    with pytest.raises(ProtocolError, match="must be a JSON object"):
        parse_action('{"tool": "list_files", "args": ["."]}')


# -- parse_action: propose_fix ----------------------------------------------

def test_parses_a_fix_proposal():
    reply = json.dumps(
        {
            "action": "propose_fix",
            "summary": "fix the sign",
            "edits": [{"path": "calc.py", "old": "a - b", "new": "a + b"}],
        }
    )
    action = parse_action(reply)
    assert action.kind == PROPOSE_FIX
    assert action.summary == "fix the sign"
    assert action.edits[0].path == "calc.py"


def test_fix_proposal_without_edits_is_rejected():
    with pytest.raises(ProtocolError, match="non-empty list"):
        parse_action('{"action": "propose_fix", "edits": []}')


def test_fix_proposal_with_a_bad_edit_is_rejected():
    reply = json.dumps({"action": "propose_fix", "edits": [{"old": "a", "new": "b"}]})
    with pytest.raises(ProtocolError, match="'path'"):
        parse_action(reply)


# -- parse_action: done and errors ------------------------------------------

def test_parses_a_done_action():
    action = parse_action('{"action": "done", "message": "nothing to change"}')
    assert action.kind == DONE
    assert action.message == "nothing to change"


def test_rejects_an_unknown_action():
    with pytest.raises(ProtocolError, match="Unknown action"):
        parse_action('{"action": "delete_repo"}')


def test_rejects_a_reply_with_neither_tool_nor_action():
    with pytest.raises(ProtocolError, match="must contain either"):
        parse_action('{"thought": "hmm"}')


# -- prompt ------------------------------------------------------------------

def test_system_prompt_documents_every_tool_and_the_reply_format():
    prompt = build_system_prompt("/tmp/project", "python -m pytest -q")
    assert "search_code" in prompt
    assert "read_file" in prompt
    assert "list_files" in prompt
    assert "propose_fix" in prompt
    assert "python -m pytest -q" in prompt
