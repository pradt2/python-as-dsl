# Research-derived QA plan for Python analysis

This test campaign was designed without inspecting `python_analysis.py`. Existing public black-box tests were consulted only to reuse the supported API vocabulary. The research suite contains 131 independent tests in 14 areas.

## Research basis

1. Salis et al., **PyCG: Practical Call Graph Generation in Python**, ICSE 2021, DOI 10.1109/ICSE43902.2021.00146. Python call-graph construction is complicated by higher-order functions, runtime class modification, duck typing, `eval`, modules, generators, closures and multiple inheritance. Online: https://arxiv.org/abs/2103.00587
2. Oh & Oh, **Towards Effective Static Type-Error Detection for Python**, ASE 2024, DOI 10.1145/3691620.3695545. The paper uses type-based context sensitivity, preserves branch type alternatives, and limits interprocedural depth for cost. Online: https://prl.korea.ac.kr/papers/ase24_wonseok.pdf
3. Smaragdakis, Bravenboer & Lhoták, **Pick your contexts well: understanding object-sensitivity**, POPL 2011, DOI 10.1145/1926385.1926390. Context selection materially affects both precision and performance; heap/object context matters. Online: https://doi.org/10.1145/1926385.1926390
4. Jeon & Oh, **Return of CFA: Call-Site Sensitivity Can Be Superior to Object Sensitivity Even for Object-Oriented Programs**, POPL 2022, DOI 10.1145/3498720. Context design, not merely context depth, determines precision/scalability. Online: https://doi.org/10.1145/3498720
5. Lagouvardos et al., **The Incredible Shrinking Context... in a Decompiler Near You**, ISSTA 2025, DOI 10.1145/3728935. Selectively forgetting context can improve the precision/scalability trade-off. Online: https://doi.org/10.1145/3728935
6. Python typing specification: https://typing.python.org/en/latest/spec/
7. Python typing specification — overloads: https://typing.python.org/en/latest/spec/overload.html
8. Python typing specification — callables: https://typing.python.org/en/latest/spec/callables.html
9. Python typing specification — generics: https://typing.python.org/en/latest/spec/generics.html
10. Python typing specification — constructors: https://typing.python.org/en/latest/spec/constructors.html
11. Python descriptor guide / data model: https://docs.python.org/3/howto/descriptor.html
12. Bouzenia, Krishan & Pradel, **DyPyBench: A Benchmark of Executable Python Software**, FSE 2024. Dynamic traces expose limitations in Python static call-graph construction. Online: https://arxiv.org/abs/2403.00539

## Risk areas translated into tests

| Area | Main failure modes exercised |
|---|---|
| Context identity/budget | Equivalent-call canonicalisation, unnecessary value sensitivity, many nominal types, per-call-site vs per-function contexts, deterministic context sets |
| Relational correlation | Argument/return correlation, structural correlations, path-correlated arguments, avoidance of impossible Cartesian products |
| Higher-order functions | Callback arguments, function aliases, returned functions, callback unions, callable objects, bound-method aliases |
| Closures | Factory-created closures, captured-type specialisation, nonlocal/global rebinding, Python late binding |
| Dispatch | Overrides, duck typing, `super`, multiple inheritance/MRO, static/class methods, union receivers |
| Dynamic object model | Properties, data/non-data descriptors, `__getattr__`, `__getattribute__`, `setattr`/`getattr`, monkey patching, decorators, `eval`, `__new__`, metaclass `__call__` |
| Heap/aliasing | Aliased fields, callee side effects, allocation sensitivity, container mutation, returned aliases, unknown alias writes |
| Termination | Direct/mutual recursion, type-toggling recursion, polymorphic recursion, recursive containers, higher-order recursion, bounded context growth |
| Call binding | Positional-only/keyword-only, `*args`, `**kwargs`, fixed tuple unpacking, literal `**dict`, unknown unpacking, bound/unbound methods |
| Generics | `TypeVar`, PEP 695 type parameters, multiple type variables, container propagation, bounds/constraints, `Self`, generic constructors, `ParamSpec` |
| Overloads | Argument-dependent returns, methods, unions, `None`, `Literal`, implementation-vs-overload contract, `Any`, keyword-only overloads |
| Gradual types | `Any`, unknown external calls, `cast`, Optional semantics, NoReturn/Never, unknown attributes |
| Narrowing | `isinstance`, `None`, assertions, early return, `TypeGuard`, `TypeIs`, pattern matching, literal-dead branches |
| Control transfer | Raises, try/except, finally overriding return, NoReturn reachability, generators, awaitables, context-manager implicit calls, iterator protocol |

## Black-box results

### Baseline before the research-driven fixes

The frozen research suite initially ran 131 tests: 75 passed, 55 failed, and 1 errored. The error was a termination failure: a function called with 48 distinct user-defined nominal types raised `NonConvergentAnalysis` rather than converging under the advertised bounded-context strategy. The largest failure clusters were dynamic object-model semantics, generics, heap/aliasing, overloads, closures, narrowing, and implicit control-flow calls.

### After the research-driven fixes

The same 131 tests now pass unchanged. The fixes introduced an explicit absorbing widening/top state at context-budget boundaries; path-, closure-, receiver-, and heap-sensitive semantic refinement; product-preserving occurrence-level structural unions; lexical closure cells; MRO/descriptor-aware dispatch; conservative handling of dynamic attributes and unknown calls; overload/generic correlation; flow narrowing; and reachability-aware handling of `NoReturn`, context managers, iterators, exceptions, generators, and async calls.

The semantic refinement layer remains separate from the original aggregate analysis. Existing aggregate facts retain conservative whole-program information and explicit widening, while occurrence-level semantic facts can add precision without mutating the parsed representation or undoing a widening boundary. Declared annotations remain contracts rather than being overwritten by runtime-inference evidence.

Regression status after integration: all 131 research tests pass, all 192 pre-existing analysis tests pass, and the complete repository suite passes 517 tests with one pre-existing host-version-gated skip.
