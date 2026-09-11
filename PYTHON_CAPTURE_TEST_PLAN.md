# Python capture reliability test plan

The parser/model test campaign is intended to establish that `parse_source` captures Python source structure faithfully enough for downstream DSL and analysis consumers without executing the source.

## Core contracts

- Parsing is syntax-only. Imports are represented, not executed, unless import following is explicitly requested.
- Source locations are preserved for declarations, statements, expressions, parameters and patterns.
- Unsupported statements remain explicit `UnsupportedStatement` nodes rather than disappearing.
- Unsupported expressions and patterns fail explicitly rather than silently degrading.
- Bodies are retained recursively for functions, classes, branches, loops, exception handlers, context managers and pattern matching.
- Function signatures retain positional-only, positional-or-keyword, vararg, keyword-only and kwarg structure together with defaults and annotations.
- Expression capture preserves operator shape, calls, attributes, subscripts/slices, comprehensions, lambdas, named expressions, f-strings and container displays.
- Assignment targets preserve tuple/list destructuring, starred targets, attributes and subscripts.
- Pattern matching preserves value, singleton, sequence, mapping, class, star, as and or patterns.
- Serialisation round-trips node classes, enums, tuples and special literals; cyclic graphs are rejected explicitly.
- Query integration is external to the representation and must not mutate captured nodes.

## Test areas

1. Module declarations, imports and source locations.
2. Class declarations, bases, decorators, methods and nested declarations.
3. Function signatures, annotations, defaults and decorators.
4. Statements: assignment, augmented/annotated assignment, expression, return, raise, assert, delete, pass, break, continue, global/nonlocal, if, while, for, async for, with, async with, try, try-star and match.
5. Expressions: literals, names, operators, comparisons, calls, attributes, subscripts/slices, conditional expressions, lambdas, comprehensions, generator expressions, await/yield/yield-from, named expressions, f-strings and starred forms.
6. Targets and patterns, including nested destructuring and all match-pattern families.
7. Nested bodies and location fidelity.
8. Syntax errors and explicitly unsupported AST forms.
9. Serialisation/deserialisation fidelity and cycle rejection.
10. Querying over parsed source without representation coupling.
11. Optional import following, relative imports, cycles, missing modules and depth bounds.
12. Regression cases for Python-version AST differences.

## Scope

The source model is AST-like rather than a concrete syntax tree. It intentionally does not preserve comments, whitespace, exact token spelling or redundant parentheses. Consumers requiring formatting-preserving rewrites need a CST/token layer in addition to this model.

The parser does not claim to reproduce Python runtime semantics. Name resolution, type inference, aliasing, mutation, call targets and other semantic facts belong to the analysis layer.

## Verification

Run the focused parser suite with:

```sh
python -m unittest -v test_python_capture
```

Run the full repository with:

```sh
python -m unittest discover -p 'test_*.py'
```

The focused campaign includes representative and adversarial cases for every captured node family, location assertions, round-trip serialisation and import-following behaviour. Full-suite regressions ensure parser changes remain compatible with querying, AnalysisCore and downstream representations.
