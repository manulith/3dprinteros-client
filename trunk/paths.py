#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import logging
import platform

LIBRARIES_FOLDER = 'libraries'
LIBRARIES = ['opencv', 'numpy', 'printrun']

def init_path_to_libs():
    #logger = logging.getLogger(__name__)
    if sys.platform.startswith('win'):
        folder_name = "win"
        LIBRARIES.append('pywin')
    elif sys.platform.startswith('linux'):
        folder_name = "linux"
    elif sys.platform.startswith('darwin'):
        folder_name = "mac"
    else:
        raise RuntimeError('Cannot define operating system')
    our_dir = os.path.dirname(os.path.abspath(__file__))
    platform_dir = os.path.join(our_dir, LIBRARIES_FOLDER, folder_name)
    for lib in LIBRARIES:
        lib_path = os.path.join(platform_dir, lib)
        #logger.info('Using library: ' + lib_path)
        print 'Using library: ' + lib_path
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
    backend_path = os.path.join(our_dir, LIBRARIES_FOLDER, folder_name, 'libusb', libusb_name)
    logger.info('Libusb from: ' + backend_path)
    return backend_path

def get_paths_to_settings_folder():
    abs_path_to_users_home = os.path.abspath(os.path.expanduser("~"))
    if sys.platform.startswith('win'):
        abs_path_to_appdata = os.path.abspath(os.getenv('APPDATA'))
        path = os.path.join(abs_path_to_appdata, '3DPrinterOS')
    elif sys.platform.startswith('linux'):
        path = os.path.join(abs_path_to_users_home, ".3DPrinterOS")
    elif sys.platform.startswith('darwin'):
        path = os.path.join(abs_path_to_users_home, "Library", "Application Support", "3DPrinterOS")
    else:
        raise EnvironmentError('Could not detect OS. Only GNU/LINUX, MAC OS X and MS WIN VISTA/7/8 are supported.')
    local_path = os.path.dirname(os.path.abspath(__file__))
    return (path, local_path)

SETTINGS_FOLDER_PATH = get_paths_to_settings_folder()[0]
if not os.path.exists(SETTINGS_FOLDER_PATH):
    os.mkdir(SETTINGS_FOLDER_PATH)