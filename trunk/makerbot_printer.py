import threading
import time
import collections
import makerbot_driver
import re
import serial
import serial.serialutil
import logging
import traceback

class Printer():

    STATE_NONE = 0
    STATE_READY = 1
    STATE_PRINTING = 2
    STATE_PRINTING_LOCALLY = 3
    STATE_PAUSED = 4
    STATE_CLOSED = 5
    STATE_RETRYABLE_ERROR = 6
    STATE_FATAL_ERROR = 7
    STATE_CANCELLED = 8

    MAX_RETRIES = 1 # should be 1 for now. don't touch before implementing good error reporting to app main loop.
    MAX_QUIET_RESTARTS = 4

    def __init__(self, profile):
        self._profile = profile
        self._logger = logging.getLogger('app.' + __name__)
        self._buffer = collections.deque()
        self._state = self.STATE_READY
        self._actual_state = self.STATE_NONE
        self._state_before_error = self.STATE_READY
        self._error_code = ''
        self._error_message = ''
        self._platform_temp = 0
        self._platform_ttemp = 0
        self._head_temp = [0, 0]
        self._head_ttemp = [0, 0]
        #self._position = ([0,0,0], None)
        self._mb = {'preheat': False, 'heat_shutdown': False}
        self._eof = False
        self._lock = threading.Lock()
        self._printing_thread = threading.Thread(target=self._printing, name='PR')
        self._printing_thread.start()
        self._logger.info('Makerbot printer created')
        self._parser = None
        try:
            self._parser = self._create_parser()
            self._parser.state.values["build_name"] = '3DPrinterOS'
        except serial.serialutil.SerialException as e:
            self._state = self.STATE_FATAL_ERROR
            self._error_code = 'serial'
            self._error_message = str(e)
        except Exception as e:
            self._logger.debug(e)
            self._state = self.STATE_FATAL_ERROR
            self._error_code = 'general'
            self._error_message = str(e)

    def _create_parser(self):
        factory = makerbot_driver.MachineFactory()
        obj = factory.build_from_port(self._profile['COM'] )
        assembler = makerbot_driver.GcodeAssembler(getattr(obj, 'profile'))
        parser = getattr(obj, 'gcodeparser')
        start, end, variables = assembler.assemble_recipe()
        parser.environment.update(variables)
        return parser

    def get_error_code(self):
        return self._error_code

    def get_error_message(self):
        return self._error_message

    def get_printing_job_state(self):
        state = {}
        state['parser_state'] = self._parser.state
        state['eof']          = self._eof
        state['buffer']       = self._buffer
        state['state']        = self._state_before_error
        self._logger.info('State before error ' + str(state['state']))
        return state

    def set_printing_job_state(self, state):
        self._parser.state = state['parser_state']
        self._eof          = state['eof']
        self._buffer       = state['buffer']
        self._state        = state['state']
        self._logger.info('Restoring state ' + str(state['state']))

    def begin(self, length):
        self.set_total_gcodes(length)

    # length argument is used for unification with Printrun. DON'T REMOVE IT!
    def set_total_gcodes(self, length):
        with self._lock:
            self._state = self.STATE_PRINTING
            self._eof   = False
            self._buffer.clear()
            self._parser.state.values["build_name"] = '3DPrinterOS'
            self._parser.state.percentage = 0
            self._logger.info('Begin of GCodes')
            self._execute(lambda: self._parser.s3g.set_RGB_LED(255, 255, 255, 0))

    def end(self):
        with self._lock:
            self._eof = True
            self._logger.info('End of GCodes')

    def enqueue(self, gcodes):
        self.gcodes(gcodes)

    def gcodes(self, gcodes):
        with self._lock:
            if self._state != self.STATE_PRINTING:
                self._state = self.STATE_FATAL_ERROR
                self._error_code = 'protocol'
                self._error_message = 'Begin was not sent'
                return
            self._buffer += gcodes
            self._logger.info('Enqueued block: ' + str(len(gcodes)) + ', total: ' + str(len(self._buffer)))

    def pause(self):
        with self._lock:
            if self._state != self.STATE_PRINTING:
                return
            self._state = self.STATE_PAUSED
            self._wait_for_actual_status(self.STATE_PAUSED)

    def resume(self):
        self.unpause()

    def unpause(self):
        with self._lock:
            if self._state == self.STATE_PAUSED:
                self._state = self.STATE_PRINTING

    def cancel(self):
        with self._lock:
            self._state = self.STATE_CANCELLED

    def emergency_stop(self):
        self.cancel()

    def reset(self):
        with self._lock:
            self._buffer.clear()
            self._state = self.STATE_READY

    def send(self, gcode):
        with self._lock:
            self._execute(gcode)
            self._logger.info('Executed GCode: ' + gcode)

    def get_buffer_free_space(self):
        return max(250*15 - len(self._buffer), 0)

    def get_state(self):
        return self._state

    def get_platform_temp(self):
        return self._platform_temp

    def get_platform_ttemp(self):
        return self._platform_ttemp

    def get_head_temp(self, i):
        return self._head_temp[i]

    def get_head_ttemp(self, i):
        return self._head_ttemp[i]

    def get_percent(self):
        return self._parser.state.percentage

    def close(self):
        self._logger.info('Closing Makerbot Printer')
        self._state = self.STATE_CLOSED

    def _close(self):
        if self._parser is not None:
            if self._parser.s3g is not None:
                self._parser.s3g.close()

    def _wait_for_actual_status(self, status):
        while self._actual_state != status:
            if not self._printing_thread.is_alive():
                return
            time.sleep(0.1)

    def _execute(self, command):
        while True:
            self._logger.debug("Executing command: {" + str(command) + "}")
            try:
                if isinstance(command, str):
                    self._parser.execute_line(command)
                    self._restarts_count = 0
                    return
                else:
                    result = command()
                    self._restarts_count = 0
                    return result

            except makerbot_driver.BufferOverflowError:
                self._logger.info('BufferOverflowError')
                time.sleep(0.1)

            except makerbot_driver.ExternalStopError:
                self._logger.info('External Stop received')
                self.close()

            except serial.serialutil.SerialException as e:
                self._logger.info('SerialException')
                self._state_before_error = self._state
                self._state = self.STATE_RETRYABLE_ERROR
                self._close()
                self._error_code = 'serial'
                self._error_message = str(e)
                raise e

            except makerbot_driver.ProtocolError as e:
                self._logger.info('ProtocolError: ' + str(traceback.format_exc()))
                self._state_before_error = self._state
                self._state = self.STATE_RETRYABLE_ERROR
                self._close()
                self._error_code = 'general'
                self._error_message = str(e)
                raise e

            except makerbot_driver.Gcode.GcodeError as e:
                self._logger.info('makerbot_driver.Gcode.GcodeError')
                self._state_before_error = self._state
                self._state = self.STATE_FATAL_ERROR
                self._close()
                self._error_code = 'gcode'
                self._error_message = str(e)
                raise e

            except Exception as e:
                self._logger.info('Unexpected error: ' + str(traceback.format_exc()))
                self._state_before_error = self._state
                self._state = self.STATE_FATAL_ERROR
                self._close()
                self._error_code = 'general'
                self._error_message = str(e)
                raise e

            #except makerbot_driver.TransmissionError as e:
            #except makerbot_driver.BuildCancelledError as e:
            #except makerbot_driver.ActiveBuildError as e:
            #except makerbot_driver.Gcode.UnspecifiedAxisLocationError as e:
            #except makerbot_driver.Gcode.UnrecognizedCommandError as e:

    def _lift_extruder(self):
        position = self._parser.state.position.ToList()
        if position[2] is None or position[3] is None or position[4] is None:
            self._logger.warning('It seems that Pause command was called in wrong command sequence(positions are None)')
        else:
            self._buffer.appendleft('G1 Z' + str(position[2]) + ' A' + str(position[3]) + ' B' + str(position[4]))
            z = min(160, position[2] + 30)
            a = max(0, position[3] - 5)
            b = max(0, position[4] - 5)
            self._execute('G1  Z' + str(z) + ' A' + str(a) + ' B' + str(b))

    def _is_physically_printing(self):
        if self._mb['preheat'] or self._mb['heat_shutdown'] or (self._platform_ttemp < 5 and self._head_ttemp[0] < 5 and self._head_ttemp[1] < 5):
            return False
        else:
            return True

    def _read_state(self):
        if self._parser:
            self._platform_temp          = self._execute(lambda: self._parser.s3g.get_platform_temperature(1))
            self._platform_ttemp         = self._execute(lambda: self._parser.s3g.get_platform_target_temperature(1))
            self._head_temp[0]  = self._execute(lambda: self._parser.s3g.get_toolhead_temperature(0))
            self._head_ttemp[0] = self._execute(lambda: self._parser.s3g.get_toolhead_target_temperature(0))
            self._head_temp[1]  = self._execute(lambda: self._parser.s3g.get_toolhead_temperature(1))
            self._head_ttemp[1] = self._execute(lambda: self._parser.s3g.get_toolhead_target_temperature(1))
            self._mb            = self._execute(lambda: self._parser.s3g.get_motherboard_status())
            #self._position      = self._execute(lambda: self._parser.s3g.get_extended_position())

    # and position
    def _read_temps(self):
        if self._parser:
            self._platform_temp         = self._execute(lambda: self._parser.s3g.get_platform_temperature(1))
            self._head_temp[0] = self._execute(lambda: self._parser.s3g.get_toolhead_temperature(0))
            self._head_temp[1] = self._execute(lambda: self._parser.s3g.get_toolhead_temperature(1))
            #self._position      = self._execute(lambda: self._parser.s3g.get_extended_position())

    def is_printing(self):
        printing = [
            self.STATE_PRINTING,
            self.STATE_PRINTING_LOCALLY,
            self.STATE_PAUSED
        ]
        return self.get_state() in printing

    def is_error(self):
        return self.get_state() in [self.STATE_FATAL_ERROR, self.STATE_RETRYABLE_ERROR]

    def is_operational(self):
        return (self.is_printing() or self.get_state() in [self.STATE_READY, self.STATE_CANCELLED])

    def is_paused(self):
        return self.get_state() == self.STATE_PAUSED

    def _printing(self):
        ttemp_regexp      = re.compile('\s*M109\s*S(\d+)\s*T(\d+)')
        head_ttemp_regexp = re.compile('\s*M104\s*S(\d+)\s*T(\d+)')
        is_heating        = False
        while True:
            if self._state == self.STATE_READY:
                if self._actual_state != self._state:
                    self._actual_state = self._state
                    self._logger.info('State is STATE_READY')
                self._read_state()
                # keep warm enabled printer goes to PRINTING_LOCALLY
                # if self._is_physically_printing():
                #     if not self.get_percent() == 100:
                #         self._state = self.STATE_PRINTING_LOCALLY
                time.sleep(1)
            elif self._state == self.STATE_PRINTING_LOCALLY:
                if self._actual_state != self._state:
                    self._actual_state = self._state
                    self._logger.info('State is STATE_PRINTING_LOCALLY')
                self._read_state()
                if not self._is_physically_printing():
                    self._state = self.STATE_READY
                time.sleep(1)
            elif self._state == self.STATE_PAUSED:
                if self._actual_state != self._state:
                    self._actual_state = self._state
                    self._lift_extruder()
                    self._logger.info('State is STATE_PAUSED')
                self._read_state()
                time.sleep(1)
            elif self._state == self.STATE_PRINTING:
                if self._actual_state != self._state:
                    self._actual_state = self._state
                    self._logger.info('State is STATE_PRINTING')
                if is_heating:
                    self._read_temps()
                    ready    = (self._platform_temp > self._platform_ttemp) or (self._platform_ttemp - self._platform_temp) < 5
                    h1_ready = (self._head_temp[0] > self._head_ttemp[0]) or (self._head_ttemp[0] - self._head_temp[0]) < 5
                    h2_ready = (self._head_temp[1] > self._head_ttemp[1]) or (self._head_ttemp[1] - self._head_temp[1]) < 5
                    if (self._platform_ttemp == 0 or ready) and (self._head_ttemp[0] == 0 or h1_ready) and (self._head_ttemp[1] == 0 or h2_ready):
                        is_heating = False
                        self._logger.info('Heating is done')
                    time.sleep(1)
                    continue
                try:
                    command = self._buffer[0]
                    self._execute(command)
                    self._buffer.popleft()
                    self._logger.info('Executed GCode: ' + command)
                    #logging.info('Buffer length: ' + str(len(self._buffer)))
                    result = head_ttemp_regexp.match(command)
                    if result is not None:
                        self._head_ttemp[int(result.group(2))] = int(result.group(1))
                        is_heating = True
                        self._logger.info('Heating toolhead ' + str(result.group(2)) + ' to ' + str(result.group(1)))
                    result = ttemp_regexp.match(command)
                    if result is not None:
                        self._platform_ttemp = int(result.group(1))
                        is_heating = True
                        self._logger.info('Heating platform to ' + str(result.group(1)))
                    #TODO check this is real print(can cause misprints)
                    #self._position = self._execute(lambda: self._parser.s3g.get_extended_position())
                except IndexError:
                    if self._eof:
                        self._logger.info('All GCodes are sent to printer')
                        self._state = self.STATE_READY
                    time.sleep(0.1)
            elif self._state == self.STATE_CLOSED:
                if self._actual_state != self._state:
                    self._actual_state = self._state
                    self._logger.info('State is STATE_CLOSED')
                self._close()
                return
            elif self._state == self.STATE_FATAL_ERROR:
                if self._actual_state != self._state:
                    self._actual_state = self._state
                    self._logger.info('State is STATE_FATAL_ERROR')
                return
            elif self._state == self.STATE_RETRYABLE_ERROR:
                if self._actual_state != self._state:
                    self._actual_state = self._state
                    self._logger.info('State is STATE_RETRYABLE_ERROR')
                return
            elif self._state == self.STATE_CANCELLED:
                if self._actual_state != self._state:
                    self._actual_state = self._state
                    self._buffer.clear()
                    self._execute(lambda: self._parser.s3g.abort_immediately())
                    self._logger.info('State is STATE_CANCELLED')
                self._read_state()
                time.sleep(1)

    def get_temps(self):
        platform_temp = self.get_platform_temp()
        first_tool_temp = self.get_head_temp(0)
        temps = [platform_temp, first_tool_temp]
        second_tool_temp = self.get_head_temp(1)
        if second_tool_temp:
            temps.append(second_tool_temp)
        return temps

    def get_target_temps(self):
        platform_temp = self.get_platform_ttemp()
        first_tool_temp = self.get_head_ttemp(0)
        target_temps = [platform_temp, first_tool_temp]
        second_tool_temp = self.get_head_ttemp(1)
        if second_tool_temp:
            target_temps.append(second_tool_temp)
        return target_temps