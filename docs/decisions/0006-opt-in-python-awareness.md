# ADR 0006: Keep Python source awareness structural, bounded, and opt-in

- Status: Accepted
- Scope: scanner and Python preview extraction

## Context

Source structure can improve project-state recovery, but arbitrary source
ingestion can expose secrets, execute side effects, consume excessive context,
or imply semantic understanding that PMA does not provide.

## Decision

Python scanning is disabled by default and requires explicit configuration. It
uses the standard-library AST without importing or executing project code and
emits only bounded structural facts such as imports, public definitions,
signatures, bases, safe annotations, and a short module summary. Literal values
and bodies remain excluded.

## Consequences

Other programming languages remain unsupported, and the preview cannot answer
body-level or runtime questions. Failures use bounded status codes and do not
echo source excerpts or absolute paths.

## Rejected alternatives

- Enable all source scanning by default.
- Import modules to inspect their runtime objects.
- Include bodies, constants, decorator arguments, and default values.

## Reliability implications

Explicit scope, hard size limits, non-execution, and literal redaction reduce
privacy and resource risks without pretending to perform full code analysis.
