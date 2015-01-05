#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import logging
import subprocess

def prepare_conveyor_import():
    sys.path.append(get_our_birdwing_dir())

def get_program_root():
    path = os.path.join(get_our_birdwing_dir(), "..")
    path = os.path.abspath(path)
    return path

def get_our_birdwing_dir():
    path = __file__
    path = os.path.abspath(path)
    dir_path = os.path.dirname(path)
    return dir_path

def get_conveyor_server():
    run_dir = get_our_birdwing_dir()
    path = os.path.join(run_dir, "conveyor", "server", "__main__.py")
    #remove double abspath if new get_our_birdwing_dir will hold
    return os.path.abspath(path)

def get_conveyor_client():
    run_dir = get_our_birdwing_dir()
    path = os.path.join(run_dir, "conveyor", "client", "__main__.py")
    #remove double abspath if new get_our_birdwing_dir will hold
    return os.path.abspath(path)

def get_conveyor_env():
    environment = os.environ
    if sys.platform.startswith('win'):
        separator = ";"
    else:
        separator = ":"
    environment.update({'PYTHONPATH' : get_program_root() + separator + get_our_birdwing_dir()})
    return environment

def start_conveyor_service():
    logger = logging.getLogger('main')
    logger.info('Our own conveyor version is used')
    call = [sys.executable, get_conveyor_server()]
    logger.debug(call)
    server = subprocess.Popen(call, stderr = subprocess.STDOUT, env = get_conveyor_env())
    # TODO: check for _pid_file_exists method in conveyor/client/__init__.py and implement it in our client
    svc_return = server.poll()
    if svc_return != None:
        logger.critical('Error: conveyor server start failed. Code' + str(svc_return))
        return None
    return server


