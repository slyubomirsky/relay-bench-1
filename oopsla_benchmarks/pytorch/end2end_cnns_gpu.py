import numpy as np
import argparse
import time
import tvm

from oopsla_benchmarks.util import run_experiments
from util import score

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-ave-curve", type=int, default=3)
    args = parser.parse_args()

    networks = ['resnet-18', 'mobilenet', 'vgg-16', 'dcgan']
    batch_sizes = [1]
    num_batches = 1

    device = 'gpu'
    device_name = tvm.gpu(0).device_name

    run_experiments(score, args.n_ave_curve,
                    'pytorch', 'cnn', device_name,
                    ['network', 'device', 'batch_size', 'num_batches'],
                    [networks, [device], batch_sizes, [num_batches]])
