import os
import json

# use import config ; config.config to get config

def get_config_file_path():
    config_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(config_path, 'settings.json')

def load_config():
    with open(get_config_file_path()) as config_file:
        try:
            config = json.loads(config_file.read())
        except Exception as e:
            print e
            print "Config is:\n" + str(config_file.read())
        else:
            return config

def update_config(config):
    with open(get_config_file_path(), 'w') as config_file:
        try:
            jdata = json.dumps(config)
        except Exception as e:
            print e
        else:
            config_file.write(jdata)

config = load_config()