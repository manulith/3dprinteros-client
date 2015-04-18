import sys
import logging
from subprocess import Popen, PIPE

from config import Config


def is_admin():
    import ctypes, os
    try:
        is_admin = os.getuid() == 0
    except:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin()

    print is_admin

def is_user_groups():
    logger = logging.getLogger('app')
    if sys.platform.startswith('linux') and Config.instance().settings['linux_rights_warning']:
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
    if sys.platform.startswith('linux'):
        p = Popen('xterm -e "sudo usermod -a -G dialout,tty,usbusers $USER"', shell=True, stdout=PIPE, stderr=PIPE)
        stdout, stderr = p.communicate()
        if stdout:
            logger.info('Adding to Linux groups result: ' + stdout)