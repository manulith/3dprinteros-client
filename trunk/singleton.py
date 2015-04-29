import threading

class InitSingleton(object):
    lock = threading.Lock()
    self = None

    @classmethod
    def instance(cls):
        print "Getting instance of " + cls.__name__
        return cls.self

    @classmethod
    def init(cls):
        if not cls.self:
            print "Getting instance of " + cls.__name__
            with cls.lock:
                print "Passed through lock"
                if not cls.self:
                    print "Creating new instance of " + cls.__name__
                    cls.self = cls()
        return cls.self

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
