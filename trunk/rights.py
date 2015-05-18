import os
import sys
import logging
from subprocess import Popen, PIPE

import config

groups_warning_flag = True

def is_admin():
    import ctypes, os
    try:
        is_admin = os.getuid() == 0
    except:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin()
    return is_admin

def is_user_groups():
    logger = logging.getLogger('app')
    if sys.platform.startswith('linux') and config.get_settings()['linux_rights_warning']:
        p = Popen('groups', stdout=PIPE, stderr=PIPE)
        stdout, stderr = p.communicate()
        groups = stdout
        if not ('tty' in groups and 'dialout' in groups and 'usbusers' in groups):
            logger.info('Current Linux user is not in tty and dialout groups')
            return False
        else:
            return True
    else:
        return True

def add_user_groups():
    logger = logging.getLogger('app')
    if sys.platform.startswith('linux') and not is_admin():
        p = Popen('xterm -e "sudo groupadd usbusers && usermod -a -G dialout,tty,usbusers $USER"', shell=True, stdout=PIPE, stderr=PIPE)
        stdout, stderr = p.communicate()
        if stdout:
            logger.info('Adding to Linux groups result: ' + stdout)

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
