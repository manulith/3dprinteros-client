from printrun.printcore import printcore
from printrun.gcoder import LightGCode
import re
import threading
import time
import logging

import base_sender


class Sender(base_sender.BaseSender):

    pause_lift_height = 5
    pause_extrude_length = 7

    TEMP_REQUEST_WAIT = 5

    def __init__(self, profile):
        self.logger = logging.getLogger('app.' + __name__)
        base_sender.BaseSender.__init__(self, profile)
        self.define_regexp()
        self.select_baudrate_and_connect()
        self.extruder_count = self.profile['extruder_count']
        self.init_callbacks()
        self.total_gcodes = 0
        self.temp_request_thread = threading.Thread(target=self.temp_request)
        self.temp_request_thread.start()
        for gcode in self.profile['end_gcodes']:
            self.printcore.send_now(gcode)

    def init_callbacks(self):
        self.printcore.tempcb = self.tempcb
        #self.printcore.recvcb = self.recvcb
        self.printcore.sendcb = self.sendcb
        #self.printcore.errorcb = self.errorcb

    def select_baudrate_and_connect(self):
        self.firmware_loaded = False
        baudrate_count = 0
        baudrates = self.profile['baudrate']
        self.logger.info('Baudrates list for %s : %s' % (self.profile['name'], str(baudrates)))
        while not self.firmware_loaded:
            if baudrate_count >= len(baudrates):
                raise RuntimeError("No more baudrates to try")
            self.logger.info("Trying to connect with baudrate %i" % baudrates[baudrate_count])
            if getattr(self, "_printer", None):
                try:
                    self.logger.debug("Resetting")
                    self.printcore.reset()
                    self.logger.debug("Disconnecting")
                    self.printcore.disconnect()
                    self.logger.debug("Done resetting and disconnecting.")
                except Exception as e:
                    self.logger.debug('Error while resetting and disconnecting : \n' + e.message)
            try:
                self.printcore = printcore(self.profile['COM'], baudrates[baudrate_count])
            except Exception as e:
                self.logger.warning("Error connecting to printer with baudrate %i" % baudrates[baudrate_count])
                try:
                    self.printcore.reset()
                    self.printcore.disconnect()
                except AttributeError:
                    pass
            else:
                time.sleep(0.1)
                self.printcore.recvcb = self.recvcb
                self.printcore.errorcb = self.errorcb
                time.sleep(0.1)
                self.printcore.send_now("M999")
                self.printcore.send_now("M105")
            time.sleep(2)
            baudrate_count += 1
        self.logger.info("Successful connection! Correct baudrate is %i" % baudrates [ baudrate_count - 1 ] )

    def define_regexp(self):
        # ok T:29.0 /29.0 B:29.5 /29.0 @:0
        self.temp_re = re.compile('.*ok T:([\d\.]+) /([\d\.]+) B:(-?[\d\.]+) /(-?[\d\.]+)')
        #self.position_re = re.compile('.*X:([\d\.]+) Y:([\d\.]+) Z:([\d\.]+).*')
        # M190 - T:26.34 E:0 B:33.7
        # M109 - T:26.3 E:0 W:?
        self.wait_tool_temp_re = re.compile('T:([\d\.]+) E:(\d+)')
        self.wait_platform_temp_re = re.compile('.+B:(-?[\d\.]+)')

    def temp_request(self):
        wait_step = 0.1
        steps_in_cycle = int(self.TEMP_REQUEST_WAIT / wait_step)
        counter = steps_in_cycle
        while not self.stop_flag:
            if counter >= steps_in_cycle:
                for extruder_num in range(0, self.profile['extruder_count'] + 1):
                    try:
                        self.printcore.send_now('M105 T' + str(extruder_num))
                    except:
                        pass
                    # self.printcore.send_now('M114')
                    time.sleep(0.01)
                    counter = 0
            time.sleep(wait_step)
            counter += 1

    def tempcb(self, line):
        self.logger.debug(line)
        match = self.temp_re.match(line)
        if match:
            tool_temp = float(match.group(1))
            tool_target_temp = float(match.group(2))
            platform_temp = float(match.group(3))
            platform_target_temp = float(match.group(4))
            self.temps = [platform_temp, tool_temp]
            self.target_temps = [platform_target_temp, tool_target_temp]
        #match = self.position_re.match(line)
        #if match:
        #    self.position = [ match.group(0), match.group(1), match.group(2) ]
        #self.logger.debug(self.debug_position())

    def recvcb(self, line):
        self.logger.debug(line)
        if line[0] == 'T':
            self.firmware_loaded = True
            self.fetch_temps(line)
        elif line[0:2] == 'ok':
            self.firmware_loaded = True

    def sendcb(self, command, gline):
        self.logger.info("command=" + command)
        # if 'M104' in command or 'M109' in command:
        #     tool = 0
        #     tool_match = re.match('.+T(\d+)', command)
        #     if tool_match:
        #         tool = int(tool_match.group(1))
        #     temp_match = re.match('.+S([\d\.]+)', command)
        #     if temp_match:
        #         self.tool_target_temp[tool] = float(temp_match.group(1))
        #
        # elif 'M140' in command or 'M190' in command:
        #     temp_match = re.match('.+S([\d\.]+)', command)
        #     if temp_match:
        #         self.platform_target_temp = float(temp_match.group(1))

    def errorcb(self, error):
        self.logger.warning("Error occurred in printrun: " + str(error))
        self.was_error = True
        self.error_code = 1
        self.error_message = error

    def fetch_temps(self, wait_temp_line):
        match = self.wait_tool_temp_re.match(wait_temp_line)
        if match:
            self.temps[int(match.group(2)) + 1] = float(match.group(1))
        match = self.wait_platform_temp_re.match(wait_temp_line)
        if match:
            self.temps[0] = float(match.group(1))

    def set_total_gcodes(self, length):
        self.total_gcodes = length

    def gcodes(self, gcodes):
        self.logger.info('len(gcodes): ' + str(len(gcodes)))
        if len(gcodes) > 0:
            gcodes = LightGCode(gcodes)
            try:
                if not self.printcore.startprint(gcodes):
                    self.logger.warning('Error starting print')
            except Exception as e:
                self.logger.warning("Can`t start printing. Error: %s" % e.message)

    def pause(self):
        self.logger.debug("Printrun pause")
        if not self.printcore.paused:
            self.printcore.pause()
            gcode = 'G1 Z' + str(self.printcore.pauseZ + self.pause_lift_height) + \
                    ' E' + str(self.printcore.pauseE - self.pause_extrude_length)
            self.printcore.send_now(gcode)
            self.logger.info("Paused successfully")

    def unpause(self):
        self.logger.debug("Printrun unpause")
        if self.printcore.paused:
            gcode = 'G1 Z' + str(self.printcore.pauseZ) + ' E' + str(self.printcore.pauseE)
            self.printcore.send_now(gcode)
            self.printcore.resume()
            self.logger.info("Unpaused successfully")

    def cancel(self):
        self.printcore.reset()
        self.printcore.disconnect()
        self.logger.info("Cancelled successfully")

    def emergency_stop(self):
        self.printcore.reset()

    def is_paused(self):
        return self.printcore.paused

    def is_printing(self):
        return self.printcore.printing

    def is_error(self):
        return self.error_code

    def is_operational(self):
        if self.printcore.printing:
            return self.printcore.read_thread and \
               self.printcore.read_thread.is_alive() and \
               self.printcore.print_thread and \
               self.printcore.print_thread.is_alive()
        if self.printcore.paused or self.printcore.online:
            return self.printcore.read_thread and \
               self.printcore.read_thread.is_alive() and \
               self.printcore.send_thread and \
               self.printcore.send_thread.is_alive()
        return True

    def get_percent(self):
        percent = 0
        if self.total_gcodes:
            percent = int( ( self.printcore.queueindex / self.total_gcodes ) * 100 )
        return percent

    def close(self):
        self.stop_flag = True
        self.logger.debug('Printrun sender is closing')
        self.printcore.disconnect()
        self.logger.debug('(Joining printrun threads...')
        self.temp_request_thread.join(10)
        if self.temp_request_thread.isAlive():
            self.logger.error("Error stopping temperature request thread.")
        else:
            self.logger.debug('...done)')

    # #def debug_position(self):
    #    text  = "X:" + str(self.position[0])
    #    text += " Y:" + str(self.position[1])
    #    text += " Z:" + str(self.position[2])
    #    return text
