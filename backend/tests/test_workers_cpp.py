"""C / C++ transformer tests."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

# Skip entire module if no libclang / no compiler
HAS_LIBCLANG = os.path.exists("/opt/homebrew/opt/llvm/lib/libclang.dylib")
HAS_GPP = shutil.which("g++") is not None

if not (HAS_LIBCLANG and HAS_GPP):
    pytest.skip(
        "libclang or g++ missing",
        allow_module_level=True,
    )

from backend.workers.c_cpp.transformer import ConfuseTransformer

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def tx() -> ConfuseTransformer:
    return ConfuseTransformer()


def test_c_basic_renames_and_compiles(tx: ConfuseTransformer):
    src = (FIXTURES / "c_basic.c").read_text()
    res = tx.handle({"language_in": "c", "preset": "default", "code": src})
    assert res["status"] == "ok", res
    assert "rename" in res["applied"]
    # Original function name gone
    assert "two_sum" not in res["code"]


def test_cpp_basic_renames_and_compiles(tx: ConfuseTransformer):
    src = (FIXTURES / "cpp_basic.cpp").read_text()
    res = tx.handle({"language_in": "cpp", "preset": "default", "code": src})
    assert res["status"] == "ok", res
    assert "rename" in res["applied"]


def test_cpp_iostream_vector_parses_and_compiles(tx: ConfuseTransformer):
    src = """
#include <iostream>
#include <vector>
using namespace std;

void bubbleSort(vector<int>& arr) {
    int n = arr.size();
    for (int i = 0; i < n - 1; i++) {
        bool swapped = false;

        for (int j = 0; j < n - 1 - i; j++) {
            if (arr[j] > arr[j + 1]) {
                swap(arr[j], arr[j + 1]);
                swapped = true;
            }
        }

        if (!swapped) break;
    }
}

int main() {
    vector<int> arr = {5, 1, 4, 2, 8, 0};

    bubbleSort(arr);

    for (int x : arr) {
        cout << x << " ";
    }
    cout << endl;

    return 0;
}
"""
    res = tx.handle({"language_in": "cpp", "preset": "default", "code": src})
    assert res["status"] == "ok", res
    assert res["verify"] == "compiled"
    assert "rename" in res["applied"]
    assert "int main()" in res["code"]


def test_cpp_literal_rewrite_preserves_runtime_value(tx: ConfuseTransformer):
    src = """
#include <iostream>
int score(int x) {
    return x + 42 + 8;
}
int main() {
    std::cout << score(10) << "\\n";
    return 0;
}
"""
    res = tx.handle(
        {
            "language_in": "cpp",
            "preset": "default",
            "overrides": {"rename": False, "shuffleIncludes": False},
            "code": src,
        }
    )
    assert res["status"] == "ok", res
    assert "literalRewrite" in res["applied"]
    assert "int main()" in res["code"]
    assert any(op in res["code"] for op in (" + ", " ^ "))

    with tempfile.TemporaryDirectory() as td:
        source = Path(td) / "main.cpp"
        binary = Path(td) / "main"
        source.write_text(res["code"])
        subprocess.run(
            ["g++", "-std=c++17", str(source), "-o", str(binary)],
            check=True,
            capture_output=True,
            text=True,
        )
        run = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
    assert run.stdout.strip() == "60"


def test_cpp_invalid_target(tx: ConfuseTransformer):
    res = tx.handle({"language_in": "python", "preset": "default", "code": "x"})
    assert res["status"] == "error"
    assert res["code"] == "invalid_target_language"


def test_cpp_parse_error_envelope(tx: ConfuseTransformer):
    src = "int main( {"  # unterminated
    res = tx.handle({"language_in": "c", "preset": "default", "code": src})
    assert res["status"] == "error"
    assert res["code"] == "parse_error"
    assert res["errors"]


def test_cpp_include_shuffle_visible(tx: ConfuseTransformer):
    src = """
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(void) { return 0; }
"""
    res = tx.handle({"language_in": "c", "preset": "default", "code": src})
    assert res["status"] == "ok", res
    # Includes are still present
    assert "#include" in res["code"]
    # Three of them, in some order
    n = res["code"].count("#include")
    assert n == 3
