import os
import sys
import time
import json
import base64
import zipfile
import logging

import paths
import http_client

def pack_login_zip(package_name, path, *args):
    logger = logging.getLogger('app.' + __name__)
    path = path
    package_path = os.path.join(path, package_name)
    temp_file_path = os.path.join(path, 'info')
    temp_file = open(temp_file_path, 'w')
    for arg in args:
        arg = base64.b64encode(arg)
        temp_file.write(arg + '\n')
    temp_file.close()
    try:
        zf = zipfile.ZipFile(package_path, mode='w')
        if sys.platform.startswith('win'):
            s = "\\"
        else:
            s = "/"
        zf.write(temp_file_path, temp_file_path.split(s)[-1])
        zf.setpassword('d0nTfe_artH_er1PPe_r')
        zf.close()
    except Exception as e:
        logger.error('Packing error: ' + e.message)
        return
    os.remove(temp_file_path)
    return True

def read_login_zip(package_name, path):
    logger = logging.getLogger('app.' + __name__)
    path = path
    package_path = os.path.join(path, package_name)
    if os.path.exists(package_path):
        zf = zipfile.ZipFile(package_path, 'r')
        packed_info = zf.read('info', pwd='d0nTfe_artH_er1PPe_r')
        packed_info = packed_info.split('\n')
        packed_info.remove('')
        for number in range(0, len(packed_info)):
            packed_info[number] = base64.b64decode(packed_info[number])
        return packed_info
    else:
        logger.error(package_name + ' not found')

def read_login():
    logger = logging.getLogger('app.' + __name__)
    pack_name = 'login_info.bin'
    paths_to_settings = paths.get_paths_to_settings_folder()
    for path in paths_to_settings:
        logger.info("Searching for login info in %s" % path)
        try:
            login_info = read_login_zip(pack_name, path)
            if login_info:
                logger.info('Login info loaded from ' + path)
                return login_info
        except Exception as e:
            logger.warning('Failed loading login from ' + path + '. Error: ' + e.message)
        logger.info("Can't read login info in %s" % str(path))
    logger.info('No login info found')
    return (None, None)

def write_login(login, password):
    logger = logging.getLogger('app.' + __name__)
    package_name = 'login_info.bin'  # probably it shoud be read from config
    path = paths.get_paths_to_settings_folder()[0]
    try:
        result = pack_login_zip(package_name, path, login, password)
    except Exception as e:
        logger.warning('Login info writing error! ' + e.message)
    else:
        if result == True:
            logger.info('Login info was written and packed.')
        else:
            logger.warning("Login info wasn't written.")
        return True
    return False

class UserLogin:

    def __init__(self, app):
        self.logger = logging.getLogger("app." + __name__)
        self.app = app
        self.login = None
        self.user_token = None
        self.http_client = http_client.HTTPClient()
        login, password = read_login()
        if login:
            error = self.login_as_user(login, password)
            if error:
                self.logger.info(str(error))

    def login_as_user(self, login, password):
        answer = self.http_client.pack_and_send('user_login', login, password)
        if not answer:
            return 0, "No connection to server"
        else:
            user_token = answer.get('user_token', None)
            profiles_str = answer.get('all_profiles', None)
            error = answer.get('error', None)
            if error:
                self.logger.warning("Error processing user_login " + str(error))
                self.logger.error("Login rejected")
                return error['code'], error['message']
            elif user_token and profiles_str:
                if write_login(login, password):
                    self.login = login # for web_interface to display
                    self.user_token = user_token
                    try:
                        profiles = json.loads(profiles_str)
                    except Exception as e:
                        self.logger.warning("Error while parsing profiles: " + str(e))
                        return 42, "Error parsing profiles"
                    self.profiles = profiles
                    self.logger.info("Successful login from user " + login)
                else:
                    return 43, "Error saving login and password"
            else:
                return 43, "Error saving login and password"

    def wait_for_login(self):
        self.logger.info("Waiting for correct user login...")
        while not self.app.stop_flag:
            time.sleep(0.1)
            if self.user_token:
                self.logger.info("User token received.")
                return True