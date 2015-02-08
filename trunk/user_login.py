import sys
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
        self.user_token = None
        login, password = utils.read_login()
        if login:
            self.login_as_user(login, password)

    def login_as_user(self, login, password):
        answer = http_client.send(http_client.package_user_login, (login, password, sys.platform))
        if not answer:
            return 0, "No connection to server"
        else:
            user_token = answer.get('user_token', None)
            error = answer.get('error', None)
            if user_token and not error:
                profiles_str = answer['all_profiles']
                all_profiles = json.loads(profiles_str)
                config.update_profiles(all_profiles)
                if utils.write_login(login, password):
                    self.user_token = answer["user_token"]
                    self.logger.info("Successful login from user " + login)
                    return
            else:
                self.logger.warning("Error processing user_login " + str(error))
                self.logger.error("Login rejected")
                return error['code'], error['message']

    def wait_for_login(self):
        self.logger.debug("Waiting for correct user login...")
        while not self.user_token or self.parent.stop_flag:
            time.sleep(0.1)
            if getattr(self.parent, "quit_flag", False):
                self.parent.quit()
        self.logger.debug("...end waiting for user login.")