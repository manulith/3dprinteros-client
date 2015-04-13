import threading

class Singleton(object):
    lock = threading.Lock()
    _instance = None

    @classmethod
    def instance(cls):
        if not cls._instance:
            print "C1"
            print cls.__name__
            with cls.lock:
                print "C2"
                if not cls._instance:
                    print "C3"
                    cls._instance = cls()
        return cls._instance
