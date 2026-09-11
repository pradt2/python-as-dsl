"""A statically evaluated config DSL with independent analysis adapters.

Requires shared_analysis.py and querying.py; the source frontend also uses
python_parser.py, python_declarations.py and config_lowering.py. Run this file to see the example and its analysis.
The IR is plain data. ConfigView supplies structural analysis capabilities;
ConfigSemantics supplies Python-like arithmetic and object behaviour. Neither
analysis imports this file. No user code is executed via eval/exec or imported.

Subset: name assignments (including chains), annotated initialised names, indexed
stores, name augmented assignments, if/else, for/while with else, and pass.
Expressions: literals, lists/tuples/dicts, operators, comparisons, conditional
expressions, indexing and calls to len/range/abs/min/max. Calls are reserved DSL
intrinsics; their names cannot be assigned. No functions, imports, attribute or
method access, comprehensions, destructuring, break/continue or arbitrary calls.
Unsupported syntax raises an error. Annotations are retained as text, not enforced.

Top-level names are config keys; leading '_' names are private working state.
Every exported value must resolve to a plain scalar/list/tuple/string-keyed dict.
Aliasing follows Python containers, including in-place list +=. Analysis facts
are separate from the graph. query() delegates to a separate graph adapter;
selectors filter the current stream. Known final values do NOT imply immutable bindings
or objects. Mutation facts conservatively cover possible paths by default;
ControlFacts from successful constant evaluation can prune unreachable branches.
Loop mutation analysis remains conservative, even with known execution outcomes.

Resource limits bound evaluation work and value growth. This is a small DSL,
not a sandbox for running arbitrary Python and not a full Python implementation.
"""
from __future__ import annotations
import json
import math
import operator
from dataclasses import dataclass
from typing import Any
from shared_analysis import ConstantAnalysis, MutationAnalysis, StaticEvaluationError, combine


@dataclass(frozen=True)
class Expr:
    key: int
    kind: str
    value: Any = None
    args: tuple[Expr,...] = ()


@dataclass(frozen=True)
class Statement:
    key: int
    kind: str
    targets: tuple[str,...] = ()
    value: Expr | None = None
    receiver: Expr | None = None
    index: Expr | None = None
    operator: str | None = None
    body: tuple[Statement,...] = ()
    otherwise: tuple[Statement,...] = ()
    annotation: str | None = None
    line: int = 0


@dataclass(frozen=True)
class Config:
    statements: tuple[Statement,...]
    filename: str = '<config>'


INTRINSICS = {'len':len, 'range':range, 'abs':abs, 'min':min, 'max':max}
BINARY = {'Add':operator.add,'Sub':operator.sub,'Mult':operator.mul,'Div':operator.truediv,
          'FloorDiv':operator.floordiv,'Mod':operator.mod,'Pow':operator.pow,
          'LShift':operator.lshift,'RShift':operator.rshift,'BitOr':operator.or_,
          'BitAnd':operator.and_,'BitXor':operator.xor}
UNARY = {'UAdd':operator.pos,'USub':operator.neg,'Not':operator.not_,'Invert':operator.invert}
COMPARE = {'Eq':operator.eq,'NotEq':operator.ne,'Lt':operator.lt,'LtE':operator.le,
           'Gt':operator.gt,'GtE':operator.ge,'In':lambda a,b:a in b,'NotIn':lambda a,b:a not in b}
INPLACE = {'Add':operator.iadd,'Sub':operator.isub,'Mult':operator.imul,'Div':operator.itruediv,
           'FloorDiv':operator.ifloordiv,'Mod':operator.imod,'Pow':operator.ipow,
           'LShift':operator.ilshift,'RShift':operator.irshift,'BitOr':operator.ior,
           'BitAnd':operator.iand,'BitXor':operator.ixor}


class ConfigParser:
    """Convenience frontend: Python graph -> config graph (no duplicate parser)."""
    def parse(self, source, *, filename='<config>'):
        from python_parser import Parser
        from config_lowering import lower_config
        graph = Parser().parse_source(source, filename=filename).project
        return lower_config(graph.modules[0])


class ConfigView:
    """Adapter only; these methods contain no analysis algorithm."""
    def __init__(self,config): self.config=config
    def statements(self): return self.config.statements
    def kind(self,n): return n.kind
    def key(self,n): return n.key
    def targets(self,n): return n.targets
    def value(self,n): return n.value
    def receiver(self,n): return n.receiver
    def body(self,n): return n.body
    def otherwise(self,n): return n.otherwise
    def reference_parts(self,e):
        # Which operands can contribute a mutable reference to the result?
        # This is domain operation semantics, not a whole-program analysis.
        if e.kind in ('literal','compare','unary'): return ()
        if e.kind=='call' and e.value in ('len','range','abs'): return ()
        if e.kind=='binary' and e.value not in ('Add','Mult'): return ()
        if e.kind=='conditional': return e.args[1:]
        if e.kind=='index': return e.args[:1]
        return e.args
    def reads(self,e):
        if e is None: return ()
        return ((e.value,) if e.kind=='name' else ()) + tuple(name for x in self.reference_parts(e) for name in self.reads(x))
    def allocations(self,e):
        if e is None: return frozenset()
        own=frozenset((e.key,)) if e.kind in ('list','dict') else frozenset()
        # New list results of +/* share a conservative abstraction with their
        # source objects. This can add false positives, never drops their aliases.
        return own | frozenset(a for x in self.reference_parts(e) for a in self.allocations(x))


class ConfigSemantics:
    def __init__(self,*,max_items=10000,max_int_bits=4096):
        self.max_items,self.max_int_bits=max_items,max_int_bits

    def check(self,value):
        if isinstance(value,int) and value.bit_length()>self.max_int_bits: raise ValueError('Integer size limit exceeded')
        if isinstance(value,float) and not math.isfinite(value): raise ValueError('Non-finite config number')
        if isinstance(value,(str,list,tuple,dict,range)) and len(value)>self.max_items: raise ValueError('Collection size limit exceeded')
        return value

    def binary(self,op,left,right,*,inplace=False):
        if op=='Mod' and isinstance(left,str):
            raise TypeError('String formatting is outside the config subset')
        if op=='Pow' and isinstance(right,(int,float)) and abs(right)>self.max_int_bits:
            raise ValueError('Exponent limit exceeded')
        if op=='Pow' and isinstance(left,int) and isinstance(right,int) and right>=0 and left.bit_length()*right>self.max_int_bits:
            raise ValueError('Integer power limit exceeded')
        if op in ('LShift','RShift') and isinstance(right,int) and abs(right)>self.max_int_bits:
            raise ValueError('Shift limit exceeded')
        if op=='Mult':
            for seq,count in ((left,right),(right,left)):
                if isinstance(seq,(str,list,tuple)) and isinstance(count,int) and len(seq)*max(0,count)>self.max_items:
                    raise ValueError('Repeated collection size limit exceeded')
        return self.check((INPLACE if inplace else BINARY)[op](left,right))

    def evaluate(self,e,env):
        visit=lambda x:self.evaluate(x,env)
        if e.kind=='literal': return self.check(e.value)
        if e.kind=='name':
            if e.value not in env: raise ValueError(f'No static value for {e.value!r}')
            return env[e.value]
        if e.kind in ('list','tuple'):
            return self.check([visit(x) for x in e.args] if e.kind=='list' else tuple(visit(x) for x in e.args))
        if e.kind=='dict':
            result={}
            for i in range(0,len(e.args),2):
                key=visit(e.args[i])
                if not isinstance(key,str): raise ValueError('Config dictionary keys must be strings')
                result[key]=visit(e.args[i+1])
            return self.check(result)
        if e.kind=='binary': return self.binary(e.value,visit(e.args[0]),visit(e.args[1]))
        if e.kind=='unary': return self.check(UNARY[e.value](visit(e.args[0])))
        if e.kind=='boolean':
            value=visit(e.args[0])
            for arg in e.args[1:]:
                if (e.value=='And' and not value) or (e.value=='Or' and value): break
                value=visit(arg)
            return value
        if e.kind=='compare':
            left=visit(e.args[0])
            for op,arg in zip(e.value,e.args[1:]):
                right=visit(arg)
                if not COMPARE[op](left,right): return False
                left=right
            return True
        if e.kind=='conditional': return visit(e.args[1] if visit(e.args[0]) else e.args[2])
        if e.kind=='index': return visit(e.args[0])[visit(e.args[1])]
        if e.kind=='call': return self.check(INTRINSICS[e.value](*(visit(x) for x in e.args)))
        raise ValueError(f'Unsupported expression: {e.kind}')

    def truth(self,value): return bool(value)
    def iterate(self,value):
        if not isinstance(value,(list,tuple,dict,str,range)): raise TypeError('Expected a static iterable')
        return iter(value)
    def store(self,n,value,env):
        target=self.evaluate(n.receiver,env)
        index=self.evaluate(n.index,env)
        if not isinstance(target,(list,dict)): raise TypeError('Only lists and dictionaries support config stores')
        if isinstance(target,dict) and not isinstance(index,str): raise TypeError('Dictionary keys must be strings')
        target[index]=value
        self.check(target)
    def update(self,n,env):
        name=n.targets[0]
        if name not in env: raise ValueError(f'Cannot update unbound name {name!r}')
        return self.binary(n.operator,env[name],self.evaluate(n.value,env),inplace=True)


def plain(value, active=None, budget=None):
    """Validate exports, rejecting cycles and excessive expanded output."""
    budget=[10000] if budget is None else budget
    budget[0]-=1
    if budget[0]<0: raise ValueError('Expanded config output exceeds item budget')
    if value is None or type(value) in (str,bool,int,float): return value
    if not isinstance(value,(list,tuple,dict,range)): raise TypeError('Not a plain config value')
    active=set() if active is None else active
    if id(value) in active: raise ValueError('Cyclic config values cannot be exported')
    active.add(id(value))
    try:
        if isinstance(value,dict): return {k:plain(v,active,budget) for k,v in value.items()}
        return [plain(x,active,budget) for x in value]
    finally: active.remove(id(value))


@dataclass
class ConfigResult:
    values: dict[str,Any]
    constants: Any
    mutations: Any
    facts: Any


def analyse(config, *, prune_known_branches=False, max_steps=10000):
    view=ConfigView(config)
    # The independent mutation pass needs no constant values at all.
    if not prune_known_branches: mutations=MutationAnalysis().run(view)
    constants=ConstantAnalysis(max_steps=max_steps).run(view,ConfigSemantics())
    if prune_known_branches: mutations=MutationAnalysis().run(view,controls=constants.controls)
    budget=[10000]
    values={k:plain(v,budget=budget) for k,v in constants.final_values.items() if not k.startswith('_')}
    return ConfigResult(values,constants,mutations,combine(constants,mutations))


# Query integration is separate from both the IR and the analysis adapters.
from querying import Graph, Query


def config_children(node):
    if isinstance(node,Config):
        yield from node.statements
    elif isinstance(node,Statement):
        for value in (node.value,node.receiver,node.index):
            if value is not None: yield value
        yield from node.body
        yield from node.otherwise
    elif isinstance(node,Expr):
        yield from node.args


class ConfigQuery(Query):
    def statements(self,*patterns,**criteria):
        return self.of_type(Statement,*patterns,**criteria)
    def expressions(self,*patterns,**criteria):
        return self.of_type(Expr,*patterns,**criteria)


class _QueryEntry:
    def __get__(self,node,owner=None):
        if node is None: return self
        return lambda recursive=False,include_self=False: ConfigQuery(node,graph=CONFIG_GRAPH).descendants(
            include_self=include_self,max_depth=None if recursive else 1)


CONFIG_GRAPH=Graph(children=config_children)
for _type in (Config,Statement,Expr):
    _type.query=_QueryEntry()
del _type


EXAMPLE = '''
retries = 2
retries = retries + 1
ports = [8000, 8001]
_alias = ports
_alias[0] = 9000
label = "ready"
total = 0
for _i in range(retries):
    total += _i
'''


if __name__=='__main__':
    config=ConfigParser().parse(EXAMPLE)
    result=analyse(config)
    print(json.dumps(result.values,indent=2))
    print('\nname       known final value    may reassign    object may mutate')
    for name in result.values:
        f=result.facts[name]
        print(f'{name:10} {str(f.final_value_known):20} {str(f.may_reassign):15} {f.object_may_mutate}')
