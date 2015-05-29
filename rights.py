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

# Author: Oleg Panasevych <panasevychol@gmail.com>, Vladimir Avdeev <another.vic@yandex.ru>

import os
import sys
import logging
import time
from subprocess import Popen, PIPE

import config

def is_admin():
    import ctypes, os
    try:
        is_admin = os.getuid() == 0
    except:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin()
    return is_admin

def launch_suprocess(file_name):
    logger = logging.getLogger('app')
    logger.info('Launching subprocess ' + file_name)
    client_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(client_dir, file_name)
    try:
        process = Popen([sys.executable, path])
    except Exception as e:
        logger.warning('Could not launch ' + file_name + ' as subprocess due to error:\n' + e.message)
    else:
        return process

class RightsCheckerAndWaiter:

    def __init__(self, app):
        self.logger = logging.getLogger('app')
        self.app = app
        self.waiting = False
        self.check()

    def wait(self):
        self.logger.info('Waiting for adding to Linux groups')
        while not self.app.stop_flag:
            time.sleep(0.1)
            if not self.waiting:
                break
        self.logger.info('...end of waiting.')

    def check(self):
        if sys.platform.startswith('linux') and config.get_settings()['linux_rights_warning'] and not is_admin():
            self.logger.info('Checking Linux rights')
            result = self.execute_command('groups')
            if not ('tty' in result and 'dialout' in result and 'usbusers' in result):
                self.logger.info('Current Linux user is not in tty and dialout groups')
                self.waiting = True

    def add_user_groups(self):
        if sys.platform.startswith('linux'):
            self.logger.info('Adding Linux user to necessary groups')
            self.execute_command(['groupadd', 'usbusers'])
            self.execute_command('xterm -e "sudo usermod -a -G dialout,tty,usbusers $USER"', shell=True)
            self.waiting = False

    def execute_command(self, command, shell=False):
        self.logger.info('Executing command: ' + str(command))
        try:
            process = Popen(command, shell=shell, stdout=PIPE, stderr=PIPE)
        except Exception as e:
            self.logger.warning('Error while executing command "' + command + '\n' + str(e))
        else:
            stdout, stderr = process.communicate()
            if stdout:
                self.logger.info('Executing result: ' + stdout)
                return stdout