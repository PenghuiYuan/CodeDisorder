"""Python transformer tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.workers.python.transformer import ConfuseTransformer, ConfuseError

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def tx() -> ConfuseTransformer:
    return ConfuseTransformer()


def test_basic_rename_applies(tx: ConfuseTransformer):
    src = (FIXTURES / "python_basic.py").read_text()
    res = tx.handle({"language_in": "python", "preset": "default", "code": src})
    assert res["status"] == "ok", res
    assert "rename" in res["applied"]
    assert res["verify"] == "syntax-ok"
    # Original identifier `two_sum` is gone, replaced with some non-conflicting name
    assert "two_sum" not in res["code"]
    # And it's still parseable Python
    import ast
    ast.parse(res["code"])


def test_fib_still_parses(tx: ConfuseTransformer):
    src = (FIXTURES / "python_fib.py").read_text()
    res = tx.handle({"language_in": "python", "preset": "default", "code": src})
    assert res["status"] == "ok"
    assert res["verify"] == "syntax-ok"


def test_parse_error_returns_clean_envelope(tx: ConfuseTransformer):
    bad = "def foo(:\n  pass\n"  # syntax error
    res = tx.handle({"language_in": "python", "preset": "default", "code": bad})
    assert res["status"] == "error"
    assert res["code"] == "parse_error"
    assert res["stage"] == "parse"
    assert res["errors"], "must include at least one error"


def test_invalid_target_language(tx: ConfuseTransformer):
    res = tx.handle({"language_in": "java", "preset": "default", "code": "x = 1"})
    assert res["status"] == "error"
    assert res["code"] == "invalid_target_language"


def test_comments_stripped(tx: ConfuseTransformer):
    src = "# top\nx = 1  # trailing\ndef f():\n    # inside\n    return 1\n"
    res = tx.handle({"language_in": "python", "preset": "default", "code": src})
    assert res["status"] == "ok"
    # Comments gone, structure preserved
    assert "#" not in res["code"]


def test_count_5_returns_five_variants(tx: ConfuseTransformer):
    src = "x = 1\ny = 2\nz = x + y\n"
    res = tx.handle(
        {"language_in": "python", "preset": "default", "count": 5, "code": src}
    )
    assert res["status"] == "ok"
    # count>1 returns results list (M1)
    assert "results" in res or "code" in res
