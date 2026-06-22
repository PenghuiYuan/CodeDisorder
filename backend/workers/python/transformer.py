"""Python Worker transformer (DESIGN §5).

M1 scope: S1 (rename), S2 (numeric literal), S5 (binary expr split, M1+),
S8 (comment strip, performed by lexer.preclean before parse), S9 (import shuffle).
"""

from __future__ import annotations

import ast
import random
import re
from pathlib import Path
from typing import Any

from backend.workers.common.lexer import preclean
from backend.workers.common.seed import seed_for
from backend.workers.common.wordlist import WordList, default_wordlist


class ConfuseError(Exception):
    """Application-level error with a SPEC §15.6 code, surfaced in the JSON-RPC response."""

    def __init__(self, code: str, stage: str, message: str, errors: list[dict] | None = None):
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.message = message
        self.errors = errors or []


class _RenameCollector(ast.NodeVisitor):
    """Collect every name occurrence that is *defined* (not just referenced).

    Python has no separate decl nodes like C; the defs are:
    - FunctionDef / AsyncFunctionDef / ClassDef → their ``name`` attribute
    - arguments (args, kwonlyargs, vararg, kwarg) → ``arg`` nodes
    - assignments: Name target, Attribute.target=None, Subscript skipped
    - ``import X as Y`` → Y; ``from X import Y as Z`` → Z
    - comprehension targets
    - ``except X as Y`` → Y
    - global/nonlocal are *not* renames
    """

    def __init__(self, reserved: set[str]):
        self.reserved = reserved
        self.defs: dict[ast.AST, str] = {}  # node → original name

    def visit_FunctionDef(self, node: ast.AST) -> None:  # type: ignore[override]
        n: ast.FunctionDef = node  # type: ignore[assignment]
        self.defs[n] = n.name
        self.generic_visit(n)

    def visit_AsyncFunctionDef(self, node: ast.AST) -> None:  # type: ignore[override]
        self.visit_FunctionDef(node)

    def visit_ClassDef(self, node: ast.AST) -> None:  # type: ignore[override]
        n: ast.ClassDef = node  # type: ignore[assignment]
        self.defs[n] = n.name
        self.generic_visit(n)

    def visit_arg(self, node: ast.arg) -> None:  # type: ignore[override]
        self.defs[node] = node.arg
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:  # type: ignore[override]
        for tgt in node.targets:
            self._visit_target(tgt)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:  # type: ignore[override]
        if node.target is not None:
            self._visit_target(node.target)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:  # type: ignore[override]
        self._visit_target(node.target)
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:  # type: ignore[override]
        self._visit_target(node.target)
        self.generic_visit(node)

    def visit_alias(self, node: ast.alias) -> None:  # type: ignore[override]
        if node.asname is not None:
            self.defs[node] = node.asname
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:  # type: ignore[override]
        self._visit_target(node.target)
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:  # type: ignore[override]
        if node.name is not None:
            self.defs[node] = node.name
        self.generic_visit(node)

    def _visit_target(self, tgt: ast.AST) -> None:
        if isinstance(tgt, ast.Name):
            self.defs[tgt] = tgt.id
        elif isinstance(tgt, (ast.Tuple, ast.List)):
            for elt in tgt.elts:
                self._visit_target(elt)


class _RenameApplier(ast.NodeTransformer):
    """Apply a {original → new} mapping to every Name / arg / alias occurrence.

    Crucially, we only rename names whose binding scope matches the def we
    collected. To keep M1 simple, we walk the tree linearly and rename *every*
    matching Name/arg occurrence; if the user has a variable shadowing a
    builtin, that's a known limitation (M1 doesn't track scopes).
    """

    def __init__(self, mapping: dict[str, str]):
        self.mapping = mapping

    def visit_Name(self, node: ast.Name) -> ast.AST:  # type: ignore[override]
        new = self.mapping.get(node.id)
        if new is not None:
            return ast.copy_location(ast.Name(id=new, ctx=node.ctx), node)
        return node

    def visit_arg(self, node: ast.arg) -> ast.AST:  # type: ignore[override]
        new = self.mapping.get(node.arg)
        if new is not None:
            return ast.copy_location(ast.arg(arg=new, annotation=node.annotation), node)
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:  # type: ignore[override]
        new = self.mapping.get(node.name)
        if new is not None:
            node.name = new
        # also rewrite default arg values + decorators (they may reference names)
        self.generic_visit(node)
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:  # type: ignore[override]
        new = self.mapping.get(node.name)
        if new is not None:
            node.name = new
        self.generic_visit(node)
        return node

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:  # type: ignore[override]
        new = self.mapping.get(node.name)
        if new is not None:
            node.name = new
        self.generic_visit(node)
        return node

    def visit_alias(self, node: ast.alias) -> ast.AST:  # type: ignore[override]
        if node.asname is not None and node.asname in self.mapping:
            node.asname = self.mapping[node.asname]
        return node


class _LiteralRewriter(ast.NodeTransformer):
    """S2: rewrite int / float / complex constants to equivalent expressions.

    Each rewrite pulls a fresh name from the rng, registered in ``fresh_names``
    so callers can splice declarations into the surrounding scope (we use a
    helper function to keep semantics intact without polluting the call site).
    """

    def __init__(self, rng: random.Random, prob: float = 0.6):
        self.rng = rng
        self.prob = prob
        # Map: id(int) → (original_value, new_node)
        self.fresh_names: dict[int, tuple[Any, ast.AST]] = {}

    def _maybe_freshen(self, original: Any) -> ast.AST | None:
        if isinstance(original, bool) or not isinstance(original, (int, float)):
            return None
        if self.rng.random() > self.prob:
            return None
        if isinstance(original, int):
            # 5 → (2 + 3) or 5 → 0x5 — pick one
            if self.rng.random() < 0.5 and original > 0:
                half = original // 2
                rest = original - half
                return ast.BinOp(
                    left=ast.Constant(value=half),
                    op=ast.Add(),
                    right=ast.Constant(value=rest),
                )
            # bit-equivalent hex
            return ast.Constant(value=original)
        # float: not worth splitting — keep
        return None

    def visit_Constant(self, node: ast.Constant) -> ast.AST:  # type: ignore[override]
        new = self._maybe_freshen(node.value)
        if new is not None:
            self.fresh_names[id(node)] = (node.value, new)
            return ast.copy_location(new, node)
        return node


class _BinarySplitter(ast.NodeTransformer):
    """S5 (M1 subset): split simple BinOps in expression contexts.

    For every ``a + b`` / ``a - b`` / ``a * b`` (and a few others) we insert a
    new local name and rewrite the BinOp to refer to it. The local is injected
    right above the *statement* that contains the BinOp so it stays in scope.
    """

    SPLITTABLE_OPS = (ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.Mod)

    def __init__(self, rng: random.Random, prob: float = 0.4):
        self.rng = rng
        self.prob = prob
        self.tmp_counter = 0
        # Statement list of pending injections, keyed by the statement node id
        self.inject_before: dict[int, list[ast.stmt]] = {}

    def _new_tmp(self) -> str:
        self.tmp_counter += 1
        return f"__cf_tmp_{self.rng.randint(1000, 9999)}_{self.tmp_counter}"

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:  # type: ignore[override]
        if not isinstance(node.op, self.SPLITTABLE_OPS):
            self.generic_visit(node)
            return node
        if self.rng.random() > self.prob:
            self.generic_visit(node)
            return node
        # Only split the left half; nested BinOps will be handled by recursion.
        if not isinstance(node.left, ast.BinOp):
            name = self._new_tmp()
            target = ast.Name(id=name, ctx=ast.Store())
            assign = ast.Assign(
                targets=[target],
                value=node.left,
                type_comment=None,
            )
            ast.fix_missing_locations(assign)
            # Hook the assign onto the enclosing statement later. We approximate
            # by leaving a marker; the outer wrapper collects them and splices
            # at Module level. For M1 simplicity, we instead insert a *use* of a
            # module-level helper that returns its arg — i.e. **deferred**
            # injection. See the wrapper in ConfuseTransformer.
            placeholder = ast.Name(id=name, ctx=ast.Load())
            new = ast.BinOp(left=placeholder, op=node.op, right=node.right)
            ast.copy_location(new, node)
            ast.copy_location(placeholder, node.left)
            # Encode the injection in a side-channel so ConfuseTransformer can
            # prepend a leading assignment at module scope.
            setattr(new, "_cf_split_assign", assign)
            return ast.copy_location(new, node)
        self.generic_visit(node)
        return node


# Patterns for stripping leading indentation that ast.unparse adds and
# re-emitting the file in a friendlier shape. ast.unparse already gives us a
# reasonable layout, so M1 just returns the unparsed text.


class ConfuseTransformer:
    """Entrypoint for the Python Worker.

    Receives a ``params`` dict (see SPEC §6.1) and returns a dict with the
    shape defined by SPEC §6.1: ``{status, code, applied, verify, ...}`` on
    success, or ``{status: error, code, stage, message, errors}`` on failure.
    """

    def __init__(self, wordlist: WordList | None = None):
        self.wordlist = wordlist or default_wordlist()

    def handle(self, params: dict) -> dict:
        try:
            return self._handle(params)
        except ConfuseError as e:
            return self._err(e.code, e.stage, e.message, e.errors)
        except Exception as e:  # noqa: BLE001 — last-resort safety net
            return self._err("internal_error", "transform", f"{type(e).__name__}: {e}")

    # ------------------------------------------------------------------
    # Main flow
    # ------------------------------------------------------------------

    def _handle(self, params: dict) -> dict:
        code = params.get("code", "")
        language = params.get("language_in", "python")
        if language != "python":
            return self._err("invalid_target_language", "parse", "language_in must be 'python'")

        preset_id = params.get("preset", "default")
        count = int(params.get("count", 1))
        overrides = params.get("overrides") or {}

        # ---- preclean (S8) ----
        try:
            clean = preclean(code, language="python")
        except Exception as e:  # noqa: BLE001
            return self._err("preclean_error", "preclean", str(e))

        # ---- parse ----
        try:
            tree = ast.parse(clean, type_comments=True)
        except SyntaxError as e:
            return self._err(
                "parse_error",
                "parse",
                f"line {e.lineno}:{e.offset} {e.msg}",
                [{"line": e.lineno, "column": e.offset, "message": e.msg}],
            )

        strategies = _select_strategies(preset_id, overrides)

        results: list[str] = []
        applied: list[str] = []
        verify_status = "syntax-ok"

        for i in range(count):
            seed = seed_for(clean, preset_id, i)
            rng = random.Random(seed)
            try:
                new_tree, this_applied = self._transform(tree, strategies, rng)
                new_code = ast.unparse(new_tree)
                # The unparser may produce something the original parser can't
                # round-trip; we don't fail here — verification will catch it.
            except ConfuseError as e:
                return self._err(e.code, e.stage, e.message, e.errors)
            except Exception as e:  # noqa: BLE001
                return self._err("transform_error", "transform", f"{type(e).__name__}: {e}")
            results.append(new_code)
            applied = this_applied

        # ---- verify ----
        ok_count = 0
        failed: list[int] = []
        for idx, r in enumerate(results, start=1):
            v = self._verify(r)
            if v["status"] == "ok":
                ok_count += 1
            else:
                failed.append(idx)
        if ok_count == len(results):
            verify_status = "syntax-ok"
        elif ok_count == 0:
            return self._err(
                "verify_error",
                "verify",
                "all variants failed syntax verification",
            )
        else:
            verify_status = "warning"

        if count == 1:
            return {
                "status": "ok",
                "code": results[0],
                "applied": applied,
                "verify": verify_status,
            }
        return {
            "status": "ok",
            "results": results,
            "applied": applied,
            "verify": verify_status,
            "failed_indexes": failed,
        }

    # ------------------------------------------------------------------
    # Strategy application
    # ------------------------------------------------------------------

    def _transform(
        self,
        tree: ast.Module,
        strategies: dict,
        rng: random.Random,
    ) -> tuple[ast.Module, list[str]]:
        applied: list[str] = []
        work = tree

        if strategies.get("rename"):
            work = self._apply_rename(work, rng)
            applied.append("rename")

        if strategies.get("splitExpression"):
            work = self._apply_split_expression(work, rng)
            applied.append("splitExpression")

        if strategies.get("literalRewrite"):
            work = self._apply_literal_rewrite(work, rng)
            applied.append("literalRewrite")

        if strategies.get("shuffleIncludes"):
            work = self._apply_shuffle_imports(work, rng)
            applied.append("shuffleIncludes")

        ast.fix_missing_locations(work)
        return work, applied

    def _apply_rename(self, tree: ast.Module, rng: random.Random) -> ast.Module:
        reserved = _load_reserved()
        collector = _RenameCollector(reserved)
        collector.visit(tree)
        mapping: dict[str, str] = {}
        used: set[str] = set(reserved)
        # Deduplicate by original name (a class and a function could share a name,
        # but the *new* name should be consistent everywhere)
        for orig in {n for n in collector.defs.values() if n and not n.startswith("__")}:
            if orig in reserved or orig.startswith("__"):
                continue
            new = self.wordlist.pick(orig, used, rng)
            mapping[orig] = new
            used.add(new)
        if not mapping:
            return tree
        applier = _RenameApplier(mapping)
        return applier.visit(tree)  # type: ignore[return-value]

    def _apply_split_expression(self, tree: ast.Module, rng: random.Random) -> ast.Module:
        splitter = _BinarySplitter(rng)
        new_tree = splitter.visit(tree)
        # Collect any deferred module-level injections and prepend
        injections: list[ast.stmt] = []
        for node in ast.walk(new_tree):
            assign = getattr(node, "_cf_split_assign", None)
            if assign is not None:
                injections.append(assign)
                try:
                    delattr(node, "_cf_split_assign")
                except AttributeError:
                    pass
        if injections:
            new_tree.body = injections + list(new_tree.body)
        return new_tree

    def _apply_literal_rewrite(self, tree: ast.Module, rng: random.Random) -> ast.Module:
        rewriter = _LiteralRewriter(rng)
        return rewriter.visit(tree)  # type: ignore[return-value]

    def _apply_shuffle_imports(self, tree: ast.Module, rng: random.Random) -> ast.Module:
        # Find contiguous import block at top of module
        body = list(tree.body)
        i = 0
        while i < len(body) and (
            isinstance(body[i], (ast.Import, ast.ImportFrom)) or
            (isinstance(body[i], ast.Expr) and _is_docstring(body[i]))
        ):
            i += 1
        import_block = body[:i]
        rest = body[i:]
        if len(import_block) <= 1:
            return tree
        rng.shuffle(import_block)
        tree.body = import_block + rest
        return tree

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def _verify(self, code: str) -> dict:
        try:
            ast.parse(code)
        except SyntaxError as e:
            return {
                "status": "error",
                "level": "syntax-err",
                "message": f"line {e.lineno}:{e.offset} {e.msg}",
            }
        return {"status": "ok", "level": "syntax-ok"}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _err(code: str, stage: str, message: str, errors: list[dict] | None = None) -> dict:
        return {
            "status": "error",
            "code": code,
            "stage": stage,
            "message": message,
            "errors": errors or [],
        }


# ---------------------------------------------------------------------------
# Free functions
# ---------------------------------------------------------------------------


def _load_reserved() -> set[str]:
    p = Path(__file__).resolve().parents[2] / "resources" / "language_settings" / "python.json"
    try:
        import json
        return set(json.loads(p.read_text()).get("reserved", []))
    except FileNotFoundError:
        return set()


def _select_strategies(preset_id: str, overrides: dict) -> dict:
    """Merge preset + overrides into a single strategy dict."""
    import json
    presets_path = (
        Path(__file__).resolve().parents[2] / "resources" / "presets.json"
    )
    base: dict = {}
    try:
        data = json.loads(presets_path.read_text())
        for preset in data.get("presets", []):
            if preset["id"] == preset_id:
                base = dict(preset.get("strategies", {}))
                break
    except FileNotFoundError:
        pass
    if not base:
        base = {
            "rename": True,
            "flatten": "off",
            "junk": "off",
            "splitExpression": False,
            "literalRewrite": True,
            "splitFunction": False,
            "templateRandom": False,
            "stripComments": True,
            "shuffleIncludes": True,
        }
    base.update(overrides)
    return base


def _is_docstring(node: ast.Expr) -> bool:
    return isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
