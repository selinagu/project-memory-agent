import tempfile
import unittest
from pathlib import Path

from artifacts import ArtifactRecord
from parsers import parse_artifact
from python_source import PYTHON_MAX_BYTES, extract_python_structure


class PythonSourceExtractorTests(unittest.TestCase):
    def test_extracts_bounded_module_structure_in_source_order(self):
        source = b'''"""Synthetic module overview.\nMore detail is omitted."""
import os
from package.tools import helper

def public_function(value: int, option="BODY_SECRET") -> str:
    local_secret = "FUNCTION_BODY_SECRET"
    return local_secret

async def fetch(item, *, timeout: float = 1.5):
    return item

class Worker(BaseWorker):
    def run(self, task: Task) -> Result:
        return execute(task)

    def _private_helper(self):
        return "PRIVATE_METHOD_SECRET"
'''
        result = extract_python_structure(source)

        self.assertEqual(result.status, "parsed")
        self.assertIn("Module docstring: Synthetic module overview.", result.content)
        self.assertIn("- os", result.content)
        self.assertIn("- package.tools", result.content)
        self.assertIn("function `public_function(value: int, option = ...) -> str`", result.content)
        self.assertIn("async function `fetch(item, *, timeout: float = ...)`", result.content)
        self.assertIn("class `Worker(BaseWorker)`", result.content)
        self.assertIn("method `run(self, task: Task) -> Result`", result.content)
        self.assertNotIn("_private_helper", result.content)
        self.assertNotIn("BODY_SECRET", result.content)
        self.assertNotIn("FUNCTION_BODY_SECRET", result.content)
        self.assertNotIn("PRIVATE_METHOD_SECRET", result.content)

    def test_redacts_defaults_decorator_arguments_constants_and_annotation_literals(self):
        source = b'''from typing import Literal
API_TOKEN = "TOKEN_LITERAL_SENTINEL"

@route("decorator-secret")
def build(token="default-secret") -> Literal["annotation-secret"]:
    return API_TOKEN
'''
        result = extract_python_structure(source)

        self.assertEqual(result.status, "parsed")
        self.assertIn("build(token = ...)", result.content)
        self.assertIn("Literal[...]", result.content)
        for secret in (
            "TOKEN_LITERAL_SENTINEL",
            "decorator-secret",
            "default-secret",
            "annotation-secret",
        ):
            self.assertNotIn(secret, result.content)

    def test_static_all_names_are_included_without_other_constants(self):
        source = b'''__all__ = ["PublicClass", "public_function"]
PRIVATE_VALUE = "do-not-include"
class PublicClass:
    pass
def public_function():
    pass
'''
        result = extract_python_structure(source)

        self.assertIn("- PublicClass", result.content)
        self.assertIn("- public_function", result.content)
        self.assertNotIn("do-not-include", result.content)

    def test_syntax_error_is_bounded_and_does_not_echo_source(self):
        source = b'def broken(:\n    secret = "syntax-secret"\n'
        result = extract_python_structure(source)

        self.assertEqual(result.status, "failed")
        self.assertIn("syntax_error", result.content)
        self.assertIn("line 1", result.content)
        self.assertNotIn("syntax-secret", result.content)
        self.assertNotIn("def broken", result.content)

    def test_large_source_is_rejected_before_ast_parsing(self):
        source = b"x" * (PYTHON_MAX_BYTES + 1)
        result = extract_python_structure(source)

        self.assertEqual(result.status, "failed")
        self.assertIn("size_limit", result.content)
        self.assertEqual(result.metadata["size_limit_bytes"], PYTHON_MAX_BYTES)

    def test_python_encoding_cookie_is_respected(self):
        source = '# -*- coding: latin-1 -*-\n"""caf\xe9 module"""\ndef run():\n    pass\n'.encode("latin-1")
        result = extract_python_structure(source)

        self.assertEqual(result.status, "parsed")
        self.assertIn("caf\xe9 module", result.content)

    def test_repeated_extraction_is_deterministic(self):
        source = b"import os\ndef run(value=123):\n    return value\n"
        self.assertEqual(extract_python_structure(source), extract_python_structure(source))

    def test_parameter_kinds_are_rendered_without_default_values(self):
        source = b"def route(a, /, b: int = 3, *items, flag=True, **options):\n    pass\n"
        result = extract_python_structure(source)

        self.assertIn(
            "route(a, /, b: int = ..., *items, flag = ..., **options)",
            result.content,
        )
        self.assertNotIn("= 3", result.content)
        self.assertNotIn("= True", result.content)

    def test_symbol_limit_uses_deterministic_truncation_marker(self):
        source = "\n".join(
            f"def function_{index}():\n    pass" for index in range(60)
        ).encode("utf-8")
        result = extract_python_structure(source)

        self.assertTrue(result.metadata["truncated"])
        self.assertIn("additional definitions omitted", result.content)
        self.assertLessEqual(len(result.content), 4_000)

    def test_decode_error_does_not_echo_bytes(self):
        source = b"# coding: ascii\n# \xff DECODE_SENTINEL\n"
        result = extract_python_structure(source)

        self.assertEqual(result.status, "failed")
        self.assertIn("decode_error", result.content)
        self.assertNotIn("DECODE_SENTINEL", result.content)


class PythonParserIntegrationTests(unittest.TestCase):
    def test_parser_hashes_original_but_exposes_only_structure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_path = root / "service.py"
            source_path.write_text(
                'def run(token="parser-secret"):\n'
                '    body_secret = "body-secret"\n'
                '    return body_secret\n',
                encoding="utf-8",
            )
            artifact = ArtifactRecord(
                path="service.py",
                artifact_type="python",
                size_bytes=source_path.stat().st_size,
                modified_time="2026-01-01T00:00:00+00:00",
            )

            parsed = parse_artifact(root, artifact)

        self.assertEqual(len(parsed.content_hash), 64)
        self.assertIn("run(token = ...)", parsed.content_for_llm)
        self.assertNotIn("parser-secret", parsed.content_for_llm)
        self.assertNotIn("body-secret", parsed.content_for_llm)
        self.assertEqual(parsed.metadata["summary_strategy"], "python_ast_structure")


if __name__ == "__main__":
    unittest.main()
