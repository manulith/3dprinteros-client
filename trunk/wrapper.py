#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import os
import time
import signal
import logging
from subprocess import Popen
import subprocess as subp

import utils
utils.init_path_to_libs()
import config
import version

import logging.handlers
import platform

class Wrapper:
    def __init__(self):
        self.logger = get_logger(config.config["wrapper_file"])
        self.logger.info("Welcome to 3DPrinterOS Wrapper version %s_%s" % (version.version, version.build))
        signal.signal(signal.SIGINT, self.intercept_signal)
        signal.signal(signal.SIGTERM, self.intercept_signal)
        self.stop_flag = False
        self.start_app()

    def start_app(self):
        self.logger.info('Launching App subprocess')
        client_dir = os.path.dirname(os.path.abspath(__file__))
        app_path = os.path.join(client_dir, 'app.py')
        try:
            self.app = Popen([sys.executable, app_path], stderr=subp.PIPE, bufsize=0)
            while not self.stop_flag:
                data = self.app.stderr.readline()
                if data is not "":
                    if "Traceback" in data:
                        self.logger.error("Wrapper detected Traceback!")
                    self.logger.info(data)

        except Exception as e:
            self.logger.warning('Could not launch App due to error:\n' + e.message)

    def quit(self):
        self.stop_flag = True
        self.logger.info("Shutdown app..")

        if self.app:
            self.app.terminate()

        time.sleep(0.1)
        self.time_stamp()
        self.logger.info("Shutdown logging..")
        logging.shutdown()
        self.logger.info("Exiting..")
        sys.exit(0)

    def time_stamp(self):
        self.logger.debug("Time stamp: " + time.strftime("%d %b %Y %H:%M:%S", time.localtime()))

    def intercept_signal(self, signal_code, frame):
        self.logger.warning("SIGINT or SIGTERM received. Closing 3DPrinterOS Client version %s_%s" % \
                            (version.version, version.build))
        self.quit()

def get_logger(log_file):
        logger = logging.getLogger("wrapper")
        logger.propagate = False
        logger.setLevel(logging.DEBUG)
        # stderr_handler = logging.StreamHandler()
        # stderr_handler.setLevel(logging.DEBUG)
        # logger.addHandler(stderr_handler)
        if log_file:
            try:
                file_handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=1024*1024*10, backupCount=0)
                file_handler.setFormatter(logging.Formatter('%(levelname)s\t%(asctime)s\t%(threadName)s/%(funcName)s\t%(message)s'))
                file_handler.setLevel(logging.DEBUG)
                logger.addHandler(file_handler)
            except Exception as e:
                logger.debug('Could not create log file because' + e.message + '\n.No log mode.')
        logger.info('Operating system: ' + platform.system() + ' ' + platform.release())
        return logger



if __name__ == '__main__':
    wrapper = Wrapper()