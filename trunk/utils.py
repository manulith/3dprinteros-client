#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import time
import uuid
import zipfile
import logging
import threading
import platform

from hashlib import md5

LIBS_FOLDER = 'libraries'
ALL_LIBS = ['opencv', 'numpy']

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

def get_paths_to_token():
    token_file_name = "3DPrinterOS-Key"
    abs_path_to_users_home = os.path.abspath(os.path.expanduser("~"))
    if sys.platform.startswith('win'):
        abs_path_to_appdata = os.path.abspath(os.getenv('APPDATA'))
        path = os.path.join(abs_path_to_appdata, '3DPrinterOS', token_file_name)
    elif sys.platform.startswith('linux'):
        path = os.path.join(abs_path_to_users_home, "." + token_file_name)
    elif sys.platform.startswith('darwin'):
        path = os.path.join(abs_path_to_users_home, "Library", "Application Support", token_file_name)
    else:
        raise EnvironmentError('Could not detect OS. Only GNU/LINUX, MAC OS X and MS WIN VISTA/7/8 are supported.')
    local_path = os.path.dirname(os.path.abspath(__file__))
    local_path = os.path.join(local_path, token_file_name)
    return (local_path, path)

def read_token():
    logger = logging.getLogger('app.' + __name__)
    paths = get_paths_to_token()
    for path in paths:
        logger.debug("Searching for token-file in %s" % path)
        try:
            with open(path) as token_file:
                token = token_file.read()
                logger.debug('Token loaded from ' + path)
        except IOError:
            continue
        else:
            return token.strip()
    logger.debug('Error while loading token in paths: %s' % str(paths) )

def write_token(token_data):
    logger = logging.getLogger('app.' + __name__)
    paths = get_paths_to_token()
    path = paths[0] # we are only writing locally
    try:
        with open(path, "w") as token_file:
            token_file.write(token_data)
    except IOError as e:
        logger.warning("Error then writing token" + str(e))
    else:
        logger.debug('Token was writen to ' + path)
        return True


def zip_file(file_obj_or_path):
    if type(file_obj_or_path) == str:
        try:
            file_obj = open(file_obj_or_path, "rb")
            data = file_obj.read()
            file_obj.close()
        except IOError:
            logging.debug("Error zipping file %s" % str(file_obj_or_path))
            return False
    return zip_data_into_file(data)

def zip_data_into_file(data):
    zip_file_name = uuid.uuid1()
    zf = zipfile.ZipFile(zip_file_name, mode='w')
    zf.write(data, compress_type=zipfile.ZIP_DEFLATED)
    zf.close()
    return zf

if __name__ == "__main__":
    print get_libusb_path()
