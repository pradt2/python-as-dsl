import unittest
from querying import IsA
import python_declarations as p
from python_parser import Parser
from config_lowering import ConfigLowerer, LoweringError, lower_config
from config_representation import analyse, ConfigParser


def module(source):
    return Parser().parse_source(source,filename='settings.py').project.modules[0]


class LoweringTests(unittest.TestCase):
    def test_aliases_and_shared_analysis(self):
        graph=module('a = b = [1]\nb[0] = 9\nx = 2\nx += 3')
        before=p.dumps(graph)
        result=ConfigLowerer().lower(graph)
        self.assertEqual(analyse(result.config).values, {'a':[9],'b':[9],'x':5})
        self.assertEqual(p.dumps(graph),before)
        keys=[n.key for n in result.config.query(recursive=True).all() if hasattr(n,'key')]
        self.assertEqual(len(keys),len(set(keys)))
        self.assertEqual(set(keys),set(result.origins))

    def test_serialized_graph_without_source(self):
        graph=p.loads(p.dumps(module('''total: int = 0
for _i in range(4):
    if _i == 0:
        total += 1
    elif _i < 3:
        total += _i
    else:
        total += 10
else:
    total += 2
while total < 18:
    total += 1
else:
    done = True
''')))
        for n in graph.query(recursive=True,include_self=True).all():
            if isinstance(n,p.Expression): n.source=None
            if isinstance(n,p.ConditionalGroup): n.header=None
        self.assertEqual(analyse(lower_config(graph)).values,{'total':18,'done':True})

    def test_expression_semantics(self):
        source='''a = {"x": [2, 3]}
x = abs(-2) + a["x"][1] * 2
y = 1 < x <= 8
z = (False and missing) or (x if y else missing)
w = (1, 2)
'''
        self.assertEqual(analyse(lower_config(module(source))).values,
                         {'a':{'x':[2,3]},'x':8,'y':True,'z':8,'w':[1,2]})

    def test_rejects_unsupported_even_when_unreachable(self):
        for source in ('x=1\ndel x','x=1\nprint(x)','if False:\n    print(1)',
                       'for x in range(2):\n    break','import math','def f():\n    pass',
                       'x: int','x = f()','x = len(*[])','a,b = [1,2]',
                       'x = 1 is 1','x = [i for i in range(2)]','"doc"\nx=1'):
            with self.subTest(source=source), self.assertRaises(LoweringError):
                lower_config(module(source))

    def test_structured_unsupported_domain_node_survives_roundtrip(self):
        graph=p.loads(p.dumps(module('x=1\ndel x')))
        nodes=graph.query(recursive=True).filter(IsA(p.Delete)).collect()
        self.assertEqual(len(nodes),1)
        self.assertEqual(nodes[0].targets[0].variable.name,'x')
        self.assertEqual(graph.query(recursive=True).filter(IsA(p.UnsupportedStatement)).count(),0)
        with self.assertRaises(LoweringError) as caught: lower_config(graph)
        self.assertEqual(caught.exception.filename,'settings.py')
        self.assertEqual(caught.exception.lineno,2)

    def test_legacy_projection_rejected(self):
        graph=module('x=1'); graph.statements_complete=False
        with self.assertRaises(LoweringError): lower_config(graph)

    def test_missing_structured_condition_rejected(self):
        graph=module('if True:\n    x=1')
        graph.members[0].condition=None
        with self.assertRaises(LoweringError): lower_config(graph)

    def test_frontend_and_explicit_conversion_agree(self):
        source='x=[1]\nx += [2]\npass'
        self.assertEqual(ConfigParser().parse(source,filename='settings.py'), lower_config(module(source)))


if __name__ == '__main__': unittest.main()
