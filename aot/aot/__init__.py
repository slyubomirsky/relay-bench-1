import ctypes
import numpy as np
import os
import subprocess
import tempfile
import tvm
from tvm import relay, get_global_func, target, register_func
from tvm.relay.expr import Expr, Let
from tvm.relay.adt import Constructor
from tvm.relay.expr_functor import ExprFunctor
from tvm.relay.backend import compile_engine
from .little_cpp import PackedCall, CPPFunction, Invoke, Decl, CPPIf, CPPTuple, CPPMatch, CPPConstructor
from . import to_source

TVM_PATH = os.environ['TVM_PATH']

def compile_cpp(source, lib_name, lib_path=None):
    if lib_path is None:
        lib_path = os.curdir

    debug_source_path = os.path.join(lib_path, 'source.cc')
    # Write out the file for debugging.
    with open(debug_source_path, 'w') as source_file:
        source_file.write(source)

    # with tempfile.TmporaryDirectory() as tmpdir:
    tmpdir = tempfile.mkdtemp(prefix="relay_aot_compiler")
    source_path = os.path.join(tmpdir, 'source.cc')
    with open(source_path, 'w') as source_file:
        source_file.write(source)

    system = os.uname()[0]
    if system == 'Darwin':
        command = [
            "clang",
            "-std=c++14",
            "-shared",
            "-undefined",
            "dynamic_lookup",
            "-o",
            lib_name,
            source_path,
		    f"-I{TVM_PATH}/3rdparty/dmlc-core/include",
		    f"-I{TVM_PATH}/3rdparty/dlpack/include",
		    f"-I{TVM_PATH}/3rdparty/HalideIR/src",
		    f"-I{TVM_PATH}/include",
		    f"-L{TVM_PATH}/build",
            "-ltvm"
        ]
    else:
        command = [
            "clang",
            "-std=c++14",
            "-shared",
            "-undefined",
            "dynamic_lookup",
            "-fPIC",
            "-o",
            lib_name,
            source_path,
		    f"-I{TVM_PATH}/3rdparty/dmlc-core/include",
		    f"-I{TVM_PATH}/3rdparty/dlpack/include",
		    f"-I{TVM_PATH}/3rdparty/HalideIR/src",
		    f"-I{TVM_PATH}/include",
		    f"-L{TVM_PATH}/build",
            "-ltvm"
        ]

    proc = subprocess.run(command)
    assert proc.returncode == 0
    cleanup = [
        "rm",
        source_path
    ]
    assert subprocess.run(cleanup).returncode == 0

def load_lib(name):
    return ctypes.CDLL(name, ctypes.RTLD_GLOBAL)

def is_primitive(func: relay.Function):
    return isinstance(func, relay.Function) and func.attrs and func.attrs.Primitive.value == 1

class AoTCompiler(ExprFunctor):
    def __init__(self, mod) -> None:
        super().__init__()
        self.mod = mod
        self.engine = compile_engine.get()
        self.bindings = [[]]
        self.gv_map = {}

    def add_binding(self, var, value):
        self.bindings[-1].append((var, value))

    def optimize(self, expr: Expr) -> Expr:
        infer_e = relay.ir_pass.infer_type(expr, self.mod)
        fused_e = relay.ir_pass.fuse_ops(infer_e, self.mod)
        fused_e = relay.ir_pass.infer_type(fused_e, self.mod)
        anf_fused = relay.ir_pass.to_anf(fused_e, self.mod)
        anf_fused = relay.ir_pass.infer_type(anf_fused, self.mod)
        return anf_fused

    def mk_primitive_op(self, func: Expr, args, output_type) -> Expr:
        if len(args) == 1 and isinstance(args[0].checked_type, relay.TupleType):
            args_is_tuple = True
            num_param = len(args[0].checked_type.fields)
        else:
            for x in args:
                assert isinstance(x.checked_type, relay.TensorType)
            args_is_tuple = False
            num_param = len(func.params)
        cc_key = compile_engine.CCacheKey(func, target.create('llvm'))
        hash = relay.ir_pass.structural_hash(func)
        name = f"op{hash}"
        if not get_global_func(name, allow_missing=True):
            jit_func = self.engine.jit(cc_key)
            register_func(name, jit_func)
        return PackedCall(name, num_param + 1, args, output_type, args_is_tuple)

    def visit_call(self, call: Expr) -> Expr:
        if is_primitive(call.op):
            return self.mk_primitive_op(call.op, call.args, call.checked_type)
        elif isinstance(call.op, Constructor):
            return CPPConstructor(call.op.tag, [self.visit(arg) for arg in call.args])
        else:
            args = [self.visit(arg) for arg in call.args]
            fn = self.visit(call.op)
            return Invoke(fn, args)

    def visit_let(self, let: Expr) -> Expr:
        self.bindings.append([])

        while isinstance(let, Let):
            cpp_value = self.visit(let.value)
            self.add_binding(let.var, cpp_value)
            let = let.body

        bindings = self.bindings.pop()
        body = self.visit(let)

        return Decl(bindings, body)

    def visit_var(self, var):
        return var

    def visit_global_var(self, gv):
        if gv not in self.gv_map:
            self.gv_map[gv] = "to be updated"
            self.gv_map[gv] = self.visit(self.mod[gv])
        return gv

    def visit_function(self, func):
        if is_primitive(func):
            body = self.mk_primitive_op(func, func.params, func.ret_type)
            return CPPFunction(func.params, body, func.checked_type.ret_type)
        else:
            return CPPFunction(func.params, self.visit(func.body), func.checked_type.ret_type)

    def visit_constant(self, const):
        return const

    def visit_if(self, i):
        return CPPIf(self.visit(i.cond),
                     self.visit(i.true_branch),
                     self.visit(i.false_branch),
                     i.checked_type)

    def visit_tuple(self, t):
        return CPPTuple([self.visit(f) for f in t.fields], t.checked_type)

    def visit_match(self, m):
        return CPPMatch(self.visit(m.data),
                        [(c.lhs, self.visit(c.rhs)) for c in m.pattern],
                        m.checked_type)

_LIB_COUNTER = 1
_LIB = []

def compile(mod, func, name='default'):
    global _LIB, _LIB_COUNTER
    packed_name = f'relay.aot.{name}.{_LIB_COUNTER}'
    compiler = AoTCompiler(mod)
    func = compiler.optimize(func)
    func = compiler.visit(func)
    params, source_code = to_source.to_source(mod, compiler.gv_map, packed_name, func)
    lib_name = f"librelay_aot_{_LIB_COUNTER}.so"
    compile_cpp(source_code, lib_name)
    _LIB_COUNTER += 1
    _LIB.append(load_lib(lib_name))
    fn = get_global_func(packed_name)
    def convert(a):
        if isinstance(a, tvm.ndarray.NDArray):
            return relay.backend.interpreter.TensorValue(a)
        if isinstance(a, relay.backend.interpreter.TensorValue):
            return a
        raise Exception(a)
    def wrap(*args):
        return fn(*[convert(a) for a in params], *[convert(a) for a in args])
    return wrap
