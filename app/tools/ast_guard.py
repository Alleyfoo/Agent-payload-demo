from __future__ import annotations

import ast
from typing import List


class ASTGuard(ast.NodeVisitor):
    """
    Very small AST guard to prevent dangerous imports/attributes in tool code.
    """

    def __init__(self, allow_imports: List[str]) -> None:
        self.allow_imports = set(allow_imports)
        self.errors: List[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name.split(".")[0] not in self.allow_imports:
                self.errors.append(f"Import not allowed: {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        base = node.module.split(".")[0] if node.module else ""
        if base not in self.allow_imports:
            self.errors.append(f"Import not allowed: {node.module}")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in {"__globals__", "__dict__", "__class__", "__subclasses__"}:
            self.errors.append(f"Attribute access not allowed: {node.attr}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec", "compile", "__import__"}:
            self.errors.append(f"Call not allowed: {node.func.id}")
        self.generic_visit(node)


def guard_code(code: str, allow_imports: List[str]) -> List[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"Syntax error: {exc}"]
    guard = ASTGuard(allow_imports)
    guard.visit(tree)
    return guard.errors
