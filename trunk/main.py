import config

import time
import logging
import logging.handlers

import http_printer

__version__ = "0.1"
box_version = False

def init_logger():
    logger = logging.getLogger(__name__)
    #logger.propagate = False
    logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(levelname)-8s\t%(threadName)-15s\t%(module)-8s\t%(funcName)-15s\t%(asctime)-25s\t%(message)s')
    #formatter = logging.Formatter('%(levelname)s\t%(asctime)s\t%(threadName)s/%(funcName)s\t%(message)s')
    formatter = logging.Formatter('%(asctime)s\t%(threadName)s/%(funcName)s\t%(message)s')
    stderr_handler = logging.StreamHandler()
    stderr_handler.setLevel(logging.DEBUG)
    stderr_handler.setFormatter(formatter)
    logger.addHandler(stderr_handler)
    log_file = config.config['log_file']
    if log_file:
        try:
            file_handler = logging.handlers.RotatingFileHandler(log_file, maxBytes=1024*1024*100, backupCount=1)
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except:
            logger.debug('Could not create log file. No log mode.')
    return logger

if __name__ == '__main__':
    logger = init_logger()
    logger.info('Starting 3DPrinterOS client version ' + __version__)

    if box_version:
        pass
    else:
        import GUI

    server = None
    printer = None
    logger.info('Start http_server')
    try:
        server = http_printer.ThreadedHTTPServer((config.config['ip'], 8008), http_printer.HTTPPrinterHandler)
        server.serve_forever()
    finally:
        logger.info('Stopping http_server')
        time.sleep(0.5)
        if server:
            server.shutdown()
        if http_printer.printer:
            try: http_printer.printer.close_now()
            except: pass
        logger.info('Exiting 3DPrinterOS client version ' + __version__)

