import re
import usb
import time
import utils
import logging
import threading
import collections

class Printer:

    GCODES_IN_BUFFER_IN_ONE_TIME = 15
    READ_TIMEOUT = 5
    TEMP_QUERY_COOF = 500 # 0.01*N second between M105
    M105 = '~M105\r\n'
    M119 = '~M119\r\n'
    M601_HANDSHAKE = "~M601 S0\r\n"
    M602_LOGOUT = "~M602\r\n"
    BUFFER_FULL_MESSAGE = 'buffer full'

    def __init__(self, profile):
        self.operational_flag = False
        self.logger = logging.getLogger('app.' + __name__)
        self.profile = profile        
        int_vid = int(self.profile['VID'], 16)
        int_pid = int(self.profile['PID'], 16)
        backend_from_our_directory = usb.backend.libusb1.get_backend(find_library=utils.get_libusb_path)
        dev = usb.core.find(idVendor=int_vid, idProduct=int_pid, backend=backend_from_our_directory)
        dev.set_configuration()
        self.dev = dev
        self.read_length = 4096
        self.endpoint_out = 0x1
        self.endpoint_in = 0x81
        self.counter = 0
        self.gcodes_in_printers_buffer = 0
        self.ok_count = 0
        self.stop_flag = False
        self.total_gcodes_in_this_job = 0
        self.tool_temp = 0
        self.tool_target_temp = 0
        self.error = ""
        self.define_regexp()
        self.buffer_full_flag = False
        self.pause_flag = False
        self.buffer = collections.deque()
        self.buffer_lock = threading.Lock()
        self.send_handshake()
        self.main_loop_thread = threading.Thread(target = self.main_loop, name="Dremels sending thread")
        self.main_loop_thread.start()
        self.operational_flag = True

    def define_regexp(self):        
        self.temp_re = re.compile("T:([\d\.]+) /([\d\.]+) B:(-?[\d\.]+) /(-?[\d\.]+).*ok")
        #self._position_re = re.compile('.*X:([\d\.]+) Y:([\d\.]+) Z:([\d\.]+).*')
        self.buffer_re = re.compile(self.BUFFER_FULL_MESSAGE)
        #self.received_re = re.compile('Received')

    def send_handshake(self):        
        self.read()
        self.write(self.M601_HANDSHAKE)
        self.read()
        time.sleep(0.5)

    def set_read_length(self, length):
        self.read_length = length

    def write(self, data):
        self.logger.info("Writing: %s" % data)
        try:
            self.dev.write(self.endpoint_out, data)
        except usb.USBError as e:
            self.logger.error("Error while writing - %s" % e.message)
            self.close()
        else:
            self.gcodes_in_printers_buffer += 1
            self.counter += 1

    def read(self, read_length=None, clear_buffer=False):
        try:
            ret = self.dev.read(self.endpoint_in, self.read_length, self.READ_TIMEOUT)
        except usb.core.USBError as e:
            ret = []
            self.logger.info("Read Timeout or %s" % str(e))
        sret = "".join([chr(x) for x in ret])
        self.logger.info(sret)
        if not clear_buffer:
            self.parse_response(sret)
            return sret

    def begin(self, length):
        self.set_total_gcodes(length)

    def set_total_gcodes(self, length):
        self.counter = 0
        self.total_gcodes_in_this_job = length
        self.buffer.clear()

    def pause(self):
        if not self.pause_flag:
            self.pause_flag = True
        else:
            self.resume()

    def resume(self):
        self.pause_flag = False

    def enqueue(self, gcodes):
        self.gcodes(gcodes)

    def gcodes(self, gcodes):
        if type(gcodes) == str:
            gcodes = gcodes.split("\n")
        if type(gcodes) == list:
            with self.buffer_lock:
                self.buffer.extend(gcodes)
        else:
            raise RuntimeError("GCodes expected to be list or str")

    def close(self):
        self.logger.info("Closing " + __name__  +  "...")
        self.stop_flag = True
        self.operational_flag = False
        self.logger.info("...closed")
        self.write(self.M602_LOGOUT) #logoff printer
        self.clear_usb_buffer()
        self.dev.close()

    def is_operational(self):
        return self.operational_flag

    def is_paused(self):
        return self.pause_flag

    def send_next_if_ready(self):
        if not self.pause_flag:
            gcode = None
            if not self.buffer_full_flag and self.gcodes_in_printers_buffer < self.GCODES_IN_BUFFER_IN_ONE_TIME:
                with self.buffer_lock:
                    gcode = self.buffer.popleft()
            if gcode:
                if not gcode.startswith("~"):
                    gcode = "~" + gcode
                gcode = gcode.strip() + "\r\n"
                self.write(gcode)
        elif self.buffer[0] == self.M105:
            gcode = self.buffer.popleft()
            assert gcode != self.M105
            self.write(gcode)

    def cancel(self):
        self.clear_usb_buffer()
        self.buffer.clear()
        self.ok_count = 0
        self.gcodes_in_printers_buffer = 0

    #TODO
    def main_loop(self):
        last_temp_query_number = 0
        while not self.stop_flag:
            #time.sleep(0.05)
            time.sleep(0.001)
            if self.counter > (last_temp_query_number + self.TEMP_QUERY_COOF):
                last_temp_query_number = self.counter
                self.buffer.appendleft(self.M105)
                self.buffer.appendleft(self.M119)
                print self.report()
            if self.buffer:
                self.send_next_if_ready()
                self.read()
                print "Send gcodes count %i" % self.counter


    def parse_response(self, response):
        self.search_for_temperature(response)
        self.search_for_buffer(response)
        self.search_for_ok(response)

    def search_for_temperature(self, response):
        match = self.temp_re.search(response)
        if match:
            self.tool_temp = int(match.group(1))
            self.tool_target_temp = int(match.group(2))
            self.logger.info("Temp: %s/%s" % (self.tool_temp, self.tool_target_temp))

    def search_for_buffer(self, response):
        match = self.buffer_re.search(response)
        if match:
            self.buffer_full_flag = True
            self.logger.info("!Buffer is full")

    def search_for_ok(self, response):
        oks = response.count("ok")
        if oks:
            self.buffer_full_flag = False
            self.gcodes_in_printers_buffer -= oks
            self.ok_count += oks
            self.logger.info("OK %i" % self.ok_count)

    # def search_for_received(self, response):
    #     match = self.received_re.match(response)
    #     if match:
    #         self.gcodes_in_printers_buffer
    #         self.logger.info("OK")

    def clear_usb_buffer(self):
        self.read(4096, True)

    def report(self):
        status = 'no_printer'
        if self.operational_flag:
            if self.buffer:
                if abs(self.tool_target_temp - self.tool_temp) < 10:
                    status = 'printing'
                else:
                    status = 'heating'
            else:
                status = 'ready'
        if self.total_gcodes_in_this_job:
            percent = int(self.counter / self.total_gcodes_in_this_job) * 100
        else:
            percent = 0
        result = {
            #'position' : self._position,
            'status': status,
            'platform_temperature': 0,
            'platform_target_temperature': 0,
            'toolhead1_temperature': self.tool_temp,
            'toolhead1_target_temperature': self.tool_target_temp,
            'toolhead2_temperature': 0,
            'toolhead2_target_temperature': 0,
            'percent': percent,
            'buffer_free_space': 10000,
            'last_error':  {}
        }
        return result

    def end(self):
        pass

if __name__ == '__main__':
    import usb_detect
    logging.basicConfig(level = logging.DEBUG)
    profiles = usb_detect.get_printers()
    print profiles
    if profiles:
        p = Printer(profiles[0])
        while not p.is_operational():
            print 'waiting'
            time.sleep(3)
        print 'ready'
        with open("tree_anton.gcode", "r") as f:
            gcodes = f.read()
        p.enqueue(gcodes.split("\n"))
        try:
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            p.close()
    else:
        print "Printer is not connected"
