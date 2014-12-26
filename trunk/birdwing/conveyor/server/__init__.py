# conveyor/src/main/python/conveyor/server/__init__.py
#
# conveyor - Printing dispatch engine for 3D objects and their friends.
# Copyright 2012 MakerBot Industries, LLC
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU Affero General Public License for more
# details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

from __future__ import (absolute_import, print_function, unicode_literals)

import collections
import ctypes
import inspect
import logging
import os.path
import socket
import subprocess
import platform
import serial
import threading
import traceback
import time
import urllib
import urllib2
import usb.core
import usb.backend.libusb1

import conveyor.address
import conveyor.networked_machine_detector
import conveyor.connection
import conveyor.job
import conveyor.jsonrpc
import conveyor.log
import conveyor.machine.digitizer
import conveyor.machine.port
import conveyor.recipe
import conveyor.slicer
import conveyor.slicer.miraclegrue
import conveyor.stoppable
import conveyor.util
from conveyor.server.disconnected_machines import DisconnectedMachines

from conveyor.decorator import jsonrpc

class Server(conveyor.stoppable.StoppableInterface):
    def __init__(
            self, config, driver_manager, listener, embedded_address):
        conveyor.stoppable.StoppableInterface.__init__(self)
        self._config = config
        self._driver_manager = driver_manager
        self._listener = listener
        self._stop = False
        self._log = conveyor.log.getlogger(self)
        self._clients = set()
        self._clients_condition = threading.Condition()
        self._queue = collections.deque()
        self._queue_condition = threading.Condition()
        self._jobs = {}
        self._jobs_condition = threading.Condition()
        self._networked_machine_detector = conveyor.networked_machine_detector.NetworkedMachineDetector.get_instance()
        self._networked_machine_detector.port_attached.attach(self._port_attached)
        self._networked_machine_detector.port_detached.attach(self._port_detached)
        self._ports = {}
        self.disconnected_machines = DisconnectedMachines()

        # If a Digitizer is detected but not its camera, it goes in this dict
        self._unpaired_digitizer_ports = {}

        self._digitlib = self._config.get("digitizer", "digitizer_library")
        self._mesher = conveyor.machine.digitizer.Mesher(self._config)
        self._point_cloud_container = conveyor.machine.digitizer.PointCloudContainer(self._config)

        # If we have specified a path to libusb, load it now.  Otherwise the system default
        # paths will be searched on the first call of usb.core.find()
        libusb_path = self._config.get("server", "libusb")
        if libusb_path:
            usb.backend.libusb1.get_backend(find_library = lambda x: libusb_path)

    def stop(self):
        self._stop = True
        with self._queue_condition:
            self._queue_condition.notify_all()
        try:
            self._mesher.destroy_all_meshes()
        except Exception as e:
            self._log.info("Error destroying all meshes in mesher object",
                exc_info=True)

    def run(self):
        self._networked_machine_detector.start()
        python_developer = self._config.get("server", "python_developer")
        while not self._stop:
            if python_developer:
                # """ This is a really bad hack to get this working on OSX.
                # WE SHOULD NOT USE THIS IN THE FINAL RELEASE VERSION
                # UNLESS THERE IS ABSOLUTELY NO OTHER CHOICE.  Heres a link
                # to an explanation of our problem:
                # http://stackoverflow.com/questions/5703754/addinput-method-of-qtcapturesession-not-returning
                # """
                 self._digitlib.digitizer_run_mainloop(
                     ctypes.c_double(.001))
            try:
                connection = self._listener.accept()
                if None is not connection:
                    jsonrpc = conveyor.jsonrpc.JsonRpc(
                        connection, connection)
                    client = _Client(self._config, self, jsonrpc)
                    client.start()
            except socket.timeout:
                continue
        return 0

    def enter_active_scan_mode(self):
        self._networked_machine_detector.detector_thread.enter_active_scan_mode()

    def end_active_scan_mode(self):
        self._networked_machine_detector.detector_thread.end_active_scan_mode()

    def clear_for_rescan(self):
        self._networked_machine_detector.clear_bots_for_rescan()

    def pdb_debug(self):
        import pdb
        pdb.set_trace()

    def _avrdude_port_path(self, port):
        path = port.get_serial_port_name()
        # TODO(nicholasbishop): copied this hack from s3g, should
        # de-duplicate the code
        if platform.system() == "Windows":
            # NOTE: Windows needs the port name in this ridiculous
            # format or ports above COM4 will not work.
            return '\\\\.\\' + path
        else:
            return path

    def _upload_firmware_to_digitizer_bootloader(self, port):
        """
        Upload firmware.  The digitizer bootloader (assuming it has
        firmware) will reboot into firmware after 5 seconds (unless we start
        the firmware upload process).  This makes the connect/disconnect logic
        in the firmware fairly straightforward.  Heres a flow diagram of whats
        going to happen:

            * user requests firmware upload to the digitizer
            * conveyor resets the digitizer firmware into the bootloader
            * conveyor discovers the bootloader and constructs a machine
            * Upon construction, we begin to upload firmware
            * We suceed/fail
            * After 5 seconds, the machine boots into firmware, this causes the
                bootloader machine to disconnect and the firmware to connect

        # ISSUES:
            Due to the 5 second time lag in the detector thread, we could
            potentially not catch the reset into bootloader.
        """
        iserial = port.get_iserial()
        self._log.info("Uploading firmware to digitizer bootloader with iserial %s", iserial)
        store = conveyor.machine.digitizer.global_get_firmware_store()
        with store.condition:
            if iserial not in store:
                # Only upload if this is a bootloader we are expecting
                self._log.info("Unidentified bootloader detected.")
                return
            else:
                [hex_path, job, success] = store[iserial]
                # If we've already done the upload, don't try to
                # re-upload it; let the board move from the bootloader
                # to the main firmware.
                if success:
                    self._log.info("Skipping upload: already succeeded")
                    return
        args = [
            self._config.get("makerbot_driver", "avrdude_exe"),
            '-C', '%s' % (self._config.get("makerbot_driver", "avrdude_conf_file")),
            '-p', 'atmega32u4',
            '-P', self._avrdude_port_path(port),
            '-c', 'avr109',
            '-U', 'flash:w:%s:i' % os.path.abspath(hex_path)]
        try:
            # Huzzah py27
            self._log.debug("Executing avrdude for digitizer upload: %s",
                ' '.join(args))
            output = subprocess.check_output(args, stderr=subprocess.STDOUT)
            self._log.info(output)
        except subprocess.CalledProcessError as e:
            self._log.info("Error calling avrdude: %s", e.output)
            with store.condition:
                store[iserial][2] = False
        except Exception as e:
            self._log.info("Error calling avrdude", exc_info=True)
            with store.condition:
                store[iserial][2] = False
        else:
            with store.condition:
                store[iserial][2] = True

    def notify_clients_of_port_attached(self, port):
        """Notify all connected clients that a new port has been detected"""
        with self._clients_condition:
            clients = self._clients.copy()
        _Client.port_attached(clients, port.get_info())

    def _digitizer_port_attached(self, port):
        """Special handling of Digitizer ports

        Due to the nature of digitizer firmware uploaders, we need to
        catch the digitizer bootloader port attached event and attach
        it.  This is done to initiate the firmware uploader without
        having a connected client tell us explicitely. Additionally,
        we'll catch digitizer connections as well and, if we just
        uploaded to them, we'll end the firmware upload process.

        Returns True if this is a successful Digitizer port attach and
        the regular port-attach code should proceed. Otherwise returns
        False.

        """
        digitizer_bootloader_pid = 0x0002
        if port.get_pid() == digitizer_bootloader_pid:
            self._log.info("Found digitizer bootloader, attempting firmware upload")
            try:
                self._upload_firmware_to_digitizer_bootloader(port)
            except Exception as e:
                self._log.info("Error uploading to digitizer bootloader",
                    exc_info=True)
            return False
        else:
            iserial = port.get_iserial()
            store = conveyor.machine.digitizer.global_get_firmware_store()
            with store.condition:
                if iserial in store:
                    [hex_path, job, success] = store[iserial]
                    if success:
                        self._log.info(
                            "Digitizer firmware upload succeeded")
                        job.end(True)
                    else:
                        self._log.info(
                            "Digitizer firmware upload failed")
                        job.fail(False)
                    store.pop(iserial)

            # Check if the Digitizer's camera is also present
            if conveyor.machine.digitizer.find_camera_from_board(iserial):
                return True
            else:
                self._unpaired_digitizer_ports[port.get_machine_hash()] = port

    def _port_attached(self, port, notify=True):
        """Handle port attachment events"""
        if port.machine_type == 'Digitizer':
            if not self._digitizer_port_attached(port):
                return
        self._log.info("Discovered new port\nName: %r", port.get_info())
        machine_hash = port.get_machine_hash()

        self.disconnected_machines.forget_hash(machine_hash)
        self._ports[machine_hash] = port
        if notify:
            self.notify_clients_of_port_attached(port)

    def _port_detached(self, port, notify=True):
        machine_hash = port.get_machine_hash()
        if machine_hash:
            self.disconnected_machines.remember(port.machine)

            self._ports.pop(machine_hash)
            if notify:
                with self._clients_condition:
                    clients = self._clients.copy()
                _Client.port_detached(clients, port.machine_name)

    def _machine_state_changed(self, machine):
        with self._clients_condition:
            clients = self._clients.copy()
        machine_info = machine.get_info()
        _Client.machine_state_changed(clients, machine_info)

    def _machine_temperature_changed(self, machine):
        with self._clients_condition:
            clients = self._clients.copy()
        machine_info = machine.get_info()
        _Client.machine_temperature_changed(clients, machine_info)

    def _machine_error_notification(self, machine, error_id, error, info, details):
        with self._clients_condition:
            clients = self._clients.copy()
        _Client.machine_error(clients, machine, error_id, error, info, details)

    def _stack_error_notification(self, error, details):
        with self._clients_condition:
            clients = self._clients.copy()
        _Client.stack_error(clients, error, details)

    def _machine_error_acknowledged(self, machine, error_id):
        with self._clients_condition:
            clients = self._clients.copy()
        _Client.machine_error_acknowledged(clients, machine, error_id)

    def _network_state_change(self, machine, state):
        with self._clients_condition:
            clients = self._clients.copy()
        _Client.network_state_changed(clients, machine, state)

    def _camera_closed(self, machine):
        with self._clients_condition:
            clients = self._clients.copy()
        _Client.camera_closed(clients, machine.digitizer_camera_device_path())

    def _add_client(self, client):
        with self._clients_condition:
            self._clients.add(client)

    def _get_clients(self):
        with self._clients_condition:
            clients = self._clients.copy()
        return clients

    def _remove_client(self, client):
        with self._clients_condition:
            self._clients.remove(client)

    def _add_job(self, job):
        with self._jobs_condition:
            self._jobs[job.id] = job
        with self._clients_condition:
            clients = self._clients.copy()
        job_info = job.get_info()
        _Client.job_added(clients, job_info)

    def _job_changed(self, job):
        job_info = job.get_info()
        with self._clients_condition:
            clients = self._clients.copy()
        _Client.job_changed(clients, job_info)

    def _find_driver(self, port):
        """
        Finds a driver attached to a given port.
        """
        if 0 == len(port.driver_profiles):
            raise conveyor.error.NoDriversException
        elif len(port.driver_profiles) > 1:
            raise MultipleDriversException
        else:
            driver = self._driver_manager.get_driver(port.driver_profiles.keys()[0])
        return driver

    def _find_profile(self, port, driver):
        profiles = port.driver_profiles[driver.name]
        if 1 == len(profiles):
            profile = driver.get_profile(profiles[0])
        else:
            # NOTE: when there are no profiles or multiple profiles, we set
            # `profile` to `None` and expect that the driver determines the
            # correct profile. It will raise an exception if it cannot.
            profile = None
        return profile

    def _get_hashed_name(self, machine_name):
        if machine_name["port_type"] == conveyor.machine.port.network.NetworkPort.__name__:
            machine_hash = conveyor.machine.port.network.NetworkPort.create_machine_hash(machine_name)
        elif machine_name["port_type"] == conveyor.machine.port.usb.UsbPort.__name__:
            machine_hash = conveyor.machine.port.usb.UsbPort.create_machine_hash(machine_name)
        else:
            raise ValueError(machine_name["port_type"])
        return machine_hash

    def _get_machine_hash(self, machine_name):
        """
        Will return the machine's hash, used for looking it up in a dict.

        @ machine_name: the machine name is either going to be a dict (actual
            machine name) full of machine information, or the machine hash.
            If it is the machine hash, we just return it.
        """
        if isinstance(machine_name, dict):
            machine_hash = self._get_hashed_name(machine_name)
        else:
            machine_hash = machine_name
        return machine_hash

    def _find_machine(self, machine_name):
        """
        Finds a machine given a machine_name
        """
        machine_hash = self._get_machine_hash(machine_name)
        if machine_hash not in self._ports:
            raise conveyor.error.UnknownMachineError(machine_hash)
        port = self._ports[machine_hash]
        if port.machine:
            return port.machine
        driver = self._find_driver(port)
        # This is a concrete profile (or None for some legacy devices,
        # which require us to query the machine to determine the profile)
        profile = self._find_profile(port, driver)
        machine = driver.new_machine_from_port(port, profile)
        port.machine = machine
        self._assign_machine_callbacks(machine)
        self._log.info('creating new machine: hash=%s, driver=%s, profile=%s',
            machine_hash, driver.name, machine.get_profile().name)
        return machine

    def _assign_machine_callbacks(self, machine):
        machine.state_changed.attach(self._machine_state_changed)
        machine.temperature_changed.attach(self._machine_temperature_changed)
        machine.error_acknowledged_event.attach(self._machine_error_acknowledged)
        machine.stack_error_notification_event.attach(self._stack_error_notification)
        machine.error_notification_event.attach(
            self._machine_error_notification)
        machine.network_state_change_event.attach(self._network_state_change)
        if isinstance(machine, conveyor.machine.birdwing.BirdWingMachine):
            def discovered_job_callbacks(job):
                self._attach_job_callbacks(job)
                self._attach_pause_callbacks(job)
            machine.discovered_job_callbacks.append(discovered_job_callbacks)

    def get_ports(self):
        return self._ports.values()

    def get_drivers(self):
        drivers = self._driver_manager.get_drivers()
        return drivers

    def get_driver(self, driver_name):
        driver = self._driver_manager.get_driver(driver_name)
        return driver

    def get_profiles(self, driver_name):
        driver = self._driver_manager.get_driver(driver_name)
        profiles = driver.get_profiles(None)
        return profiles

    def get_profile(self, driver_name, profile_name):
        driver = self._driver_manager.get_driver(driver_name)
        profile = driver.get_profile(profile_name)
        return profile

    def get_machines(self):
        def port_has_machine(port):
            return None is not port.machine
        ports_with_machines = filter(port_has_machine, self._ports.values())
        machines = map(lambda port : port.machine, ports_with_machines)
        return machines

    def get_authentication_code(self, machine_name, client_secret, username,
                                thingiverse_token):
        machine = self._find_machine(machine_name)
        code = machine.get_authentication_code(client_secret, username, thingiverse_token)
        return code

    def get_authentication_token(self, machine_name, client_secret, birdwing_code, context):
        machine = self._find_machine(machine_name)
        token = machine.get_authentication_token(client_secret, birdwing_code, context);
        return token

    def send_thingiverse_credentials(self, machine_name, username, thingiverse_token,
                                     birdwing_code, client_secret):
        machine = self._find_machine(machine_name)
        if(machine.is_usb):
            return machine.set_thingiverse_credentials(username, thingiverse_token)
        return machine.send_thingiverse_credentials(username, thingiverse_token,
                                                    birdwing_code, client_secret)

    def set_thingiverse_credentials(self, machine_name, thingiverse_username, thingiverse_token,):
        machine = self._find_machine(machine_name)
        return machine.set_thingiverse_credentials(thingiverse_username, thingiverse_token)

    def expire_thingiverse_credentials(self, machine_name):
        machine = self._find_machine(machine_name)
        return machine.expire_thingiverse_credentials()

    def sync_account_to_bot(self,machine_name):
        machine = self._find_machine(machine_name)
        return machine.sync_account_to_bot()

    def authenticate_connection(self, machine_name, client_secret, birdwing_code):
        machine = self._find_machine(machine_name)
        machine.authenticate_connection(client_secret, birdwing_code)

    def change_display_name(self, machine_name, new_display_name):
        machine = self._find_machine(machine_name)
        machine.change_display_name(new_display_name)

    def ignore_filament_slip_errors(self, machine_name, ignore_errors):
        machine = self._find_machine(machine_name)
        machine.ignore_filament_slip_errors(ignore_errors)

    def first_contact(self, machine_name):
        machine = self._find_machine(machine_name)
        return machine.first_contact()

    def network_state(self, machine_name):
        machine = self._find_machine(machine_name)
        return machine.network_state()

    def wifi_scan(self, machine_name):
        machine = self._find_machine(machine_name)
        return machine.wifi_scan()

    def wifi_connect(self, machine_name, path, password):
        machine = self._find_machine(machine_name)
        return machine.wifi_connect(path, password)

    def wifi_disconnect(self, machine_name):
        machine = self._find_machine(machine_name)
        return machine.wifi_disconnect()

    def wifi_forget(self, machine_name, path):
        machine = self._find_machine(machine_name)
        return machine.wifi_forget(path)

    def wifi_disable(self, machine_name):
        machine = self._find_machine(machine_name)
        return machine.wifi_disable()

    def wifi_enable(self, machine_name):
        machine = self._find_machine(machine_name)
        return machine.wifi_enable()

    def acknowledge_error(self, machine_name, error_id):
        machine = self._find_machine(machine_name)
        return machine.acknowledge_error(error_id)

    def birdwing_put(self, machine_name, localpath, remotepath):
        machine = self._find_machine(machine_name)
        return machine.put(localpath, remotepath)

    def birdwing_get(self, machine_name, localpath, remotepath):
        machine = self._find_machine(machine_name)
        return machine.get(localpath, remotepath)

    def birdwing_list(self, machine_name, directory):
        machine = self._find_machine(machine_name)
        return machine.list(directory)

    def birdwing_ziplogs(self, machine_name, zip_path):
        machine = self._find_machine(machine_name)
        job_id = self._create_job_id()
        name = "zip_logs"
        job = conveyor.job.ZipLogsJob(job_id, name, machine)
        machine.zip_logs(zip_path, job)
        self._attach_job_callbacks(job)
        return job

    def birdwing_brooklyn_burn(self, machine_name, filepath):
        machine = self._find_machine(machine_name)
        if isinstance(machine, conveyor.machine.s3g._S3gMachine):
            raise NotImplementedError
        if not machine.is_authenticated():
            raise conveyor.error.MachineAuthenticationError
        if not machine.is_idle():
            raise conveyor.error.PrintQueuedException
        else:
            job_id = self._create_job_id()
            job_name = filepath
            job = conveyor.job.FirmwareJob(job_id, job_name, machine)
            def brooklyn_burn(job):
                try:
                    machine.brooklyn_burn(filepath, job)
                except Exception as e:
                    self._log.info("Error burning firmware", exc_info=True)
                    job.fail(False)
            self._attach_job_callbacks(job)
            job.startevent.attach(brooklyn_burn)
            job.start()
            return job

    def direct_connect(self, ip_address):
        driver = self._driver_manager.get_driver(
            conveyor.machine.birdwing.BirdWingDriver.name)
        machine = driver.direct_connect(ip_address)
        self._assign_machine_callbacks(machine)
        self._port_attached(machine.get_port(), notify=False)
        return self.connect(machine.name)

    def connect(self, machine_name):
        machine = self._find_machine(machine_name)
        if not machine._port:
            raise Exception('machine has no port before connect')
        if conveyor.machine.MachineState.DISCONNECTED == machine.get_state():
            machine.connect()
        if not machine._port:
            raise Exception('machine has no port after connect')
        if hasattr(machine, 'camera_closed_event'):
            machine.camera_closed_event.attach(self._camera_closed)
        return machine

    def disconnect(self, machine_name):
        machine = self._find_machine(machine_name)
        machine.disconnect()

    def get_reprojection_error(self, machine_name):
        machine = self._find_machine(machine_name)
        error = machine.get_reprojection_error()
        return error

    def reset_to_factory(self, machine_name, username):
        machine = self._find_machine(machine_name)
        job_id = self._create_job_id()
        job = conveyor.job.ResetToFactoryJob(job_id, "reset_to_factory", machine)
        machine.reset_to_factory(username, job)
        self._attach_job_callbacks(job)
        job.start()
        return job

    def change_chamber_lights(self, machine_name, red, green, blue, blink_hz, brightness):
        machine = self._find_machine(machine_name)
        job_id = self._create_job_id()
        job = conveyor.job.ChangeChamberLightsJob(job_id, "change_chamber_lights", machine)
        machine.change_chamber_lights(red, green, blue, blink_hz, brightness, job)
        self._attach_job_callbacks(job)
        job.start()
        return job

    def scanner_jog(self, machine_name, steps, rotation_resolution):
        machine = self._find_machine(machine_name)
        if not machine.is_idle():
            raise conveyor.error.MachineStateException
        else:
            job_id = self._create_job_id()
            job_name = self._get_job_name('scannerjog')
            job = conveyor.job.JogJob(job_id, job_name)
            job = conveyor.job.Job()
            def start_callback(job):
                machine.jog(steps, rotation_resolution, job)
            job.startevent.attach(start_callback)
            self._attach_job_callbacks(job)
            machine.register_jog_job_callbacks(job)
            job.start()
            return job

    def jog(self, machine_name, axis, distance_mm, duration):
        machine = self._find_machine(machine_name)
        if (not machine.is_idle()):
            raise conveyor.error.MachineStateException
        else:
            job_id = self._create_job_id()
            job_name = self._get_job_name('jog')
            job = conveyor.job.JogJob(job_id, job_name)
            job = conveyor.job.Job()
            def start_callback(job):
                machine.jog(axis, distance_mm, duration, job)
            job.startevent.attach(start_callback)
            self._attach_job_callbacks(job)
            job.start()
            return job

    def tom_calibration(self, machine_name):
        machine = self._find_machine(machine_name)
        if(not machine.is_idle()):
            raise conveyor.error.MachineStateException
        else:
            job = conveyor.job.Job()
            machine.tom_calibration(job)
            return job

    def home(self, machine_name):
        machine = self._find_machine(machine_name)
        if(not machine.is_idle()):
            raise conveyor.error.MachineStateException
        else:
            job = conveyor.job.Job()
            machine.home(job)
            return job

    def calibrate_camera_deprecated(self, machine_name, calibration_images):
        machine = self._find_machine(machine_name)
        if not machine.is_idle():
            raise conveyor.error.MachineStateException
        return machine.calibrate_camera_deprecated(calibration_images)

    def calibrate_turntable_deprecated(self, machine_name):
        machine = self._find_machine(machine_name)
        if not machine.is_idle():
            raise conveyor.error.MachineStateException
        return machine.calibrate_turntable_deprecated()

    def calibrate_laser(self, machine_name, calibration_images,
            laser_images, laser):
        machine = self._find_machine(machine_name)
        if not machine.is_idle():
            raise conveyor.error.MachineStateException
        machine.calibrate_laser(calibration_images, laser_images, laser)

    def save_calibration(self, machine_name, filepath):
        machine = self._find_machine(machine_name)
        if not machine.is_idle():
            raise conveyor.error.MachineStateException
        machine.save_calibration(filepath)

    def load_calibration(self, machine_name, filepath):
        machine = self._find_machine(machine_name)
        if not machine.is_idle():
            raise conveyor.error.MachineStateException
        machine.load_calibration(filepath)

    def load_user_calibration(self, machine_name):
        machine = self._find_machine(machine_name)
        if not machine.is_idle():
            raise conveyor.error.MachineStateException
        machine.load_user_calibration()

    def load_factory_calibration(self, machine_name):
        machine = self._find_machine(machine_name)
        if not machine.is_idle():
            raise conveyor.error.MachineStateException
        machine.load_factory_calibration()

    def save_user_calibration(self, machine_name):
        machine = self._find_machine(machine_name)
        if not machine.is_idle():
            raise conveyor.error.MachineStateException
        machine.save_user_calibration()

    def save_factory_calibration(self, machine_name):
        machine = self._find_machine(machine_name)
        if not machine.is_idle():
            raise conveyor.error.MachineStateException
        machine.save_factory_calibration()

    def digitizer_invalidate_user_calibration(self, machine_name):
        machine = self._find_machine(machine_name)
        if not machine.is_idle():
            raise conveyor.error.MachineStateException
        machine.digitizer_invalidate_user_calibration()

    def digitizer_load_name(self, machine_name):
        machine = self._find_machine(machine_name)
        if not machine.is_idle():
            raise conveyor.error.MachineStateException
        return machine.load_name()

    def digitizer_save_name(self, machine_name, name):
        machine = self._find_machine(machine_name)
        if not machine.is_idle():
            raise conveyor.error.MachineStateException
        machine.save_name(name)

    def digitizer_camera_device_path(self, machine_name):
        machine = self._find_machine(machine_name)
        return machine.digitizer_camera_device_path()

    def toggle_camera(self, machine_name, toggle):
        machine = self._find_machine(machine_name)
        if not machine.is_idle():
            raise conveyor.error.MachineStateException
        machine.toggle_camera(toggle)

    def capture_background(self, machine_name, exposure, laser, output_name):
        machine = self._find_machine(machine_name)
        if not machine.is_idle():
            raise conveyor.error.MachineStateException
        machine.capture_background(exposure, laser, output_name)

    def capture_image(self, machine_name, exposure, laser, output_file):
        machine = self._find_machine(machine_name)
        if not machine.is_idle():
            raise conveyor.error.MachineStateException
        machine.capture_image(exposure, laser, output_file)

    def capture_image_auto_exposure(self, machine_name, output_file):
        machine = self._find_machine(machine_name)
        if not machine.is_idle():
            raise conveyor.error.MachineStateException
        machine.capture_image_auto_exposure(output_file)

    def query_digitizer(self, machine_name):
        machine = self._find_machine(machine_name)
        if not machine.is_idle():
            raise conveyor.error.MachineStateException
        info = machine.query()
        return info

    def toggle_laser(self, machine_name, toggle, laser):
        machine = self._find_machine(machine_name)
        if not machine.is_idle():
            raise conveyor.error.MachineStateException
        machine.toggle_laser(toggle, laser)

    def scan(self, machine_name, point_cloud_id, rotation_resolution,
            exposure, intensity_threshold, laserline_peak,
            laser, archive, output_left_right, bounding_cylinder_top,
            bounding_cylinder_bottom, bounding_cylinder_radius, archive_path):
        machine = self._find_machine(machine_name)
        if not machine.is_idle():
            raise conveyor.error.ScanQueuedException
        point_data = self._point_cloud_container.get_point_cloud(
            point_cloud_id)
        job_id = self._create_job_id()
        job = conveyor.job.ScanJob(job_id, "scan", machine, point_data,
            rotation_resolution, exposure, intensity_threshold,
            laserline_peak, laser, archive, output_left_right,
            bounding_cylinder_top, bounding_cylinder_bottom,
            bounding_cylinder_radius, archive_path)
        self._attach_job_callbacks(job)
        def running_callback(job):
            machine.scan(job, job.point_data,
                job.rotation_resolution, job.exposure,
                job.intensity_threshold, job.laserline_peak,
                job.laser,
                job.archive, job.output_left_right,
                job.bounding_cylinder_top,
                job.bounding_cylinder_bottom,
                job.bounding_cylinder_radius,
                job.debug_output_path)
        job.runningevent.attach(running_callback)
        job.start()
        return job

    def calibrate_camera(self, machine_name, archive, archive_path):
        machine = self._find_machine(machine_name)
        if not machine.is_idle():
            raise conveyor.error.MachineStateException
        job_id = self._create_job_id()
        job = conveyor.job.CameraCalibrationJob(job_id, "calibrate_camera", machine,
            archive, archive_path)
        self._attach_job_callbacks(job)
        def running_callback(job):
            machine.calibrate_camera(job, job.archive,
                job.debug_output_path)
        job.runningevent.attach(running_callback)
        job.start()
        return job

    def calibrate_turntable(self, machine_name, archive, archive_path):
        machine = self._find_machine(machine_name)
        if not machine.is_idle():
            raise conveyor.error.MachineStateException
        job_id = self._create_job_id()
        job = conveyor.job.TurntableCalibrationJob(job_id, "calibrate_turntable",
            machine, archive, archive_path)
        self._attach_job_callbacks(job)
        def calibrate_callback(job):
            machine.calibrate_turntable(job, job.archive,
                job.debug_output_path)
        job.runningevent.attach(calibrate_callback)
        job.start()
        return job

    def point_cloud_create(self):
        return self._point_cloud_container.point_cloud_create()

    def point_cloud_destroy(self, point_cloud_id):
        self._point_cloud_container.point_cloud_destroy(point_cloud_id)

    def point_cloud_save(self, point_cloud_id, output_path):
        self._point_cloud_container.point_cloud_save(point_cloud_id,
            output_path)

    def point_cloud_load(self, point_cloud_id, side, input_path):
        self._point_cloud_container.point_cloud_load(point_cloud_id, side,
            input_path)

    def point_cloud_load_from_id(self, src_id, src_side, dst_id, dst_side):
        self._point_cloud_container.point_cloud_load_from_id(src_id, src_side,
            dst_id, dst_side)

    def point_cloud_fine_alignment(self, point_cloud_id, sample_rate,
            max_samples, inlier_ratio, max_iterations):
        self._point_cloud_container.point_cloud_fine_alignment(point_cloud_id,
            sample_rate, max_samples, inlier_ratio, max_iterations)

    def point_cloud_coarse_alignment(self, point_cloud_id):
        self._point_cloud_container.point_cloud_coarse_alignment(point_cloud_id)

    def point_cloud_process(self, point_cloud_id, grid_size, nearest_neighbors,
            adaptive_sigma, smoothing_nearest_neighbors, smoothing_iterations,
            fixed_cutoff_percent, remove_outliers):
        self._point_cloud_container.point_cloud_process(point_cloud_id,
            grid_size, nearest_neighbors, adaptive_sigma,
            smoothing_nearest_neighbors, smoothing_iterations,
            fixed_cutoff_percent, remove_outliers)

    def point_cloud_global_alignment(self, point_cloud_id, input_files, sample_rate,
            max_samples, inlier_ratio, max_iterations):
        self._point_cloud_container.point_cloud_global_alignment(point_cloud_id,
            input_files, sample_rate, max_samples, inlier_ratio, max_iterations)

    def point_cloud_crop(self, point_cloud_id, side, bounding_cylinder_top,
            bounding_cylinder_bottom, bounding_cylinder_radius):
        self._point_cloud_container.point_cloud_crop(point_cloud_id, side,
            bounding_cylinder_top, bounding_cylinder_bottom, bounding_cylinder_radius)

    def create_mesh(self):
        return self._mesher.create_mesh()

    def poisson_reconstruction(self, mesh_id, point_cloud_id,
            max_octree_depth, min_octree_depth, solver_divide, iso_divide,
            min_samples, scale, manifold):
        point_data = self._point_cloud_container.get_point_cloud(
            point_cloud_id)
        self._mesher.poisson_reconstruction(mesh_id, point_data,
            max_octree_depth, min_octree_depth, solver_divide, iso_divide,
            min_samples, scale, manifold)

    def cut_plane(self, mesh_id, x_normal, y_normal, z_normal, plane_origin):
        self._mesher.cut_plane(mesh_id, x_normal, y_normal, z_normal,
            plane_origin)

    def place_on_platform(self, mesh_id):
        self._mesher.place_on_platform(mesh_id)

    def load_mesh(self, mesh_id, input_file):
        self._mesher.load_mesh(mesh_id, input_file)

    def save_mesh(self, mesh_id, output_file):
        self._mesher.save_mesh(mesh_id, output_file)

    def destroy_mesh(self, mesh_id):
        self._mesher.destroy_mesh(mesh_id)

    def mesh_copy(self, mesh_src_id, mesh_dst_id):
        self._mesher.deep_copy(mesh_src_id, mesh_dst_id)

    def get_digitizer_version(self, machine_name):
        machine = self._find_machine(machine_name)
        return machine.get_firmware_version()

    def _stage_job(self, job):
        """
        Both sets a job up and starts its internal job.  We use the recipe
        to string together the correct jobs.
        """
        self._attach_job_callbacks(job)
        self._attach_pause_callbacks(job)
        recipe = conveyor.recipe.Recipe(self._config, self, job)
        recipe.cook()
        job.start()

    def _streaming_stage_job(self, job):
        """
        Both sets a streaming job up and starts its internal job.  We use the recipe
        to string together the correct jobs.
        """
        self._attach_job_callbacks(job)
        self._attach_pause_callbacks(job)
        recipe = conveyor.recipe.Recipe(self._config, self, job)
        recipe.streaming_cook()
        job.start()

    def _attach_pause_callbacks(self, job):
        def pause_callback(job):
            self._job_changed(job)
        job.pauseevent.attach(pause_callback)
        def unpause_callback(job):
            self._job_changed(job)
        job.unpauseevent.attach(unpause_callback)
        if hasattr(job, 'machine'):
            machine = job.machine
            if isinstance(machine, conveyor.machine.s3g._S3gMachine):
                def pause_callback(job):
                    machine.pause()
                    self._job_changed(job)
                def unpause_callback(job):
                    machine.unpause()
                    self._job_changed(job)
                job.pauseevent.attach(pause_callback)
                job.unpauseevent.attach(unpause_callback)
            elif isinstance(machine, conveyor.machine.birdwing.BirdWingMachine):
                def pause_callback(job):
                    # HACKY: There is currently no good way to pass additional
                    # information into job callbacks, so we patch the job
                    # object to get the was_remote flag in

                    # Remote jobs DO NOT get this functionality run, since we dont
                    # want to double pause
                    if not getattr(job, "was_remote", False):
                        try:
                            machine.pause(job.process_id)
                        except Exception as e:
                            self._log.info("Error pausing job")
                        else:
                            self._log.info("Local job pause, pausing machine")
                    else:
                        self._log.info("Remote job pause, not pausing machine")
                    # We now remove the attr, to make this an even worse
                    # implementation
                    try:
                        delattr(job, 'was_remote')
                    except AttributeError as e:
                        pass
                def unpause_callback(job):
                    # HACKY: There is currently no good way to pass additional
                    # information into job callbacks, so we patch the job
                    # object to get the was_remote flag in
                    if not getattr(job, "was_remote", False):
                        try:
                            machine.unpause(job.process_id)
                        except Exception as e:
                            self._log.info("Error unpausing job")
                        else:
                            self._log.info("Local job unpause, unpausing machine")
                    else:
                        self._log.info("Remote job unpause, not unpausing machine")
                    # We now remove the attr, to make this an even worse
                    # implementation.
                    try:
                        delattr(job, 'was_remote')
                    except AttributeError as e:
                        pass
                job.pauseevent.attach(pause_callback)
                job.unpauseevent.attach(unpause_callback)

    def print_again(self, machine_name):
        job_id = self._create_job_id()
        job_name = "print_again"
        machine = self._find_machine(machine_name)
        if isinstance(machine, conveyor.machine.s3g._S3gMachine):
            raise NotImplementedError
        if not machine.is_authenticated():
            raise conveyor.error.MachineAuthenticationError
        if not machine.is_idle():
            raise conveyor.error.PrintQueuedException
        else:
            job = conveyor.job.StrictlyPrintJob(job_id, job_name, machine)
            def print_again(job):
                try:
                    machine.print_again(job)
                except Exception as e:
                    self._log.info("Error printing file again", exc_info=True)
                    job.fail(False)
            self._attach_job_callbacks(job)
            self._attach_pause_callbacks(job)
            job.startevent.attach(print_again)
            job.start()
            return job

    def _add_job_metadata(self, job, job_metadata):
        """Add optional metadata to job."""
        self._log.info("DEBUG: {0}".format(job_metadata))
        if job_metadata:
            for key, val in job_metadata.iteritems():
                job.add_extra_info(key, val, callback=False)

    def print(self, machine_name, input_file,
            has_start_end, slicer_settings, thumbnail_dir,
            metadata, job_metadata, username):
        job_id = self._create_job_id()
        job_name = self._get_job_name(input_file)
        machine = self._find_machine(machine_name)
        if not machine.is_authenticated():
            raise conveyor.error.MachineAuthenticationError
        if not machine.is_idle():
            raise conveyor.error.PrintQueuedException
        else:
            job = conveyor.job.PrintJob(
                job_id, job_name, machine, input_file,
                has_start_end,
                slicer_settings, thumbnail_dir, metadata, username)
            self._add_job_metadata(job, job_metadata)
            used_extruders = conveyor.util.get_used_extruders(slicer_settings,
                self._config.get("server", "makerbot_thing_tool"), input_file)
            # We need to do a check here for the total number of extruders we can
            # use against the total number of requested extruders so we don't use
            # an invalid profile
            if machine.get_toolhead_count() < len(used_extruders):
                self._log.info("Not enough extruders to print to.  Requested: %r, Usable: %r", len(used_extruders), machine.get_toolhead_count())
                raise conveyor.error.NotEnoughExtrudersException
            else:
                # MONKEY PATCH!
                # This is picked up by the recipe
                job.used_extruders = used_extruders
            self._stage_job(job)
            return job

    def streaming_print(self, machine_name, layout_id,
                        thingiverse_token, job_name, metadata_tmp_path):
        job_id = self._create_job_id()
        machine = self._find_machine(machine_name)
        if not machine.is_authenticated():
            raise conveyor.error.MachineAuthenticationError
        if not machine.is_idle():
            raise conveyor.error.PrintQueuedException
        else:
            job = conveyor.job.StreamingPrintJob(
                job_id,
                job_name,
                machine,
                layout_id,
                thingiverse_token,
                metadata_tmp_path)
            self._streaming_stage_job(job)
            return job

    def print_from_file(self, machine_name, input_file, username):
        job_id = self._create_job_id()
        job_name = self._get_job_name(input_file)
        machine = self._find_machine(machine_name)
        if not machine.is_authenticated():
            raise conveyor.error.MachineAuthenticationError
        if not machine.is_idle():
            raise conveyor.error.PrintQueuedException
        else:
            job = conveyor.job.PrintFromFileJob(
              job_id,
              job_name,
              machine,
              input_file,
              username)
            self._stage_job(job)
            return job

    def pause(self, machine_name):
        machine = self._find_machine(machine_name)
        machine.pause()

    def unpause(self, machine_name):
        machine = self._find_machine(machine_name)
        machine.unpause()

    def print_to_file(
            self, profile_name, input_file, output_file,
            has_start_end,
            slicer_settings, thumbnail_dir, metadata, job_metadata):
        job_id = self._create_job_id()
        job_name = self._get_job_name(output_file)
        driver, profile = self._driver_manager.get_from_profile(profile_name)
        job = conveyor.job.PrintToFileJob(
            job_id, job_name, driver, profile, input_file,
            output_file, has_start_end,
            slicer_settings, thumbnail_dir, metadata)
        self._add_job_metadata(job, job_metadata)
        used_extruders = conveyor.util.get_used_extruders(slicer_settings,
            self._config.get("server", "makerbot_thing_tool"), input_file)
        # We need to do a check here for the total number of extruders we can
        # use against the total number of requested extruders so we don't use
        # an invalid profile
        if profile.number_of_tools < len(used_extruders):
            self._log.info("Not enough extruders to print to.  Requested: %rUsable: %r",
                len(used_extruders),
                profile.number_of_tools)
            raise conveyor.error.NotEnoughExtrudersException
        else:
            # MONKEY PATCH
            # This is picked up by the recipe
            job.used_extruders = used_extruders
        self._stage_job(job)
        return job

    def set_toolhead_temperature(self, machine_name, tool_index,
                                 temperature_deg_c):
        machine = self._find_machine(machine_name)
        job = conveyor.job.Job()
        machine.set_toolhead_temperature(tool_index, temperature_deg_c, job)
        return job

    def miracle_grue_config_version_check(self, config):
        return (conveyor.slicer.miraclegrue.MiracleGrueSlicer.
                config_compare_version(config))

    def upgrade_miracle_grue_config(self, config):
        return (conveyor.slicer.miraclegrue.MiracleGrueSlicer.
                upgrade_config(config))

    def slice(
            self, profile_name, input_file, output_file,
            add_start_end, slicer_settings,
            job_metadata):
        """
        Slices an stl/thing file for printing.

        NB: Currently (as of 2.3) makerware will actually tell conveyor
        to slice .gcode files.  This is a bad thing.  It should be changed
        to call print_to_file on gcode files (MW-1412)
        """
        job_id = self._create_job_id()
        job_name = self._get_job_name(output_file)
        driver, profile = self._driver_manager.get_from_profile(profile_name)
        job = conveyor.job.SliceJob(
            job_id, job_name,driver, profile, input_file,
            output_file, add_start_end,
            slicer_settings)
        self._add_job_metadata(job, job_metadata)
        # MONKEY PATCH
        # This is picked up by the recipe later
        job.used_extruders = conveyor.util.get_used_extruders(
            slicer_settings,
            self._config.get("server", "makerbot_thing_tool"), input_file)
        self._stage_job(job)
        return job

    def get_jobs(self, client):
        with self._jobs_condition:
            jobs = self._jobs.copy()
        return jobs

    def get_job(self, job_id):
        with self._jobs_condition:
            try:
                job = self._jobs[job_id]
            except KeyError:
                raise conveyor.error.UnknownJobError(job_id)
            else:
                return job

    def cancel_job(self, job_id):
        job = self.get_job(job_id)
        if job.state != conveyor.job.JobState.STOPPED and job.can_cancel:
            job.cancel()

    def pause_job(self, job_id):
        job = self.get_job(job_id)
        if not job.pausable:
            raise NotImplementedError
        else:
            job.pause()

    def unpause_job(self, job_id):
        job = self.get_job(job_id)
        if not job.ispaused():
            raise AttributeError
        else:
            job.unpause()

    def _create_job_id(self):
        return conveyor.job.JobCounter.create_job_id()

    def _get_job_name(self, p):
        root, ext = os.path.splitext(p)
        job_name = os.path.basename(root)
        return job_name

    def _attach_job_callbacks(self, job):
        """
        Attaches all of the required callbacks for jobs.  These callbacks handle
        doing things like:
            * Logging they have started
            * Registering themselves with the server
            * Notifying clients of various job_changed events
        """
        def start_callback(job):
            job.log_job_started(self._log)
            self._add_job(job)
        job.startevent.attach(start_callback)
        def heartbeat_callback(job):
            job.log_job_heartbeat(self._log)
            self._job_changed(job)
        job.heartbeatevent.attach(heartbeat_callback)
        def stopped_callback(job):
            job.log_job_stopped(self._log)
            self._job_changed(job)
        job.stoppedevent.attach(stopped_callback)
        job.attach_changed_callback(self._job_changed)

    def reset_eeprom_completely(self, machine_name):
        machine = self._find_machine(machine_name)
        job = conveyor.job.Job()
        machine.reset_eeprom_completely(job)
        return job

    def upload_firmware(self, machine_name, input_file):
        """
        Creates an upload firmware job and passes it to the machine object,
        which is expected to assign all of the proper callbacks.
        """
        machine = self._find_machine(machine_name)
        job_id = self._create_job_id()
        name = "firmware_upload"
        job = conveyor.job.FirmwareJob(job_id, name, machine)
        machine.upload_firmware(input_file, job)
        self._attach_job_callbacks(job)
        return job

    def read_eeprom(self, machine_name):
        machine = self._find_machine(machine_name)
        job = conveyor.job.Job()
        machine.read_eeprom(job)
        return job

    def write_eeprom(self, machine_name, eeprom_map):
        machine = self._find_machine(machine_name)
        job = conveyor.job.Job()
        machine.write_eeprom(eeprom_map, job)
        return job

    def usb_device_inserted(self, vid, pid, serial):
        try:
            machine_name = conveyor.machine.port.usb.UsbPort.create_machine_name(
                vid, pid, serial)
            machine_hash = self._get_hashed_name(machine_name)
            if machine_hash in self._ports:
                self._log.info('%s already inserted' % (machine_name))
            else:
                self._log.info('Device %s inserted' % (machine_name))

            port = conveyor.machine.port.usb.UsbPort(vid, pid, serial)
            self._log.debug(
                'Found device category for {}: {}'.format(
                    port.machine_name, port.machine_type))

            # TODO(nicholasbishop): this looks suspicious, should
            # at least get commented or moved into its own
            # function
            for driver_name in port.driver_profiles:
                driver = self._driver_manager.get_driver(driver_name)
                profiles = driver.get_profiles(port)
                port.driver_profiles[driver_name] = [p.name for p in profiles]

            self._port_attached(port, notify=False)

            if machine_hash not in self._ports:
                # Port didn't attach, don't bother trying to connect
                return
            # Try to connect, delete the port if that fails
            try:
                machine = self.connect(machine_name)
            except Exception as e:
                self._log.error(
                    'Error connecting to machine {}'.format(machine_name),
                    exc_info=True)
                self._port_detached(port, notify=False)
            else:
                if isinstance(machine,
                              conveyor.machine.birdwing.BirdWingMachine):
                    # We're done here.  Dont tell makerware our dirty little
                    # secret either, save that for when we've secured out
                    # connection.
                    return

            # Don't notify clients until after connecting. This makes
            # sense for printers, because they're not useful until
            # connected anyway, but it's essential for Digitizer (at
            # least as the UI is currently written.)
            #
            # If we notify before connecting, the UI will be telling
            # conveyor to load calibration at the same time that the
            # server is trying to connect. The UI then fails because
            # the machine is busy.
            self.notify_clients_of_port_attached(port)
        except conveyor.error.UsbNoCategoryException:
            # Not really an error: this is not a known machine type
            #
            # There's one case we need to handle here: a Digitizer
            # camera being plugged in is not a machine in its own
            # right, but there might be a board waiting for it
            if conveyor.machine.digitizer.is_camera(vid, pid):
                for machine_hash, p in self._unpaired_digitizer_ports.items():
                    if conveyor.machine.digitizer.find_camera_from_board(
                            p.get_iserial()):
                        del self._unpaired_digitizer_ports[machine_hash]
                        self.usb_device_inserted(
                            p.get_vid(),
                            p.get_pid(),
                            p.get_iserial())
        except Exception as e:
            # Don't allow any exceptions to escape this hook
            self._log.error(
                'Error adding port for {}:{}:{}'.format(vid, pid, serial),
                exc_info=True)

    def usb_device_removed(self, vid, pid, iserial):
        try:
            machine_name = conveyor.machine.port.usb.UsbPort.create_machine_name(vid, pid, iserial)
            machine_hash = self._get_hashed_name(machine_name)

            if machine_hash in self._unpaired_digitizer_ports:
                del self._unpaired_digitizer_ports[machine_hash]

            if machine_hash in self._ports:
                port = self._ports[machine_hash]
                machine = port.machine
                if machine:
                    # If BirdWing, call the specific disconnect USB
                    # functionality to stop the client thread
                    if isinstance(machine,
                                  conveyor.machine.birdwing.BirdWingMachine):
                        machine.usb_unplugged()
                    else:
                        machine.disconnect()
                self._port_detached(port)
                self._log.info('Removed device %s.' % (machine_name))
            else:
                self._log.info('Nothing to remove for %s' % (machine_name))
        except Exception as e:
            self._log.info("Error removing USB device", exc_info=True)

    def usb_scan_devices(self):
        """
        When conveyor starts up, we scan once for already connected devices.
        """
        for device in usb.core.find(find_all = True):
            vid, pid = (device.idVendor, device.idProduct)
            self._log.debug("Checking for printer class devices.  VID: %s, PID: %s", vid, pid)
            # Take action based on whether or not the printer we're looking at
            # is a USB printer class (i.e. Class 7) device
            if conveyor.machine.port.usb.is_usb_printer_device(vid, pid) :
                try:
                    self._log.debug("Found a Birdwing device.  VID: %s, PID: %s", vid, pid)
                    iserial = usb.util.get_string(device, device.iSerialNumber)
                    self.usb_device_inserted(vid, pid, iserial)
                except Exception as e:
                    self._log.error("Could not access a MakerBot USB device VID: %s, PID: %s.  Please make sure libusb or a libusb-enabled driver is installed and try again.", vid, pid)

        # Loop over all possible VIDs and PIDs that are not USB printer class devices,
        # find all instances and configure them
        # for device_category in conveyor.machine.port.usb.get_port_categories():
        #     # After we're through with the real USB devices, find all the serial ones and
        #     # create connections for those.
        #     if not conveyor.machine.port.usb.is_usb_printer_device(device_category.vid, device_category.pid):
        #         serial_ports = serial.tools.list_ports.list_ports_by_vid_pid(device_category.vid, device_category.pid)
        #
        #         for port in serial_ports:
        #             self.usb_device_inserted(device_category.vid, device_category.pid, port['iSerial'])

    def global_align_and_mesh(self, point_cloud_id, mesh_id, input_path, output_file):
        #add archiving of transformed scans
        """
        temporary function for debugging purposes until something is implemented
        on the UI side
        """
        #fine-align params
        input_files = [os.path.join(input_path, file) for file in os.listdir(input_path) if file.endswith('.xyz')]
        sample_rate = 0.2
        max_samples = 100000
        inlier_ratio = 0.9
        max_iterations = 200

        #process params
        grid_size = 0.5
        nearest_neighbors = 20
        adaptive_sigma = 2
        smoothing_nearest_neighbors = 20
        smoothing_iterations = 0
        fixed_cutoff_percent = 0.02

        #meshing params
        min_octree_depth = 5
        max_octree_depth = 8
        solver_divide = 8
        iso_divide = 8
        min_samples = 1
        scale = 1.25
        manifold = True

        self.point_cloud_global_alignment(point_cloud_id, input_files,
            sample_rate, max_samples, inlier_ratio, max_iterations)
        self.point_cloud_process(point_cloud_id, grid_size, nearest_neighbors,
            adaptive_sigma, smoothing_nearest_neighbors, smoothing_iterations,
            fixed_cutoff_percent, remove_outliers=False)
        self.point_cloud_save(point_cloud_id, "%s.xyz" % output_file[:-4])
        self.poisson_reconstruction(mesh_id, point_cloud_id,
            max_octree_depth, min_octree_depth, solver_divide, iso_divide,
            min_samples, scale, manifold)
        self.save_mesh(mesh_id, output_file)

    def load_filament(self, machine_name, tool_index, temperature):
        machine = self._find_machine(machine_name)
        job_id = self._create_job_id()
        job = conveyor.job.LoadFilamentJob(job_id, "load_filament", machine)
        machine.load_filament(tool_index, temperature, job)
        self._attach_job_callbacks(job)
        job.start()
        return job

    def unload_filament(self, machine_name, tool_index, temperature):
        machine = self._find_machine(machine_name)
        job_id = self._create_job_id()
        job = conveyor.job.UnloadFilamentJob(job_id, "unload_filament", machine)
        machine.unload_filament(tool_index, temperature, job)
        self._attach_job_callbacks(job)
        job.start()
        return job

    def load_print_tool(self, machine_name, tool_index):
        machine = self._find_machine(machine_name)
        job_id = self._create_job_id()
        job = conveyor.job.LoadPrintToolJob(job_id, "load_print_tool", machine)
        machine.load_print_tool(tool_index, job)
        self._attach_job_callbacks(job)
        job.start()
        return job


class _Client(conveyor.stoppable.StoppableThread):
    '''
    This is the `Server`'s notion of a client. One `_Client` is allocated for
    each incoming connection.

    '''

    def __init__(self, config, server, jsonrpc):
        conveyor.stoppable.StoppableThread.__init__(self)
        self._config = config
        self._server = server
        self._jsonrpc = jsonrpc
        self._username = ''
        self._tv_username = ''
        self._log = conveyor.log.getlogger(self)

    def stop(self):
        self._jsonrpc.stop()

    def run(self):
        def func():
            conveyor.jsonrpc.install(self._jsonrpc, self)
            self._server._add_client(self)
            try:
                self._jsonrpc.run()
            finally:
                self._server._remove_client(self)
        conveyor.error.guard(self._log, func)

    @staticmethod
    def _send_notification(clients, name, params):
        for client in clients:
            client._jsonrpc.notify(name, params)

    @staticmethod
    def port_attached(clients, port_info):
        params = port_info
        _Client._send_notification(clients, 'port_attached', params)

    @staticmethod
    def port_detached(clients, machine_name):
        params = {'machine_name': machine_name}
        _Client._send_notification(clients, 'port_detached', params)

    @staticmethod
    def machine_state_changed(clients, machine_info):
        params = machine_info
        _Client._send_notification(clients, 'machine_state_changed',
                                         params)

    @staticmethod
    def machine_temperature_changed(clients, machine_info):
        params = machine_info
        _Client._send_notification(clients, 'machine_temperature_changed',
                                   params)

    @staticmethod
    def camera_closed(clients, device_path):
        _Client._send_notification(clients, 'camera_closed', device_path)

    @staticmethod
    def job_added(clients, job_info):
        params = job_info
        _Client._send_notification(clients, 'jobadded', params)

    @staticmethod
    def job_changed(clients, job_info):
        params = job_info
        _Client._send_notification(clients, 'jobchanged', params)

    @staticmethod
    def machine_error(clients, machine, error_id, error, info, details):
        # This data directly copies the format sent back from
        # kaiten. Might want to change this in the future, but for now
        # this is simplest and doesn't introduce any new formats.
        params = {
            'machine_name': machine.name,
            'error_id': error_id,
            'error': error,
            'info': info,
            'details': details
        }
        _Client._send_notification(clients, 'machine_error_notification', params)

    @staticmethod
    def machine_error_acknowledged(clients, machine,error_id):
        # This data directly copies the format sent back from
        # kaiten. Might want to change this in the future, but for now
        # this is simplest and doesn't introduce any new formats.
        params = {
            'machine_name': machine.name,
            'error_id': error_id,
        }
        _Client._send_notification(clients, 'machine_error_acknowledged', params)

    @staticmethod
    def network_state_changed(clients, machine, state):
        params = {
            'machine_name': machine.name,
            'state': state
        }
        _Client._send_notification(clients, 'network_state_changed', params)

    @staticmethod
    def stack_error(clients, error, details):
        '''
        notifies clients that an error occured in some part of the stack other
        than the bot
        '''
        params = {
            'error': error,
            'details': details
        }
        _Client._send_notification(clients, 'stack_error_notification', params)

    @jsonrpc(cxx_types = {'username': 'std::string'})
    def hello(self, username):
        '''
        This is the first method any client must invoke after connecting to the
        conveyor service.

        '''
        self._username = username.replace(" ", "")
        return 'world'

    @jsonrpc()
    def pdb_debug(self):
        self._server.pdb_debug()

    @jsonrpc()
    def dir(self):
        '''
        Lists the methods available from the conveyor service.

        '''
        _dir = []
        for method, func in self._jsonrpc.getmethods().iteritems():
            args = inspect.getargspec(func).args
            try:
                args.remove("self")
            except ValueError:
                # no implied self in this function
                pass
            _dir.append({
                "method": method,
                "params": args,
                "doc": getattr(func, "__doc__", None)
            })
        return _dir

    @jsonrpc()
    def enter_active_scan_mode(self):
        self._server.enter_active_scan_mode()

    @jsonrpc()
    def end_active_scan_mode(self):
        self._server.end_active_scan_mode()

    @jsonrpc()
    def clear_for_rescan(self):
        self._server.clear_for_rescan()

    @jsonrpc()
    def get_log_path(self):
        return os.path.abspath(self._config.get('server', 'logging', 'file'))

    @jsonrpc()
    def getports(self):
        result = []
        for port in self._server.get_ports():
            dct = port.get_info()
            result.append(dct)
        return result

    @jsonrpc()
    def get_drivers(self):
        result = []
        for driver in self._server.get_drivers():
            dct = driver.get_info()
            result.append(dct)
        return result

    @jsonrpc(cxx_types = {'username': 'std::string'})
    def set_tv_username(self, username):
        self._tv_username = username.replace(" ","")

    @jsonrpc(cxx_types = {'driver_name': 'std::string'})
    def get_driver(self, driver_name):
        driver = self._server.get_driver(driver_name)
        result = driver.get_info()
        return result

    @jsonrpc(cxx_types = {'driver_name': 'std::string'})
    def get_profiles(self, driver_name):
        result = []
        for profile in self._server.get_profiles(driver_name):
            dct = profile.get_info()
            result.append(dct)
        return result

    @jsonrpc(cxx_types = {
            'driver_name': 'std::string',
            'profile_name': 'std::string'})
    def get_profile(self, driver_name, profile_name):
        profile = self._server.get_profile(driver_name, profile_name)
        result = profile.get_info()
        return result

    @jsonrpc(cxx_types = {
            'machine_name': 'conveyor::MachineName',
            'client_secret': 'std::string',
            'username': "std::string",
            'thingiverse_token': "std::string",})
    def get_authentication_code(self, machine_name, client_secret, username,
                                thingiverse_token=''):
        return self._server.get_authentication_code(machine_name, client_secret, username,
                                                    thingiverse_token)

    @jsonrpc(cxx_types = {
            'machine_name': 'conveyor::MachineName',
            'username': "std::string",
            'thingiverse_token': "std::string",
            'birdwing_code': 'conveyor::Printer::AuthenticationCode',
            'client_secret': 'std::string'})
    def send_thingiverse_credentials(self, machine_name, username, thingiverse_token,
                                     birdwing_code, client_secret):
        return self._server.send_thingiverse_credentials(machine_name, username,
                                                         thingiverse_token,
                                                         birdwing_code,
                                                         client_secret)

    @jsonrpc(cxx_types = {
            'machine_name': 'conveyor::MachineName',
            'thingiverse_username': "std::string",
            'thingiverse_token': "std::string"})
    def set_thingiverse_credentials(self, machine_name, thingiverse_username, thingiverse_token):
        return self._server.set_thingiverse_credentials(machine_name, thingiverse_username, thingiverse_token)

    @jsonrpc(cxx_types = {
            'machine_name': 'conveyor::MachineName'})
    def expire_thingiverse_credentials(self,machine_name):
        return self._server.expire_thingiverse_credentials(machine_name)

    @jsonrpc(cxx_types = {
            'machine_name': 'conveyor::MachineName'})
    def sync_account_to_bot(self,machine_name):
        return self._server.sync_account_to_bot(machine_name)

    @jsonrpc(cxx_types = {
            'machine_name': 'conveyor::MachineName',
            'client_secret': 'std::string',
            'birdwing_code': 'conveyor::Printer::AuthenticationCode'})
    def authenticate_connection(self, machine_name, client_secret, birdwing_code):
        self._server.authenticate_connection(machine_name, client_secret,
            birdwing_code)

    @jsonrpc(cxx_types = {
            'machine_name': 'conveyor::MachineName',
            'client_secret': 'std::string',
            'birdwing_code': 'conveyor::Printer::AuthenticationCode',
            'context': 'std::string'})
    def get_authentication_token(self, machine_name, client_secret, birdwing_code, context):
        return self._server.get_authentication_token(machine_name, client_secret, birdwing_code, context)

    @jsonrpc(cxx_types = {
            'machine_name': 'conveyor::MachineName',})
    def connect_to_machine(self, machine_name):
        machine = self._server.connect(machine_name)
        dct = machine.get_info()
        return dct

    @jsonrpc(cxx_types = {'machine_name': 'conveyor::MachineName'})
    def disconnect(self, machine_name):
        self._server.disconnect(machine_name)
        return None

    @jsonrpc(
        cxx_types = {
            'machine_name': 'conveyor::MachineName',})
    def print_again(self, machine_name):
        job = self._server.print_again(machine_name)
        return job.get_info()


    @jsonrpc(
        cxx_types = {
            'machine_name': 'conveyor::MachineName',
            'input_file': 'std::string'})
    def print_from_file(self, machine_name, input_file):
        job = self._server.print_from_file(
            machine_name,
            input_file,
            self._get_username())
        dct = job.get_info()
        return dct

    @jsonrpc(
        cxx_types = {
            'machine_name': 'conveyor::MachineName',
            'input_file': 'std::string',
            'has_start_end': 'bool',
            'slicer_settings': 'conveyor::PrintSettings',
            'thumbnail_dir': 'std::string',
            'metadata': 'Json::Value',
            'job_metadata': 'Json::Value'})
    def print(
            self, machine_name, input_file,
            has_start_end, slicer_settings,
            thumbnail_dir, metadata, job_metadata={}):

        job = self._server.print(machine_name, input_file,
            has_start_end, slicer_settings,
            thumbnail_dir, metadata, job_metadata, self._get_username())
        dct = job.get_info()
        return dct

    @jsonrpc( cxx_types = {
        'machine_name' : 'conveyor::MachineName',
        'layout_id' : 'int',
        'access_token' : 'std::string',
        'job_name' : 'std::string',
        'metadata_tmp_path' : 'std::string' }
    )
    def streaming_print(self, machine_name, layout_id,
                        access_token, job_name, metadata_tmp_path):
        job = self._server.streaming_print(
            machine_name, layout_id, access_token, job_name, metadata_tmp_path)
        dct = job.get_info()
        return dct

    @jsonrpc(cxx_types = {'machine_name': 'conveyor::MachineName'})
    def pause(self, machine_name):
        self._server.pause(machine_name)
        return None

    @jsonrpc(cxx_types = {'machine_name': 'conveyor::MachineName'})
    def unpause(self, machine_name):
        self._server.unpause(machine_name)
        return None

    @jsonrpc()
    def getprinters(self):
        result = []
        # Add connected machines
        for machine in self._server.get_machines():
            dct = machine.get_info()
            result.append(dct)

        # Add disconnected machines
        result += self._server.disconnected_machines.get_json_list()

        # Add archetype printers
        for driver in self._server._driver_manager.get_drivers():
            for profile in driver.get_profiles(None):
                if profile.json_profile:
                    axes = profile.json_profile.values['axes']
                    dct = {
                        'name': profile.json_profile.values["type"],
                        'driver_name': driver.name,
                        'profile_name': profile.name,
                        'state': conveyor.machine.MachineState.DISCONNECTED,
                        'toolhead_target_temperature': None,
                        'display_name': profile.json_profile.values["type"],
                        'printer_type': profile.json_profile.values['type'],
                        'can_print': False,
                        'has_heated_platform': (0 != len(profile.json_profile.values['heated_platforms'])),
                        'number_of_toolheads': len(profile.json_profile.values['tools']),
                        'temperature': None,
                        'firmware_version': None,
                        'build_volume': [axes['X']['platform_length'],
                                         axes['Y']['platform_length'],
                                         axes['Z']['platform_length']],
                    }
                    result.append(dct)
        return result

    # TODO(nicholasbishop): lots of weirdness here to look at
    @jsonrpc(cxx_types={
            'profile_name': 'conveyor::MachineName',
            'input_file': 'std::string',
            'output_file': 'std::string',
            'has_start_end': 'bool',
            'slicer_settings': 'conveyor::PrintSettings',
            'thumbnail_dir': 'std::string',
            'metadata': 'Json::Value',
            'job_metadata': 'Json::Value'})
    def print_to_file(
            self, profile_name, input_file, output_file,
            has_start_end,
            slicer_settings, thumbnail_dir, metadata,
            job_metadata={}):
        job = self._server.print_to_file(profile_name, input_file,
            output_file, has_start_end,
            slicer_settings, thumbnail_dir, metadata,
            job_metadata)
        dct = job.get_info()
        return dct

    # TODO(nicholasbishop): lots of weirdness here to look at
    @jsonrpc(cxx_types={
            'profile_name': 'conveyor::MachineName',
            'input_file': 'std::string',
            'output_file': 'std::string',
            'add_start_end': 'bool',
            'slicer_settings': 'conveyor::PrintSettings',
            'job_metadata': 'Json::Value'})
    def slice(
            self, profile_name, input_file, output_file,
            add_start_end,
            slicer_settings, job_metadata={}):
        job = self._server.slice(profile_name, input_file,
            output_file, add_start_end,
            slicer_settings, job_metadata)
        dct = job.get_info()
        return dct

    @jsonrpc()
    def getjobs(self):
        jobs = self._server.get_jobs(self)
        result = []
        for job_id in jobs:
            result.append(jobs[job_id].get_info())
        return result

    @jsonrpc(cxx_types={'id': 'conveyor::JobID'})
    def getjob(self, id):
        job = self._server.get_job(id)
        result = job.get_info()
        return result

    @jsonrpc(cxx_types={'id': 'conveyor::JobID'})
    def job_cancel(self, id):
        self._server.cancel_job(id)
        return None

    @jsonrpc(cxx_types={'id': 'conveyor::JobID'})
    def job_pause(self, id):
        self._server.pause_job(id)
        return None

    @jsonrpc(cxx_types={'id': 'conveyor::JobID'})
    def job_resume(self, id):
        self._server.unpause_job(id)
        return None

    @staticmethod
    def _format_s3g_pid(machine):
        """Format machine pid as needed by s3g firmware upload functions"""
        pid = machine.get_port().get_pid()
        return '0x{:04X}'.format(pid)

    @staticmethod
    def _format_s3g_machine_type(machine):
        """Format machine type as expected by s3g firmware upload functions"""
        return machine.get_profile().json_profile.values['machinenames'][0]

    def _get_username(self):
        username = self._username

        if self._tv_username != '':
            username = self._tv_username

        return username

    @jsonrpc(cxx_types={'machine_name': 'conveyor::MachineName'})
    def download_s3g_firmware_versions(self, machine_name):
        """Download available firmware versions for an s3g printer"""
        driver = self._server._driver_manager.get_driver('s3g')
        machine = self._server._find_machine(machine_name)
        job = conveyor.job.Job()
        driver.get_machine_versions(
            _Client._format_s3g_machine_type(machine),
            _Client._format_s3g_pid(machine),
            job)
        return job

    @jsonrpc(cxx_types={'machine_name': 'conveyor::MachineName',
                        'firmware_version': 'std::string'})
    def download_s3g_firmware(self, machine_name, firmware_version):
        """Download a particular firmware package for an s3g printer"""
        driver = self._server._driver_manager.get_driver('s3g')
        machine = self._server._find_machine(machine_name)
        job = conveyor.job.Job()
        driver.download_firmware(
            _Client._format_s3g_machine_type(machine),
            _Client._format_s3g_pid(machine),
            firmware_version,
            job)
        return job

    @jsonrpc(cxx_types = {'machine_name': 'conveyor::MachineName'})
    def reseteepromcompletely(self, machine_name):
        job = self._server.reset_eeprom_completely(machine_name)
        return job

    @jsonrpc(cxx_types = {
            'machine_name': 'conveyor::MachineName',
            'filename': 'std::string'})
    def uploadfirmware(self, machine_name, filename):
        self._log.info("Doing synchronous firmware upload job")
        job = self._server.upload_firmware(machine_name, filename)
        return job

    @jsonrpc(cxx_types = {
            'machine_name': 'conveyor::MachineName',
            'filename': 'std::string'})
    def start_upload_firmware_job(self, machine_name, filename):
        self._log.info("Starting firmware upload job; returning job handle")
        job = self._server.upload_firmware(machine_name, filename)
        job.start()
        return job.get_info()

    @jsonrpc(cxx_types = {'printername': 'conveyor::MachineName'})
    def readeeprom(self, printername):
        job = self._server.read_eeprom(printername)
        return job

    @jsonrpc(cxx_types = {
            'printername': 'conveyor::MachineName',
            'eeprommap': 'EepromMap'})
    def writeeeprom(self, printername, eeprommap):
        job = self._server.write_eeprom(printername, eeprommap)
        return job

    @jsonrpc(cxx_types = {
            'machine_name': 'conveyor::MachineName',
            'axis': 'conveyor::Printer::Axis',
            'distance_mm': 'int',
            'duration': 'int'})
    def jog(self, machine_name, axis, distance_mm, duration):
        job = self._server.jog(machine_name, axis, distance_mm, duration)
        dct = job.get_info()
        return dct

    @jsonrpc(cxx_types = {'machine_name': 'conveyor::MachineName'})
    def tom_calibration(self, machine_name):
        job = self._server.tom_calibration(machine_name)
        return job

    @jsonrpc(cxx_types = {'machine_name': 'conveyor::MachineName'})
    def home(self, machine_name):
        job = self._server.home(machine_name)
        return job

    @jsonrpc(cxx_types = {
            'machine_name': 'conveyor::MachineName',
            'tool_index': 'conveyor::Printer::Toolhead',
            'temperature_deg_c': 'int'})
    def set_toolhead_temperature(self, machine_name, tool_index,
                                 temperature_deg_c):
        self._server.set_toolhead_temperature(machine_name, tool_index,
                                              temperature_deg_c)

    @jsonrpc(cxx_types = {
        'machine_name': 'conveyor::MachineName',
        'new_display_name': 'std::string'})
    def change_display_name(self, machine_name, new_display_name):
        self._server.change_display_name(machine_name, new_display_name)

    @jsonrpc(cxx_types = {
        'machine_name': 'conveyor::MachineName',
        'ignore_errors': 'bool'})
    def ignore_filament_slip_errors(self, machine_name, ignore_errors):
        self._server.ignore_filament_slip_errors(machine_name, ignore_errors)

    @jsonrpc(cxx_types = {
        'machine_name': 'conveyor::MachineName',})
    def first_contact(self, machine_name):
        return self._server.first_contact(machine_name)

    @jsonrpc(cxx_types = {
        'machine_name': 'conveyor::MachineName',})
    def network_state(self, machine_name):
        return self._server.network_state(machine_name)

    @jsonrpc(cxx_types = {
        'machine_name': 'conveyor::MachineName',})
    def wifi_scan(self, machine_name):
        return self._server.wifi_scan(machine_name)

    @jsonrpc(cxx_types = {
        'machine_name': 'conveyor::MachineName',
        'path': 'std::string',
        'password': 'std::string'})
    def wifi_connect(self, machine_name, path, password):
        return self._server.wifi_connect(machine_name, path, password)

    @jsonrpc(cxx_types = {
        'machine_name': 'conveyor::MachineName'})
    def wifi_disconnect(self, machine_name):
        return self._server.wifi_disconnect(machine_name)

    @jsonrpc(cxx_types = {
        'machine_name': 'conveyor::MachineName',
        'path': 'std::string',})
    def wifi_forget(self, machine_name, path):
        return self._server.wifi_forget(machine_name, path)

    @jsonrpc(cxx_types = {
        'machine_name': 'conveyor::MachineName',})
    def wifi_disable(self, machine_name):
        return self._server.wifi_disable(machine_name)

    @jsonrpc(cxx_types = {
        'machine_name': 'conveyor::MachineName',})
    def wifi_enable(self, machine_name):
        return self._server.wifi_enable(machine_name)

    @jsonrpc(cxx_types = {
        'machine_name': 'conveyor::MachineName',
        'error_id': 'int'})
    def acknowledge_error(self, machine_name, error_id):
        return self._server.acknowledge_error(machine_name, error_id)

    @jsonrpc()
    def birdwingcancel(self, machine_name):
        machine = self._server._find_machine(machine_name)
        return machine.cancel()

    @jsonrpc(cxx_types = {
        'machine_name': 'conveyor::MachineName',
        'filepath': 'std::string'})
    def birdwing_brooklyn_burn(self, machine_name, filepath):
        job = self._server.birdwing_brooklyn_burn(machine_name, filepath)
        return job.get_info()

    @jsonrpc()
    def birdwinghandshake(self, machine_name, host_version):
        machine = self._server._find_machine(machine_name)
        return machine.handshake(host_version)

    @jsonrpc(cxx_types = {
        'machine_name': 'conveyor::MachineName',
        'localpath': 'std::string',
        'remotepath': 'std::string'})
    def birdwingget(self, machine_name, localpath, remotepath):
        return self._server.birdwing_get(machine_name, localpath, remotepath)

    @jsonrpc(cxx_types = {
        'machine_name': 'conveyor::MachineName',
        'directory': 'std::string'})
    def birdwinglist(self, machine_name, directory):
        return self._server.birdwing_list(machine_name, directory)

    @jsonrpc(cxx_types = {
        'machine_name': 'conveyor::MachineName',
        'localpath': 'std::string',
        'remotepath': 'std::string'})
    def birdwingput(self, machine_name, localpath, remotepath):
        return self._server.birdwing_put(machine_name, localpath, remotepath)

    @jsonrpc()
    def birdwinglock(self, machine_name, username):
        machine = self._server._find_machine(machine_name)
        return machine.lock(username)

    @jsonrpc()
    def birdwingunlock(self, machine_name, username):
        machine = self._server._find_machine(machine_name)
        return machine.unlock(username)

    @jsonrpc(cxx_types = {
        'machine_name': 'conveyor::MachineName',
        'zip_path': 'std::string',})
    def birdwingziplogs(self, machine_name, zip_path):
        job = self._server.birdwing_ziplogs(machine_name, zip_path)
        return job

    @jsonrpc()
    def usb_device_inserted(self, name, vid, pid, iserial):
        self._server.usb_device_inserted(name, vid, pid, iserial)
        return

    @jsonrpc()
    def usb_device_removed(self, vid, pid, iserial):
        self._server.usb_device_removed(vid, pid, iserial)
        return

    @jsonrpc(cxx_types={
        "ip_address": "std::string",})
    def direct_connect(self, ip_address):
        self._server.direct_connect(ip_address)

    @jsonrpc(cxx_types = {'config': 'Json::Value'})
    def miracle_grue_config_version_check(self, config):
        return self._server.miracle_grue_config_version_check(config)

    @jsonrpc(cxx_types = {'config': 'Json::Value'})
    def upgrade_miracle_grue_config(self, config):
        return self._server.upgrade_miracle_grue_config(config)

    @jsonrpc(cxx_types = {
            'machine_name': 'conveyor::MachineName',
            'tool_index': 'int',
            'temperature': 'conveyor::OptionalTemperature'})
    def load_filament(self, machine_name, tool_index, temperature):
        job = self._server.load_filament(machine_name, tool_index, temperature)
        return job.get_info()

    @jsonrpc(cxx_types = {
            'machine_name': 'conveyor::MachineName',
            'tool_index': 'int',
            'temperature': 'conveyor::OptionalTemperature'})
    def unload_filament(self, machine_name, tool_index, temperature):
        job = self._server.unload_filament(machine_name, tool_index, temperature)
        return job.get_info()

    @jsonrpc(cxx_types = {
            'machine_name': 'conveyor::MachineName',
            'tool_index': 'int'})
    def load_print_tool(self, machine_name, tool_index):
        job = self._server.load_print_tool(machine_name, tool_index)
        return job.get_info()

    @jsonrpc(cxx_types = {
            'machine_name': 'conveyor::MachineName'})
    def reset_to_factory(self, machine_name):
        job = self._server.reset_to_factory(machine_name, self._get_username())
        return job.get_info()

    @jsonrpc(cxx_types = {
             'machine_name': 'conveyor::MachineName',
             'red': 'int',
             'green': 'int',
             'blue': 'int',
             'blink_hz': 'int',
             'brightness': 'conveyor::OptionalBrightness'})
    def change_chamber_lights(self, machine_name, red, green, blue, blink_hz, brightness):
        job = self._server.change_chamber_lights(machine_name, red, green, blue, blink_hz, brightness)
        return job.get_info()

    ##### Scanner Functionality #####
    @jsonrpc(cxx_types = {
        'machine_name': 'conveyor::digitizer::Key',
        'steps': 'int',
        'rotation_resolution': 'conveyor::digitizer::StepsPerRotation'})
    def scannerjog(self, machine_name, steps, rotation_resolution):
        job = self._server.scanner_jog(machine_name, steps, rotation_resolution)
        dct = job.get_info()
        return dct

    @jsonrpc(cxx_types = {
            'machine_name': 'conveyor::digitizer::Key',
            'point_cloud_id': 'conveyor::digitizer::PointCloudID',
            'rotation_resolution': 'conveyor::digitizer::StepsPerRotation',
            'exposure': 'conveyor::digitizer::Exposure',
            'intensity_threshold': 'conveyor::digitizer::IntensityThreshold',
            'laserline_peak': 'conveyor::digitizer::LaserlinePeak',
            'laser': 'conveyor::digitizer::Laser',
            'bounding_cylinder_top': 'conveyor::digitizer::BoundingCylinderTop',
            'bounding_cylinder_bottom': 'conveyor::digitizer::BoundingCylinderBottom',
            'bounding_cylinder_radius': 'conveyor::digitizer::BoundingCylinderRadius',
            'archive_images': 'conveyor::digitizer::ArchiveImages',
            'archive_point_clouds': 'conveyor::digitizer::ArchivePointClouds',
            'archive_path': 'conveyor::digitizer::ArchivePath' })
    def scan(self, machine_name, point_cloud_id, rotation_resolution,
             exposure, intensity_threshold, laserline_peak, laser,
             bounding_cylinder_top, bounding_cylinder_bottom,
             bounding_cylinder_radius,
             archive_images, archive_point_clouds, archive_path):
        # Treat an empty path as disabling output rather than cwd
        if archive_path != None and len(archive_path) == 0:
            archive_path = None

        job = self._server.scan(machine_name, point_cloud_id,
            rotation_resolution, exposure, intensity_threshold,
            laserline_peak, laser, archive_images, archive_point_clouds,
            bounding_cylinder_top, bounding_cylinder_bottom,
            bounding_cylinder_radius, archive_path)
        dct = job.get_info()
        return dct

    @jsonrpc(cxx_types = {
            'machine_name': 'conveyor::digitizer::Key',
            'archive': 'conveyor::digitizer::ArchiveImages',
            'archive_path': 'conveyor::digitizer::ArchivePath',})
    def create_calibrate_camera_job(self, machine_name, archive, archive_path):
        job = self._server.calibrate_camera(machine_name, archive, archive_path)
        dct = job.get_info()
        return dct

    @jsonrpc(cxx_types = {
            'machine_name': 'conveyor::digitizer::Key',
            'archive': 'conveyor::digitizer::ArchiveImages',
            'archive_path': 'conveyor::digitizer::ArchivePath',})
    def create_calibrate_turntable_job(self, machine_name, archive, archive_path):
        job = self._server.calibrate_turntable(machine_name, archive, archive_path)
        dct = job.get_info()
        return dct

    @jsonrpc()
    def point_cloud_create(self):
        return self._server.point_cloud_create()

    @jsonrpc(cxx_types = {
        'point_cloud_id': 'conveyor::digitizer::PointCloudID'})
    def point_cloud_destroy(self, point_cloud_id):
        self._server.point_cloud_destroy(point_cloud_id)

    @jsonrpc(cxx_types = {
        'point_cloud_id': 'conveyor::digitizer::PointCloudID',
        'side': 'conveyor::digitizer::Side',
        'input_file': 'conveyor::digitizer::InputPath'})
    def point_cloud_load(self, point_cloud_id, side, input_file):
        self._server.point_cloud_load(point_cloud_id, side, input_file)

    @jsonrpc(cxx_types = {
        'src_id': 'conveyor::digitizer::PointCloudID',
        'src_side': 'conveyor::digitizer::Side',
        'dst_id': 'conveyor::digitizer::PointCloudID',
        'dst_side': 'conveyor::digitizer::Side',})
    def point_cloud_load_from_id(self, src_id, src_side, dst_id, dst_side):
        self._server.point_cloud_load_from_id(src_id, src_side, dst_id, dst_side)

    @jsonrpc(cxx_types = {
        'point_cloud_id': 'conveyor::digitizer::PointCloudID',
        'output_path': 'conveyor::digitizer::OutputPath',})
    def point_cloud_save(self, point_cloud_id, output_path):
        self._server.point_cloud_save(point_cloud_id, output_path)

    @jsonrpc(cxx_types = {
        'point_cloud_id': 'conveyor::digitizer::PointCloudID',
        'sample_rate': 'conveyor::digitizer::SampleRate',
        'max_samples': 'conveyor::digitizer::MaxSamples',
        'inlier_ratio': 'conveyor::digitizer::InlierRatio',
        'max_iterations': 'conveyor::digitizer::MaxIterations',})
    def point_cloud_fine_alignment(self, point_cloud_id, sample_rate,
            max_samples, inlier_ratio, max_iterations):
        self._server.point_cloud_fine_alignment(point_cloud_id,
            sample_rate, max_samples, inlier_ratio, max_iterations)

    @jsonrpc(cxx_types = {
        'point_cloud_id': 'conveyor::digitizer::PointCloudID',})
    def point_cloud_coarse_alignment(self, point_cloud_id):
        self._server.point_cloud_coarse_alignment(point_cloud_id)

    @jsonrpc(cxx_types = {
        'point_cloud_id': 'conveyor::digitizer::PointCloudID',
        'grid_size': 'conveyor::digitizer::GridSize',
        'nearest_neighbors': 'conveyor::digitizer::NearestNeighbors',
        'adaptive_sigma': 'conveyor::digitizer::AdaptiveSigma',
        'smoothing_nearest_neighbors': 'conveyor::digitizer::SmoothingNearestNeighbors',
        'smoothing_iterations': 'conveyor::digitizer::SmoothingIterations',
        'fixed_cutoff_percent': 'conveyor::digitizer::FixedCutoffPercent',
        'remove_outliers': 'conveyor::digitizer::RemoveOutliers',})
    def point_cloud_process(self, point_cloud_id, grid_size, nearest_neighbors,
            adaptive_sigma, smoothing_nearest_neighbors, smoothing_iterations,
            fixed_cutoff_percent, remove_outliers):
        self._server.point_cloud_process(point_cloud_id, grid_size,
            nearest_neighbors, adaptive_sigma, smoothing_nearest_neighbors,
            smoothing_iterations, fixed_cutoff_percent, remove_outliers)

    @jsonrpc(cxx_types = {
        'point_cloud_id': 'conveyor::digitizer::PointCloudID',
        'input_files': 'std::vector<conveyor::digitizer::InputPath>',
        'sample_rate': 'conveyor::digitizer::SampleRate',
        'max_samples': 'conveyor::digitizer::MaxSamples',
        'inlier_ratio': 'conveyor::digitizer::InlierRatio',
        'max_iterations': 'conveyor::digitizer::MaxIterations',})
    def point_cloud_global_alignment(self, point_cloud_id, input_files, sample_rate,
            max_samples, inlier_ratio, max_iterations):
        self._server.point_cloud_global_alignment(point_cloud_id, input_files, sample_rate,
            max_samples, inlier_ratio, max_iterations)

    @jsonrpc(cxx_types = {
        'point_cloud_id': 'conveyor::digitizer::PointCloudID',
        'side': 'conveyor::digitizer::Side',
        'bounding_cylinder_top': 'conveyor::digitizer::BoundingCylinderTop',
        'bounding_cylinder_bottom': 'conveyor::digitizer::BoundingCylinderBottom',
        'bounding_cylinder_radius': 'conveyor::digitizer::BoundingCylinderRadius',})
    def point_cloud_crop(self, point_cloud_id, side, bounding_cylinder_top,
            bounding_cylinder_bottom, bounding_cylinder_radius):
        self._server.point_cloud_crop(point_cloud_id, side, bounding_cylinder_top,
            bounding_cylinder_bottom, bounding_cylinder_radius)

    @jsonrpc(cxx_types = {
            'machine_name': 'conveyor::digitizer::Key'})
    def querydigitizer(self, machine_name):
        info = self._server.query_digitizer(machine_name)
        return info

    @jsonrpc(cxx_types = {
            'machine_name': 'conveyor::digitizer::Key',
            'calibration_images': 'std::vector<conveyor::digitizer::InputPath>'})
    def calibratecamera(self, machine_name, calibration_images):
        return self._server.calibrate_camera_deprecated(machine_name, calibration_images)

    @jsonrpc(cxx_types = {
            'machine_name': 'conveyor::digitizer::Key'})
    def calibrateturntable(self, machine_name):
        return self._server.calibrate_turntable_deprecated(machine_name)

    @jsonrpc(cxx_types = {
            'machine_name': 'conveyor::digitizer::Key',
            'calibration_images': 'std::vector<conveyor::digitizer::InputPath>',
            'laser_images': 'std::vector<conveyor::digitizer::InputPath>',
            'laser': 'conveyor::digitizer::Laser'})
    def calibratelaser(self, machine_name, calibration_images,
            laser_images, laser):
        self._server.calibrate_laser(machine_name, calibration_images,
            laser_images, laser)
        return True

    @jsonrpc(cxx_types = {
            'machine_name': 'conveyor::digitizer::Key',
            'filepath': 'conveyor::digitizer::OutputPath'
            })
    def savecalibration(self, machine_name, filepath):
        self._server.save_calibration(machine_name, filepath)
        return filepath

    @jsonrpc(cxx_types = {
            'machine_name': 'conveyor::digitizer::Key',
            'filepath': 'conveyor::digitizer::InputPath'
            })
    def loadcalibration(self, machine_name, filepath):
        self._server.load_calibration(machine_name, filepath)
        return True

    @jsonrpc()
    def capturebackground(self, machine_name, exposure, laser, output_file):
        self._server.capture_background(machine_name, exposure, laser, output_file)
        return True

    @jsonrpc(cxx_types = {
            'machine_name': 'conveyor::digitizer::Key',
            'exposure': 'conveyor::digitizer::Exposure',
            'laser': 'conveyor::digitizer::Laser',
            'output_file': 'conveyor::digitizer::OutputPath'})
    def captureimage(self, machine_name, exposure, laser, output_file):
        self._server.capture_image(machine_name, exposure, laser, output_file)
        return True

    @jsonrpc(cxx_types = {
            'machine_name': 'conveyor::digitizer::Key',
            'output_file': 'conveyor::digitizer::OutputPath'})
    def capture_image_auto_exposure(self, machine_name, output_file):
        self._server.capture_image_auto_exposure(
            machine_name, output_file)

    @jsonrpc(cxx_types = {
            'machine_name': 'conveyor::digitizer::Key',
            'laser': 'conveyor::digitizer::Laser'})
    def digitizer_set_enabled_lasers(self, machine_name, laser):
        self._server.toggle_laser(machine_name, True, laser)

    @jsonrpc(cxx_types = {
        'machine_name': 'conveyor::digitizer::Key',
        'toggle': 'bool'})
    def togglecamera(self, machine_name, toggle):
        self._server.toggle_camera(machine_name, toggle)

    @jsonrpc(cxx_types = {
        'machine_name': 'conveyor::digitizer::Key',
        'toggle': 'bool',
        'laser': 'conveyor::digitizer::Laser'})
    def togglelaser(self, machine_name, toggle, laser):
        self._server.toggle_laser(machine_name, toggle, laser)

    @jsonrpc(cxx_types = {
        'machine_name': 'conveyor::digitizer::Key'})
    def getreprojectionerror(self, machine_name):
        error = self._server.get_reprojection_error(machine_name)
        return error

    @jsonrpc(cxx_types={'machine_name': 'conveyor::digitizer::Key',})
    def read_user_calibration_from_eeprom(self, machine_name):
        self._server.load_user_calibration(machine_name)

    @jsonrpc(cxx_types={'machine_name': 'conveyor::digitizer::Key',})
    def read_factory_calibration_from_eeprom(self, machine_name):
        self._server.load_factory_calibration(machine_name)

    @jsonrpc(cxx_types={'machine_name': 'conveyor::digitizer::Key',})
    def write_user_calibration_to_eeprom(self, machine_name):
        self._server.save_user_calibration(machine_name)

    @jsonrpc(cxx_types={'machine_name': 'conveyor::digitizer::Key',})
    def write_factory_calibration_to_eeprom(self, machine_name):
        self._server.save_factory_calibration(machine_name)

    @jsonrpc(cxx_types={'machine_name': 'conveyor::digitizer::Key',})
    def digitizer_invalidate_user_calibration(self, machine_name):
        self._server.digitizer_invalidate_user_calibration(machine_name)

    @jsonrpc(cxx_types={'machine_name': 'conveyor::digitizer::Key'})
    def digitizer_load_name(self, machine_name):
        return self._server.digitizer_load_name(machine_name)

    @jsonrpc(cxx_types={'machine_name': 'conveyor::digitizer::Key',
                        'name': 'std::string'})
    def digitizer_save_name(self, machine_name, name):
        return self._server.digitizer_save_name(machine_name, name)

    @jsonrpc(cxx_types={'machine_name': 'conveyor::digitizer::Key'})
    def digitizer_camera_device_path(self, machine_name):
        return self._server.digitizer_camera_device_path(machine_name)

    @jsonrpc(cxx_types = {
            'mesh_id': 'conveyor::digitizer::MeshID',
            'point_cloud_id': 'conveyor::digitizer::PointCloudID',
            'min_octree_depth': 'conveyor::digitizer::MinOctreeDepth',
            'max_octree_depth': 'conveyor::digitizer::MaxOctreeDepth',
            'solver_divide': 'conveyor::digitizer::SolverDivide',
            'iso_divide': 'conveyor::digitizer::IsoDivide',
            'min_samples': 'conveyor::digitizer::MinSamples',
            'scale': 'conveyor::digitizer::Scale',
            'manifold': 'conveyor::digitizer::MakeManifold'})
    def mesh_reconstruct_point_cloud(self, mesh_id, point_cloud_id,
                                     min_octree_depth, max_octree_depth,
                                     solver_divide, iso_divide, min_samples,
                                     scale, manifold):
        self._server.poisson_reconstruction(mesh_id, point_cloud_id,
            max_octree_depth, min_octree_depth, solver_divide, iso_divide,
            min_samples, scale, manifold)

    @jsonrpc(cxx_types = {
            'mesh_id': 'conveyor::digitizer::MeshID',
            'plane_equation': 'conveyor::Plane3f'})
    def mesh_cut_plane(self, mesh_id, plane_equation):
        self._server.cut_plane(mesh_id,
            plane_equation[0], plane_equation[1],
            plane_equation[2], plane_equation[3])

    @jsonrpc()
    def mesh_create(self):
        return self._server.create_mesh()

    @jsonrpc(cxx_types = {
            'mesh_id': 'conveyor::digitizer::MeshID'})
    def mesh_place_on_platform(self, mesh_id):
        self._server.place_on_platform(mesh_id)

    @jsonrpc(cxx_types = {
            'mesh_id': 'conveyor::digitizer::MeshID',
            'input_file': 'conveyor::digitizer::InputPath'})
    def mesh_load(self, mesh_id, input_file):
        self._server.load_mesh(mesh_id, input_file)

    @jsonrpc(cxx_types = {
            'mesh_id': 'conveyor::digitizer::MeshID',
            'output_file': 'conveyor::digitizer::OutputPath'})
    def mesh_save(self, mesh_id, output_file):
        self._server.save_mesh(mesh_id, output_file)

    @jsonrpc(cxx_types = {
            'mesh_id': 'conveyor::digitizer::MeshID'})
    def mesh_destroy(self, mesh_id):
        self._server.destroy_mesh(mesh_id)

    @jsonrpc(cxx_types = {
            'mesh_src_id': 'conveyor::digitizer::MeshID',
            'mesh_dst_id': 'conveyor::digitizer::MeshID'})
    def mesh_copy(self, mesh_src_id, mesh_dst_id):
        self._server.mesh_copy(mesh_src_id, mesh_dst_id)

    @jsonrpc(cxx_types = {
            'machine_name': 'conveyor::digitizer::Key'})
    def get_digitizer_version(self, machine_name):
        return self._server.get_digitizer_version(machine_name)

    #temporary function until UI side of global alignment is implemented
    @jsonrpc(cxx_types = {
            'point_cloud_id': 'conveyor::digitizer::PointCloudID',
            'mesh_id': 'conveyor::digitizer::MeshID',
            'input_path': 'conveyor::digitizer::InputPath',
            'output_file': 'conveyor::digitizer::OutputPath'})
    def global_align_and_mesh(self, point_cloud_id, mesh_id, input_path, output_file):
        self._server.global_align_and_mesh(point_cloud_id, mesh_id,
            input_path, output_file)
