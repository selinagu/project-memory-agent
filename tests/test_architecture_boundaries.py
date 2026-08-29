from __future__ import annotations

import ast
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

FOUNDATION_MODULES = {
    "alignment_models",
    "artifacts",
    "project_layout",
    "prompts",
    "schemas",
}
COLLECTION_MODULES = {
    "artifact_manifest",
    "git_context",
    "parsers",
    "python_source",
    "scan_project",
    "scanner_config",
}
STATE_MODULES = {
    "diff_states",
    "extract_state",
    "semantic_diff",
}
PERSISTENCE_MODULES = {
    "checkpoint_reader",
    "checkpoint_store",
}
APPLICATION_MODULES = {
    "brief",
    "checkpoint",
    "freshness",
    "memo",
    "progress_window",
    "query",
    "source_lookup",
    "status_note",
}
PRESENTATION_MODULES = {
    "render_card",
    "render_checkpoint_summary",
    "validate_state",
}
INTERFACE_MODULES = {"pma"}

ARCHITECTURE_MODULES = {
    "foundation": FOUNDATION_MODULES,
    "collection": COLLECTION_MODULES,
    "state": STATE_MODULES,
    "persistence": PERSISTENCE_MODULES,
    "application": APPLICATION_MODULES,
    "presentation": PRESENTATION_MODULES,
    "interface": INTERFACE_MODULES,
}


def _runtime_modules() -> set[str]:
    return {
        path.stem
        for path in SRC_ROOT.glob("*.py")
        if path.name != "__init__.py"
    }


def _internal_imports(module: str, runtime_modules: set[str]) -> set[str]:
    tree = ast.parse(
        (SRC_ROOT / f"{module}.py").read_text(encoding="utf-8"),
        filename=f"src/{module}.py",
    )
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            candidates = (alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            candidates = (node.module.split(".", 1)[0],)
        else:
            continue
        imported.update(name for name in candidates if name in runtime_modules)
    return imported


def _dependency_graph() -> dict[str, set[str]]:
    modules = _runtime_modules()
    return {
        module: _internal_imports(module, modules)
        for module in sorted(modules)
    }


def _find_cycles(graph: dict[str, set[str]]) -> list[tuple[str, ...]]:
    cycles: set[tuple[str, ...]] = set()
    visiting: list[str] = []
    active: set[str] = set()
    complete: set[str] = set()

    def canonicalize(cycle: list[str]) -> tuple[str, ...]:
        body = cycle[:-1]
        rotations = [tuple(body[index:] + body[:index]) for index in range(len(body))]
        return min(rotations)

    def visit(module: str) -> None:
        if module in complete:
            return
        if module in active:
            start = visiting.index(module)
            cycles.add(canonicalize(visiting[start:] + [module]))
            return
        active.add(module)
        visiting.append(module)
        for dependency in sorted(graph[module]):
            visit(dependency)
        visiting.pop()
        active.remove(module)
        complete.add(module)

    for module in sorted(graph):
        visit(module)
    return sorted(cycles)


class ArchitectureBoundaryTests(unittest.TestCase):
    def test_every_runtime_module_has_exactly_one_architecture_area(self):
        classified = [
            module
            for modules in ARCHITECTURE_MODULES.values()
            for module in modules
        ]

        self.assertEqual(len(classified), len(set(classified)))
        self.assertEqual(set(classified), _runtime_modules())

    def test_runtime_dependency_graph_has_no_cycles(self):
        self.assertEqual(_find_cycles(_dependency_graph()), [])

    def test_cli_is_not_imported_by_runtime_modules(self):
        graph = _dependency_graph()
        reverse_importers = {
            module for module, dependencies in graph.items() if "pma" in dependencies
        }

        self.assertEqual(reverse_importers, set())

    def test_foundation_modules_do_not_depend_on_higher_layers(self):
        graph = _dependency_graph()
        dependencies = {
            module: graph[module]
            for module in sorted(FOUNDATION_MODULES)
            if graph[module]
        }

        self.assertEqual(dependencies, {})

    def test_checkpoint_store_is_independent_of_application_and_collection(self):
        graph = _dependency_graph()
        forbidden = (
            COLLECTION_MODULES
            | STATE_MODULES
            | APPLICATION_MODULES
            | PRESENTATION_MODULES
            | INTERFACE_MODULES
        )

        self.assertEqual(graph["checkpoint_store"] & forbidden, set())

    def test_checkpoint_reader_depends_only_on_foundation_models(self):
        graph = _dependency_graph()

        self.assertLessEqual(graph["checkpoint_reader"], FOUNDATION_MODULES)


if __name__ == "__main__":
    unittest.main()
