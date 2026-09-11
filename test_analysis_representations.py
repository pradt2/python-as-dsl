"""Run: python3 -m unittest -v test_analysis_representations

Keep this file beside cpp_representation.py, config_representation.py,
shared_analysis.py and querying.py. The native comparison uses g++ when present;
all other tests require only Python 3.10+ and the standard library.
"""
import pickle
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import shared_analysis as shared
import config_representation as config
import cpp_representation as cpp


class ConfigRegressionTests(unittest.TestCase):
    def run_config(self,source,**kw):return config.analyse(config.ConfigParser().parse(source),**kw)

    def test_example_and_shared_implementation(self):
        r=self.run_config(config.EXAMPLE)
        self.assertEqual(r.values,{'retries':3,'ports':[9000,8001],'label':'ready','total':3})
        self.assertTrue(r.facts['retries'].may_reassign)
        self.assertFalse(r.facts['retries'].object_may_mutate)
        self.assertFalse(r.facts['ports'].may_reassign)
        self.assertTrue(r.facts['ports'].object_may_mutate)
        self.assertIs(config.ConstantAnalysis,shared.ConstantAnalysis)
        self.assertIs(cpp.ConstantAnalysis,shared.ConstantAnalysis)
        self.assertIs(cpp.MutationAnalysis,config.MutationAnalysis)

    def test_aliases_stores_and_chains(self):
        r=self.run_config('a=b=[1]\nb += [2]\nb[0]=3')
        self.assertEqual(r.values,{'a':[3,2],'b':[3,2]})
        self.assertTrue(r.facts['a'].object_may_mutate)
        self.assertFalse(r.facts['a'].may_reassign)
        r=self.run_config('a=[0]\nb=[1]\na[0]=b\na[0][0]=9')
        self.assertTrue(r.facts['b'].object_may_mutate)
        self.assertEqual(r.values['b'],[9])

    def test_loop_fixedpoint_and_branch_facts(self):
        model=config.ConfigParser().parse('a=[0]\nb=[1]\nfor _i in range(2):\n a[0]=2\n a=b')
        facts=shared.MutationAnalysis().run(config.ConfigView(model))
        self.assertTrue(facts['b'].object_may_mutate)
        source='x=1\nif False:\n x=2'
        self.assertTrue(self.run_config(source).facts['x'].may_reassign)
        self.assertFalse(self.run_config(source,prune_known_branches=True).facts['x'].may_reassign)

    def test_short_circuit_and_failure(self):
        self.assertEqual(self.run_config('x=False and missing').values,{'x':False})
        with self.assertRaises(shared.StaticEvaluationError):self.run_config('x=missing')
        with self.assertRaises(shared.StaticEvaluationError):self.run_config('while True:\n pass',max_steps=10)
        with self.assertRaises(SyntaxError):config.ConfigParser().parse('import os')


RECORD='class Box:\n    value: int\n'


class CppTests(unittest.TestCase):
    def test_default_copy_has_fresh_storage(self):
        unit=cpp.Lowerer().parse(RECORD+'''\ndef run() -> int:\n    a: Box = Box(1)\n    b: Box = a\n    b.value = 9\n    return a.value\n''')
        c,m,_=cpp.analyse(unit,'run')
        self.assertEqual(c.return_value,1)
        self.assertFalse(m['a'].object_may_mutate)
        self.assertTrue(m['b'].object_may_mutate)
        self.assertEqual(m['b'].field_writes,{('value',)})

    def test_reference_assignment_writes_through(self):
        unit=cpp.Lowerer().parse(RECORD+'''\ndef run() -> int:\n    a: Box = Box(1)\n    other: Box = Box(4)\n    alias: Ref[Box] = a\n    alias = other\n    alias.value = 7\n    return a.value + other.value\n''')
        c,m,_=cpp.analyse(unit,'run')
        self.assertEqual(c.return_value,11)
        self.assertIs(c.final_values['a'],c.final_values['alias'])
        self.assertEqual(c.final_values['other'].fields['value'],4)
        self.assertFalse(m['other'].object_may_mutate)
        self.assertFalse(m['alias'].may_reassign)
        self.assertTrue(m['a'].object_may_mutate)

    def test_record_storage_survives_overwrite_and_self_assignment(self):
        unit=cpp.Lowerer().parse(RECORD+'''\ndef run() -> int:\n    a: Box = Box(1)\n    r: Ref[Box] = a\n    a = Box(5)\n    a = a\n    return r.value\n''')
        self.assertEqual(cpp.analyse(unit,'run')[0].return_value,5)

    def test_parameter_effects_without_values(self):
        unit=cpp.Lowerer().parse(RECORD+'''\ndef by_value(p: Box) -> int:\n    p.value = 10\n    return p.value\n\ndef by_reference(p: Ref[Box], q: Ref[Box]) -> int:\n    p.value = 10\n    return q.value\n''')
        value_fn,ref_fn=unit.functions
        value_effects=shared.MutationAnalysis().run(cpp.CppView(value_fn))
        ref_effects=shared.MutationAnalysis().run(cpp.CppView(ref_fn))
        self.assertTrue(value_effects['p'].object_may_mutate)
        self.assertEqual(cpp.caller_mutations(value_fn,value_effects),{})
        self.assertEqual(set(cpp.caller_mutations(ref_fn,ref_effects)),{'p','q'})
        t=ref_fn.parameters[0].type
        original=cpp.RecordValue(t,{'value':2})
        c,_,_=cpp.analyse(unit,'by_reference',arguments={'p':original,'q':original})
        self.assertEqual(c.return_value,10)
        self.assertEqual(original.fields['value'],2)
        self.assertIs(c.final_values['p'],c.final_values['q'])
        c,_,_=cpp.analyse(unit,'by_value',arguments={'p':original})
        self.assertEqual(c.return_value,10)
        with self.assertRaises(ValueError):cpp.analyse(unit,'by_value')

    def test_scalar_parameters_control_and_return(self):
        unit=cpp.Lowerer().parse('''\ndef sum_down(n: int) -> int:\n    total: int = 0\n    while n > 0:\n        total += n\n        n -= 1\n    if total > 2:\n        return total\n    else:\n        return 0\n''')
        c,m,_=cpp.analyse(unit,'sum_down',arguments={'n':3})
        self.assertEqual(c.return_value,6)
        self.assertTrue(c.has_return)
        self.assertTrue(m['n'].may_reassign)
        self.assertFalse(m['n'].object_may_mutate)
        self.assertEqual(cpp.analyse(unit,'sum_down',arguments={'n':0})[0].return_value,0)

    def test_domain_arithmetic_is_not_python_arithmetic(self):
        unit=cpp.Lowerer().parse('''\ndef wrapped() -> uint32:\n    x: uint32 = 4294967295\n    return x + 1\n\ndef divide() -> int:\n    return -7 / 3\n\ndef remainder() -> int:\n    return -7 % 3\n\ndef overflow() -> int:\n    x: int = 2147483647\n    return x + 1\n''')
        self.assertEqual(cpp.analyse(unit,'wrapped')[0].return_value,0)
        self.assertEqual(cpp.analyse(unit,'divide')[0].return_value,-2)
        self.assertEqual(cpp.analyse(unit,'remainder')[0].return_value,-1)
        with self.assertRaises(shared.StaticEvaluationError):cpp.analyse(unit,'overflow')
        python=config.analyse(config.ConfigParser().parse('x=4294967295+1\ny=-7/3'))
        self.assertEqual(python.values['x'],4294967296)
        self.assertEqual(python.values['y'],-7/3)
        self.assertIs(cpp.I32.python_type,cpp.U32.python_type)

    def test_rejections_and_queryability(self):
        for source in (
            'def f() -> int:\n return missing',
            'def f() -> int:\n x: int=1.5\n return x',
            'def f(x: int) -> int:\n if True:\n  y: int=2\n return x',
            RECORD+'def f() -> int:\n a: Ref[Box]=Box(1)\n return a.value',
            'class C:\n @property\n def method(self): pass',
        ):
            with self.subTest(source=source):
                with self.assertRaises((ValueError,TypeError)):cpp.Lowerer().parse(source)
        unit=cpp.Lowerer().parse(cpp.EXAMPLE)
        self.assertEqual(unit.query().structs(name='Particle').count(),1)
        self.assertEqual(unit.query().functions().count(),3)
        self.assertEqual(unit.query(recursive=True).variables(name='alias').count(),1)
        self.assertEqual(pickle.loads(pickle.dumps(unit)),unit)
        self.assertEqual(cpp.analyse(cpp.Lowerer().parse('def f() -> None:\n return None'),'f')[0].return_value,None)

    @unittest.skipUnless(shutil.which('g++'),'g++ not available')
    def test_native_cpp_agrees(self):
        unit=cpp.Lowerer().parse(cpp.EXAMPLE+'''\ndef division() -> int:\n    return -7 / 3\n''')
        names=['demo','wrapped','division']
        expected=[cpp.analyse(unit,name)[0].return_value for name in names]
        main='\n#include <iostream>\nint main() {\n'
        for name in names:main+='std::cout << '+cpp.cxx_identifier(name)+'() << "\\n";\n'
        main+='}\n'
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'example.cpp';binary=Path(tmp)/'example'
            source.write_text(cpp.emit_cpp(unit)+main)
            subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror=return-type',str(source),'-o',str(binary)],check=True,capture_output=True,text=True)
            actual=subprocess.run([str(binary)],check=True,capture_output=True,text=True).stdout.splitlines()
        self.assertEqual([int(x) for x in actual],expected)


if __name__=='__main__':unittest.main()
