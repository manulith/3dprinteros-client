#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import time
import zipfile
import logging
import logging.handlers
import platform

from config import Config
import paths
import requests
import http_client
import version

LOG_SNAPSHOT_LINES = 200

def create_logger(logger_name, log_file_name):
    logger = logging.getLogger(logger_name)
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    stderr_handler = logging.StreamHandler()
    stderr_handler.setLevel(logging.DEBUG)
    logger.addHandler(stderr_handler)
    if log_file_name:
        try:
            file_handler = logging.handlers.RotatingFileHandler(log_file_name, maxBytes=1024*1024*10, backupCount=10)
            file_handler.setFormatter(logging.Formatter('%(levelname)s\t%(asctime)s\t%(threadName)s/%(funcName)s\t%(message)s'))
            file_handler.setLevel(logging.DEBUG)
            logger.addHandler(file_handler)
        except Exception as e:
            logger.debug('Could not create log file because' + e.message + '\n.No log mode.')
    return logger

def make_log_snapshot():
    logger = logging.getLogger("app." + __name__)
    with open(Config.instance().settings['log_file']) as log_file:
        log_text = "3DPrinterOS %s_%s_%s\n" % (version.version, version.build, version.commit)
        log_text += tail(log_file, LOG_SNAPSHOT_LINES)
    if not os.path.exists(paths.LOG_SNAPSHOTS_DIR):
        try:
            os.mkdir(paths.LOG_SNAPSHOTS_DIR)
        except IOError:
            logger.warning("Can't create directory %s" % paths.LOG_SNAPSHOTS_DIR)
            return
    while True:
        filename = time.strftime("%Y_%m_%d___%H_%M_%S", time.localtime()) + ".log"
        path = os.path.join(paths.LOG_SNAPSHOTS_DIR, filename)
        if os.path.exists(path):
            time.sleep(1)
        else:
            break
    with open(path, "w") as log_snap_file:
        log_snap_file.write(log_text)
    return path

def make_full_log_snapshot():
    logger = logging.getLogger("app." + __name__)
    for handler in logger.handlers:
        handler.flush()
    possible_paths = [os.path.abspath(os.path.dirname(__file__))]
    if sys.platform.startswith('linux'):
        possible_paths.append(os.path.abspath(os.path.expanduser("~")))
    log_files = []
    for path in possible_paths:
        for log in os.listdir(path):
            try:
                if log.startswith(Config.instance().settings['log_file']) or log.startswith(Config.instance().settings['error_file']):
                    log_files.append(log)
            except Exception:
                continue
    #logger.info('Files to log : ' + str(log_files))
    if not log_files:
        logger.info('Log files was not created for some reason. Nothing to send')
        return
    log_snapshots_dir = os.path.join(paths.get_paths_to_settings_folder()[0], paths.LOG_SNAPSHOTS_DIR)
    if not os.path.exists(log_snapshots_dir):
        try:
            os.mkdir(log_snapshots_dir)
        except Exception as e:
            logger.warning("Can't create directory %s" % log_snapshots_dir)
            return
    filename = time.strftime("%Y_%m_%d___%H_%M_%S", time.localtime()) + ".log"
    file_path = os.path.abspath(os.path.join(log_snapshots_dir, filename))
    logger.info('Creating snapshot file : ' + file_path)
    with open(file_path, 'w') as outfile:
        for fname in log_files:
            with open(fname, 'r') as infile:
                outfile.write('/////\nLog file:\n' + fname + '\n/////\n')  # See if logs are concatenated in right order
                for line in infile:
                    outfile.write(line)
            outfile.write('\n')
    return filename

def compress_and_send(user_token, log_file_name=None):
    logger = logging.getLogger('app.' + __name__)
    log_snapshots_dir = os.path.join(paths.get_paths_to_settings_folder()[0], paths.LOG_SNAPSHOTS_DIR)
    if not log_file_name:
        log_file_name = Config.instance().settings['log_file']
    zip_file_name = log_file_name + ".zip"
    log_file_name_path = os.path.abspath(os.path.join(log_snapshots_dir, log_file_name))
    zip_file_name_path = os.path.abspath(os.path.join(log_snapshots_dir, zip_file_name))
    logger.info('Creating zip file : ' + zip_file_name)
    try:
        zf = zipfile.ZipFile(zip_file_name_path, mode='w')
        zf.write(log_file_name_path, os.path.basename(log_file_name), compress_type=zipfile.ZIP_DEFLATED)
        zf.close()
    except Exception as e:
        logger.warning("Error while creating logs archive " + zip_file_name)
        logger.warning('Error: ' + e.message)
    else:
        get_path = http_client.HTTPClient()
        url = 'https://' + get_path.URL + get_path.token_send_logs_path
        #if http_client.multipart_upload(url, {"token": read_token()}, {'files': file}):
            #os.remove(LOG_SNAPSHOTS_DIR + '/' + log_file_name)
        user_token = {'user_token': user_token}
        logger.info('Sending logs to %s' % url)
        with open(zip_file_name_path, 'rb') as f:
            files = {'file_data': f}
            r = requests.post(url, data=user_token, files=files)
        result = r.text
        logger.info("Log sending response: " + result)
        os.remove(zip_file_name_path)
        if '"success":true' in result:
            os.remove(os.path.join(log_file_name_path))
        else:
            logger.warning('Error while sending logs: %s' % result)
            return result

def send_all_snapshots(user_token):
    log_snapshots_dir = os.path.join(paths.get_paths_to_settings_folder()[0], paths.LOG_SNAPSHOTS_DIR)
    try:
        snapshot_dir = os.listdir(log_snapshots_dir)
    except OSError:
        logging.info("No logs snapshots to send")
    else:
        for file_name in snapshot_dir:
            #print '\n\n%s\n\n' % str(file_name)
            if not file_name.endswith('zip'):
                error = compress_and_send(user_token, file_name)
                if error:
                    return False
        return True

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

def get_file_tail(file):
    if os.path.isfile(file):
        with open(file) as f:
            lines = f.readlines()
        file_tail = []
        for line in range(-1,-100, -1):
            try:
                file_tail.append(lines[line])
            except IndexError:
                break
        if file_tail:
            return file_tail