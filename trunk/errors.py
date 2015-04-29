import sys
import time
import traceback

EXCEPTIONS_LOG = 'critical_errors.log'

def log_exception(func):
    try:
        result = func()
    except SystemExit:
        pass
    except:
        trace = traceback.format_exc()
        print trace
        with open(EXCEPTIONS_LOG, "a") as f:
            f.write(time.ctime() + "\n" + trace + "\n")
        sys.exit(0)
    else:
        return result