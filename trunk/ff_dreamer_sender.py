import re
import raw_usb_sender
import time
import usb.core

class Sender(raw_usb_sender.Sender):

    #M601_HANDSHAKE = "~M601 S0\r\n"
    #TEMP_REQUEST_GCODE = '~M105\r\n'
    #M602_LOGOUT = "~M602\r\n"

    M601_HANDSHAKE = "M601 S0\r"
    TEMP_REQUEST_GCODE = 'M105'
    M602_LOGOUT = "~M602\r\n"

    def __init__(self, profile, usb_info, app):
        raw_usb_sender.Sender.__init__(self, profile, usb_info, app)
        #self.endpoint_out = 0x1
        #self.endpoint_in = 0x81
        self.define_regexps()
        self.logger.info('FlashForge Dreamer Sender started!')

    def define_regexps(self):
        self.temp_re = re.compile('T0:([\d\.]+) /([\d\.]+) T1:([\d\.]+) /([\d\.]+) B:([\d\.]+) /([\d\.]+)')

    def handshake(self):
        self.logger.info('Handshaking to printer')
        self.write('M601 S0')  # TODO: get and parse answer string, for now printer does not return anything.
        #time.sleep(0.01)
        #self.read()

    def define_endpoints(self):
        self.endpoint_in = 0x81
        self.endpoint_out = 0x1

    def parse_response(self, ret):
        self.logger.info('Parsing %s' % ret)
        if ret == 'ok':
            self.oks += 1
        elif ret.startswith('T0:'):
            self.temp_request_counter -= 1
            match = self.match_temps(ret)
            if match:
                self.logger.info('TEMP UPDATE')
        else:
            self.logger.debug('Got unpredictable answer from printer: %s' % ret.decode())

    # M105 based matching. Redefine if needed.
    def match_temps(self, request):
        match = self.temp_re.match(request)
        if match:
            tool_temp = float(match.group(1))
            tool_target_temp = float(match.group(2))
            # TODO: add 2nd extruder(3 and 4 pos)
            platform_temp = float(match.group(5))
            platform_target_temp = float(match.group(6))
            self.temps = [platform_temp, tool_temp]
            self.target_temps = [platform_target_temp, tool_target_temp]
            #self.logger.info('Got temps: T %s/%s B %s/%s' % (tool_temp, tool_target_temp, platform_temp, platform_target_temp))
            return True
        return False

    def pause(self):
        pass
        # if not self.pause_flag:
        #     self.logger.info("Pausing...")
        #     self.pause_flag = True
        #     self.get_pos_counter += 1
        #     with self.write_lock:
        #         self.write('get pos')

    def temp_request(self):
        while not self.stop_flag:
            time.sleep(2)
            with self.write_lock:
                self.write(self.TEMP_REQUEST_GCODE)

    def read(self):
        try:
            print 'Reading...'
            #data = self.dev.read(self.endpoint_in.bEndpointAddress, self.endpoint_in.wMaxPacketSize, 2000)
            data = self.dev.read(self.endpoint_in, 64, 2000)
        except usb.core.USBError as e:
            self.logger.info('USBError : %s' % str(e))
            # TODO: parse ERRNO 110 here to separate timeout exceptions | [Errno 110] Operation timed out
            return None
        except Exception as e:  # TODO: make not operational
            self.logger.warning('Error while reading gcode: %s' % str(e))
            return None
        else:
            return data

    def write(self, gcode):
        try:
            print 'Writing...'
            self.dev.write(self.endpoint_out, '~' + gcode + '\n', 2000)
        #except usb.core.USBError:
        except Exception as e:
            self.logger.warning('Error while writing gcode "%s"\nError: %s' % (gcode, e.message))
        else:
            print 'SENT: %s' % gcode