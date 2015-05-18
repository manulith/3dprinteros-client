import os
import sys
import time
import signal
import logging
from subprocess import Popen, PIPE

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
                conveyor_pid.append(task)  # Adding whole tasks to parse them later, for chmod path finding
    return conveyor_pid

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
        elif sys.platform.startswith('linux'):
            # TODO: it does not work
            #os.kill(int(pid), signal.SIGTERM)
            pids = []
            conveyor_svc_path = None
            for id in pid:  # List of processes here, should be 2 processes as usual
                if 'sudo' in pid:  # Convenient task for parsing conveyor-svc path
                    conveyor_svc_path = id[8]
                    if conveyor_svc_path.startswith('/') and conveyor_svc_path.endswith('conveyor-svc'):
                        logger.info('Got conveyor service path: %s. Applying "chmod -x"') % conveyor_svc_path
                pids.append(id[0])
            pids_sting = ' '.join(pids)
            if conveyor_svc_path and pids_sting:
                command = 'sudo chmod -x %s && kill -9 %s' % (conveyor_svc_path, pids_sting)
                p = Popen('xterm -e "%s"', shell=True, stdout=PIPE, stderr=PIPE) % command
                stdout, stderr = p.communicate()
                if stdout:
                    logger.info('Adding to Linux groups result: ' + stdout)
            else:
                logger.info('Cannot get conveyor path or pids:\nconveyor_path: %s\nconveyor_pids: %s') % (str(conveyor_svc_path), str(pids))
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