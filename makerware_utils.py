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

# Author: Alexey Slynko <alex_ey@i.ua>, Author: Vladimir Avdeev <another.vic@yandex.ru>

import os
import sys
import time
import logging
from subprocess import Popen

# Getting Makerbot service named Conveyor from MakerWare killed.
# It binds COM-ports to itself even for non-makerbot printers and we can not work

def detect_makerware_paths():
    logger = logging.getLogger('app')
    makerware_path = None
    if sys.platform.startswith('linux'):
        paths = ['/usr/share/makerbot/', '/usr/local/share/makerbot/']
        for path in paths:
            if os.path.isdir(path):
                makerware_path = path
    elif sys.platform.startswith('darwin'):
        darwin_default_path = '/Library/MakerBot/'
        if os.path.isdir(darwin_default_path):
            makerware_path = darwin_default_path
    elif sys.platform.startswith('win'):
        import _winreg
        try:
            key = _winreg.OpenKey('HKEY_LOCAL_MACHINE', 'SOFTWARE\\MakerBot\\MakerWare')
            makerware_path = str(_winreg.QueryValueEx(key, 'InstallPath')[0])
        except Exception as e:
            print "No conveyor installed or some other winreg error" + e.message
    else:
        raise EnvironmentError('Error. Undetectable or unsupported OS. \
                               Only GNU/LINUX, MAC OS X and MS Windows are supported.')
    if not makerware_path:
        logger.info('Could not define makerware path')
    return makerware_path

def get_conveyor_pid():
    conveyor_pid = None
    if sys.platform.startswith('win'):
        tasks = os.popen('tasklist /svc').readlines()
        for task in tasks:
            # TODO: Second condition need tests on win with our soft(if script argument in split[0] and check backslash magic)
            try:
                if task.startswith('conveyor-svc.exe') or task.split()[0].endswith('/conveyor/server/__main__.py'):
                    conveyor_pid = task.split()[1]
                    # print conveyor_pid
                    # print task
            except IndexError:
                pass
    elif sys.platform.startswith('darwin'):
        tasks = os.popen('ps ax').readlines()
        for task in tasks:
            # TODO: make conveyor service die on linux with makerware
            try:
                if task.split()[4].endswith('conveyor-svc') or task.split()[5].endswith('/conveyor/server/__main__.py'):
                    conveyor_pid = task.split()[0]
                    # print conveyor_pid
                    # print task
            except IndexError:
                pass
    elif sys.platform.startswith('linux'):
        conveyor_pid = []  # There are 2 processes for conveyor at linux, so we should return both
        tasks = os.popen('ps ax|grep conveyor').readlines()
        for task in tasks:
            if 'conveyor-svc' in task:
                conveyor_pid.append(task)  # Adding whole tasks to parse them later, for chmod path finding in killing function
    return conveyor_pid

# Getting Makerbot service named Conveyor from MakerWare killed.
# It binds COM-ports to itself even for non-makerbot printers and we can not work
def kill_existing_conveyor():
    wait_count = 5
    sleep_time = 1
    logger = logging.getLogger('app')
    pid = get_conveyor_pid()
    if pid:
        logger.info('Makerbot conveyor service is running. Shutting down...')
        if sys.platform.startswith('win'):
            #os.popen('taskkill /f /pid ' + pid)
            os.popen('sc stop "MakerBot Conveyor Service"')
        # At linux we have very bad and unfriendly conveyor behaviour, so little magic here
        elif sys.platform.startswith('linux'):
            pids = []
            conveyor_svc_path = None
            for id in pid:  # List of processes here, should be 2 processes as usual
                id = id.split()
                # if we get 'sudo' word in process string from 'ps ax|grep conveyor', then it means we got this string format:
                # sudo -u conveyor LD_LIBRARY_PATH=/usr/lib/makerbot/ /usr/bin/conveyor-svc --config /etc/conveyor.conf
                # this is the one of two conveyor processes, the second is like
                # /usr/bin/conveyor-svc --config /etc/conveyor.conf
                # The processes have respawn flag, so you could not just kill them.
                if 'sudo' in id:  # Convenient task string for parsing conveyor-svc path
                    conveyor_svc_path = id[8]  # '/usr/bin/conveyor-svc' string position
                    if conveyor_svc_path.startswith('/') and conveyor_svc_path.endswith('conveyor-svc'):
                        logger.info('Got conveyor service path: {0}. Applying "chmod -x"'.format(conveyor_svc_path))
                pids.append(id[0])  # Get pids to kill
            pids_sting = ' '.join(pids)
            # to kill it, we need to forbid executable rights for file /usr/bin/conveyor-svc
            # and then kill these two processes. For now it will stop conveyor for forever.
            # However you can turn in on again by executing these commands:
            # sudo chmod +x /usr/bin/conveyor-svc
            # sudo -u conveyor LD_LIBRARY_PATH=/usr/lib/makerbot/ /usr/bin/conveyor-svc --config /etc/conveyor.conf &
            # This process also will start second conveyor process and all should be fine
            if conveyor_svc_path and pids_sting:
                command = 'sudo chmod -x %s && sudo kill -9 %s' % (conveyor_svc_path, pids_sting)
                p = Popen('xterm -e "{0}"'.format(command), shell=True)
                while p.poll() is None:  # Returns 0 when finished
                    time.sleep(0.1)
                # Returned code is 0 either user closes the console or enters pass.
                # But if console was closed, message and button to kill still on place and can be done again
                logger.info('Xterm process returned code: ') + str(p.returncode)
            else:
                logger.info('Cannot get conveyor path or pids:\nconveyor_path: {0}\nconveyor_pids: {1}'.format(str(conveyor_svc_path), str(pids)))
        elif sys.platform.startswith('darwin'):
            makerware_path = detect_makerware_paths()
            command = os.path.join(makerware_path, 'stop_conveyor_service')
            command_to_stop = "osascript -e '" + 'do shell script "sudo ' + command + '" with administrator privileges' + "'"
            os.popen(command_to_stop)
        for i in range(wait_count):
            if get_conveyor_pid():
                logger.info('Conveyor still alive, awaiting %s time' % str(i + 1))
                time.sleep(sleep_time)
            else:
                logger.info('Makerbot Conveyor Service successfully killed.')
                return True
        logger.info('Could not kill Makerbot Conveyor Service. Please stop it manually and restart program.')

class ConveyorKiller:

    def __init__(self, app):
        self.logger = logging.getLogger('app')
        self.app = app
        self.waiting = False
        self.check()

    def wait(self):
        self.logger.info('Waiting for Makerbot Conveyor to stop')
        while not self.app.stop_flag:
            time.sleep(0.1)
            if not self.waiting:
                break

    def check(self):
        if get_conveyor_pid():
            self.waiting = True

    def kill(self):
        if kill_existing_conveyor():
            self.waiting = False