"""Python source model + reusable lazy object-graph queries (Python 3.10+).

Run this file for examples. Standard library only; ingested code never executes.

The dataclasses are plain source data. Graph supplies a children callback; Query
knows nothing about Python. PythonQuery adds classes/functions/variables/etc.
Context manages ingestion and exposes that specialised query interface.

Queries are repeatable live plans, not snapshots. No graph traversal occurs
until all(), first(), one(), count() or exists(). all() returns a plain iterator;
first()/one() return plain objects. Re-enter querying with python_query(object).
where() filters current results; descendants()/nodes() traverse below them.
Traversal is depth-first, identity-deduplicated and cycle-safe per traversal.
recursive=False means immediate AST children, not lexical scope members.

Generic strings match exactly; PythonQuery additionally treats filter strings
as globs. Eq('Particle*') forces literal equality. Regex uses fullmatch, so use
Regex(r'Particle.*'). Boolean matchers compose with &, | and ~ as well as
AllOf/AnyOf/NoneOf. Attrs supports nested attribute/key paths ('data.value').
Model templates, e.g. Class(name=Glob('Particle*')), match non-default fields;
use Attrs(name=Eq(None)) to explicitly match a field's default value.

variables() returns Store-name and argument occurrences, not resolved symbols.
Annotations remain source spellings and AST nodes. No type inference or layout
policy is part of ingestion. Raw AST fields and locations are retained, plus
original text when supplied; AST input alone cannot recover comments/formatting.

Imports are followed statically only when enabled, within explicit search_paths.
All syntactic imports are considered, including conditional ones. Runtime hooks,
dynamic imports and extension modules are outside this prototype. Imported
modules are document roots; aliases are not resolved. JSON is representation
version 2, intentionally incompatible with the earlier prototype.
"""
from __future__ import annotations

import ast
import fnmatch
import json
import re
import tokenize
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import MISSING, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any


# Pure source representation: no query base classes or matcher sentinels.
@dataclass
class Node:
    name: str | None = None
    kind: str = ''
    annotation: str | None = None
    source: str = ''
    span: tuple = (None, None, None, None)  # UTF-8 byte columns, as in ast
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Module(Node):
    pass


@dataclass
class Class(Node):
    pass


@dataclass
class Function(Node):
    pass


@dataclass
class Variable(Node):
    pass


@dataclass
class Import(Node):
    pass


@dataclass
class Document:
    roots: list[Node] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)
    diagnostics: list[str] = field(default_factory=list)


# Generic matching: independent of every source-model class above.
class Matcher:
    def matches(self, value):
        raise NotImplementedError

    def __and__(self, other):
        return AllOf(self, other)

    def __or__(self, other):
        return AnyOf(self, other)

    def __invert__(self):
        return NoneOf(self)


@dataclass(frozen=True)
class Eq(Matcher):
    value: Any

    def matches(self, value):
        return value == self.value


@dataclass(frozen=True)
class Neq(Matcher):
    value: Any

    def matches(self, value):
        return value != self.value


@dataclass(frozen=True)
class Glob(Matcher):
    pattern: str

    def matches(self, value):
        return isinstance(value, str) and fnmatch.fnmatchcase(value, self.pattern)


@dataclass(frozen=True)
class Regex(Matcher):
    pattern: str
    flags: int = 0

    def matches(self, value):
        return isinstance(value, str) and re.fullmatch(self.pattern, value, self.flags) is not None


@dataclass(frozen=True)
class IsA(Matcher):
    kind: type | tuple[type, ...]

    def matches(self, value):
        return isinstance(value, self.kind)


@dataclass(frozen=True)
class Predicate(Matcher):
    test: Callable[[Any], bool]

    def matches(self, value):
        return bool(self.test(value))


class AllOf(Matcher):
    def __init__(self, *patterns):
        self.matchers = tuple(as_matcher(p) for p in patterns)

    def matches(self, value):
        return all(m.matches(value) for m in self.matchers)


class AnyOf(AllOf):
    def matches(self, value):
        return any(m.matches(value) for m in self.matchers)


class NoneOf(AnyOf):
    def matches(self, value):
        return not super().matches(value)


def read_path(value, path):
    for part in path.split('.'):
        value = value[part] if isinstance(value, Mapping) else getattr(value, part)
    return value


class Attrs(Matcher):
    def __init__(self, **criteria):
        self.criteria = {k: as_matcher(v) for k, v in criteria.items()}

    def matches(self, value):
        for path, matcher in self.criteria.items():
            try:
                actual = read_path(value, path)
            except (AttributeError, KeyError):
                return False  # Missing is different from present with value None.
            if not matcher.matches(actual):
                return False
        return True


def as_matcher(pattern):
    if isinstance(pattern, Matcher):
        return pattern
    if is_dataclass(pattern) and not isinstance(pattern, type):
        specified = {}
        for f in fields(pattern):
            value = getattr(pattern, f.name)
            default = f.default
            if f.default_factory is not MISSING:
                default = f.default_factory()
            if isinstance(value, Matcher) or default is MISSING or value != default:
                specified[f.name] = value
        return AllOf(IsA(type(pattern)), Attrs(**specified))
    return Eq(pattern)


# Generic graph queries. A supplier is used so each terminal starts fresh.
@dataclass(frozen=True)
class Graph:
    children: Callable[[Any], Iterable[Any]]

    def query(self, root):
        return Query(lambda: iter((root,)), self)


class Query:
    def __init__(self, supplier: Callable[[], Iterator[Any]], graph: Graph):
        self._supplier, self._graph = supplier, graph

    def _derive(self, supplier):
        return type(self)(supplier, self._graph)

    def where(self, *patterns, **criteria):
        matcher = AllOf(*patterns, Attrs(**criteria))
        return self._derive(lambda: (v for v in self._supplier() if matcher.matches(v)))

    def descendants(self, *, recursive=True, include_self=False):
        def resolve():
            seen = set()
            visited = []
            for root in self._supplier():
                # Retain visited objects to prevent id reuse for generated children.
                if include_self:
                    stack = [iter((root,))]
                else:
                    seen.add(id(root))
                    visited.append(root)
                    stack = [iter(self._graph.children(root))]
                while stack:
                    try:
                        item = next(stack[-1])
                    except StopIteration:
                        stack.pop()
                        continue
                    if id(item) in seen:
                        continue
                    seen.add(id(item))
                    visited.append(item)
                    yield item
                    if recursive:
                        stack.append(iter(self._graph.children(item)))
        return self._derive(resolve)

    def all(self):
        return iter(self._supplier())

    def first(self, default=None):
        return next(self.all(), default)

    def one(self):
        items = self.all()
        absent = object()
        first = next(items, absent)
        if first is absent or next(items, absent) is not absent:
            raise ValueError('Expected exactly one result')
        return first

    def count(self):
        return sum(1 for _ in self.all())

    def exists(self):
        absent = object()
        return next(self.all(), absent) is not absent


# Python-specific adapter: the generic engine needs no knowledge of these names.
def python_children(value):
    if isinstance(value, Document):
        yield from value.roots
    elif isinstance(value, Node):
        def collect(v):
            if isinstance(v, Node):
                yield v
            elif isinstance(v, (list, tuple)):
                for item in v:
                    yield from collect(item)
        for v in value.data.values():
            yield from collect(v)


class PythonSelectors:
    def classes(self, **kw):
        return self.nodes(Class, **kw)

    def functions(self, **kw):
        return self.nodes(Function, **kw)

    def variables(self, **kw):
        return self.nodes(Variable, **kw)

    def modules(self, **kw):
        return self.nodes(Module, **kw)

    def imports(self, **kw):
        return self.nodes(Import, **kw)


class PythonQuery(Query, PythonSelectors):
    def where(self, *patterns, **criteria):
        return super().where(*patterns, **{k: Glob(v) if isinstance(v, str) else v for k, v in criteria.items()})

    def nodes(self, kind=Node, *, like=None, recursive=True, **criteria):
        patterns = (IsA(kind),) if like is None else (IsA(kind), like)
        return self.descendants(recursive=recursive).where(*patterns, **criteria)


def python_query(root):
    return PythonQuery(lambda: iter((root,)), Graph(python_children))


@dataclass(frozen=True)
class Settings:
    follow_imports: bool = False
    search_paths: tuple[Path, ...] = ()
    max_import_depth: int = 16
    missing_imports: str = 'record'

    def __post_init__(self):
        if self.max_import_depth < 0 or self.missing_imports not in ('record', 'error'):
            raise ValueError('Invalid import settings')


class Context(PythonSelectors):
    def __init__(self, *roots, settings=None):
        self.settings = settings or Settings()
        self.document = Document()
        self._seen = set()
        for root in roots:
            self.ingest(root)

    @property
    def diagnostics(self):
        return self.document.diagnostics

    def nodes(self, *args, **kwargs):
        return python_query(self.document).nodes(*args, **kwargs)

    def to_json(self, **kwargs):
        return dumps(self.document, **kwargs)

    @classmethod
    def from_json(cls, text, *, settings=None):
        ctx = cls(settings=settings)
        ctx.document = loads(text)
        ctx._seen = {Path(n.source).resolve() for n in ctx.document.roots if not n.source.startswith('<')}
        return ctx

    def ingest_source(self, text, *, name='<memory>', filename='<memory>'):
        self.document.sources[filename] = text
        return self.ingest(ast.parse(text, filename=filename), name=name, filename=filename)

    def ingest(self, root, *, name=None, filename='<ast>', _depth=0):
        if isinstance(root, (str, Path)):
            path = Path(root).resolve()
            if path in self._seen:
                return self._seen_node(path)
            with tokenize.open(path) as stream:
                text = stream.read()
                tree = ast.parse(text, filename=str(path))
            self.document.sources[str(path)] = text
            name = name or self._module_name(path)
            filename = str(path)
        elif isinstance(root, ast.AST):
            path, tree = None, root
        else:
            raise TypeError('Expected an AST or a file path; use ingest_source for text')
        node = self._convert(tree, filename)
        if isinstance(node, Module):
            node.name = name or '<ast>'
        self.document.roots.append(node)
        if path:
            self._seen.add(path)
        if self.settings.follow_imports:
            package = (node.name if path and path.name == '__init__.py' else (name or '').rpartition('.')[0])
            self._follow(tree, package, _depth)
        return node

    def _seen_node(self, path):
        return next(n for n in self.document.roots if n.source == str(path))

    def _module_name(self, path):
        for base in self.settings.search_paths:
            try:
                parts = list(path.relative_to(Path(base).resolve()).with_suffix('').parts)
                if parts[-1] == '__init__':
                    parts.pop()
                return '.'.join(parts)
            except ValueError:
                pass
        return path.stem

    def _convert(self, obj, filename, annotation=None):
        if isinstance(obj, list):
            return [self._convert(v, filename) for v in obj]
        if not isinstance(obj, ast.AST):
            return obj
        cls = (Module if isinstance(obj, ast.Module) else
               Class if isinstance(obj, ast.ClassDef) else
               Function if isinstance(obj, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) else
               Variable if isinstance(obj, ast.arg) or isinstance(obj, ast.Name) and isinstance(obj.ctx, ast.Store) else
               Import if isinstance(obj, (ast.Import, ast.ImportFrom)) else Node)
        ann = getattr(obj, 'annotation', None) or annotation
        spelling = ast.unparse(ann) if ann is not None else None
        data = {key: self._convert(value, filename, obj.annotation if isinstance(obj, ast.AnnAssign) and key == 'target' else None)
                for key, value in ast.iter_fields(obj)}
        return cls(name=getattr(obj, 'name', getattr(obj, 'id', getattr(obj, 'arg', None))),
                   kind=obj.__class__.__name__,
                   annotation=spelling, source=filename,
                   span=tuple(getattr(obj, key, None) for key in ('lineno', 'col_offset', 'end_lineno', 'end_col_offset')),
                   data=data)

    def _find(self, name):
        if not name or any(not p.isidentifier() for p in name.split('.')):
            return None
        for base in self.settings.search_paths:
            stem = Path(base).resolve().joinpath(*name.split('.'))
            for candidate in (stem / '__init__.py', stem.with_suffix('.py')):
                if candidate.is_file():
                    return candidate
        return None

    def _follow(self, tree, package, depth):
        if depth >= self.settings.max_import_depth:
            self.diagnostics.append(f'Import depth limit reached at {package or "<root>"}')
            return
        requests = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                requests.extend((a.name, True) for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                parts = package.split('.') if package else []
                if node.level > len(parts):
                    self._missing(f'Relative import outside known package: {ast.unparse(node)}')
                    continue
                prefix = parts[:len(parts) - node.level + 1] if node.level else []
                module = '.'.join(prefix + ([node.module] if node.module else []))
                requests.append((module, True))
                requests.extend((module + '.' + a.name, False) for a in node.names if a.name != '*')
        for name, required in requests:
            # Include package initialisers as well as the requested module.
            for i in range(1, len(name.split('.')) + 1):
                part = '.'.join(name.split('.')[:i])
                path = self._find(part)
                if path:
                    self.ingest(path, name=part, _depth=depth + 1)
                elif required and part == name:
                    self._missing(f'Unresolved static import: {name}')

    def _missing(self, message):
        if self.settings.missing_imports == 'error':
            raise ModuleNotFoundError(message)
        self.diagnostics.append(message)


# Standalone representation codec; never imports classes named in input JSON.
def dumps(document, **kwargs):
    def encode(v):
        if is_dataclass(v):
            return {'node': type(v).__name__, 'fields': {f.name: encode(getattr(v, f.name)) for f in fields(v)}}
        if isinstance(v, dict):
            return {'mapping': {k: encode(x) for k, x in v.items()}}
        if isinstance(v, tuple):
            return {'tuple': [encode(x) for x in v]}
        if isinstance(v, list):
            return [encode(x) for x in v]
        if isinstance(v, (bytes, complex)) or v is Ellipsis:
            return {'literal': repr(v)}
        return v
    return json.dumps({'version': 2, 'document': encode(document)}, **kwargs)


def loads(text):
    kinds = {c.__name__: c for c in (Document, Node, Module, Class, Function, Variable, Import)}
    def decode(v):
        if isinstance(v, list):
            return [decode(x) for x in v]
        if not isinstance(v, dict):
            return v
        if 'node' in v:
            return kinds[v['node']](**{k: decode(x) for k, x in v['fields'].items()})
        if 'mapping' in v:
            return {k: decode(x) for k, x in v['mapping'].items()}
        if 'tuple' in v:
            return tuple(decode(x) for x in v['tuple'])
        if 'literal' in v:
            return Ellipsis if v['literal'] == 'Ellipsis' else ast.literal_eval(v['literal'])
        raise ValueError('Unknown encoded value')
    payload = json.loads(text)
    if payload['version'] != 2:
        raise ValueError('Unsupported representation version')
    result = decode(payload['document'])
    if not isinstance(result, Document):
        raise ValueError('Expected a Document')
    return result


# Compatibility aliases for explicit matcher names from the first prototype.
Equal = Eq
RegexMatcher = Regex


if __name__ == '__main__':
    ctx = Context()
    ctx.ingest_source('''
class Particle:
    mass: float
    def move(self, steps: int):
        distance: float = steps * 0.5
        return distance
class ParticlePair:
    pass
''', name='physics')
    selection = ctx.classes(name='Particle*').where(name=Neq('ParticlePair'))
    particle = selection.one()  # Plain Class, no query methods.
    assert not hasattr(particle, 'classes')
    assert ctx.classes(like=Class(name=Regex(r'Particle.*'))).count() == 2
    move = ctx.classes(name='Particle').functions(name='move').one()
    locals_query = python_query(move).variables(annotation=AnyOf('float', 'int'))
    assert [v.name for v in locals_query.all()] == ['steps', 'distance']
    assert isinstance(ctx.classes().all(), Iterator)
    assert ctx.classes(name=AllOf(Glob('Particle*'), NoneOf(Eq('ParticlePair')))).one() is particle
    assert loads(dumps(ctx.document)) == ctx.document

    # Same engine over a cyclic graph of ordinary dictionaries.
    root = {'name': 'root', 'children': []}
    leaf = {'name': 'leaf', 'children': [root]}
    root['children'].append(leaf)
    visits = []
    def children(obj):
        visits.append(obj['name'])
        return obj['children']
    graph_query = Graph(children).query(root).descendants().where(name=Eq('leaf'))
    assert visits == []  # Building the query never reads the graph.
    assert graph_query.first() is leaf
    assert graph_query.count() == 1
    print('Classes:', [n.name for n in ctx.classes().all()])
    print('move bindings:', [n.name for n in locals_query.all()])
    print('Lazy queries, generic cyclic graph and serialisation checks passed.')
