import time
import logging

import utils
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
        self.errors = set()
        answer = http_client.send(http_client.user_login, (login, password, http_client.MACADDR))
        if answer:
            user_token = answer.get('user_token', None)
            errors = utils.check_for_errors(answer)
            if user_token and not errors:
                self.user_token = login
                self.errors = set()
                utils.write_token(login, password)
                return 0
            else:
                self.errors.union(errors)
                return (errors)
                self.logger.warning("Error processing user_login " + str(errors))
        self.logger.error("Login rejected")

    def wait_for_login(self):
        self.logger.debug("Waiting for correct user login...")
        while not self.token or self.parent.stop_flag:
            self.user_login()
            time.sleep(1)
            if self.quit_flag:
                self.quit()
        self.logger.debug("...end waiting for user login.")