import threading

class Singleton(object):
    lock = threading.Lock()
    _instance = None

    @classmethod
    def instance(cls):
        if not cls._instance:
            print "Getting instance of " + cls.__name__
            with cls.lock:
                print "Passed through lock"
                if not cls._instance:
                    print "Creating new instance of " + cls.__name__
                    cls._instance = cls()
        return cls._instance
