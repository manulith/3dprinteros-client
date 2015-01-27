#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import time
import string
import zipfile
import logging
import threading
import platform
from hashlib import md5
import base64

import config
import http_client
import requests
import version

LIBS_FOLDER = 'libraries'
ALL_LIBS = ['opencv', 'numpy']
LOG_SNAPSHOTS_DIR = "log_snapshots"

LOG_SNAPSHOT_LINES = 200



def is_admin():
    import ctypes, os
    try:
        is_admin = os.getuid() == 0
    except:
        is_admin = ctypes.windll.shell32.IsUserAnAdmin()

    print is_admin

def md5_hash(text):
    hash = md5(text)
    hex_str_hash = hash.hexdigest()
    return hex_str_hash

def singleton(cls):
    instances = {}
    lock = threading.Lock()
    def getinstance():
        with lock:
            if cls not in instances:
                instances[cls] = cls()
        return instances[cls]
    return getinstance()

def elapse_stretcher(looptime):
    SLEEP_STEP = 0.01
    def edec(func):
        def idec(*args, **kwargs):
            start_time = time.time()
            result = func(*args, **kwargs)
            while (time.time() - start_time) < looptime:
                time.sleep(SLEEP_STEP)
            return result
        return idec
    return edec

def init_path_to_libs():
    logger = logging.getLogger('app.' + __name__)
    if sys.platform.startswith('win'):
        folder_name = "win"
        ALL_LIBS.append('pywin')
    elif sys.platform.startswith('linux'):
        folder_name = "linux"
    elif sys.platform.startswith('darwin'):
        folder_name = "mac"
    else:
        raise RuntimeError('Cannot define operating system')
    our_dir = os.path.dirname(os.path.abspath(__file__))
    platform_dir = os.path.join(our_dir, LIBS_FOLDER, folder_name)
    for lib in ALL_LIBS:
        lib_path = os.path.join(platform_dir, lib)
        logger.info('Using library: ' + lib_path)
        sys.path.append(lib_path)


def get_libusb_path(lib):
    logger = logging.getLogger('app.' + __name__)
    logger.info('Using: ' + lib)
    if sys.platform.startswith('win'):
        folder_name = "win"
        python_version = platform.architecture()[0]
        if '64' in python_version:
            libusb_name = 'libusb-1.0-64.dll'
        else:
            libusb_name = 'libusb-1.0.dll'
    elif sys.platform.startswith('linux'):
        folder_name = "linux"
        libusb_name = 'libusb-1.0.so'
    elif sys.platform.startswith('darwin'):
        folder_name = "mac"
        libusb_name = 'libusb-1.0.dylib'
    else:
        raise EnvironmentError('Could not detect OS. Only GNU/LINUX, MAC OS X and MS WIN VISTA/7/8 are supported.')
    our_dir = os.path.dirname(os.path.abspath(__file__))
    backend_path = os.path.join(our_dir, LIBS_FOLDER, folder_name, 'libusb', libusb_name)
    logger.info('Libusb from: ' + backend_path)
    return backend_path

# def get_paths_to_token():
#     token_file_name = "3DPrinterOS-Key"
#     abs_path_to_users_home = os.path.abspath(os.path.expanduser("~"))
#     if sys.platform.startswith('win'):
#         abs_path_to_appdata = os.path.abspath(os.getenv('APPDATA'))
#         path = os.path.join(abs_path_to_appdata, '3DPrinterOS', token_file_name)
#     elif sys.platform.startswith('linux'):
#         path = os.path.join(abs_path_to_users_home, "." + token_file_name)
#     elif sys.platform.startswith('darwin'):
#         path = os.path.join(abs_path_to_users_home, "Library", "Application Support", token_file_name)
#     else:
#         raise EnvironmentError('Could not detect OS. Only GNU/LINUX, MAC OS X and MS WIN VISTA/7/8 are supported.')
#     local_path = os.path.dirname(os.path.abspath(__file__))
#     local_path = os.path.join(local_path, token_file_name)
#     return (local_path, path)
#
# def read_token():
#     logger = logging.getLogger('app.' + __name__)
#     paths = get_paths_to_token()
#     for path in paths:
#         logger.debug("Searching for token-file in %s" % path)
#         try:
#             with open(path) as token_file:
#                 token = token_file.read()
#                 logger.debug('Token loaded from ' + path)
#         except IOError:
#             continue
#         else:
#             return token.strip()
#     logger.debug('Error while loading token in paths: %s' % str(paths) )
#
# def write_token(token_data):
#     logger = logging.getLogger('app.' + __name__)
#     paths = get_paths_to_token()
#     path = paths[0] # we are only writing locally
#     try:
#         with open(path, "w") as token_file:
#             token_file.write(token_data)
#     except IOError as e:
#         logger.warning("Error while writing token" + str(e))
#     else:
#         logger.debug('Token was writen to ' + path)
#         return True

#here start login utils

def read_login():
    logger = logging.getLogger('app.' + __name__)
    pack_name = 'login_info.bin'
    logger.debug("Searching for login info in %s" % pack_name)
    try:
        login_info = read_info_zip(pack_name)
        logger.debug('Login info loaded from ' + pack_name)
    except Exception as e:
        logger.warning('Failed login loading! ' + e.message)
    else:
        return login_info
    logger.debug('Error while loading login info in paths: %s' % str(pack_name) )

def write_login(login, password):
    logger = logging.getLogger('app.' + __name__)
    package_name = 'login_info.bin' #TODO: it probably shoud be read from config
    try:
        pack_info_zip(package_name, login, password)
    except Exception as e:
        logger.warning('Login info writing error! ' + e.message)
    else:
        logger.info('Login info was written and packed.')
        return True

#login utils end

def tail(f, lines=200):
    total_lines_wanted = lines
    BLOCK_SIZE = 1024
    f.seek(0, 2)
    block_end_byte = f.tell()
    lines_to_go = total_lines_wanted
    block_number = -1
    blocks = [] # blocks of size BLOCK_SIZE, in reverse order starting
                # from the end of the file
    while lines_to_go > 0 and block_end_byte > 0:
        if (block_end_byte - BLOCK_SIZE > 0):
            # read the last block we haven't yet read
            f.seek(block_number*BLOCK_SIZE, 2)
            blocks.append(f.read(BLOCK_SIZE))
        else:
            # file too small, start from begining
            f.seek(0,0)
            # only read what was not read
            blocks.append(f.read(block_end_byte))
        lines_found = blocks[-1].count('\n')
        lines_to_go -= lines_found
        block_end_byte -= BLOCK_SIZE
        block_number -= 1
    all_read_text = ''.join(reversed(blocks))
    return '\n'.join(all_read_text.splitlines()[-total_lines_wanted:])

def make_log_snapshot():
    logger = logging.getLogger("app." + __name__)
    with open(config.config['log_file']) as log_file:
        log_text = "3DPrinterOS %s_%s_%s\n" % (version.version, version.build, version.commit)
        log_text += tail(log_file, LOG_SNAPSHOT_LINES)
    if not os.path.exists(LOG_SNAPSHOTS_DIR):
        try:
            os.mkdir(LOG_SNAPSHOTS_DIR)
        except Exception as e:
            logger.warning("Can't create directory %s" % LOG_SNAPSHOTS_DIR)
            return
    while True:
        filename = time.strftime("%Y_%m_%d___%H_%M_%S", time.localtime()) + ".log"
        path = os.path.join(LOG_SNAPSHOTS_DIR, filename)
        if os.path.exists(path):
            time.sleep(1)
        else:
            break
    with open(path, "w") as log_snap_file:
        log_snap_file.write(log_text)
    return path

def compress_and_send(log_file_name=None, server_path=http_client.token_send_logs_path):
    logger = logging.getLogger('app.' + __name__)
    if not log_file_name:
        log_file_name = config.config['log_file']
    zip_file_name = log_file_name + ".zip"
    try:
        zf = zipfile.ZipFile(zip_file_name, mode='w')
        zf.write(LOG_SNAPSHOTS_DIR + '/' + log_file_name, os.path.basename(log_file_name), compress_type=zipfile.ZIP_DEFLATED)
        zf.close()
    except Exception as e:
        logger.warning("Error while creating logs archive " + zip_file_name)
    else:
        url = 'https://' + http_client.AUX_URL + http_client.token_send_logs_path
        #if http_client.multipart_upload(url, {"token": read_token()}, {'files': file}):
            #os.remove(LOG_SNAPSHOTS_DIR + '/' + log_file_name)
        token = {'token': read_token()}
        f = open(zip_file_name)
        files = {'file_data': f}
        r = requests.post(url, data = token, files = files)
        f.close()
        result = r.text
        print "Log sending response: " + result
        if '"success":true' in result:
            os.remove(LOG_SNAPSHOTS_DIR + '/' + log_file_name)
        os.remove(zip_file_name)

def send_all_snapshots():
    try:
        dir = os.listdir(LOG_SNAPSHOTS_DIR)
    except OSError:
        logging.info("No logs snapshots to send")
    else:
        for file_name in dir:
            compress_and_send(file_name)
        return  True

def pack_info_zip(package_name, *args):
    if package_name in os.listdir(os.getcwd()):
        print 'File with that package name already exists in the working dir. Please choose another one'
        return
    file_name = 'info'
    temp_file = open(file_name, 'w')
    for arg in args:
        arg = base64.b64encode(arg)
        temp_file.write(arg + '\n')
    temp_file.close()
    try:
        zf = zipfile.ZipFile(package_name, mode='w')
        zf.write(file_name)
        zf.setpassword('d0nTfe_artH_er1PPe_r')
        zf.close()
    except Exception as e:
        print 'Error: ' + e.message
        return
    os.remove(file_name)

def read_info_zip(package_name):
    if package_name not in os.listdir(os.getcwd()):
        print 'Package not found'
        return
    zf = zipfile.ZipFile(package_name, 'r')
    packed_info = zf.read('info', pwd='d0nTfe_artH_er1PPe_r')
    packed_info = packed_info.split('\n')
    packed_info.remove('')
    for number in range(0, len(packed_info)):
        packed_info[number] = base64.b64decode(packed_info[number])
    return packed_info


def kill_makerbot_conveyor(self):
    logger = logging.getLogger("app.kill_makerbot_conveyor")
    logger.info('[Stopping third party software...')
    try:
        from birdwing.conveyor_from_egg import kill_existing_conveyor
        kill_existing_conveyor()
    except ImportError as e:
        logger.debug(e)
        logger.info('...fail]')
    else:
        logger.info('...done]')

def check_for_errors(data_dict):
    logger = logging.getLogger("app." + __name__)
    error = data_dict.get('error', None)
    if error:
        logger.warning("Server returned error %s:%s" % (error[0], error[1]))
        return error[0]

def remove_illegal_symbols(data):
    count = 0
    length = len(data)
    while count < len(data):
        if not data[count] in string.printable:
            data.replace(data[count], "")
        count += 1
    return data

def remove_corrupted_lines(lines):
    for line in lines:
        if not line or line in string.whitespace:
            lines.remove(line)
    return lines



if __name__ == "__main__":
    make_log_snapshot()
    send_all_snapshots()
