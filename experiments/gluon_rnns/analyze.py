from validate_config import validate
from common import invoke_main, write_status, write_json, render_exception
from analysis_util import trials_stat_summary, add_detailed_summary

def main(data_dir, config_dir, output_dir):
    config, msg = validate(config_dir)
    if config is None:
        write_status(output_dir, False, msg)
        return 1

    frameworks = config['frameworks']
    methods = config['relay_methods']
    devices = config['devices']
    networks = config['networks']
    num_reps = config['n_inputs']

    listing_settings = {}

    if 'mxnet' in frameworks:
        listing_settings['MxNet'] = ('mxnet', ['device', 'network'], {})

    if 'relay' in frameworks:
        if 'aot' in methods:
            listing_settings['Aot'] = ('relay', ['device', 'method', 'network'],
                                       {'method': 'aot'})
        if 'intp' in methods:
            listing_settings['Intp'] = ('relay', ['device', 'method', 'network'],
                                        {'method': 'intp'})


    # output averages on each network for each framework and each device
    ret = {}
    for dev in devices:
        ret[dev] = {}
        for listing, (framework, fieldnames, field_settings) in listing_settings.items():
            ret[dev][listing] = {}
            field_values = {
                'device': dev
            }
            for extra_field, value in field_settings.items():
                field_values[extra_field] = value
            for network in networks:
                field_values['network'] = network
                summary, success, msg = trials_stat_summary(data_dir, framework, 'gluon_rnns', num_reps,
                                                            fieldnames, field_values)
                if not success:
                    write_status(output_dir, False, msg)
                    return 1

                ret[dev][listing][network] = summary['mean']
                add_detailed_summary(ret, summary, dev, listing, network)

    write_json(output_dir, 'data.json', ret)
    write_status(output_dir, True, 'success')


if __name__ == '__main__':
    invoke_main(main, 'data_dir', 'config_dir', 'output_dir')
