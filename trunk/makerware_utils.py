import os
import sys
import time
import signal
import logging

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
    elif sys.platform.startswith('linux') or sys.platform.startswith('darwin'):
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
            os.kill(int(pid), signal.SIGTERM)
        elif sys.platform.startswith('darwin'):
            makerware_path = detect_makerware_paths()
            os.popen(os.path.join(makerware_path, 'stop_conveyor_service'))
        for i in range(wait_count):
            if get_conveyor_pid():
                logger.info('Conveyor still alive, awaiting %s time' % str(i + 1))
                time.sleep(sleep_time)
            else:
                logger.info('Makerbot Conveyor Service successfully killed.')
                return True
        logger.info('Could not kill Makerbot Conveyor Service. Please stop it manually and restart program.')