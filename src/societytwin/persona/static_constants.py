"""Read literal constants from the experiment's adapter and runner sources without importing them.

Importing those modules would mutate sys.path and pull in the external framework; parsing their
source keeps a single source of truth for mappings and fixed IDs.
"""

from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path


def _literal(node: ast.AST):
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"frozenset", "set", "tuple"} and len(node.args) == 1:
        return _literal(node.args[0])
    return ast.literal_eval(node)


@lru_cache(maxsize=32)
def _constants(path_str: str, mtime_ns: int) -> dict:
    tree = ast.parse(Path(path_str).read_text(encoding="utf-8"))
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                out[node.targets[0].id] = _literal(node.value)
            except (ValueError, TypeError, SyntaxError):
                continue
    return out


def read_constants(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return _constants(str(path), path.stat().st_mtime_ns)
    except (SyntaxError, UnicodeDecodeError, OSError):
        return {}
