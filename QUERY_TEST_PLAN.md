# Query reliability test plan

Run the focused suites with:

```sh
python -m unittest -v test_query_robustness test_query_relations
```

Run integration regressions with:

```sh
python -m unittest discover -p 'test_*.py'
```

Tests use only the standard library. Generated cases use fixed random seeds, report the seed/case on failure, and compare results against small independent reference algorithms. Counts of generated cases are separate from unittest method counts.

| Group | Contract and edge cases |
| --- | --- |
| Terminals and laziness | Empty and false-valued streams; exact consumption by first/one/take; infinite sources bounded by take; factory and selector timing; independent simultaneous iterators; fresh execution following exceptions; invalid limits. |
| Matching and paths | Boolean algebra and short-circuiting; equality versus structural patterns; missing versus None; nested mappings and sequence indices; regex/glob boundaries; user exceptions must remain visible. |
| Structural patterns | Dataclass defaults and factories; explicit default constraints; inherited/private/uninitialised slots; shared subpatterns versus cyclic patterns; leaf values and enums. |
| Traversal and relationships | Self-cycles, diamonds, overlapping roots, identity versus equality; finite-depth breadth-first order; deeply nested containers; transparent versus explicit container edges; relationship filters preserve parents. |
| Projection and distinct | Duplicate preservation, identity keys, hash collisions; generator projections, missing paths, empty outputs, live mutation, adapter propagation. |
| Grouping | Stable group/member order, composite/None/equal-but-not-identical/colliding keys; empty input; duplicate occurrences; key evaluation counts; full-input buffering; snapshot membership with original live objects. |
| Joins | All six modes versus an independent nested-loop oracle; duplicates on both sides, absent/None sides, empty sources, collisions, composite keys, self-joins, input order, replay and early termination. |
| Integration and failures | Subclass preservation, custom edge adapters, nested relation pipelines, round-trip serialisation of plain results, source errors, reserved absence marker, retry after failure. |

Scope boundaries: graph adapters must yield finite repeatable children; grouping requires a finite input and joins a finite right input. Hash/equality and key stability are supplied by callers. Factories must return fresh iterables. These are caller contracts, not guarantees that arbitrary user code terminates. Different join-side graph policies require explicit projection with the corresponding graph.

Cycle safety of graph traversal does not imply that recursive structural patterns are meaningful: recursive patterns should fail clearly instead of overflowing the Python call stack. Eq/Predicate can express an explicit identity/equality policy.

## Verification results

- 70 focused robustness tests plus 9 existing relational tests: 79 query tests.
- Independent seeded cases: 120 cyclic graphs, 100 groupings, and 600 joins across all six modes (820 cases within those tests).
- Full discovery: 118 tests passed, including config, specialisation, mutation-analysis and native C++ integration tests.
- A duplicate-key join also checks its 15,000-pair cardinality and bounded consumption.

## Defects exposed and fixed

1. `take(0)` invoked a source factory despite requiring no items; it now avoids the factory entirely.
2. A property raising `ValueError` was treated as a non-match; user failures now propagate while malformed sequence indices remain missing paths.
3. Cyclic structural patterns overflowed the call stack; compilation now rejects cycles explicitly and resets its tracking after failures.
4. Uninitialised dataclass slots crashed graph inspection; missing stored slots are now skipped.
5. Enum values exposed implementation attributes as graph edges; enums are now equality-matched leaves.
6. A non-callable source factory was accepted until execution; it now fails at query construction.
7. Supplying the outer-join absence marker as a source row was ambiguous; it is now explicitly reserved (it can be wrapped in a data record).
8. Base-class slots overwrote same-named derived slots; the most-derived slot now takes precedence.

These checks establish the tested contracts, not universal correctness for arbitrary user callbacks, malformed adapters, or unbounded input streams.
