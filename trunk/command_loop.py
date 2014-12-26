import logging
import threading
import collections
import Queue

import command
import utils
import printer_interface

class LockedList(list):

    def __init__(self):
        self.lock = threading.Lock()
        super(LockedList, self).__init__()

    def pop(self):
        with self.lock:
            ret = super(LockedList, self).pop()
        return ret

    def append(self, item):
        with self.lock:
            super(LockedList, self).append(item)

    def __getitem__(self, item):
        with self.lock:
            ret = super(LockedList, self).__getitem__(item)
        return ret

    def __setitem__(self, item):
        with self.lock:
            super(LockedList, self).__setitem__(item)

@utils.singleton
class CommandLoop(object):

    LOOPTIME = 6

    def __init__(self):
        self.logger = logging.getLogger('main')
        self.next_condition = threading.Condition()
        self.queue = collections.deque
        self.state = None

        self.running_commands = LockedList()
        self.waiting_commands = Queue.Queue(1)
        self.running_flag = True
        self.run()

    def enqueue_command(self, proto_command_data):
        com = command.Command(proto_command_data)
        self.waiting_commands.put_nowait(com)

    def next(self):
        pass


    @utils.elapse_stretcher(LOOPTIME)
    def run(self):
        #while self.running_flag:
          print 1

class CommandProcessor(object):
    pass

if __name__ == "__main__":
    c = CommandLoop()