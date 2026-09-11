# Python source-capture test plan

Run `python -m unittest -v test_python_capture`, then `python -m unittest discover -p 'test_*.py'` for integration checks.

The representation tests inspect captured source structure, not inferred types, purity, mutability or control-flow facts. The resolver integration checks only that syntactic `Name` nodes in newly captured function bodies are linked to the existing sidecar; semantic analyses remain separate. No fixture executes user source.

| Group | Genuine edge cases |
| --- | --- |
| Declarations and assignment targets | Repeated names; chains versus unpacking; starred/nested targets; annotation-only versus explicit None; parenthesised annotated names; attribute/index/delete targets; all augmented operators. |
| Functions and signatures | Positional-only/default alignment; required keyword-only parameters; annotated variadics; function/argument type comments; decorators in source order; async declarations; complete ordered bodies; nested functions; lambdas. |
| Classes, imports and generics | Lexically interleaved class arguments; nested declarations; decorator syntax without interpretation; import aliases and relative levels; wildcard syntax; PEP 695 bounds, constraints, variadics and defaults. |
| Statement capture | Every host `ast.stmt` subclass; return/delete/raise/assert/expression/pass/break/continue; elif versus nested-if; loop targets/conditions/else; async loops and with; try/except*/else/finally; type comments. |
| Pattern capture | Every host `ast.pattern` subclass; value/singleton/sequence/mapping/class/star/as/or patterns; capture variables; match subjects and guards. |
| Expressions | Every host `ast.expr` subclass; every unary/binary/comparison operator; precedence; call argument ordering; starred containers/dict unpacking; slices, walrus, comprehensions, await/yield, f-strings and version-gated template strings. |
| Locations and text | UTF-8 byte columns; multiline expressions; exact source segments; escaped/raw/concatenated strings; CRLF and type-ignore comments; anonymous ASTs without locations. |
| Entry points and files | Empty/stub files; AST/source mismatch; normalised AST-only capture; syntax errors; repeated roots; file encodings; opt-in/cyclic/depth-bounded import ingestion without module execution. |
| Serialisation | Complete function/pattern graphs; concrete classes/enums/tuples; bytes, complex, ellipsis, nonfinite numbers; optional fields; shared nodes; malformed payloads; cyclic graph rejection. |
| Query/resolver integration | Structural edges excluding provenance; body traversal; pattern queries; round-trip queries; body-name links into the separate resolution sidecar; representation free of analysis/query state. |

Boundaries: the model is AST-based, not a concrete syntax tree, so comments, redundant parentheses and other CST-only spelling are not represented beyond available source provenance. All statement, expression and match-pattern forms exposed by the host AST are structured. An unknown future statement is retained as `UnsupportedStatement` rather than silently dropped; an unknown future expression or pattern fails explicitly so coverage cannot be mistaken for support. AST-only input is normalised through unparse/reparse. Host-version syntax tests are gated explicitly.

## Results on Python 3.13

- 76 source-capture tests pass; the Python-3.14 template-string test is skipped on this host.
- Coverage guards verify every host `ast.stmt`, `ast.expr` and `ast.pattern` subclass is exercised by a structured representation path.
- 150 deterministic generated expression trees are compared structurally with CPython AST and round-tripped through the codec.
- Full available integration discovery: 124 tests pass, with the same one Python-3.14 skip. This includes config lowering, shared analyses, C++ representation/specialisation and query-relation regressions.

## Changes validated by the suite

1. Function declarations now retain complete ordered bodies; docstrings remain separate while later string-expression statements are preserved.
2. Return, delete, raise, assert, expression, pass, break and continue statements are explicit model nodes.
3. `if`/`for`/`while`/`with`/`try`/`match` groups retain semantic operands, including with-items, exception aliases, type comments, match subjects, guards and every pattern form.
4. Delete targets retain delete binding context. Pattern and exception capture names use ordinary `Variable` binding occurrences, so the existing resolver can associate them with symbols.
5. Query traversal and JSON serialisation include function bodies, statement operands and pattern trees.
6. Config lowering no longer depends on parser information loss: it explicitly ignores structured `Pass` while continuing to reject syntax outside the config domain.
7. Names inside function bodies resolve to the corresponding model `Name` objects, while symbol/type/alias/mutability analyses remain external to the representation.
