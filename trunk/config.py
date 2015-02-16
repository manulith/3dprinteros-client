import os
import json
import utils
# use import config ; config.config to get config

def get_config_file_path():
    config_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(config_path, 'settings.json')

def get_profiles_file_path():
    config_path = utils.get_paths_to_settings_folder()[0]
    return os.path.join(config_path, 'profiles.json')

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

def update_profiles(profiles):
    path = utils.get_paths_to_settings_folder()[0]
    if not os.path.isdir(path):
        os.mkdir(path)
    with open(get_profiles_file_path(), 'w') as profiles_file:
        try:
            jdata = json.dumps(profiles)
        except Exception as e:
            print e
        else:
            profiles_file.write(jdata)

def load_profiles():
    with open(get_profiles_file_path()) as profiles_file:
        try:
            profiles = json.loads(profiles_file.read())
        except Exception as e:
            print e
            print "Config is:\n" + str(profiles_file.read())
        else:
            return profiles



config = load_config()