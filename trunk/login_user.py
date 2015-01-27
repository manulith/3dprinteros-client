import time

import utils
import http_client

class UserLogin:

    def __init__(self, parent_obj):
        self.parent = parent_obj

    def attempt_login(self, login, password):
        pass

    def login_user(self):
        self.logger.debug("Waiting for correct user login")
        self.errors = set()
        if self.token:
            answer = http_client.send(http_client.user_login, self.token)
            if answer:
                login = answer.get('user_token', None)
                errors = utils.check_for_errors(answer)
                if not errors:
                    if login:
                        self.login = login
                        self.errors = set()
                else:
                    self.errors.union(errors)
                    self.logger.warning("Error processing user_login " + str(errors))
            self.logger.error("Login rejected")

    def wait_for_login(self):
        while not self.token or self.parent.stop_flag:
            self.user_login()
            time.sleep(1)
            if self.quit_flag:
                self.quit()