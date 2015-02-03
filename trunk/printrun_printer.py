from printrun.printcore import printcore
from printrun.gcoder import LightGCode
import re
import threading
import time
import logging

import base_sender

    # def debug_info(self):
    #     info = 'len(_gcodes): ' + str(len(self.gcodes)) + '\n'
    #     info += '_length: ' + str(self.length) + '\n'
    #     info += 'len(_append_buffer): ' + str(len(self.append_buffer)) + '\n'
    #     info += '_printing: ' + str(self.printing) + '\n'
    #     info += '_printer.online: ' + str(self.printer.online) + '\n'
    #     info += '_printer.printing: ' + str(self.printer.printing) + '\n'
    #     info += '_printer.paused: ' + str(self.printer.paused) + '\n'
    #     info += '_printer.queueindex: ' + str(self.printer.queueindex) + '\n'
    #     info += '_printer.read_thread.is_alive(): ' + \
    #             str(self.printer.read_thread and self.printer.read_thread.is_alive()) + '\n'
    #     info += '_printer.print_thread.is_alive(): ' + \
    #             str(self.printer.print_thread and self.printer.print_thread.is_alive()) + '\n'
    #     info += '_printer.send_thread.is_alive(): ' + \
    #             str(self.printer.send_thread and self.printer.send_thread.is_alive()) + '\n'
    #     return info
    #
    # def debug_temp(self):
    #     temp = '_tool_temp: ' + str(self.tool_temp) + '\n'
    #     temp += '_tool_target_temp: ' + str(self.tool_target_temp) + '\n'
    #     temp += '_platform_temp: ' + str(self.platform_temp) + '\n'
    #     temp += '_platform_target_temp: ' + str(self.platform_target_temp)
    #     return temp
    #
    # #def debug_position(self):
    #    text  = "X:" + str(self.position[0])
    #    text += " Y:" + str(self.position[1])
    #    text += " Z:" + str(self.position[2])
    #    return text

class Printer(base_sender.BaseSender):

    pause_lift_height = 5
    pause_extrude_length = 7

    def _init__(self, profile):
        base_sender.BaseSender.__init__(self, profile)
        self.logger = logging.getLogger('app.' + __name__)
        self.extruder_count = self.profile['extruder_count']
        self.select_baudrate_and_connect()
        self.init_callbacks()
        self.define_regexp()
        self.gcodes = LightGCode([])
        self.temp_request_thread = threading.Thread(target=self.temp_request)
        for gcode in self.profile['end_gcodes']:
            self.printer.send_now(gcode)

    def init_callbacks(self):
        self.printer.tempcb = self.tempcb
        self.printer.recvcb = self.recvcb
        self.printer.sendcb = self.sendcb
        self.printer.errorcb = self.errorcb

    def recvcb_for_connection_check(self, line):
        self.logger.debug("While selecting baudrate received: %s", str(line))
        if "ok " in line or 'echo' in line:
            self.connected_flag = True

    def select_baudrate_and_connect(self):
        self.connected_flag = False
        baudrate_count = 0
        baudrates = self.profile['baudrate']
        self.logger.info('Baudrates list for %s : %s' % (self.profile['name'], str(baudrates)))
        while not self.connected_flag:
            if baudrate_count >= len(baudrates):
                raise RuntimeError("No more baudrates to try")
            self.logger.info("Trying to connect with baudrate %i" % baudrates[baudrate_count])
            if getattr(self, "_printer", None):
                try:
                    self.logger.debug("Resetting")
                    self.printer.reset()
                    self.logger.debug("Disconnecting")
                    self.printer.disconnect()
                    self.logger.debug("Done resetting and disconnecting.")
                except Exception as e:
                    self.logger.debug('Error while resetting and disconnecting : \n' + e.message)
            try:
                self.printer = printcore(self.profile['COM'], baudrates[baudrate_count])
            except Exception as e:
                self.logger.warning("Error connecting to printer with baudrate %i" % baudrates[baudrate_count])
                try:
                    self.printer.reset()
                    self.printer.disconnect()
                except AttributeError:
                    pass
            else:
                time.sleep(0.1)
                self.printer.recvcb = self.recvcb_for_connection_check
                #self.printer.errorcb = self.logger.warning
                self.printer.send("M105")
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

    def gcodes(self, gcodes):
        length = len(gcodes)
        if not self.printer.printing and not self.printer.paused:
            if not self.printer.startprint(self.gcodes, length):
                self.logger.warning('Error starting print, startindex: ' + str(length))
            else:
                self.logger.info('Printing started, startindex: ' + str(length))
        time.sleep(1)

    def temp_request(self):
        while not self.stop_flag:
            if self.temp_timeout < time.time():
                self.temp_request_extruder = (self.temp_request_extruder + 1) % self.extruder_count
                self.printer.send_now('M105 T'+str(self.temp_request_extruder))
                #self.printer.send_now('M114')
                self.temp_timeout = time.time() + 5
            time.sleep(1)

    #also updates position now
    def tempcb(self, line):
        match = self.temp_re.match(line)
        if match:
            self.tool_temp[self.temp_request_extruder] = float(match.group(1))
            self.tool_target_temp[self.temp_request_extruder] = float(match.group(2))
            self.platform_temp = float(match.group(3))
            self.platform_target_temp = float(match.group(4))
        #match = self.position_re.match(line)
        #if match:
        #    self.position = [ match.group(0), match.group(1), match.group(2) ]
        #self.logger.debug(self.debug_position())

    def recvcb(self, line):
        self.logger.debug(line)
        if line[0] == 'T':
            self.wait_heading = True
            self.fetch_temps(line)
            self.logger.debug(self.debug_temp())
        elif line[0:2] == 'ok':
            self.wait_heading = False

    def sendcb(self, command, gline):
        self.logger.info("command=" + command)
        if 'M104' in command or 'M109' in command:
            tool = 0
            tool_match = re.match('.+T(\d+)', command)
            if tool_match:
                tool = int(tool_match.group(1))
            temp_match = re.match('.+S([\d\.]+)', command)
            if temp_match:
                self.tool_target_temp[tool] = float(temp_match.group(1))
            self.logger.debug(self.debug_temp())

        elif 'M140' in command or 'M190' in command:
            temp_match = re.match('.+S([\d\.]+)', command)
            if temp_match:
                self.platform_target_temp = float(temp_match.group(1))
            self.logger.debug(self.debug_temp())
        self.logger.debug(command)

    def errorcb(self, error):
        self.was_error = True
        self.error_code = 'general'
        self.error_message = error
        self.logger.debug(error)

    def fetch_temps(self, wait_temp_line):
        self.logger.info("_fetch_temp" + str(wait_temp_line))
        match = self.wait_tool_temp_re.match(wait_temp_line)
        if match:
            self.tool_temp[int(match.group(2))] = float(match.group(1))
        match = self.wait_platform_temp_re.match(wait_temp_line)
        if match:
            self.platform_temp = float(match.group(1))

    def set_total_gcodes(self, length):
        self.total_gcodes = length

    def gcodes(self, gcodes):
        self.logger.info('len(gcodes): ' + str(len(gcodes)) + ', ' + self.debug_info())
        if len(self.gcodes) > 0:
            self.append_buffer += gcodes
            return

        if len(gcodes) > 0:
            self.gcodes = LightGCode(gcodes[0:2000])
            try:
                if self.printer.startprint(self.gcodes):
                    time.sleep(2)
                    self.append_buffer += gcodes[2000:]
                else:
                    self.logger.critical('Error starting print')
            except Exception as e:
                self.logger.warning("Can`t start printing. Error: %s" % e.message)

    def pause(self):
        self.logger.debug("Printrun pause")
        if not self.printer.paused:
            self.printer.pause()
            gcode = 'G1 Z' + str(self.printer.pauseZ + self.pause_lift_height) + \
                    ' E' + str(self.printer.pauseE - self.pause_extrude_length)
            self.printer.send_now(gcode)
            self.logger.info("Paused successfully")

    def unpause(self):
        self.logger.debug("Printrun unpause")
        if self.printer.paused:
            gcode = 'G1 Z' + str(self.printer.pauseZ) + ' E' + str(self.printer.pauseE)
            self.printer.send_now(gcode)
            self.printer.resume()
            self.logger.info("Unpaused successfully")

    def cancel(self):
        self.printer.reset()
        self.printer.disconnect()
        self.logger.info("Cancelled successfully")

    def emergency_stop(self):
        self.printer.reset()

    def is_paused(self):
        return self.printer.paused

    def is_error(self):
        return not (self.printer.online and self.printer.read_thread.is_alive() and \
               (self.printer.send_thread.is_alive() or self.printer.print_thread.is_alive()))

    def close(self):
        self.logger.debug('Printrun closing')
        self.printer.disconnect()
        self.logger.debug('(Joining printrun_printer threads...')
        self.temp_request_thread.join(10)
        if self.temp_request_thread.isAlive():
            self.logger.error("Error stopping temperature request thread.")
        else:
            self.logger.debug('...done)')