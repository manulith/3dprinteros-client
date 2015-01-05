import logging
import threading
from collections import deque

import config

_logger = logging.getLogger('app')
lock = threading.Lock()
messages = deque()

_PROGRAM_STARTED = 'Program started!'

def notificate(message):
    if config.config['gui']:
        with lock:
            messages.append(message)
    _logger.info(message)

def program_started():
    notificate(_PROGRAM_STARTED)

def stub():
    notificate('STUB!')


