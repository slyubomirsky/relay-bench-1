from validate_config import validate
from exp_templates import visualize_template, common_individual_comparison


if __name__ == '__main__':
    visualize_template(
        validate,
        common_individual_comparison(
            'Executor', 'Char RNN Comparison', 'char_rnn', use_networks=False))
