import numpy as np
import tvm
from tvm import relay
from tvm import IRModule as Module
from tvm.relay import op
from tvm.relay import create_executor
from tvm.relay.prelude import Prelude
import aot

def initialize(param):
    ty = param.type_annotation
    shape = [int(i) for i in ty.shape]
    return np.random.normal(0, 1, shape).astype('float32')

class Network:
    def add_param(self, name="", shape=()):
        x = relay.var(name, shape=shape)
        self.parameters.append((x, initialize(x)))
        return x

    def linear(self, input_size, output_size, x, name=""):
        weight = self.add_param(f'{name}linear_weight', shape=(output_size, input_size))
        bias = self.add_param(f'{name}linear_bias', shape=(output_size,))
        return op.add(op.nn.dense(x, weight), bias)

    def __init__(self, do_aot, use_gpu, *args):
        assert isinstance(do_aot, bool)
        assert isinstance(use_gpu, bool)
        self.mod = Module()
        self.prelude = Prelude(self.mod)
        self.use_gpu = use_gpu
        self.context = tvm.gpu(0) if use_gpu else tvm.cpu(0)
        self.target = tvm.target.cuda() if use_gpu else tvm.target.create('llvm')
        self.executor = create_executor(mod=self.mod, ctx=self.context, target=self.target)
        self.parameters = []
        self.forward_var = relay.GlobalVar('forward_var')

        # Set up forward pass.
        inputs, body, ret_type = self.compute(*args)
        self.inputs = inputs

        forward_compute = relay.Function(inputs + list([p[0] for p in self.parameters]), body, ret_type)
        self.mod[self.forward_var] = forward_compute
        self.mod['main'] = self.mod[self.forward_var]
        if do_aot:
            self.forward = aot.compile(self.forward_var, self.mod, ctx=self.context, tgt=self.target)
        else:
            self.forward = self.executor.evaluate(self.forward_var)
        self.args = [None] * len(inputs) + list([p[1] for p in self.parameters])

    def __call__(self, *inputs):
        assert len(self.inputs) == len(inputs)
        for i, inp in enumerate(inputs):
            self.args[i] = inp

        return self.forward(*self.args)

    def recurse(self, *inputs):
        return self.forward_var(*inputs, *[p[0] for p in self.parameters])

def copy_var(v):
    return relay.Var(name_hint=v.name_hint, type_annotation=v.type_annotation)
