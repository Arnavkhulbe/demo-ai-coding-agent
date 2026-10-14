"""Tests for the read-only tools the model can call."""

from __future__ import annotations

import pytest

from agent.tools import list_files, read_file, run_tool, search_code
from agent.workspace import Workspace


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "shop").mkdir()
    (tmp_path / "shop" / "pricing.py").write_text(
        "def apply_discount(price, percent_off):\n"
        "    return price - price * percent_off\n"
        "\n"
        "\n"
        "def add_vat(price):\n"
        "    return price * 1.2\n",
        encoding="utf-8",
    )
    (tmp_path / "shop" / "orders.py").write_text(
        "from shop.pricing import apply_discount\n\n\ndef total(items):\n    return apply_discount(sum(items), 10)\n",
        encoding="utf-8",
    )
    (tmp_path / "notes.txt").write_text("nothing to see here\n", encoding="utf-8")
    return Workspace(tmp_path)


def test_search_reports_path_and_line_numbers(workspace):
    output = search_code(workspace, "def apply_discount")
    assert "shop/pricing.py:1:" in output
    assert "apply_discount" in output


def test_search_is_case_insensitive_by_default(workspace):
    assert "shop/pricing.py" in search_code(workspace, "APPLY_DISCOUNT")


def test_search_can_be_case_sensitive(workspace):
    assert "No matches" in search_code(workspace, "APPLY_DISCOUNT", case_sensitive=True)


def test_search_falls_back_to_literal_matching_for_regex_metacharacters(workspace):
    # "apply_discount(" is not a valid regex, so it must be escaped internally.
    output = search_code(workspace, "apply_discount(")
    assert "shop/pricing.py:1:" in output


def test_search_reports_no_matches_clearly(workspace):
    assert "No matches" in search_code(workspace, "definitely_not_present")


def test_search_stops_at_the_result_cap(tmp_path):
    # A file with far more matches than one search is allowed to return.
    (tmp_path / "big.py").write_text("match me\n" * 60, encoding="utf-8")
    output = search_code(Workspace(tmp_path), "match me")
    assert "stopped after 50 matches" in output


def test_search_can_be_limited_to_a_subdirectory(workspace):
    output = search_code(workspace, "import", path="shop")
    assert "shop/orders.py" in output
    assert "notes.txt" not in output


def test_search_rejects_an_empty_query(workspace):
    with pytest.raises(ValueError, match="non-empty"):
        search_code(workspace, "   ")


def test_read_file_returns_numbered_lines(workspace):
    output = read_file(workspace, "shop/pricing.py", start=1, end=2)
    assert "lines 1-2 of 6" in output
    assert "1 | def apply_discount" in output
    assert "2 |     return price - price * percent_off" in output


def test_read_file_can_read_a_window_in_the_middle(workspace):
    output = read_file(workspace, "shop/pricing.py", start=5, end=6)
    assert "5 | " in output
    assert "def apply_discount" not in output


def test_read_file_rejects_an_inverted_range(workspace):
    with pytest.raises(ValueError, match="must be >="):
        read_file(workspace, "shop/pricing.py", start=5, end=2)


def test_read_file_reports_empty_files(tmp_path):
    (tmp_path / "empty.py").write_text("", encoding="utf-8")
    assert "is empty" in read_file(Workspace(tmp_path), "empty.py")


def test_list_files_lists_every_file(workspace):
    output = list_files(workspace, ".")
    assert "shop/pricing.py" in output
    assert "shop/orders.py" in output
    assert "notes.txt" in output


def test_run_tool_dispatches_by_name(workspace):
    assert "shop/pricing.py" in run_tool(workspace, "search_code", {"query": "apply_discount"})


def test_run_tool_rejects_unknown_tool_names(workspace):
    with pytest.raises(ValueError, match="Unknown tool"):
        run_tool(workspace, "delete_everything", {})


def test_run_tool_rejects_unexpected_arguments(workspace):
    with pytest.raises(ValueError, match="does not accept those arguments"):
        run_tool(workspace, "read_file", {"path": "notes.txt", "sudo": True})


def test_run_tool_surfaces_sandbox_escapes_as_errors(workspace):
    with pytest.raises(ValueError, match="outside the workspace"):
        run_tool(workspace, "read_file", {"path": "../../etc/passwd"})


def test_run_tool_requires_an_argument_object(workspace):
    with pytest.raises(ValueError, match="object of arguments"):
        run_tool(workspace, "list_files", ["."])
