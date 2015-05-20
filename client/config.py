#Copyright (c) 2015 3D Control Systems LTD

#3DPrinterOS client is free software: you can redistribute it and/or modify
#it under the terms of the GNU Affero General Public License as published by
#the Free Software Foundation, either version 3 of the License, or
#(at your option) any later version.

#3DPrinterOS client is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#GNU Affero General Public License for more details.

#You should have received a copy of the GNU Affero General Public License
#along with 3DPrinterOS client.  If not, see <http://www.gnu.org/licenses/>.

__author__ = 'Vladimir Avdeev <another.vic@yandex.ru>'

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