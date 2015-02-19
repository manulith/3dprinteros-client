#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import time
import signal
import logging
import subprocess
import utils


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


def start_conveyor_service():
    #TODO improve and echance with try/finally protection against "conveyor server already running"
    logger = logging.getLogger('main')
    logger.info('Our own conveyor version is used')
    conv_path = utils.detect_makerware_paths()
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