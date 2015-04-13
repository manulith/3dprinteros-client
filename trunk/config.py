import json

from singleton import Singleton

class Config(Singleton):

    CONFIG_FILE_NAME = 'settings.json'

    def __init__(self):
        self.config = self.read()
        self.profiles = None

    #def get_config_file_path(self):
        #config_path = os.path.dirname(os.path.abspath(__file__))
        #return os.path.join(config_path, 'settings.json')

    def read(self):
        with open(self.CONFIG_FILE_NAME) as config_file:
            try:
                config = json.loads(config_file.read())
            except Exception as e:
                print "Error reading %s: %s" % (self.CONFIG_FILE_NAME, str(e))
            else:
                return config

    def update(self, new_config):
        with open(self.CONFIG_FILE_NAME, 'w') as config_file:
            try:
                jdata = json.dumps(new_config)
            except Exception as e:
                print "Error writing %s: %s" % (self.CONFIG_FILE_NAME, str(e))
            else:
                config_file.write(jdata)

    def set_profiles(self, profiles):
        self.profiles = profiles