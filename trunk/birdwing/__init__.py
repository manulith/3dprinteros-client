import os
import sys
import time
import json
import logging
import tempfile
import threading
import subprocess
import conveyor_path

def process_network_responses(addr, response_data):
    serial = response_data['iserial']
    processed_data = response_data.copy()
    processed_data['machine_name'] = serial[0:4] + ':' + serial[4:8] + ':' + serial
    print "BIRDWING_NETWORK_DATA_PROCESSING: " + str(processed_data)
    return processed_data

class Printer:

    UPDATE_TIME = 15
    UNKNOWN_STATE = 'UNKNOWN'

    def __init__(self, profile):
        self.init_conveyor_server()
        self.logger = logging.getLogger('main')
        self.logger.propagate = True
        self._profile = profile
        if profile.get('SNR'):
            self.logger.info('Machine name from usb_detect')
            self.machine_name = profile['VID'] + ":" + profile['PID'] + ":" + profile['SNR']
        elif profile.get('machine_name', None):
            self.machine_name = profile.get('machine_name')
        else:
            self.logger.info('Machine name from conveyor')
            self.machine_name = self.get_active_machine_name()
        if self.machine_name:
            self.logger.info('Printer: ' + self.machine_name)
            self.job = None
            self.job_id = None
            self.printer_info = None
            self._error_code = ""
            self._error_message = ""
            self.tmp_file = None
            self.print_process = None
            #self.print_lock = threading.Lock()
            self.state_updating = threading.Thread(target=self.state_updating, name='Birdwing printer info polling thread')
            self.state_updating.start()
        else:
            self._error_code = "general"
            message = "No printer detected"
            self._error_message = message
            self.conveyor_service.close()
            raise RuntimeError(message)

    def init_conveyor_server(self):
        self.conveyor_service = conveyor_path.ConveyorService()
        from conveyor.machine import MachineState
        self.MachineState = MachineState

    def get_error_code(self):
        return self._error_code

    def get_error_message(self):
        return self._error_message

    def spawn_conveyor_client_subproc(self, args_list):
        call = [sys.executable, conveyor_path.conveyor_loader.get_conveyor_client()]
        call.extend(args_list)
        self.logger.info("Run: " + str(call))
        environment = conveyor_path.conveyor_loader.get_conveyor_env()
        #we have to ignore stderr, to get performance boots and stability
        return subprocess.Popen(call, stdout = subprocess.PIPE, env = environment)

    def communicate_and_cut_conveyor_errors(self, process):
        stdout = process.communicate()[0]
        if stdout:
            last_bracket_index = 0
            last_brace_index = 0
            if "]" in stdout:
                last_bracket_index = stdout.rindex("]")
            if "}" in stdout:
                last_brace_index = stdout.rindex("}")
            index_of_end_of_json = max(last_bracket_index, last_brace_index)
            clean_stdout = stdout[:index_of_end_of_json + 1]
            data = json.loads(clean_stdout)
            #self.logger.debug("Parsed data: " + str(data))
            return data
        else:
            message = "Conveyor client process return empty string"
            self._error_code = "general"
            self._error_message = message
            raise RuntimeError(message)

    def get_active_machine_name(self):
        process = self.spawn_conveyor_client_subproc(['printers', "-j"])
        result = self.communicate_and_cut_conveyor_errors(process)
        print result
        for machine in result:
            if machine['state'] != self.MachineState.DISCONNECTED:
                serial = machine['name']['iserial']
                #TODO get real VID:PID, not the first letters of serial number
                return serial[0:4] + ':' + serial[4:8] + ':' + serial

    def update_state(self):
        args = ['printers', "-j"]
        process = self.spawn_conveyor_client_subproc(args)
        printer_info_list = self.communicate_and_cut_conveyor_errors(process)
        if printer_info_list:
            self.printer_info = printer_info_list[0]
            self.logger.info("State: " + printer_info_list[0]['state'])
            return True
        else:
            self.logger.debug("Error while running command 'printers' - no result")

    def state_updating(self):
        self.state_updating_flag = True
        while self.state_updating_flag:
            start_time = time.time()
            result = self.update_state()
            if self.print_process:
                self.update_print_job()
            while (time.time() - start_time) < self.UPDATE_TIME and result:
                time.sleep(0.2)
        # this is end sequence - real close of the module
        self.printer_info = None
        if self.machine_name:
            if self.print_process:
                self.cancel()
            time.sleep(0.3)
            self.logger.info('Disconnecting printer ' + self.machine_name)
            call = ['disconnect', '-m', self.machine_name]
            self.spawn_conveyor_client_subproc(call)
            self.logger.info('..done')
            conveyor_path.conveyor_svc.close()

    def get_print_job(self, jobs):
        #self.logger.debug("Jobs type are " + str(type(jobs)))
        #self.logger.debug("Jobs/Job: "  + str(type(jobs)))
        print_jobs = filter(lambda job:job['type'] == 'PrintFromFileJob' and job['conclusion'] == None, jobs)
        if len(print_jobs) == 1:
            self.logger.info("Print job:" + str(print_jobs[0]))
            return print_jobs[0]
        elif len(print_jobs) > 1:
            self._error_code = 'general'
            self._error_message = "More than one running print jobs at same time."
            self.logger.critical('Error. More than one running print jobs at same time.')
            self.logger.critical('Jobs:' + str(print_jobs))
            raise RuntimeError("More than one running print job!")

    def get_all_jobs(self):
        command = ['jobs', "-j"]
        process = self.spawn_conveyor_client_subproc(command)
        return self.communicate_and_cut_conveyor_errors(process)

    def get_job(self, id = None):
        command = ['job', str(id), "-j"]
        process = self.spawn_conveyor_client_subproc(command)
        return self.communicate_and_cut_conveyor_errors(process)

    def parse_progress_to_general_percent(self, job):
        #self.logger.debug("Jobs has progress")
        progress_name = job['progress']['name']
        progress = job['progress']['progress']
        if progress_name == 'printing':
            print_progress = min(progress, 95)
        elif progress_name == 'end_sequence':
            print_progress = max(progress, 95)
        else:
            print_progress = 0
        if progress_name:
            self.logger.info("Job in " + progress_name + ":" + str(progress))
            self.logger.info("General progress" + ":" + str(print_progress))
        return print_progress

    def update_print_job(self):
        if self.job_id:
            current_job = self.get_job(self.job_id)
        else:
            current_job = self.get_print_job(self.get_all_jobs())
        #TODO process change in job state(external factors)
        #self.logger.debug("Current job:" + str(current_job))
        if self.print_process:
            if self.print_process.poll() is not None:
                self.logger.critical("Print process exited with error code")
                self.end_print()
        if current_job:
            self.job = current_job
            self.job_id = str(current_job['id']) # job_id need to be str, don't remove!
        else:
            self.logger.critical("No running print job!")
    def enqueue(self, makerbot_file):
        self.binary_file(makerbot_file)

    def binary_file(self, makerbot_file):
        #self.logger.debug("Acquiring print lock")
        #self.print_lock.acquire()
        self.job_id = None # essential. don't remove
        tmp_file = tempfile.NamedTemporaryFile(delete=False, prefix='conveyor-secured3d-', suffix='.makerbot')
        tmp_file.write(makerbot_file)
        tmp_file.close()
        self.tmp_file = tmp_file
        arguments = ["printfromfile", tmp_file.name, '-m', self.machine_name]
        self.print_process = self.spawn_conveyor_client_subproc(arguments)
        self.logger.info("Staring print of: " + tmp_file.name)

    def end_print(self):
        self.logger.info("Performing End Print")
        os.remove(self.tmp_file.name)
        self.tmp_file = None
        self.job_id = None
        self.print_process = None
        #self.print_lock.release()

    def get_state(self):
        if self.printer_info:
            return self.printer_info['state']
        else:
            return self.UNKNOWN_STATE

    def pause(self):
        if self.job_id:
            self.logger.info("Pause job " + str(self.job_id))
            call = ['jobpause', str(self.job_id)]
            self.spawn_conveyor_client_subproc(call)

    def end(self):
        pass

    def resume(self):
        if self.job_id:
            self.logger.info("Resume job " + str(self.job_id))
            call = ['jobresume', str(self.job_id)]
            self.spawn_conveyor_client_subproc(call)

    def cancel(self):
        if self.job_id:
            self.logger.info("Cancel job " + str(self.job_id))
            call = ['cancel', str(self.job_id)]
            self.spawn_conveyor_client_subproc(call)
            self.end_print()

    def get_temp(self):
        temp = 0
        if self.printer_info:
            temp = int(self.printer_info['machine_info']['toolhead_0_heating_status']['current_temperature'])
        return temp

    def get_ttemp(self):
        temp = 0
        if self.printer_info:
            temp = int(self.printer_info['machine_info']['toolhead_0_heating_status']['target_temperature'])
        return temp

    def get_head_temp(self, i):
        if i == 0:
            return self.get_temp()
        else:
            return 0

    def get_head_ttemp(self, i):
        if i == 0:
            return self.get_ttemp()
        else:
            return 0

    def get_platform_temp(self):
        platform_temp = 0
        if self.printer_info:
            if self.printer_info["has_heated_platform"]:
                platform_temp = int(self.printer_info['platform_temperature'])
        return platform_temp

    #TODO get real platform target temp(we need 5th gen printer with heated platform for this)
    def get_platform_ttemp(self):
        return self.get_platform_temp()

    def send(self, gcode):
        pass

    def get_percent(self):
        if self.job:
            percent = int(self.parse_progress_to_general_percent(self.job))
        else:
            percent = 0
        return percent

    def close(self):
        self.state_updating = False

    def is_paused(self):
        return self.get_state() == self.MachineState.PAUSED

    def is_printing(self):
        return self.get_state() in [self.MachineState.RUNNING, self.MachineState.PAUSED]

    def is_operational(self):
        result = self.is_printing() or \
            self.get_state() in \
            (self.MachineState.IDLE,
             self.MachineState.PAUSED,
             self.MachineState.PENDING,
             self.MachineState.RUNNING)
        return result

    def begin(self, length):
        self._error_code = ''
        self._error_message = ''

    def report(self):
        platform_temp = self.get_platform_temp()
        platform_target_temp = self.get_platform_ttemp()
        tool_temp = [ self.get_head_temp(0), self.get_head_temp(1) ]
        tool_target_temp = [ self.get_head_ttemp(0), self.get_head_ttemp(1) ]
        if not self.is_operational():
            status = 'no_printer'
        elif not self.is_printing():
            status = 'ready'
        else:
            tool_ready = [
                abs(tool_target_temp[0] - tool_temp[0]) < 10,
                abs(tool_target_temp[1] - tool_temp[1]) < 10
            ]
            platform_ready = platform_target_temp < 5 or abs(platform_target_temp - platform_temp) < 10
            if platform_ready and (tool_ready[0] or tool_ready[1]):
                status = 'printing'
            else:
                status = 'heating'
        if self._error_code:
            error = { "code" : self._error_code, "message" : self._error_message }
        else:
            error = {}
        result = {
            'status': status,
            'platform_temperature': platform_temp,
            'platform_target_temperature': platform_target_temp,
            'toolhead1_temperature': tool_temp[0],
            'toolhead1_target_temperature': tool_target_temp[0],
            'toolhead2_temperature': tool_temp[1],
            'toolhead2_target_temperature': tool_target_temp[1],
            'percent': self.get_percent(),
            'buffer_free_space': 10000,
            'last_error': error
        }
        return result

if __name__ == '__main__':
     Printer({"SNR": None})