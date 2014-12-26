import os
import sys
import time
import logging
import threading

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
    SLEEP_STEP = 0.1
    def edec(func):
        def idec(*args, **kwargs):
            start_time = time.time()
            result = func(*args, **kwargs)
            while (time.time() - start_time) < looptime:
                time.sleep(SLEEP_STEP)
            return result
        return idec
    return edec

def get_libusb_path(lib):
    logger = logging.getLogger('app.' + __name__)
    logger.info("Using: " + lib)
    if sys.platform.startswith('win'):
        # We are using x32 python in our software which cannot handle with x64 dll
        # if 'PROGRAMFILES(X86)' in os.environ:
        #     libusb_name = 'libusb-1.0-64.dll'
        # else:
        #     libusb_name = 'libusb-1.0.dll'
        libusb_name = 'libusb-1.0.dll'
    elif sys.platform.startswith('linux'):
        libusb_name = 'libusb-1.0.so'
    elif sys.platform.startswith('darwin'):
        libusb_name = 'libusb-1.0.dylib'
    else:
        raise EnvironmentError('Could not detect OS. Only GNU/LINUX, MAC OS X and MS WIN VISTA/7/8 are supported.')
    our_dir = os.path.dirname(os.path.abspath(__file__))
    backend_path = os.path.join(our_dir, libusb_name)
    logger.info('Using: ' + backend_path)
    return backend_path

def read_token():
    logger = logging.getLogger('app.' + __name__)
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
    paths = [os.path.join('./', token_file_name)]
    paths.append(path)
    for path in paths:
        logger.debug("Searching for token-file in %s" % path)
        with open(path) as token_file:
            try:
                token = token_file.read()
                logger.debug('Token loaded from ' + path)
            except IOError as e:
                continue
            return token.strip()
    logger.debug('Error while loading token in paths: %s' % str(paths) )

if __name__ == '__main__':
    logging.basicConfig()

    print read_token()