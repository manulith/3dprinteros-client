import sys
import time
import json
import logging

import utils
import http_client

class UserLogin:

    def __init__(self, app):
        self.logger = logging.getLogger("app." + __name__)
        self.app = app
        self.login = None
        self.user_token = None
        self.http_client = http_client.HTTPClient()
        login, password = utils.read_login()
        if login:
            error = self.login_as_user(login, password)
            if error:
                self.logger.info(str(error))

    def login_as_user(self, login, password):
        answer = self.http_client.pack_and_send('user_login', login, password, sys.platform)
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
                if utils.write_login(login, password):
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