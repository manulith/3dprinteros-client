import os
import sys
import time
import signal
import logging
import subprocess

def prepare_conveyor_import(makerware_path=True):
    if makerware_path:
        print "Found MakerWare in"
        print makerware_path
        egg_path = os.path.join(makerware_path, 'python')
        if os.path.exists(egg_path):
            for egg in os.listdir(egg_path):
                if egg.endswith('.egg'):
                    egg = os.path.join(egg_path, egg)
                    if egg not in sys.path:
                        sys.path.append(egg)
                        print "Add path to egg module:" + egg
    else:
        print 'No MakerWare found.'

def detect_makerware_paths():
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
    return makerware_path

def start_conveyor_service():
    #TODO improve and echance with try/finally protection against "conveyor server already running"
    logger = logging.getLogger('main')
    logger.info('Our own conveyor version is used')
    conv_path = detect_makerware_paths()
    if conv_path:
        logger.info('Conveyor directory: ' + conv_path)
        try:
            conveyor_start_binary = [conv_path, 'start_conveyor_service']
            conveyor_svc = subprocess.Popen(conveyor_start_binary, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            time.sleep(3)
            # this joins stdout and stderr
            response = ''.join(conveyor_svc.communicate())
        except EnvironmentError as e:
            logger.critical('Error starting conveyor server')
            logger.critical(e)
            return False
        if response.find('Already loaded') == -1:
            return None
            logger.info('Conveyor service is started')
        else:
            return conveyor_svc
            logger.info('Conveyor service is already running')

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
    pid = get_conveyor_pid()
    if pid:
        if sys.platform.startswith('win'):
            os.popen('taskkill /f /pid ' + pid)
        elif sys.platform.startswith('linux'):
            # TODO: it does not work
            os.kill(int(pid), signal.SIGTERM)
        elif sys.platform.startswith('darwin'):
            makerware_path = detect_makerware_paths()
            os.popen(os.path.join(makerware_path, 'stop_conveyor_service'))