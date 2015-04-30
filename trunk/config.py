import json
import threading

def get_settings():
    return Config.instance().settings

def get_profiles():
    return Config.instance().profiles

def get_app():
    return Config.instance().app

class Singleton(object):
    lock = threading.Lock()
    _instance = None

    @classmethod
    def instance(cls):
        with cls.lock:
            if not cls._instance:
                print "Creating new instance of " + cls.__name__
                cls._instance = cls()
        return cls._instance

class Config(Singleton):

    SETTINGS_FILE_NAME = 'settings.json'

    def __init__(self):
        self.settings = self.load_settings()
        self.profiles = None
        self.app = None

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

    def set_app_pointer(self, app):
        self.app = app