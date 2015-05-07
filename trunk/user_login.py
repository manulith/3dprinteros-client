import time
import json
import logging

import utils
import config
import http_client

class UserLogin:

    def __init__(self, parent_obj):
        self.logger = logging.getLogger("app." + __name__)
        self.parent = parent_obj
        self.login = None
        self.user_token = None
        self.http_client = http_client.HTTPClient()
        login, password = utils.read_login()
        if login:
            self.login_as_user(login, password)

    def login_as_user(self, login, password):
        answer = self.http_client.pack_and_send('user_login', login, password)
        if not answer:
            return 0, "No connection to server"
        else:
            user_token = answer.get('user_token')
            error = answer.get('error')
            if user_token and not error:
                profiles_str = answer['all_profiles']
                all_profiles = json.loads(profiles_str)
                config.update_profiles(all_profiles)
                if utils.write_login(login, password):
                    self.login = login # for web_interface to display
                    self.user_token = answer["user_token"]
                    self.logger.info("Successful login from user " + login)
                    return
            else:
                self.logger.warning("Error processing user_login " + str(error))
                self.logger.error("Login rejected")
                return error['code'], error['message']

    def wait_for_login(self):
        self.logger.debug("Waiting for correct user login...")
        while not self.user_token:
            time.sleep(0.1)
            if getattr(self.parent, "stop_flag", False):
                break
        self.logger.debug("...end waiting for user login.")