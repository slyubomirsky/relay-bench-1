import matplotlib
matplotlib.use('Agg')
from matplotlib.ticker import FuncFormatter
import matplotlib.pyplot as plt

import argparse
import csv
import numpy as np

SCORE_FIELDS = ['rep', 'run', 'time']
BASE_FIELDS = ['network', 'device']
CNN_FIELDS = BASE_FIELDS + ['batch_size']
CHAR_RNN_FIELDS = ['hidden_size', 'language', 'input']
TREE_LSTM_FIELDS = ['dataset', 'idx']

FRAMEWORK_CNN_FIELDS = {
    'relay': CNN_FIELDS + ['opt_level'] + SCORE_FIELDS,
    'nnvm': CNN_FIELDS + ['opt_level'] + SCORE_FIELDS,
    'mxnet': CNN_FIELDS + SCORE_FIELDS,
    'tf': CNN_FIELDS + ['enable_xla'] + SCORE_FIELDS,
    'pytorch': CNN_FIELDS + SCORE_FIELDS
}

FRAMEWORK_CHAR_RNN_FIELDS = {
    'pytorch': BASE_FIELDS + CHAR_RNN_FIELDS + SCORE_FIELDS,
    'relay': BASE_FIELDS + ['configuration', 'method'] + CHAR_RNN_FIELDS + SCORE_FIELDS
}

FRAMEWORK_TREE_LSTM_FIELDS = {
    'pytorch': ['device'] + TREE_LSTM_FIELDS + SCORE_FIELDS,
    'relay': ['device', 'method'] + TREE_LSTM_FIELDS + SCORE_FIELDS
}


def mean_of_means(data, trait_name, trait_values, is_numeric=False):
    means = []
    for value in trait_values:
        def filter_func(r):
            if is_numeric:
                return int(r[trait_name]) == value
            return r[trait_name] == value
        mean = np.mean(list(map(lambda r: float(r['time']),
                         filter(filter_func, data))))
        means.append(mean)
    return np.mean(means)


def average_across_reps(data, num_reps):
    return mean_of_means(data, 'rep', range(num_reps), is_numeric=True)


def format_ms(ax):
    def milliseconds(value, tick_position):
        return '{:3.1f}'.format(value*1e3)
    formatter = FuncFormatter(milliseconds)
    ax.yaxis.set_major_formatter(formatter)


def framework_cnn_average(framework, network, dev, num_reps, opt_params):
    with open('{}-cnn.csv'.format(framework), newline='') as csvfile:
        reader = csv.DictReader(csvfile, FRAMEWORK_CNN_FIELDS[framework])

        def filter_func(row):
            ret = row['device'] == dev and row['network'] == network
            for (name, value) in opt_params.items():
                ret = ret and row[name] == value
                if not ret:
                    return False
            return ret
        return average_across_reps(list(filter(filter_func, reader)), num_reps)


def generate_relay_cnn_opt_comparisons(networks, num_reps, opt_levels, dev):
    fig, ax = plt.subplots()
    format_ms(ax)

    width = 0.05
    positions = np.arange(opt_levels)
    offset = 0
    bars = []
    for network in networks:
        means = [
            framework_cnn_average('relay', network, dev, num_reps, {'opt_level': str(opt)})
            for opt in range(opt_levels)
        ]
        bar = ax.bar(positions + offset, means, width)
        offset += width
        bars.append(bar)

    ax.legend(tuple(bars), tuple(networks))
    ax.set_xticks(positions + width*(len(networks) / 2))
    ax.set_xticklabels(['O{}'.format(opt) for opt in range(opt_levels)])
    plt.title('Relay CNN Opt Level on {}'.format(dev))
    plt.xlabel('Opt Level')
    plt.ylabel('Time (ms)')
    plt.savefig('relay-cnn-{}.png'.format(dev.upper()))


def generate_cnn_comparisons(networks, num_reps, dev):
    fig, ax = plt.subplots()
    format_ms(ax)

    width = 0.05
    positions = np.arange(len(networks))
    offset = 0
    bars = []

    bar_settings = {
        'Relay': ('relay', {'opt_level': str(3)}),
        'TF': ('tf', {'enable_xla': str(False)}),
        'TF XLA': ('tf', {'enable_xla': str(True)}),
        'Pytorch': ('pytorch', {}),
        'MxNet': ('mxnet', {}),
        'NNVM': ('nnvm', {})
    }

    for (_, (framework, options)) in bar_settings.items():
        means = [framework_cnn_average(framework, network, dev, num_reps, options)
                 for network in networks]
        bar = ax.bar(positions + offset, means, width)
        offset += width
        bars.append(bar)

    ax.legend(tuple(bars), tuple([label for (label, _) in bar_settings.items()]))
    ax.set_xticks(positions + width*(len(bar_settings) / 2))
    ax.set_xticklabels(tuple(networks))
    plt.title('CNN Comparison on {}'.format(dev.upper()))
    plt.xlabel('Network')
    plt.ylabel('Time (ms)')
    plt.savefig('cnns-{}.png'.format(dev.upper()))


def average_across_languages(data, languages):
    return mean_of_means(data, 'language', languages)


def framework_char_rnn_average(framework, network, hidden_size, languages, opt_params):
    with open('{}-rnn.csv'.format(framework), newline='') as csvfile:
        reader = csv.DictReader(csvfile, FRAMEWORK_CHAR_RNN_FIELDS[framework])

        def filter_func(row):
            ret = row['device'] == dev and row['network'] == network
            ret = ret and int(row['hidden_size']) == hidden_size
            for (name, value) in opt_params.items():
                ret = ret and row[name] == value
                if not ret:
                    return False
            return ret
        return average_across_languages(list(filter(filter_func, reader)), languages)


def generate_char_rnn_comparison(network, languages, hidden_size, dev):
    fig, ax = plt.subplots()
    format_ms(ax)

    bar_settings = {
        'AoT': ('relay', {'method': 'aot', 'configuration': 'loop'}),
        'Intp Cell': ('relay', {'method': 'intp', 'configuration': 'cell'}),
        'Intp Loop': ('relay', {'method': 'intp', 'configuration': 'loop'}),
        'Pytorch': ('pytorch', {})
    }

    means = [
        framework_char_rnn_average(framework, network, hidden_size, languages, options)
        for (_, (framework, options)) in bar_settings.items()
    ]

    settings = np.arange(len(bar_settings.items()))
    plt.bar(settings, means)
    plt.xticks(settings, [config for (config, _) in bar_settings.items()])
    plt.title('Char RNN Comparison on {}'.format(dev.upper()))
    plt.xlabel('Framework')
    plt.ylabel('Time (ms)')
    plt.savefig('char-rnns-{}.png'.format(dev.upper()))


def average_across_datasets(data, num_idxs, datasets):
    means = [mean_of_means(list(filter(lambda r: r['dataset'] == dataset, data)),
                           'idx', range(num_idxs), is_numeric=True)
             for dataset in datasets]
    return np.mean(means)


def framework_tree_lstm_average(framework, num_idxs, datasets, opt_params, dev):
    with open('{}-treelstm.csv'.format(framework), newline='') as csvfile:
        reader = csv.DictReader(csvfile, FRAMEWORK_TREE_LSTM_FIELDS[framework])

        def filter_func(row):
            ret = row['device'] == dev
            for (name, value) in opt_params.items():
                ret = ret and row[name] == value
                if not ret:
                    return False
            return ret
        return average_across_datasets(list(filter(filter_func, reader)), num_idxs, datasets)


def generate_tree_lstm_comparison(num_idxs, datasets, dev):
    fig, ax = plt.subplots()
    format_ms(ax)

    bar_settings = {
        'AoT': ('relay', {'method': 'aot'}),
        'Intp': ('relay', {'method': 'intp'}),
        'Pytorch': ('pytorch', {})
    }

    means = [
        framework_tree_lstm_average(framework, num_idxs, datasets, options, dev)
        for (_, (framework, options)) in bar_settings.items()
    ]

    settings = np.arange(len(bar_settings.items()))
    plt.bar(settings, means)
    plt.xticks(settings, [config for (config, _) in bar_settings.items()])
    plt.title('TreeLSTM Comparison on {}'.format(dev.upper()))
    plt.xlabel('Framework')
    plt.ylabel('Time (ms)')
    plt.savefig('tree-lstm-{}.png'.format(dev.upper()))



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='get hidden')
    parser.add_argument('--n-hidden', type=int, default=16,
                        help='Number of hidden layers for char RNN')
    args = parser.parse_args()

    networks = ['resnet-18', 'mobilenet', 'nature-dqn', 'vgg-16']
    num_reps = 3
    opt_levels = 4
    for dev in ['cpu', 'gpu']:
        generate_relay_cnn_opt_comparisons(networks, num_reps, opt_levels, dev)
        generate_cnn_comparisons(networks, num_reps, dev)

    # we only have RNNs working on CPU for now
    network = 'char-rnn'
    dev = 'cpu'
    languages = ['Arabic', 'Chinese', 'Czech', 'Dutch', 'English',
                 'French', 'German', 'Greek', 'Irish', 'Italian',
                 'Japanese', 'Korean', 'Polish', 'Portuguese', 'Russian',
                 'Scottish', 'Spanish', 'Vietnamese']
    hidden_size = args.n_hidden
    generate_char_rnn_comparison(network, languages, hidden_size, dev)

    num_idxs = 500
    datasets = ['dev', 'test', 'train']
    generate_tree_lstm_comparison(num_idxs, datasets, dev)