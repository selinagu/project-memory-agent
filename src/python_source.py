from __future__ import annotations

import ast
import io
import tokenize
from dataclasses import dataclass
from typing import Any


PYTHON_MAX_BYTES = 262_144
PYTHON_MAX_PREVIEW_CHARS = 4_000
PYTHON_MAX_DOCSTRING_CHARS = 240
PYTHON_MAX_IMPORTS = 20
PYTHON_MAX_SYMBOLS = 40
PYTHON_MAX_METHODS_PER_CLASS = 20
TRUNCATION_MARKER = "[... Python structure truncated ...]"


@dataclass(frozen=True)
class PythonSourceResult:
    status: str
    content: str
    metadata: dict[str, Any]
    warnings: tuple[str, ...] = ()


def _failure(
    code: str,
    detail: str,
    *,
    size_bytes: int,
    line: int | None = None,
) -> PythonSourceResult:
    location = f" at line {line}" if line is not None else ""
    return PythonSourceResult(
        status="failed",
        content=f"[Python source unavailable: {code}{location}.]",
        metadata={
            "summary_strategy": "python_ast_structure",
            "failure_code": code,
            "size_bytes": size_bytes,
            "size_limit_bytes": PYTHON_MAX_BYTES,
        },
        warnings=(detail,),
    )


def _bounded_text(value: str, limit: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: max(0, limit - 3)].rstrip()}..."


def _safe_annotation(node: ast.AST | None) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _safe_annotation(node.value)
        return f"{parent}.{node.attr}" if parent and parent != "..." else node.attr
    if isinstance(node, ast.Subscript):
        value = _safe_annotation(node.value)
        slice_value = _safe_annotation(node.slice)
        return f"{value}[{slice_value or '...'}]" if value else "..."
    if isinstance(node, (ast.Tuple, ast.List)):
        values = ", ".join(_safe_annotation(item) or "..." for item in node.elts)
        brackets = ("(", ")") if isinstance(node, ast.Tuple) else ("[", "]")
        return f"{brackets[0]}{values}{brackets[1]}"
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return f"{_safe_annotation(node.left) or '...'} | {_safe_annotation(node.right) or '...'}"
    if isinstance(node, ast.Constant):
        return "None" if node.value is None else "..."
    return "..."


def _format_argument(argument: ast.arg) -> str:
    annotation = _safe_annotation(argument.annotation)
    return f"{argument.arg}: {annotation}" if annotation else argument.arg


def _format_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    arguments = node.args
    positional = [*arguments.posonlyargs, *arguments.args]
    default_start = len(positional) - len(arguments.defaults)
    rendered: list[str] = []

    for index, argument in enumerate(positional):
        value = _format_argument(argument)
        if index >= default_start:
            value = f"{value} = ..."
        rendered.append(value)
        if arguments.posonlyargs and index + 1 == len(arguments.posonlyargs):
            rendered.append("/")

    if arguments.vararg is not None:
        rendered.append(f"*{_format_argument(arguments.vararg)}")
    elif arguments.kwonlyargs:
        rendered.append("*")

    for argument, default in zip(arguments.kwonlyargs, arguments.kw_defaults):
        value = _format_argument(argument)
        if default is not None:
            value = f"{value} = ..."
        rendered.append(value)

    if arguments.kwarg is not None:
        rendered.append(f"**{_format_argument(arguments.kwarg)}")

    result = f"{node.name}({', '.join(rendered)})"
    returns = _safe_annotation(node.returns)
    return f"{result} -> {returns}" if returns else result


def _import_names(tree: ast.Module) -> tuple[list[str], bool]:
    imports: list[str] = []
    seen: set[str] = set()
    total = 0
    for node in tree.body:
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * node.level
            names = [f"{prefix}{node.module or ''}"]
        for name in names:
            total += 1
            if name not in seen and len(imports) < PYTHON_MAX_IMPORTS:
                seen.add(name)
                imports.append(name)
    return imports, total > len(imports)


def _static_all(tree: ast.Module) -> list[str]:
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(target, ast.Name) and target.id == "__all__" for target in targets):
            continue
        value = node.value
        if not isinstance(value, (ast.List, ast.Tuple)):
            return []
        names = [
            item.value
            for item in value.elts
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        ]
        return names[:PYTHON_MAX_SYMBOLS]
    return []


def _definition_lines(
    tree: ast.Module,
) -> tuple[list[str], dict[str, int], bool, bool]:
    lines: list[str] = []
    counts = {"classes": 0, "functions": 0, "async_functions": 0, "methods": 0}
    private_omitted = False
    limit_truncated = False
    emitted_symbols = 0

    for node in tree.body:
        if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name.startswith("_"):
            private_omitted = True
            continue
        if emitted_symbols >= PYTHON_MAX_SYMBOLS:
            limit_truncated = True
            break
        emitted_symbols += 1

        if isinstance(node, ast.ClassDef):
            counts["classes"] += 1
            bases = [value for base in node.bases if (value := _safe_annotation(base))]
            suffix = f"({', '.join(bases)})" if bases else ""
            lines.append(f"- class `{node.name}{suffix}`")
            method_count = 0
            for child in node.body:
                if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if child.name.startswith("_"):
                    private_omitted = True
                    continue
                if method_count >= PYTHON_MAX_METHODS_PER_CLASS:
                    limit_truncated = True
                    break
                method_count += 1
                counts["methods"] += 1
                kind = "async method" if isinstance(child, ast.AsyncFunctionDef) else "method"
                lines.append(f"  - {kind} `{_format_signature(child)}`")
        else:
            key = "async_functions" if isinstance(node, ast.AsyncFunctionDef) else "functions"
            counts[key] += 1
            kind = "async function" if isinstance(node, ast.AsyncFunctionDef) else "function"
            lines.append(f"- {kind} `{_format_signature(node)}`")

    return lines, counts, private_omitted, limit_truncated


def _bounded_lines(lines: list[str]) -> tuple[str, bool]:
    selected: list[str] = []
    length = 0
    truncated = False
    for line in lines:
        added = len(line) + (1 if selected else 0)
        if length + added > PYTHON_MAX_PREVIEW_CHARS - len(TRUNCATION_MARKER) - 1:
            truncated = True
            break
        selected.append(line)
        length += added
    if truncated:
        selected.append(TRUNCATION_MARKER)
    return "\n".join(selected), truncated


def extract_python_structure(source: bytes) -> PythonSourceResult:
    size_bytes = len(source)
    if size_bytes > PYTHON_MAX_BYTES:
        return _failure(
            "size_limit",
            f"Python source exceeds the {PYTHON_MAX_BYTES}-byte parsing limit.",
            size_bytes=size_bytes,
        )

    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(source).readline)
        text = source.decode(encoding)
    except (SyntaxError, UnicodeDecodeError, LookupError) as exc:
        return _failure(
            "decode_error",
            f"Python source encoding could not be decoded: {type(exc).__name__}.",
            size_bytes=size_bytes,
        )

    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError) as exc:
        return _failure(
            "syntax_error",
            "Python source could not be parsed safely.",
            size_bytes=size_bytes,
            line=getattr(exc, "lineno", None),
        )

    docstring = ast.get_docstring(tree, clean=False)
    imports, imports_truncated = _import_names(tree)
    exported = _static_all(tree)
    definitions, counts, private_omitted, definitions_truncated = _definition_lines(tree)

    lines = ["# Python Structure"]
    if docstring:
        lines.append(
            f"Module docstring: {_bounded_text(docstring, PYTHON_MAX_DOCSTRING_CHARS)}"
        )
    if imports:
        lines.extend(["", "## Imports", *(f"- {name}" for name in imports)])
    if imports_truncated:
        lines.append("- [... additional imports omitted ...]")
    if exported:
        lines.extend(["", "## Public API (__all__)", *(f"- {name}" for name in exported)])
    lines.extend(["", "## Definitions"])
    lines.extend(definitions or ["[No public top-level definitions found.]"])
    if definitions_truncated:
        lines.append("[... additional definitions omitted ...]")

    content, length_truncated = _bounded_lines(lines)
    truncated = imports_truncated or definitions_truncated or length_truncated
    warnings = (
        ("Python structure was truncated to deterministic bounds.",)
        if truncated
        else ()
    )
    metadata = {
        "summary_strategy": "python_ast_structure",
        "encoding": encoding,
        "size_bytes": size_bytes,
        "line_count": len(text.splitlines()),
        "import_count": len(imports),
        "export_count": len(exported),
        **counts,
        "private_symbols_omitted": private_omitted,
        "truncated": truncated,
        "preview_limit_chars": PYTHON_MAX_PREVIEW_CHARS,
        "size_limit_bytes": PYTHON_MAX_BYTES,
    }
    return PythonSourceResult(
        status="parsed",
        content=content,
        metadata=metadata,
        warnings=warnings,
    )
