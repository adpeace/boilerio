import configparser

CONFIG_PATH = '/etc/sensors/config'

def load_config(path=CONFIG_PATH):
    cfg = configparser.RawConfigParser()
    with open(path, 'r') as f:
        cfg.readfp(f)
    return cfg
