import json

from singleton import Singleton

class Config(Singleton):

    SETTINGS_FILE_NAME = 'settings.json'

    def __init__(self):
        self.settings = self.load_settings()
        self.profiles = None

    def load_settings(self):
        with open(self.SETTINGS_FILE_NAME) as settings_file:
            try:
                config = json.loads(settings_file.read())
            except Exception as e:
                print "Error reading %s: %s" % (self.SETTINGS_FILE_NAME, str(e))
            else:
                return config

    def save_settings(self, settings):
        with open(self.SETTINGS_FILE_NAME, 'w') as settings_file:
            try:
                jdata = json.dumps(settings)
            except Exception as e:
                print "Error writing %s: %s" % (self.SETTINGS_FILE_NAME, str(e))
                return False
            settings_file.write(jdata)
            return True

    def set_profiles(self, profiles):
        self.profiles = profiles