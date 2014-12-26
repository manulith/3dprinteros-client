# conveyor/src/main/python/conveyor/machine/birdwing.py
#
# conveyor - Printing dispatch engine for 3D objects and their friends.
# Copyright 2013 MakerBot Industries
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
from distutils.version import StrictVersion

import base64
import binascii
import datetime
import httplib
import HTMLParser
import json
import makerbot_driver
import os
import socket
import time
import threading
import urllib, urllib2
import urlparse
import zipfile

import conveyor.address
import conveyor.error
import conveyor.jsonrpc
import conveyor.machine
import conveyor.networked_machine_detector
import conveyor.log
import conveyor.stoppable
import conveyor.util

from conveyor.constants import CONSTANTS
from conveyor.jsonrpc import JsonRpcException
from conveyor.decorator import jsonrpc

class api_versions:
    DEFAULT = "1.0.0"
    SUPPORTED = ["0.0.1","1.0.0"]
    MAX_VERSION_SUPPORTED = max([StrictVersion(version) for version in SUPPORTED])
    MIN_VERSION_SUPPORTED = min([StrictVersion(version) for version in SUPPORTED])

class errors:
    FIRMWARE_OUTDATED_CODE = 9998
    CONVEYOR_OUTDATED_CODE = 9999

def birdwing_join(*paths):
    """
    The birdwing filesystem in a linux machine, so we need to always join paths
    in that fashion.

    Technically this is not quite the same as os.path.join on linux, since
    os.path.join('a', '/b') == '/b'.  But why would you ever do that?

    PS: I <3 reduce
    """
    if len(paths) == 0:
        return ""
    elif len(paths) == 1:
        return paths[0]
    else:
        return reduce(lambda x, y: "%s/%s" % (x, y), paths)

def url_fix(s, charset='utf-8'):
    """Sometimes you get an URL by a user that just isn't a real
    URL because it contains unsafe characters like ' ' and so on.  This
    function can fix some of the problems in a similar way browsers
    handle data entered by the user:
    """
    if isinstance(s, unicode):
        s = s.encode(charset, 'ignore')
    scheme, netloc, path, qs, anchor = urlparse.urlsplit(s)
    path = urllib.quote(path, '/%')
    qs = urllib.quote_plus(qs, ':&=')
    return urlparse.urlunsplit((scheme, netloc, path, qs, anchor))

class BirdWingDriver(conveyor.machine.Driver):
    name = 'birdwing'

    @staticmethod
    def create(config, profile_dir):
        driver = BirdWingDriver(config, profile_dir)
        for profile_name in makerbot_driver.list_profiles(profile_dir):
            json_profile = makerbot_driver.Profile(profile_name, profile_dir)
            profile = _BirdWingProfile._create(profile_name, driver, json_profile)
            driver._profiles[profile.name] = profile
        return driver

    def __init__(self, config, profile_dir):
        conveyor.machine.Driver.__init__(self, self.name, config)
        self._profile_dir = profile_dir
        self._profiles = {}

    def get_profiles(self, port):
        if None is port:
            profiles = self._profiles.values()
        else:
            profiles = []
            for profile in self._profiles.values():
                if profile._check_port(port):
                    profiles.append(profile)
        return profiles

    def get_profile(self, profile_name):
        try:
            profile = self._profiles[profile_name]
        except KeyError:
            raise conveyor.error.UnknownProfileError(profile_name)
        else:
            return profile

    def new_machine_from_port(self, port, profile):
        """ Precondition: port.machine is None """
        if profile is None:
            # Birdwing devices must have already identified the correct profile
            raise conveyor.error.NoProfileException()
        elif isinstance(profile, (str, unicode)):
            profile = self.get_profile(profile)
        machine = BirdWingMachine(port, self, profile)
        port.register_disconnected_callbacks(machine)
        return machine

    def direct_connect(self, ip_address, port=9999):
        address = conveyor.address.Address.address_factory("tcp:%s:%i" % (
                                                           ip_address,
                                                           port))
        machine = BirdWingMachine(None, self, None, name="direct", address=address)
        # This DOES NOT officially connect the machine, it just starts the client
        # thread so we can communicate with it and get some info about it
        machine.start_client_thread()
        data = machine.handshake("PUT_A_REAL_VERSION_HERE")
        port = conveyor.machine.port.network.NetworkPort(data)
        machine.set_port(port)
        profile_name = port.driver_profiles[self.name][0]
        profile = self.get_profile(profile_name)
        machine.set_profile(profile)
        machine.set_name(port.machine_name)
        return machine

def handle_auth_errors(func):
    """
    When an auth function fails because we were specifically told we were not
    authorized, we leave the machine in its current state and return a JSON
    error code.  Otherwise, the failure is likely a network issue, so we retry
    the method a few times first.  If the function repeatedly fails, we drop
    the connection and set the machine state to ERROR.

    TODO: Actually set the machine state to error when the state exists
    """
    def decorator(*args, **kwargs):
        for dummy in xrange(4):
            try:
                return func(*args, **kwargs)
            except conveyor.error.MachineAuthenticationError as e:
                # TODO: I just chose a random numer for the error code
                raise JsonRpcException(93, 'Authentication rejected', None)
            except Exception as e:
                # Don't slam the auth server with requests
                time.sleep(0.5)
        self = args[0]
        self._log.info('Auth error on %s, dropping connection'% func.__name__,
                       exc_info=True)
        self.disconnect()
        raise JsonRpcException(94, 'Authentication error', None)
    return decorator

class BirdWingMachine(conveyor.stoppable.StoppableInterface, conveyor.machine.Machine):
    """
    The BirdWingMachine is conveyor's abstraction for a remote BirdWing
    machine.  Unlike the _S3gMachine, which requires heavy manipulation
    and tracking of state/print setting up/tearing down, the BirdWing
    machines are capable of taking care of themselves.  For instance:
    s3g machines can only pause if conveyor's idea of their state is in
    a pausable; BirdWing machines know very well if they can pause, and,
    when told, will either successfully pause or fail (and report their
    status back to conveyor).
    """


    def __init__(self, port, driver, profile, name=None, address=None):
        conveyor.stoppable.StoppableInterface.__init__(self)
        conveyor.machine.Machine.__init__(self, port, driver, profile, name=name)
        self._log = conveyor.log.getlogger(self)
        # Override specifically for direct_connect, where we connect w/o a port
        if not address:
            self._address = self._port.address
        else:
            self._address = address
        self._client_thread = None
        self._system_info = {}
        # THIS IS A TEMPORARY USERNAME.  This will eventually be removed
        # in favor of the command line argument username
        self._stop = False
        # This list gets the network_detector_manager's disconnect callback
        # assigned to it via the network port's "register_disconnected_callback"
        # funciton.
        # TODO: Make all this callback nonesense simpler
        self._disconnected_callbacks = []
        # Process dict {process_handle: job}
        self._processes = {}
        # process_condition is taken during the entirety of a system/state
        # notification, in addition to registering a print process.
        self._processes_condition = threading.Condition()
        self.discovered_job_callbacks = []
        self._firmware_version = None
        self._api_version = api_versions.DEFAULT
        # This is the ideal firmware version.  Conveyor will try and print to
        # machines with unknown firmware, but there are no promises about fitness
        self._expected_firmware_version = {
            "major": 0,
            "minor": 5,
        }
        self._supported_api_versions = api_versions.SUPPORTED
        self._compatible_api = None
        self._error_notifications = False
        self._error_acknowledged = False
        self._system_notifications = False
        self._state_notifications = False
        self.authenticated = False
        self._additional_machine_info = {}
        self._disconnect_limit = 1
        self._disconnect_count = 0
        self._ping_threshold_seconds = 15
        self._ping_paused = False
        self.last_incoming_notification_time = None
        # These are some select keys we want to relay back to makerware
        self._system_notification_keys = {
            "machine_name": "display_name",
            "has_been_connected_to": "has_been_connected_to",
            "disabled_errors": "disabled_errors",
            "machine": "machine_info"}

    def _start_birdwing_process(self, job, callback, *args, **kwargs):
        """
        Starts a process on the birdwing machine and assigns a job to it

        Starting processes from conveyor is wrought with trickery.  Conveyor
        needs to know which processes IT started and which processes were started
        by other users.  Normally we could have conveyor lock all notifications,
        execute the print and mark the process it just got back and continue getting
        notifications.  HOWEVER, since notifications are processed in the same
        thread as JsonRPC responses, taking a mutex here will cause a deadlock.

        We get around this by requesting process ids up front, marking them
        before we actually execute the call.  This allows us to know which
        processes we've started using the process id.

        Note that this function also catches all errors that the callback throws,
        which is stupid but I don't want to break everything by changing it.  You
        can override this by passing in catch_errors=False as a keyword arg.
        """
        catch_errors=True
        if 'catch_errors' in kwargs:
            catch_errors = kwargs['catch_errors']
            del kwargs['catch_errors']
        requested_id = self._request_process_id()
        # We now set this process ID aside, to deal with race condition where
        # we could potentially get notifications for a job WE started but we
        # haven't tracked.  This causes us to think somebody else started the job
        with self._processes_condition:
            self._processes[requested_id] = job
        job.process_id = requested_id
        try:
            result = callback(*args, requested_id=requested_id, **kwargs)
        except Exception as e:
            # If there was an error, we need to pop this ID off since we won't
            # be using it
            self._processes.pop(requested_id)
            if catch_errors:
                import traceback
                self._log.info("Error staring process: {0}".format(traceback.format_exc()))
            else:
                raise
        else:
            self._log.info("Successfully running process {0}".format(result))
            return result

    def is_usb(self):
        return isinstance(self._address, conveyor.address.UsbAddress)

    def reset_disconnect_count(self):
        self._disconnect_count = 0

    def reset_notification_timeout(self):
        self._log.debug("resetting last notification time for {0}".format(self.name))
        self.last_incoming_notification_time = datetime.datetime.now()

    def increment_disconnect_count(self):
        self._log.info("Incrementing disconnect count for {0}".format(self.name))
        self._disconnect_count += 1

    def should_disconnect(self):
        return self._disconnect_count > self._disconnect_limit

    def ping_pause(self,pause):
        if pause:
            self._log.debug("pausing ping for {0}".format(self.name))
        else:
            self._log.debug("unpausing ping for {0}".format(self.name))
        self._ping_paused = pause

    def should_ping(self):
        if self.last_incoming_notification_time is None:
            self._log.debug("have never contacted {0}, pinging".format(self.name))
            return True
        else:
            self._log.debug("Checking if we should ping {0}".format(self.name))
            return (datetime.datetime.now() - \
                self.last_incoming_notification_time > datetime.timedelta(seconds=self._ping_threshold_seconds)) \
                and not self._ping_paused

    def set_profile(self, profile):
        self._profile = profile

    def set_name(self, name):
        self.name = name

    def get_info(self):
        """
        We override the super's get_info function so we can update the base info
        dict with some new values.
        """
        info = super(BirdWingMachine, self).get_info()
        info.update(self._additional_machine_info)
        return info

    def get_display_name(self):
        """
        Override for the super's get_display_name.  We always want the display
        name in the addition_info dict to trump the port's display name.
        """
        display_name = self._additional_machine_info.get("display_name",
            super(BirdWingMachine, self).get_display_name())
        return display_name

    def is_idle(self):
        return self._state == conveyor.machine.MachineState.IDLE

    def change_display_name(self, new_display_name):
        """
        Changes the machine name
        """
        self._do_change_display_name(new_display_name)
        system_info = self.get_system_information()
        self.system_notification(system_info)
        self.state_changed(self)

    def ignore_filament_slip_errors(self, ignore_error):
        """
        Changes if the machine ignores filament slip errors
        """
        self._do_ignore_filament_slip_errors(ignore_error)
        system_info = self.get_system_information()
        self.system_notification(system_info)
        self.state_changed(self)

    def _update_network_state(self):
        try:
            info = self.network_state()
            self._additional_machine_info["connection_type"] = info["state"]
        except conveyor.error.JobFailedException as ex:
            self._log.debug("firmware does not support network_state method, defaulting to wired")
            self._additional_machine_info["connection_type"] = "wired"
        system_info = self.get_system_information()
        self.system_notification(system_info)

    @handle_auth_errors
    def get_authentication_code(self, client_secret, username, thingiverse_token):
        """
        Grabs the authenticaiton code from the kaiten machine we're connected to.
        """
        self._log.info("Retrieving auth code from %s", self.name)
        return self._client_thread.get_authentication_code(client_secret,
                                                           username,
                                                           thingiverse_token)

    @handle_auth_errors
    def authenticate_connection(self, client_secret, birdwing_code):
        self._log.info("Authenticating connection for %s", self.name)
        self._client_thread.authenticate_connection(client_secret, birdwing_code)
        self.authenticated = True
        self._update_network_state()
        self._sync_machine()

    @handle_auth_errors
    def get_authentication_token(self, client_secret, birdwing_code, context):
        return self._client_thread.get_birdwing_token(client_secret, birdwing_code, context)

    def _sync_machine(self):
        try:
            # Time to get the updated system notification
            system_info = self.get_system_information()

            self.system_notification(system_info, force=True)
            self._firmware_version = self._convert_firmware_version(
                                        system_info["firmware_version"])

            if self._compatible_api is None:
                self._compatible_api = self._is_api_compatible_api(system_info)
            self._check_new_firmware()
            # We set a flag to determine if we have compatible firmware
            if not self._is_compatible_firmware(self._firmware_version):
                self._additional_machine_info["compatible_firmware"] = False
            else:
                self._additional_machine_info["compatible_firmware"] = True
            # Check to see if we have previously updated firmware
        except Exception as e:
            print("Exception in _sync_machine")
            print(e)
            self._log.info("Error connecting to machine %s", self.name, exc_info=True)
            self.disconnect()
        else:
            # Begin to process all kaiten notifications
            self._change_state(conveyor.machine.MachineState.IDLE)
            self._log.info("Successfully authenticated %s", self.name)
            self._heed_kaiten_notifications()

    def start_client_thread(self):
        if self._client_thread:
            if self._client_thread.is_alive():
                self._log.info("Client thread already active")
                # If we're already alive, break
                return
        with self._state_condition:
            if self._state == conveyor.machine.MachineState.DISCONNECTED:
                try:
                    self._client_thread = _BirdWingClient(self, self._address)
                    self._client_thread.start()
                except:
                    self._log.info("ERROR: could not connect to bot", exc_info=True)
                    self.disconnect()
            else:
                self._log.info("Trying to start client thread on already "
                               "connected machines; something probably "
                               "went wrong")

    def sync_usb_machine(self):
        self._log.info("Auto-authentication to USB connected machine")
        self.authenticated = True
        self._sync_machine()
        # Lets deal with that manager
        detector = conveyor.networked_machine_detector.NetworkedMachineDetector.get_instance()
        detector.register_networked_machine(self)
        detector.remove_usb_hotplug(self)

    def connect(self):
        # Only do the connect logic if we are disconnected
        with self._state_condition:
            if self._state == conveyor.machine.MachineState.DISCONNECTED:
                self.start_client_thread()
                detector = conveyor.networked_machine_detector.NetworkedMachineDetector.get_instance()
                if isinstance(self._port, conveyor.machine.port.network.NetworkPort):
                    self._change_state(conveyor.machine.MachineState.UNAUTHENTICATED)
                    detector.register_networked_machine(self)
                    info = self.get_info()
                    self._log.info("Connecting %r", info)
                elif isinstance(self._port, conveyor.machine.port.usb.UsbPort):
                    # Connecting to a USB machine doesn't insinuate that we can acually
                    # communicate with them; we need to wait for kaiten to finish
                    # starting up before we can do that.
                    self._state = conveyor.machine.MachineState.PENDING
                    detector.register_usb_hotplug(self)

    def _is_compatible_firmware(self, firmware_version):
        """
        Checks to see if this firmware version is this firmware version is
        compatible with this version of conveyor.  We consider firmware versions
        to be at this version or before to be compatible.  All other versions
        are incompatible.
        """
        # Major firmware version is ahead of us
        if self._expected_firmware_version["major"] < firmware_version[0]:
            return False
        # Major is the same, check if minor is ahead of us
        elif self._expected_firmware_version["minor"] < firmware_version[1]:
            return False
        # We're at least up to date, return True
        else:
            return True

    def _is_api_compatible_api(self,system_info):
        self._api_version = system_info.get("version",api_versions.DEFAULT)
        if self._api_version in self._supported_api_versions :
            return True
        self._log.info("Incompatible api version, expected %s bot was %s",
                        self._supported_api_versions,self._api_version)
        error_details = {
            "firmware_version": self._api_version,
            "supported_versions": self._supported_api_versions
        }
        if StrictVersion(self._api_version) > api_versions.MAX_VERSION_SUPPORTED:
            self.stack_error_notification(
                errors.CONVEYOR_OUTDATED_CODE,
                error_details)
        elif StrictVersion(self._api_version) < api_versions.MIN_VERSION_SUPPORTED:
            self.stack_error_notification(
                errors.FIRMWARE_OUTDATED_CODE,
                error_details)
        return False

    def _check_new_firmware(self):
        """
        Checks to see if there is a firmware process that was started before the
        disconnect, and that the bot is reporting the correct firmware version
        """
        detector = conveyor.networked_machine_detector.NetworkedMachineDetector.get_instance()
        try:
            job = detector.get_firmware_upload_job(self)
        except KeyError as e:
            self._log.info("No previous firmware upload job")
        else:
            self._log.info("Found previous firmware upload job.  Checking new "
                           "firmware version.")
            # Only check the [major, minor, revision] firmware versions
            expected = job._process_info.get("firmware_version", [])[:3]
            got = self._firmware_version[:3]
            if expected == got:
                self._log.info("Successfully updated machine connected")
                job.end(True)
            else:
                self._log.info("Firmware did not upload to machine correctly.\n"
                               "Expected: %r\nGot: %r", expected, got)
                job.fail(False)

    def _heed_kaiten_notifications(self):
        """
        Turn the various notifications on.  This is done to support initial
        connection, since we want to set out state up before we get all
        these notifications.
        """
        self._error_notifications = True
        self._system_notifications = True
        self._state_notifications = True
        self._error_acknowledged = True

    def _convert_firmware_version(self, firmware_version):
        """
        Makerware likes firmware versions in lists.  Make it so.
        """
        return [
            firmware_version.get("major", 0),
            firmware_version.get("minor", 0),
            firmware_version.get("bugfix", 0),
            firmware_version.get("build", 0)
        ]

    def _disconnect_client_thread(self):
        """
        Stops the client thread
        """
        if self._client_thread:
            if self._client_thread.is_alive():
                self._log.info("%s: Client thread alive, stopping it.",
                    self.name)
                self._client_thread.stop()
                try:
                    self._client_thread.join(5)
                except RuntimeError as e:
                    self._log.info("Cannot stop birdwing client thread",
                        exc_info=True)
            else:
                self._log.info("%s: Client thread not alive.", self.name)
        self._client_thread = None

    def _disconnect_networked_machine(self):
        """
        Disconnecting the networked machine should stop the client thread
        and disconnect the port associated with this machine.
        """
        # These callbacks are the port detached callbacks
        # TODO: Too many ambiguous callback lists, lets remove these soon?
        for callback in self._disconnected_callbacks:
            callback(self._port)
        self._disconnect_client_thread()

    def _disconnect_usb_machine(self):
        """
        USB machines should keep the main detector thread alive, but register
        themselves as a usb_hotplug device so we can get the kaiten restart.
        """
        conveyor.networked_machine_detector.NetworkedMachineDetector.get_instance().register_usb_hotplug(self)

    def usb_unplugged(self):
        """
        We need specific USB functionality that gets executed when the port
        gets unplugged
        """
        self._log.info("Birdwing machine unplugged")
        # This happens when we get an unplug event BEFORE kaiten disconnect
        if self._state != conveyor.machine.MachineState.DISCONNECTED:
            self.disconnect()
        # We always want to call this logic, regardless of our state
        detector = conveyor.networked_machine_detector.NetworkedMachineDetector.get_instance()
        # There is the potential for a race condition here.  We could remove
        # the usb port after we begin checking then disconnect the client
        # before we get to our machine.  We hold this condition to mitigate
        # that.
        with detector.usb_check_condition:
            detector.remove_usb_hotplug(self)
        self._disconnect_client_thread()

    def disconnect(self):
        if self._state != conveyor.machine.MachineState.DISCONNECTED:
            self._log.info("Disconnecting %s", self.name)
            with self._state_condition:
                self._change_state(conveyor.machine.MachineState.DISCONNECTED)
            detector = conveyor.networked_machine_detector.NetworkedMachineDetector.get_instance()
            with detector.ping_condition:
                detector.remove_networked_machine(self)
            # We need separate logic for these different ports, due to USB
            # devices only giving us the plug event when they are actually
            # plugged in
            if isinstance(self._port, conveyor.machine.port.usb.UsbPort):
                self._disconnect_usb_machine()
            elif isinstance(self._port,
                            conveyor.machine.port.network.NetworkPort):
                self._disconnect_networked_machine()
            with self._processes_condition:
                for process_id, job in self._processes.items():
                    # We want to keep the firmware upload process alive
                    process_info = getattr(job, "_process_info", {})
                    firmware_job = isinstance(job, conveyor.job.FirmwareJob)
                    if (firmware_job):
                        self._log.info("Firmware job shutdown machine, waiting"
                                       " for reconnect to pass/fail.")
                        detector.register_firmware_upload_job(job)
                    else:
                        job.end("disconnected")
                        self._processes.pop(process_id)

    def get_toolhead_count(self):
        profile = self.get_profile()
        return len(profile.json_profile.values['tools'])

    def stop(self):
        self._stop = True
        with self._state_condition:
            self._log.info("Stopping %s", self.name)
            self.disconnect()
            self._state_condition.notify_all()

    def _check_for_important_keys(self, info):
        updated = False
        current_info = self.get_info()
        for key, val in self._system_notification_keys.iteritems():
            if key in info and info[key] != current_info.get(key, None):
                self._additional_machine_info[val] = info[key]
                updated = True
        if updated:
            self.state_changed(self)

    def system_notification(self, info, force=False):
        """
        A system update is sent from the birdwing machine when something on its
        system changes.  A cause of a system_notification can be a:
            * Change in progress
        Unlike state reports, system_notifications contain informaiton about
        the entire machine; state_notifications only contain information about
        the object that changed state.

        Kaiten can have any number of processes running, in addition to any
        number of suspended processes.  We really only care about the
        currently running processes, though.
        """
        self.reset_notification_timeout()
        if not self._system_notifications and not force:
            self._log.debug("Not ready to execute system_notifications yet...")
            return
        self._log.debug("System notification: %r", info)
        # This is to support the initial system_notification evaluation in "connect"
        self._map_kaiten_state_to_machine_state(info["machine"]["state"])
        # Double check some of these values to make sure we have them correct
        self._check_for_important_keys(info)
        for process_id, process_info in info["current_processes"].items():
            self._handle_process_notification(process_id, process_info)
        for process_id, process_info in info["suspended_processes"].items():
            self._handle_process_notification(process_id, process_info)
        self._system_info = info

    def _handle_process_notification(self, process_id, process_info):
        # Python will de-serialize dict keys that are ints as strings
        # We can assume process_ids will always be ints, so we force it
        # into an int
        process_id = int(process_id)
        # Get job for the process, creating it if necessary
        with self._processes_condition:
            new_job = process_id not in self._processes
        if new_job:
            self._new_job_from_new_process(process_info)
        with self._processes_condition:
            job = self._processes[process_id]
        # Update extra data
        job._process_info = process_info
        if "elapsed_time" in process_info:
            job.add_extra_info("elapsed_time", process_info["elapsed_time"])
        # Update progress
        if ("step" in process_info and "progress" in process_info):
            progress_dict = {
                "name": process_info["step"],
                "progress": process_info["progress"]}
            self._issue_heartbeat(job, progress_dict)

    def _issue_heartbeat(self, job, progress_dict):
        if job.state == conveyor.job.JobState.RUNNING:
            job.heartbeat(progress_dict)

    def _cancel_print_callback(self, job):
        """Cancel remote print process if necessary.

        If a job is canceled locally then a cancel command must be
        sent. Otherwise, if the job is being canceled because it was
        canceled remotely, no need to do anything.

        """
        if not getattr(job, 'canceled_remotely', False):
            self.cancel(job.process_id)

    def _new_job_from_new_process(self, process_info):
        """
        Conveyor needs to support other connected clients starting processes.
        Here we will create a new job to track that job and alert conveyor's
        connected clients about that job.
        """
        _id = conveyor.job.JobCounter.create_job_id()
        # We need to support discovering a process that is already paused.
        # We need to start in the paused state so we don't do try and tell
        # kaiten to pause an already paused process
        if process_info.get("paused", False):
            init_state = conveyor.job.JobState.PAUSED
        else:
            # This is how jobs normally start
            init_state = conveyor.job.JobState.PENDING
        if process_info["name"] == "PrintProcess":
            new_job = conveyor.job.StrictlyPrintJob(_id, process_info["filepath"],
                self, state=init_state)
        else:
            new_job = conveyor.job.AnonymousJob(process_info["name"], _id,
                process_info["name"], self, state=init_state)
        for callback in self.discovered_job_callbacks:
            callback(new_job)
        new_job.cancelevent.attach(self._cancel_print_callback)
        with self._processes_condition:
            self._processes[process_info["id"]] = new_job
        # This is done to support processes that are started from pause.  They
        # still need to call their startevents, since those events contain
        # client notifications.
        if process_info.get("paused", False):
            new_job.startevent(new_job)
        # If not paused, we start the job normally
        else:
            new_job.start()
        if "time_estimation" in process_info:
            new_job.add_extra_info("duration_s",
                process_info["time_estimation"])
        if "extrusion_mass_a_grams" in process_info:
            new_job.add_extra_info("extrusion_mass_a_grams",
                process_info["extrusion_mass_a_grams"])

        # TODO(nicholasbishop): added this so that Birdwing jobs
        # can be paused, but I'm not sure if this is actually
        # always true. I assume that at least Birdwing will
        # gracefully fail if we try to pause an unpausable job.
        new_job.set_pausable()
        self._log.info("Non-Makerware print starting: %r",
            new_job.get_info())

        # Associate the kaiten process id with the job so that
        # conveyor operations like pause can send kaiten commands with
        # the appropriate process
        new_job.process_id = process_info["id"]
        self._map_kaiten_process_state_to_job(new_job, process_info)

    def error_acknowledged(self, error_id):
        """
        acknowledged a machine critical error. Lets the client know that a user has seen
        and acknowledged the error on the printer panel
        """
        self.reset_notification_timeout()
        if not self._error_acknowledged:
            self._log.debug("Not ready to execute error_notifications yet...")
            return
        all_info = {
            "error_id": error_id,
        }

        # Notify conveyor's clients of the error_acknowledged
        self.error_acknowledged_event(self, error_id)

    def stack_error_notification(self, error, details):
        """
         internal errors  from conveyor itself.
        """
        # Notify conveyor's clients of the error
        self.stack_error_notification_event(error, details)

    def network_state_change(self, state):
        # Notify conveyor's clients that a bot's network state has changed
        self.network_state_change_event(self, state)

    def error_notification(self,error_id, error, info, details):
        """
        Processes a machine critical error.  In the event of a machine critical
        error, we want to disconnect the machine.  In the event of process
        critical error, we do nothing and just let the state_notification take
        care of its job.

        internal errors come from conveyor itself.
        """
        self.reset_notification_timeout()
        if not self._error_notifications:
            self._log.debug("Not ready to execute error_notifications yet...")
            return
        all_info = {
            "error_id" : error_id,
            "errorno": error,
            "info": info,
            "details": details,
        }

        # Notify conveyor's clients of the error
        self.error_notification_event(self, error_id, error, info, details)

        error_string = json.dumps(all_info)
        if not details.get('process_critical'):
            self._log.debug("Non critical error %s", all_info)
        else:
            self._log.info("Process critical error %s", all_info)
        if details.get('machine_critical'):
            self._log.info("Machine critical error %s", all_info)
            with self._state_condition:
                self.disconnect()
                self._state_condition.notify_all()

    def state_notification(self, state_change):
        """
        State notifications from kaiten are processed here.  This is the only
        place where state notifications should be processed.
        """
        self.reset_notification_timeout()
        if not self._state_notifications:
            self._log.debug("Not ready to execute state_notifications yet...")
            return
        if state_change["object_type"] == "process":
            if state_change["details"] == "state_change":
                self._handle_process_state_change(state_change)
            elif state_change["details"] == "step_change":
                self._handle_process_step_change(state_change)
            self._handle_process_change_common(state_change)
        elif state_change["object_type"] == "machine_manager":
            if state_change["details"] == "state_change":
                self._handle_machine_manager_state_change(state_change)
            elif state_change["details"] == "step_change":
                self._handle_machine_manager_step_change(state_change)

    def _handle_machine_manager_step_change(self, step_change):
        """
        Handles a step change for the machine manager.
        """
        pass

    def _handle_machine_manager_state_change(self, state_change):
        """
        Handles a state change of the machine manager.  This is the only place
        where we can modify conveyor's machine state.
        """
        self._map_kaiten_state_to_machine_state(state_change["state"])

    def _map_kaiten_state_to_machine_state(self, state):
        """
        Maps kaiten's state to the machine state.  Unlike legacy machines,
        birdwing machines can execute several processes (i.e. jobs) at once.
        """
        with self._state_condition:
            if state == "idle":
                self._change_state(conveyor.machine.MachineState.IDLE)
            # We map all other states to OPERATION
            else:
                self._change_state(conveyor.machine.MachineState.RUNNING)

    def _handle_process_step_change(self, step_change):
        try:
            process_id = step_change["object_id"]
            with self._processes_condition:
                job = self._processes[process_id]
        except KeyError as e:
            self._log.info("Cannot find information about id {0}".format(
                           process_id))
        else:
            paused_steps = ["suspending", "suspended", "paused"]
            # Here is our remote pause logic.
            if (step_change["step"] in paused_steps and
                  job.state != conveyor.job.JobState.PAUSED):
                job.was_remote = True
                job.pause()
            else:
                # Here is our remote resume logic
                if (step_change["step"] not in paused_steps and
                        job.state == conveyor.job.JobState.PAUSED):
                    job.was_remote = True
                    job.unpause()
                progress = {
                    "name": step_change["step"],
                    "progress": step_change["object_info"].get("progress", 0),
                }
                self._issue_heartbeat(job, progress)

    def _handle_process_state_change(self, state_change):
        """
        Handles a state change for a process.  If a the state change report is
        about a process that doens't exist, we create it first then evaluate it.
        """
        try:
            with self._processes_condition:
                job = self._processes[state_change["object_id"]]
        # Object_id not in processe
        except KeyError as e:
            pass
        else:
            state = state_change["state"]
            self._map_kaiten_process_state_to_job(job, state_change["object_info"])

    def _handle_process_change_common(self, state_change):
        """
        Handles process changes regardless if its a state or step change
        """
        # TODO: Keeping this here for a future place to do work
        pass

    def _map_kaiten_process_state_to_job(self, job, process_info):
        state = process_info["state"]
        if state == "done":
            self._process_finished(job, process_info)
        elif state == "immutable":
            self._set_process_immutable(job, process_info)
        elif state == "only_cancellable":
            self._set_process_only_cancellable(job, process_info)
        elif state == "running":
            self._set_process_running(job, process_info)

    def _process_finished(self, job, process_info):
        """
        Evaluate a process that is finished.  Depending on the processes'
        different state variables, we can end/fail the job.
        """
        self._log.info("Process finished: %r", process_info)
        # We ONLY want to fail/end jobs if the job is running, otherwise
        # the job has already been cancelled by the user
        if job.state == conveyor.job.JobState.RUNNING:
            if process_info.get("cancelled"):
                # Mark this job as having been canceled remotely so
                # that the cancel event callback knows not to send the
                # cancel command
                job.canceled_remotely = True

                job.cancel()
            elif process_info.get("complete"):
                job.end(True)
            else:
                job.fail("error")
        with self._processes_condition:
            self._processes.pop(job.process_id)

    def _set_process_running(self, job, process_info):
        """
        Running processes can be manipulated in any way a user sees fit.
        """
        for key, val in {"can_suspend": True,}.items():
            job.add_extra_info(key, val, callback=False)
        job.set_cancellable()

    def _set_process_immutable(self, job, process_info):
        """
        An immutable process is one that currently cannot be changed
        """
        for key, val in {"can_suspend": False}.items():
            job.add_extra_info(key, val, callback=False)
        job.set_not_cancellable()

    def _set_process_only_cancellable(self, job, process_info):
        """
        An only_cancellable process can only be cancelled, not suspended, etc.
        """
        for key, val in {"can_suspend": False}.items():
            job.add_extra_info(key, val, callback=False)
        job.set_cancellable()

    def _change_state(self, state):
        with self._state_condition:
            if self._state != state:
                self._state = state
                self._state_condition.notify_all()
                self.state_changed(self)

    def upload_firmware(self, filepath, job):
        """
        Stages the job for firmware uploading.
        """
        remote_path = birdwing_join(
            "/firmware",
            os.path.basename(filepath),
        )

        # Caution: the job heartbeat names in these callbacks are part
        # of the client-side API.

        def legacy_start_callback(job):
            self._log.info("Manually alerting kaiten to firmware upload")
            job.heartbeat({
                "name": "start",
                "progress": 0})
            try:
                self._legacy_start_firmware_upload()
            except Exception as e:
                self._log.info("Cannot start firmware upload", exc_info=True)
                job.fail(conveyor.util.exception_to_failure(e))
                raise
        def legacy_failed_callback(job):
            end_upload = False
            with self._state_condition:
                if self._state != conveyor.machine.MachineState.DISCONNECTED:
                    end_upload = True
            if end_upload:
                self._log.info("Legacy firmware upload failed, resetting machine.")
                try:
                    self._legacy_end_firmware_upload()
                except Exception as e:
                    self._log.info("Error ending firmware upload", exc_info=True)
        def put_callback(job):
            self._log.info("Put: %s -> %s", filepath, remote_path)
            try:
                job.heartbeat({
                    "name": "put",
                    "progress": 0})
                self.put(filepath, remote_path, job)
                install_callback(job)
            except Exception as e:
                self._log.info("Error putting file", exc_info=True)
                job.fail(conveyor.util.exception_to_failure(e))
                raise
        def install_callback(job):
            try:
                self._log.info("Firmware put complete, starting update")
                job.heartbeat({
                    "name": "install",
                    "progress": 0})
            except Exception as e:
                    self._log.info("Error sending install heartbeat", exc_info=True)
                    raise
        def legacy_upload_callback(job):
            try:
                self._log.info("Firmware put complete, starting update")
                job.heartbeat({
                    "name": "install",
                    "progress": 0})
                result = self._start_birdwing_process(job,
                    self._legacy_do_firmware_upload, remote_path)
            except Exception as e:
                self._log.info("Error burning firmware", exc_info=True)
                job.fail(conveyor.util.exception_to_failure(e))
                raise
        def upload_firmware_callback(job):
            try:
                self._log.info("Starting firmware update process")
                job.heartbeat({
                    "name": "initialize",
                    "progress": 0})
                result = self._start_birdwing_process(job,
                    self._do_firmware_upload, remote_path, catch_errors=False)
                # Succcessfully started a process that is waiting
                # for us to initiate a transfer...
                put_callback(job)
            except conveyor.error.JobFailedException as e:
                if not isinstance(e.failure, dict) or 'code' not in e.failure \
                   or e.failure['code'] != -32602: # Invalid params
                    self._log.info("Error burning firmware", exc_info=True)
                    job.fail(conveyor.util.exception_to_failure(e))
                    raise
                # Failed to start the upload because this bot does not support
                # processes that wait for file transfers.  We need to use the
                # annoying legacy upload method
                self._log.info("Falling back to legacy firmware update process")
                job.failevent.attach(legacy_failed_callback)
                legacy_start_callback(job)
                put_callback(job)
                legacy_upload_callback(job)
            except Exception as e:
                self._log.info("Error burning firmware", exc_info=True)
                job.fail(conveyor.util.exception_to_failure(e))
                raise
        job.runningevent.attach(upload_firmware_callback)

    def put(self, localpath, remotepath, parent_job=None):
        self._client_thread.put(localpath, remotepath, parent_job)

    def get(self, localpath, remotepath):
        self._client_thread.get(localpath, remotepath)

    def list(self, directory):
        return self._client_thread.list(directory)

    def zip_logs(self, zip_path, job, requested_id=None):
        def zip_logs_callback(job):
            job.heartbeat({
                "name": "zip_logs",
                "progress": 0})
            try:
                self._start_birdwing_process(job, self._do_zip_logs, zip_path)
            except Exception as e:
                self._log.info("Zipping failed", exc_info=True)
                job.fail(conveyor.util.exception_to_failure(e))
                raise
        job.runningevent.attach(zip_logs_callback)

    # TODO (pauln, or whoever else takes this over): Implement this once
    # the required calls are exposed in kaiten.
    def change_chamber_lights(self, red, green, blue, blink_hz, brightness, job):
        return

    @conveyor.decorator.check_firmware_version
    def load_filament(self, tool_index, temperature, job):
        #job = conveyor.job.Job()
        def running_callback(job):
            self._start_birdwing_process(job, self._do_load_filament, tool_index,
                                         temperature)
        job.runningevent.attach(running_callback)
        def cancel_callback(job):
            self.cancel(job.process_id)
        job.cancelevent.attach(cancel_callback)
        return job

    @conveyor.decorator.check_firmware_version
    def load_print_tool(self, tool_index, job):
        def running_callback(job):
            self._start_birdwing_process(job, self._do_load_print_tool, tool_index)
        job.runningevent.attach(running_callback)
        def cancel_callback(job):
            self.cancel(job.process_id)
        job.cancelevent.attach(cancel_callback)
        return job

    @conveyor.decorator.check_firmware_version
    def unload_filament(self, tool_index, temperature, job):
        #job = conveyor.job.Job()
        def running_callback(job):
            self._start_birdwing_process(job, self._do_unload_filament,
                                         tool_index, temperature)
        job.runningevent.attach(running_callback)
        def cancel_callback(job):
            self.cancel(job.process_id)
        job.cancelevent.attach(cancel_callback)
        return job

    @conveyor.decorator.check_firmware_version
    def streaming_print(self, layout_id, thingiverse_token,
                        build_name, metadata_tmp_path, job):
        data = urllib.urlencode({
            'layout_id' : layout_id,
            'access_token' : thingiverse_token})
        streaming_config = CONSTANTS["DIGITAL_STORE"]["STREAMING"]
        metadata_url = urlparse.urlunsplit(
            (streaming_config["SCHEME"], # scheme
             streaming_config["HOST"] + ":" + str(streaming_config["PORT"]), # host
             streaming_config["METADATA"], # path
             "", "")) # empty
        full_meta_data = urllib2.urlopen(metadata_url, data).read()
        with open(metadata_tmp_path, 'w') as f:
            f.write(full_meta_data)
        tinything_archive = zipfile.ZipFile(metadata_tmp_path, "r")

        self._meta_data = json.loads(tinything_archive
                                        .read("meta.json")
                                        .decode("UTF-8"))
        for k,v in self._meta_data.items():
            job.add_extra_info(k, v, callback=False)

        try:
            remotepath = birdwing_join("/",
                                      "current_thing",
                                      build_name)
            self.put(metadata_tmp_path, remotepath, job)
            # We swallow the thingiverse token here. The birdwing machine is
            # auth'd to a user so there's no need to pass a token along.
            self._start_birdwing_process(job, self._do_streaming_print,
                                         layout_id, remotepath, build_name)
            job.cancelevent.attach(self._cancel_print_callback)
        except Exception as e:
            self._log.info("Error executing streaming print of layout %s",
                           layout_id,
                           exc_info=True)
            job.fail(conveyor.util.exception_to_failure(e))

    def reset_to_factory(self, username, job):
        #job = conveyor.job.Job()
        def running_callback(job):
            self._start_birdwing_process(job, self._do_reset_to_factory,
                                         username)
        job.runningevent.attach(running_callback)
        def cancel_callback(job):
            self.cancel(job.process_id)
        job.cancelevent.attach(cancel_callback)
        return job

    @conveyor.decorator.check_firmware_version
    def print(self, toolpath, extruders, extruder_temperature, platform_temperature, heat_platform, material_name, build_name, job, username):
        self._log.info("Posting %s to %s", toolpath, self.name)
        try:
            remotepath= birdwing_join("/",
                                     "current_thing",
                                     "%s%s" % (os.path.basename(build_name),
                                               os.path.splitext(toolpath)[1])
            )
            self.put(toolpath, remotepath, job)
            self._start_birdwing_process(job, self._do_print, remotepath, username)
            job.cancelevent.attach(self._cancel_print_callback)
            # Associate the kaiten process id with the job so that
            # conveyor operations like pause can send kaiten commands with
            # the appropriate process
        except Exception as e:
            self._log.info("Error executing print of %s", build_name,
                           exc_info=True)
            job.fail(conveyor.util.exception_to_failure(e))

    @conveyor.decorator.check_firmware_version
    def print_from_file(self, toolpath, build_name, job, username):
        self._log.info("Posting %s to %s", toolpath, self.name)
        try:
            remotepath= birdwing_join("/",
                                     "current_thing",
                                     "%s%s" % (os.path.basename(build_name),
                                               os.path.splitext(toolpath)[1])
            )
            self.put(toolpath, remotepath, job)
            self._start_birdwing_process(job, self._do_print, remotepath, username)
            job.cancelevent.attach(self._cancel_print_callback)
            # Associate the kaiten process id with the job so that
            # conveyor operations like pause can send kaiten commands with
            # the appropriate process
        except Exception as e:
            self._log.info("Error executing print of %s", build_name,
                           exc_info=True)
            job.fail(conveyor.util.exception_to_failure(e))

    @conveyor.decorator.check_firmware_version
    def preheat(self, job, extruders, extruder_temperatures, heat_platform,
            platform_temperature):
        """
        Preheats the machine. After we tell kaiten to preheat, we wait for its
        state to return to idle, so we dont start the print job too quickly and
        get a "ProcessAlreadyStarted" error. We always give the wait_till_heater
        flag as false, so kaiten's started process doesnt block.

        @param job: Job that will run this function
        @param <int> extruders: List of extruders
        @param <int> extruder_temperatures: List of extruder temperatures.  Each
            index of this list corresponds to an extruder.  AFAICT this is always
            of length two (since we have two extruders)
        @param bool heat_platform: True if we want to heat the platform, false
            otherwise
        @param platform_temperature: Platform temperature to heat to
        """
        temperature_settings = [0, 0, 0, 0]
        for extruder in extruders:
            temperature_settings[extruder] = extruder_temperatures[extruder]
        if heat_platform:
            temperature_settings[2] = platform_temperature
        wait_till_heated = False
        try:
            self._start_birdwing_process(job, self._do_preheat,
                                         temperature_settings, wait_till_heated)
            # Now we wait for kaiten to get idle again, since we can't print
            # to a non-idle machine
            timeout = 10 # Timeout to wait for state change to idle, in seconds
            start_time = datetime.datetime.now()
            while not self._stop:
                with self._state_condition:
                    if self._state == conveyor.machine.MachineState.IDLE:
                        break
                    elif (datetime.datetime.now() - start_time).total_seconds() > timeout:
                        self._log.info("Kaiten is taking too long to preheat, conveyor is continuing.")
                        break
                time.sleep(0.5)
        except Exception as e:
            self._log.info("Error preheating %s", self.name, exc_info=True)

    # ****
    # These functions will get/set information from the kaiten server.
    # They do not start long-running processes.
    # ****
    def send_thingiverse_credentials(self, username, thingiverse_token,
                                     birdwing_code, client_secret):
        """
        Sends a set  of thingiverse credentails over to the birdwing machine
        """
        self._client_thread.send_thingiverse_credentials(username,
                                                         thingiverse_token,
                                                         birdwing_code,
                                                         client_secret)

    @conveyor.decorator.run_job()
    def set_thingiverse_credentials(self, thingiverse_username, thingiverse_token):
        """
        Sends a set of thingiverse credentails over to the birdwing machine via JSON-RPC
        """
        params = {
            "thingiverse_username": thingiverse_username,
            "thingiverse_token": thingiverse_token}
        job = self._client_thread.generate_job("set_thingiverse_credentials", params,False)
        return job

    @conveyor.decorator.run_job()
    def expire_thingiverse_credentials(self):
        params = {}
        job = self._client_thread.generate_job("expire_thingiverse_credentials", params,False)
        return job

    @conveyor.decorator.run_job()
    def sync_account_to_bot(self):
        params = {}
        job = self._client_thread.generate_job("sync_account_to_bot", params,False)
        return job

    @conveyor.decorator.run_job()
    def ping(self):
        method = "ping"
        params = {}
        return self._client_thread.generate_job(method, params)

    @conveyor.decorator.run_job()
    def _request_process_id(self):
        method = "request_process_id"
        params = {}
        return self._client_thread.generate_job(method, params)

    @conveyor.decorator.run_job()
    def first_contact(self):
        """
        Executs "first contact" with the machine, marking it as having made
        a connection for the first time.
        """
        params = {}
        job = self._client_thread.generate_job("first_contact", params)
        return job

    @conveyor.decorator.run_job()
    def _do_change_display_name(self, new_display_name):
        """
        Changes the machine's display name
        """
        params = {
            "machine_name": new_display_name}
        job = self._client_thread.generate_job("change_machine_name", params)
        return job

    @conveyor.decorator.run_job()
    def _do_ignore_filament_slip_errors(self, ignore_errors):
        """
        Changes if we ignore filament slip errors
        """
        params = {
            "ignored": ignore_errors,
            "error" : "filament_slip"}
        job = self._client_thread.generate_job("set_toolhead_error_visibility", params)
        return job

    @conveyor.decorator.run_job()
    def _legacy_start_firmware_upload(self):
        """
        Manually put the kaiten server in the firmware_upload state.  Normally,
        this state is enterred by actually starting a firmware upload process,
        """
        self.ping_pause(True)
        params = {}
        return self._client_thread.generate_job("start_firmware_upload",
                                                params)

    @conveyor.decorator.run_job()
    def _legacy_end_firmware_upload(self):
        """
        Manually exit the firmware_upload state.  Normally the bot will do this
        if the firmware_upload fails/is cancelled, but old bots would not do this
        if the file transfer failed.
        """

        self.ping_pause(False)
        params = {}
        return self._client_thread.generate_job("end_firmware_upload",
                                                params)

    @conveyor.decorator.run_job()
    def lock(self, username):
        """
        Locks the machine, so only this user can use the machine.
        """
        raise NotImplementedError
        method = "lock"
        params = {}
        return self._client_thread.generate_job(method, params)

    @conveyor.decorator.run_job()
    def unlock(self, username):
        """
        Unlocks the machine, so other users can use it
        """
        raise NotImplementedError
        method = "unlock"
        params = {}
        return self._client_thread.generate_job(method, params)

    @conveyor.decorator.run_job()
    def pause(self, process_id):
        method = "suspend_process"
        params = {"process_id": process_id}
        return self._client_thread.generate_job(method, params)

    @conveyor.decorator.run_job()
    def unpause(self, process_id):
        method = "unsuspend_process"
        params = {"process_id": process_id}
        return self._client_thread.generate_job(method, params)

    @conveyor.decorator.run_job()
    def cancel(self, process_id):
        method = "cancel"
        params = {"process_id": process_id}
        return self._client_thread.generate_job(method, params)

    @conveyor.decorator.run_job()
    def handshake(self, host_version):
        """
        Does a handshake with the machine, which returns some information about
        itself.
        """
        method = "handshake"
        params = {
            "host_version": host_version}
        return self._client_thread.generate_job(method, params)

    @conveyor.decorator.run_job()
    def get_system_information(self):
        method = "get_system_information"
        params = {}
        return self._client_thread.generate_job(method, params)

    @conveyor.decorator.run_job()
    def network_state(self):
        method = "network_state"
        params = {}
        return self._client_thread.generate_job(method, params, update=False)

    @conveyor.decorator.run_job()
    def wifi_scan(self):
        method = "wifi_scan"
        params = {}
        return self._client_thread.generate_job(method, params, update=False)

    @conveyor.decorator.run_job()
    def wifi_connect(self, path, password):
        method = "wifi_connect"
        params = {
            "path": path,
            "password": password
        }
        return self._client_thread.generate_job(method, params, update=False)

    @conveyor.decorator.run_job()
    def wifi_disconnect(self):
        method = "wifi_disconnect"
        params = {}
        return self._client_thread.generate_job(method, params, update=False)

    @conveyor.decorator.run_job()
    def wifi_forget(self, path):
        method = "wifi_forget"
        params = {
            "path": path}
        return self._client_thread.generate_job(method, params, update=False)

    @conveyor.decorator.run_job()
    def wifi_disable(self):
        method = "wifi_disable"
        params = {}
        return self._client_thread.generate_job(method, params, update=False)

    @conveyor.decorator.run_job()
    def wifi_enable(self):
        method = "wifi_enable"
        params = {}
        return self._client_thread.generate_job(method, params, update=False)

    @conveyor.decorator.run_job()
    def acknowledge_error(self, error_id):
        method = "acknowledged"
        params = {
            "error_id": error_id }
        return self._client_thread.generate_job(method, params)


    # ****
    # These functions will start actual processes on the kaiten server
    # They all take a kwarg for requested_id, which allows conveyor to to
    # request ids in advance before actually starting the process.
    # ****

    @conveyor.decorator.run_job()
    def _legacy_do_firmware_upload(self, filepath, requested_id=None):
        """
        Start a firmware upload process, on a file that has already been fully
        transferred to the bot
        """
        params = {
                 "filepath": filepath,
        }
        if requested_id != None:
            params.update({"requested_id": requested_id})
        job = self._client_thread.generate_job("brooklyn_upload", params)
        return job

    @conveyor.decorator.run_job()
    def _do_firmware_upload(self, filepath, requested_id=None):
        """
        Starst the actual firmware upload process
        """
        params = {
                 "filepath": filepath,
                 "transfer_wait": True,
        }
        if requested_id != None:
            params.update({"requested_id": requested_id})
        job = self._client_thread.generate_job("brooklyn_upload", params)
        return job

    @conveyor.decorator.run_job()
    def _do_load_print_tool(self, tool_index, requested_id=None):
        """
        Start change toolhead process
        """
        method = "load_print_tool"
        params = {
            "index" : tool_index,
        }
        if requested_id != None:
            params.update({"requested_id": requested_id})
        return self._client_thread.generate_job(method, params)

    @conveyor.decorator.run_job()
    def _do_load_filament(self, tool_index, temperature, requested_id=None):
        """
        Starts the load filament process
        """
        method = "load_filament"
        params = {
            "tool_index": tool_index,
            "temperature_settings": temperature,
        }
        if requested_id != None:
            params.update({"requested_id": requested_id})
        return self._client_thread.generate_job(method, params)

    @conveyor.decorator.run_job()
    def _do_unload_filament(self, tool_index, temperature, requested_id=None):
        """
        Starts the unload filament process
        """
        method = "unload_filament"
        params = {
            "tool_index": tool_index,
            "temperature_settings": temperature,
        }
        if requested_id != None:
            params.update({"requested_id": requested_id})
        return self._client_thread.generate_job(method, params)

    @conveyor.decorator.run_job()
    def _do_streaming_print(self, layout_id, remotepath, build_name, requested_id=None):
        """
        Starts a streaming print process
        """
        method = "streaming_print"
        params = {
            'layout_id' : layout_id,
            'filepath' : os.path.basename(remotepath),
            'build_name' : build_name
        }
        print(os.path.basename(remotepath))
        if requested_id is not None:
            params.update({"requested_id" : requested_id})
        return self._client_thread.generate_job(method, params)

    @conveyor.decorator.run_job()
    def _do_print(self, remotepath, username, requested_id=None):
        """
        Starts the actual print process.
        """
        method = "print"
        params = {
            "filepath": os.path.basename(remotepath),
            "username": username,
        }
        self._log.info("Sending print with username: %s", username)
        if requested_id != None:
            params.update({"requested_id": requested_id})
        return self._client_thread.generate_job(method, params, False)

    @conveyor.decorator.run_job()
    def _do_reset_to_factory(self, username, requested_id=None):
        """
        Starts the reset to factory process
        """
        method = "reset_to_factory"
        params = {
            "username": username,
        }
        if requested_id != None:
            params.update({"requested_id": requested_id})
        return self._client_thread.generate_job(method, params)

    @conveyor.decorator.run_job()
    def _do_preheat(self, temperature_settings, wait_till_heated, requested_id=None):
        """
        Starts the preheat process
        """
        method = "preheat"
        params = {
            'temperature_settings': temperature_settings,
            'wait_till_heated': wait_till_heated,
        }
        if requested_id != None:
            params.update({"requested_id": requested_id})
        return self._client_thread.generate_job(method, params)

    @conveyor.decorator.run_job()
    def _do_zip_logs(self, zip_path, requested_id=None):
        method = 'zip_logs'
        params = {
            'zip_path': birdwing_join('/home', zip_path),
        }
        if requested_id != None:
            params.update({"requested_id": requested_id})
        return self._client_thread.generate_job(method, params)

class _BirdWingClient(conveyor.stoppable.StoppableThread):

    def __init__(self, birdwing_machine, address):
        conveyor.stoppable.StoppableThread.__init__(self)
        self._log = conveyor.log.getlogger(self)
        self._birdwing_machine = birdwing_machine
        self._address = address
        # TODO: Debug why connections take so long
        connection = self._address.create_connection()
        self._jsonrpc = conveyor.jsonrpc.JsonRpc(connection, connection)
        self._transfer = _BirdWingTransfer(self._jsonrpc)
        self._generic_args = {'username': 'conveyor'}

        class Parser(HTMLParser.HTMLParser):
            """
            Parses HTML data.  Used for the list functionality.
            """
            _starting_dir = False
            files = []
            def handle_starttag(self, tag, attr):
                """
                Parses the filepath out of the various hyperlink tags
                """
                # All files are marked with as links
                # Apache walks the tree in a very specific way.  Once it
                # sends the root, we can assume the files will follow
                if self._starting_dir and 'a' == tag:
                    self.files.append(attr[0][1])
            def handle_endtag(self, tag):
                """
                Parses the end of the tags.  We have no use for these
                """
                pass
            def handle_data(self, data):
                """
                Handles the regular data nested inside tags.  While it
                contains filepath data, its truncated, so we cant use it.
                """
                if 'Parent Directory' == data:
                    # Ignore Parent Directory and anything that comes before it
                    self._starting_dir = True
            def reset_parser(self):
                self.reset()
                self._starting_dir = False
                self.files = []

        self._html_parser = Parser()
        self._birdwing_code = None
        # Common client_id for all auth functions
        self.client_id = "MakerWare"

    def get_authentication_code(self, client_secret, username, thingiverse_token):
        answer_code = self.get_answer_code(client_secret, username, thingiverse_token)
        return self.loop_for_birdwing_code(answer_code, client_secret)

    def authenticate_connection(self, client_secret, birdwing_code):
        self._client_secret = client_secret
        self._birdwing_code = birdwing_code
        birdwing_token = self.get_birdwing_token(self._client_secret,
            self._birdwing_code)
        params = {
            "access_token": birdwing_token,
        }
        authenticate_job = self._jsonrpc.request("authenticate", params)
        self._log.info("Authenticating connection")
        conveyor.util.execute_job(authenticate_job, 6.0)

    def do_auth_get(self, response_type, **kwargs):
        remoteargs = ["/auth?response_type=" + response_type]
        for key in kwargs:
            remoteargs.append(key + '=' + kwargs[key])
        remotepath = '&'.join(remoteargs)
        return self.do_get(remotepath, port=443)

    def loop_for_birdwing_code(self, answer_code, client_secret):
        answer = {}
        start = datetime.datetime.now()
        timeout = 120 # seconds
        while (not answer or answer['answer'] == 'pending' and
               (datetime.datetime.now() - start).total_seconds > timeout):
            response = self.do_auth_get(
                'answer',
                client_id = self.client_id,
                client_secret = client_secret,
                answer_code = answer_code,
            )
            answer = json.loads(response)
        if answer.get("answer", None) == "accepted":
            return answer['code']
        else:
            self._log.info("Error looping for birdwing access code: %r", answer)
            raise conveyor.error.MachineAuthenticationError

    def send_thingiverse_credentials(self, username, thingiverse_token, birdwing_code,
                                     client_secret):
        response = self.do_auth_get(
            'thingiverse_token',
            client_id = self.client_id,
            client_secret = client_secret,
            username = username,
            thingiverse_token = thingiverse_token,
            auth_code = birdwing_code,
        )
        return response

    def get_answer_code(self, client_secret, username, thingiverse_token):
        """
        Asks the FCGI to generate a birdwing_code using the username and client_secret.
        This code can then be used to request birdwing tokens.
        """
        # The FCGI doesn't like it when usernames have spaces, and windows
        # tends to have spaces in their usernames
        response = self.do_auth_get(
            'code',
            client_id = self.client_id,
            client_secret = client_secret,
            username = username,
            thingiverse_token = thingiverse_token,
        )
        self._log.info("Response from getting BirdwingCode: %s", response)
        token_request = json.loads(response)
        if token_request.get("status", "error") != "ok":
            raise conveyor.error.MachineAuthenticationError
        else:
            return token_request['answer_code']

    def get_birdwing_token(self, client_secret, birdwing_code, context="jsonrpc"):
        """
        Asks the FCGI for an authentic birdwing_token, a onetime use access token
        consumed by kaiten used to authenticate this connection.
        """
        response = self.do_auth_get(
            'token',
            client_id = self.client_id,
            client_secret = client_secret,
            context = context,
            auth_code = birdwing_code,
        )
        self._log.debug("Response from getting BirdwingToken: %s", response)
        token_request = json.loads(response)
        if token_request.get('status', "error") == "success":
            return token_request['access_token']
        else:
            raise conveyor.error.MachineAuthenticationError

    def stop(self):
        try:
            self._jsonrpc.stop()
        except Exception as e:
            self._log.info("Unhandled exception", exc_info=True)

    def run(self):
        def func():
            conveyor.jsonrpc.install(self._jsonrpc, self)
            conveyor.jsonrpc.install(self._jsonrpc, self._transfer)
            try:
                self._jsonrpc.run()
            except Exception as e:
                self._log.info("unhandled exception, socket closed", exc_info=True)
                # We explicitely disconnect here, since we unintentionally
                # errored out (as opposed to an intentional disconnect VIA
                # the command line client)
                self._birdwing_machine.disconnect()
        conveyor.error.guard(self._log, func)

    @jsonrpc()
    def system_notification(self, info):
        self._birdwing_machine.system_notification(info)

    @jsonrpc()
    def error_notification(self,error_id, error, info, details):
        self._birdwing_machine.error_notification(error_id, error, info, details)

    @jsonrpc()
    def network_state_change(self, state):
        self._birdwing_machine.network_state_change(state)

    @jsonrpc()
    def error_acknowledged(self,error_id):
        self._birdwing_machine.error_acknowledged(error_id)

    @jsonrpc()
    def state_notification(self, state_change):
        self._birdwing_machine.state_notification(state_change)

    def do_get(self, remotepath, localpath=None, port=80):
        self._log.debug("Executing get: %s -> %s", remotepath, localpath)
        if port == 443:
            con = httplib.HTTPSConnection(self._address._host, port)
        else:
            con = httplib.HTTPConnection(self._address._host, port)
        remotepath = url_fix(remotepath)
        con.request("GET", remotepath)
        resp = con.getresponse()
        if resp.status != 200:
            msg = resp.read()
            self._log.error('Error %d getting %s, message\n%s'%
                            (resp.status, remotepath, msg))
            raise httplib.HTTPException(resp.status)
        if not localpath:
            return resp.read()
        else:
            with open(localpath, 'wb') as f:
                f.write(resp.read())

    @conveyor.decorator.run_job(None) # No Timeout
    def get(self, localpath, remotepath):
        """
        We encode the type of file into the URL we are getting, so the
        the kaiten server knows what type of file we are getting.
        """
        if isinstance(self._address, conveyor.address.UsbAddress):
            return self._transfer.get(remotepath, localpath)
        job = conveyor.job.Job()
        def runningcallback(job):
            try:
                self.do_get(remotepath, localpath)
            except httplib.HTTPException as e:
                self._log.info("Error connecting to remote server. Errno: %r", e.message)
                job.fail(e.message)
            except Exception as e:
                self._log.info("Unhandled exception", exc_info=True)
                job.fail(str(e))
            else:
                job.end(True)
        job.runningevent.attach(runningcallback)
        return job

    def _do_list(self, remote_dir):
        """
        Gets files belonging to a specific directory by "GET"ting the
        requested directory.

        Apache embeds the filepaths in the data it sends back.  We need
        to use an HTMLParser to get that data.
        """
        self._html_parser.reset_parser()
        self._log.debug("Getting directory contents of %s", remote_dir)
        con = httplib.HTTPConnection("%s:%s" % (self._address._host, 80))
        con.request("GET", remote_dir)
        resp = con.getresponse()
        if resp.status != 200:
            raise httplib.HTTPException(resp.status)
        else:
            self._html_parser.feed(resp.read())
        return self._html_parser.files

    def _list_all_files(self, root, remote_dir, files):
        # Heres our hacky check to see if we're looking a directory
        if remote_dir[-1] == "/":
            for path in self._do_list(remote_dir):
                self._list_all_files(root, birdwing_join(remote_dir, path), files)
        # If its a file, we don't want to "GET" it, we just want to record it
        else:
            files.append(remote_dir)

    @conveyor.decorator.run_job()
    def list(self, remote_dir):
        """
        This function is a bit finicky, since it requires us to be very
        specific with the way we specify directories.  Since the GET command
        is used, we need to make sure we are requesting directory paths,
        otherwise we could start requesting whole files.
        """
        # This is done to make sure we have the trailing "/" at the end,
        # otherwise we could potentially grab whole files accidentally
        if remote_dir[-1] != "/":
            remote_dir = "%s/" % (remote_dir)

        # If machine is connected via USB, ask Kaiten to list remote_dir instead
        if isinstance(self._address, conveyor.address.UsbAddress):
            method = "birdwing_list"
            params = {
                "path": remote_dir}
            return self.generate_job(method, params)

        job = conveyor.job.Job()
        def running_callback(job):
            try:
                self._log.info("Getting files at %s", remote_dir)
                files = []
                self._list_all_files(remote_dir, remote_dir, files)
            except httplib.HTTPException as e:
                self._log.info("Directory listing failed.  Errorno: %r", e.message)
                job.fail(e.message)
            except Exception as e:
                self._log.info("Unhandled Exception", exc_info=True)
                job.fail(e.message)
            else:
                job.end(files)
        job.runningevent.attach(running_callback)
        return job

    @conveyor.decorator.run_job(None, heartbeat_timeout=30.0)
    def json_put(self, local_path, remote_path, parent_job=None):
        """
        USB file upload

        The parent_job parameter is a hack (blame nicholasbishop) to
        send progress events back up to the client. Obviously we need
        to clean this up at some point, because this nested job crap
        is awful.

        chris.moore: Pretty sure the problem is the run_job decorator,
        not nested jobs in general.
        """
        job = self._transfer.put(local_path, remote_path)
        def heartbeat(job):
            parent_job.heartbeat(job.progress)
        if parent_job:
            job.heartbeatevent.attach(heartbeat)
        return job

    def _do_put(self, localpath, remotepath, parent_job=None):
        """HTTP file upload

        The parent_job parameter is a hack (blame nicholasbishop) to
        send progress events back up to the client. Obviously we need
        to clean this up at some point, because this nested job crap
        is awful.

        """

        put_token = self.get_birdwing_token(self._client_secret,
            self._birdwing_code, context="put")
        con = httplib.HTTPConnection("%s:%i" % (self._address._host, 80))
        remotepath = "%s?token=%s" % (remotepath, put_token)
        remotepath = url_fix(remotepath)
        total_length = os.path.getsize(localpath)
        with open(localpath, 'rb') as f:
            class FileWithProgress:
                """Wrapper around file object for job progress heartbeat"""

                def __init__(self, file):
                    self._file = file
                    self._consumed_size = 0

                def __len__(self):
                    return total_length

                def __nonzero__(self):
                    return total_length > 0

                def fileno(self):
                    return self._file.fileno()

                def read(self, size):
                    chunk = self._file.read(size)
                    self._consumed_size += len(chunk)
                    self._update_progress()
                    return chunk

                def _update_progress(self):
                    if parent_job:
                        progress = {
                            'name': 'put',
                            'progress':
                            (self._consumed_size * 100.0) / total_length
                        }
                        parent_job.heartbeat(progress)

            con.request("PUT", remotepath, FileWithProgress(f))
        resp = con.getresponse()
        errcode = resp.status
        if errcode != 200:
            msg = resp.read()
            self._log.error('Received http code %d, message\n%s'%
                            (errcode, msg))
            raise httplib.HTTPException(errcode)

    def put(self, localpath, remotepath, parent_job=None):
        if isinstance(self._address, conveyor.address.UsbAddress):
            return self.json_put(localpath, remotepath, parent_job)
        else:
            return self.http_put(localpath, remotepath, parent_job)

    @conveyor.decorator.run_job(None) # No Timeout
    def http_put(self, localpath, remotepath, parent_job=None):
        job = conveyor.job.Job()
        def runningcallback(job):
            try:
                self._do_put(localpath, remotepath, parent_job)
            except httplib.HTTPException as e:
                self._log.info(
                    "Error uploading file %s to remote server.  Errorno: %r",
                    localpath,
                    e.message)
                job.fail(e.message)
            except Exception as e:
                self._log.info("Unhandled exception", exc_info=True)
                job.fail(False)
            else:
                job.end(True)
        job.runningevent.attach(runningcallback)
        return job

    def generate_job(self, method, params, update=True):
        if update:
            params.update(self._generic_args)
        job = self._jsonrpc.request(method, params)
        return job

class _BirdWingTransfer(object):
    """
    JSON file transfers are complex enough to get their own class
    Maybe someday they can get their own file.
    """
    def __init__(self, jsonrpc):
        self._log = conveyor.log.getlogger(self)
        self._jsonrpc = jsonrpc
        self._transfers = {}
        self._file_id_counter = 0

    def _json_file_id(self):
        # Not thread safe, must be called by a single client thread
        id_int = self._file_id_counter
        self._file_id_counter += 1
        id_bytes = bytearray(3)
        for i in range(3):
            id_int, id_bytes[i] = divmod(id_int, 256)
        id_b64 = base64.b64encode(id_bytes)
        return id_b64

    def put(self, local_path, remote_path, block_size = 32768):
        """ File upload """
        job = conveyor.job.Job(name="json_put")
        # This needs to be assigned here for thread safety issues
        file_id = self._json_file_id()

        def run_job():
            # A generator that yields subjobs to be run, and receives their resuls
            try:
                total_length = os.path.getsize(local_path)
                file = open(local_path, 'rb')
            except:
                job.fail('Could not open %s for reading'% (local_path))
                return
            with file:
                start_time = datetime.datetime.now()
                try:
                    yield self._put_init(remote_path, file_id, block_size, total_length)
                except JsonRpcException as e:
                    if e.code == -32602: # Invalid params
                        self._log.info('put_init with length failed, trying again without it')
                        yield self._put_init(remote_path, file_id, block_size)
                    else:
                        raise
                length = 0
                crc = binascii.crc32('')
                while True:
                    block = file.read(block_size)
                    if len(block) == 0:
                        break
                    yield self._put_raw(block, file_id)
                    crc = binascii.crc32(block, crc)
                    length += len(block)

                    progress = {
                        'name': 'put',
                        'progress': (length * 100.0) / total_length
                    }
                    job.heartbeat(progress)
                    if len(block) < block_size:
                        break
                # Kaiten is running python 3.3, so its crc is a long.  Ours is not.
                real_crc = long(crc)
                if real_crc < 0:
                    real_crc += 2L ** 32
                if not (yield self._put_term(file_id, length, real_crc)):
                    job.fail('File %s corrupted during transfer, aborting'% (local_path))
                    return
                # Calculate and log the transfer rate
                elapsed = datetime.datetime.now() - start_time
                rate = float(length) / elapsed.total_seconds()
                self._log.info("Successfully sent a file at %f bytes/s"% (rate))
                job.end(True)

        runner = run_job()

        def run_subjob(subjob):
            def end(subjob):
                try:
                    next_job = runner.send(subjob.result)
                    run_subjob(next_job)
                except StopIteration:
                    pass
            def fail(subjob):
                try:
                    next_job = runner.throw(JsonRpcException(
                        subjob.failure['code'],
                        subjob.failure['message'],
                        None))
                    run_subjob(next_job)
                except JsonRpcException as e:
                    # TODO: allow other failure messages
                    job.fail(subjob.failure)
                except StopIteration:
                    pass
            subjob.endevent.attach(end)
            subjob.failevent.attach(fail)
            subjob.start()

        # The main jobs start and cancel methods
        def start(job):
            try:
                next_job = runner.next()
                run_subjob(next_job)
            except StopIteration:
                pass

        def cancel(job):
            runner.close()
            # We need to get kaiten to close the file, but we can't wait
            # around for the response from put_term.  We probably should
            # implement a dedication notification for this, but for now:
            term_job = self._put_term(file_id, 0, -1)
            term_job.start()

        job.startevent.attach(start)
        job.cancelevent.attach(cancel)
        return job

    def get(self, remote_path, local_path, block_size = 131072):
        """ Get a file from the bot
            @param remote_path Path on the bot to get (chrooted to /home)
            @param local_path Path to store the file to, or if None,
                   directly return the contents of the file
            @param block_size specify # of bytes per chunk
        """
        job = conveyor.job.Job()
        file_id = self._json_file_id()
        transfer = self.Transfer()
        transfer.job = job
        self._transfers[file_id] = transfer

        def init_fail(init_job):
            """ Handle failure to start a transfer """
            failure = init_job.failure
            del self._transfers[file_id]
            if hasattr(failure, 'get') and failure.get('code') == -32602:
                # Invalid params -> only legacy get supported
                self._log.info("Normal get() failed, trying legacy")
                job.cancelevent.detach(cancel_handle)
                self._legacy_get(remote_path, local_path, job,
                                 file_id, transfer.fileio)
            else:
                transfer.close()
                job.fail(init_job.failure)

        def start(job):
            try:
                transfer.fileio = open(local_path, 'wb')
            except:
                job.fail('Could not open %s for writing'% (local_path))
                raise
            init_job = self._get_init(remote_path, file_id, block_size)
            init_job.failevent.attach(init_fail)
            init_job.start()
            transfer.start_time = datetime.datetime.now()

        def cancel(job):
            # This will cause the next call to get_raw to respond with an
            # error code, which will get kaiten to stop and close the file
            transfer.error = JsonRpcException(40, "Transfer cancelled", None)
            transfer.close()

        job.startevent.attach(start)
        cancel_handle = job.cancelevent.attach(cancel)
        job._machine_func_name = 'get'
        return job

    def _legacy_get(self, remote_path, local_path, job, file_id, fileio):
        """
        If the standard get was found to be unsupported, continue from where
        we left off, but with a legacy get.
        """
        block_size = 3012
        class S(object):
            def __init__(self, fileio):
                self.file_write = fileio
                self.last_block_length = 0
                self.idx = 0
                self.crc = binascii.crc32('')
                self.start_time = datetime.datetime.now()
        s = S(fileio)

        # Functions to call the three subjobs
        def start_init():
            def init_end(init_job):
                if init_job.result: # Remote file opened sucessfully
                    start_get()
                else:
                    job.fail('Could not open %s for reading'% (remote_path))
            def init_fail(init_job):
                job.fail(init_job.failure)
            init_job = self._legacy_get_init(remote_path, file_id, block_size)
            init_job.endevent.attach(init_end)
            init_job.failevent.attach(init_fail)
            init_job.start()

        def start_get():
            def get_end(get_job):
                job.heartbeat(s.idx)
                if None is get_job.result:
                    job.fail('Device has dropped transfer of %s'% remote_path)
                    return
                block_b64 = get_job.result
                try:
                    block = base64.b64decode(block_b64)
                except TypeError:
                    self._log.error('Failed to convert block "%s"'% block_b64)
                    job.fail('Failed to convert block of length %d'% len(block_b64))
                    raise
                if (len(block) > 0):
                    s.file_write.write(block)
                    s.crc = binascii.crc32(block, s.crc)
                    s.idx += 1
                    s.last_block_length = len(block)
                if (len(block) < block_size):
                    start_term()
                else:
                    start_get()
            def get_fail(get_job):
                job.fail(get_job.failure)
            get_job = self._legacy_get_base64(file_id, s.idx)
            get_job.endevent.attach(get_end)
            get_job.failevent.attach(get_fail)
            get_job.start()

        def start_term():
            def term_end(term_job):
                remote_crc = term_job.result['crc']
                # Kaiten is running 3.3, so its crc is a long.  Ours is not.
                real_crc = long(s.crc)
                if real_crc < 0:
                    real_crc += 2L ** 32
                if remote_crc == real_crc:
                    job.end(True)
                    # Calculate and log the transfer rate
                    elapsed = datetime.datetime.now() - s.start_time
                    length = (s.idx - 1) * block_size + s.last_block_length
                    rate = float(length) / elapsed.total_seconds()
                    self._log.info("Received a file at %f bytes/s", rate)
                else:
                    self._log.info("Failed to receive a file, crcs: %d, %d",
                                   remote_crc, real_crc)
                    job.fail('File %s corrupted during transfer, aborting'%
                              (local_path))
            def term_fail(term_job):
                job.fail(term_job.failure)
            s.file_write.close()
            term_job = self._legacy_get_term(file_id)
            term_job.endevent.attach(term_end)
            term_job.failevent.attach(term_fail)
            term_job.start()

        def cancel(job):
            term_job = self._json_get_term(file_id)
            term_job.start()

        job.cancelevent.attach(cancel)
        start_init()

    class Transfer(object):
        """ Keep track of each individual incoming transfer """
        def __init__(self):
            self.fileio = None
            self.closed = False
            self.error = None
            self.crc = binascii.crc32('')
            self.start_time = None
            self.job = None
            self.written = 0

        def write(self, data):
            if self.closed: return
            try:
                self.fileio.write(data)
                self.crc = binascii.crc32(data, self.crc)
                self.written += len(data)
            except Exception as e:
                if None is not self.error: self.error = e
                try:
                    self.close()
                except Exception as e:
                    pass
                # TODO: This is the least helpful failure message
                self.job.fail('Write error during transfer')

        def write_raw(self, length):
            while length > 0:
                data = yield
                if length < len(data):
                    self.write(data[0:length])
                    yield data[length:]
                else:
                    self.write(data)
                    length -= len(data)

        def close(self):
            if not self.closed:
                try:
                    self.fileio.close()
                except:
                    pass
            self.closed = True

    ###########################################
    # Low level JSON file transfer BOT -> HOST
    ###########################################

    @jsonrpc()
    def get_raw(self, id, length):
        """ Invoked directly by the birdwing machine """
        if id not in self._transfers:
            # Still need something to parse in the non-jsonrpc data
            transfer = self.Transfer()
            transfer.closed = True
            self._jsonrpc.set_raw_handler(transfer.write_raw(length))
            raise JsonRpcException(37, 'Unknown file_id', file_id)
        transfer = self._transfers[id]
        self._jsonrpc.set_raw_handler(transfer.write_raw(length))
        if transfer.error:
            raise transfer.error
        else:
            transfer.job.heartbeat(transfer.written)
        return True

    @jsonrpc()
    def get_term(self, id, crc):
        """ Invoked directly by the birdwing machine """
        if id not in self._transfers:
            raise JsonRpcException(37, 'Unknown file_id', file_id)
        transfer = self._transfers[id]
        del self._transfers[id]
        # Kaiten is running python 3.3, so its crc is a long.  Ours is not.
        real_crc = long(transfer.crc)
        if real_crc < 0:
            real_crc += 2L ** 32
        if crc == real_crc:
            transfer.job.end(True)
            # Calculate and log the transfer rate
            elapsed = datetime.datetime.now() - transfer.start_time
            rate = float(transfer.written) / elapsed.total_seconds()
            self._log.info("Successfully received a file at %f bytes/s", rate)
            transfer.close()
        else:
            transfer.job.fail('File %s corrupted during transfer'% remote_path)

    ###########################################
    # Low level JSON file transfer HOST -> BOT
    ###########################################

    def _put_init(self, file_path, file_id, block_size, length=None):
        method = 'put_init'
        params = {
            'file_path' : file_path,
            'file_id' : file_id,
            'block_size' : block_size,
        }
        if None is not length:
            params['length'] = length
        job = self._jsonrpc.request(method, params)
        return job

    def _put_raw(self, block, file_id):
        method = 'put_raw'
        params = [ file_id, len(block) ]
        job = self._jsonrpc.request(method, params, block)
        return job

    def _put_term(self, file_id, length, crc):
        method = 'put_term'
        params = {
            'file_id' : file_id,
            'length' : length,
            'crc' : crc,
        }
        job = self._jsonrpc.request(method, params)
        return job

    def _get_init(self, file_path, file_id, block_size):
        method = 'get_init'
        params = {
            'file_path' : file_path,
            'file_id' : file_id,
            'block_size' : block_size,
            'do_raw' : True,
        }
        job = self._jsonrpc.request(method, params)
        return job

    def _legacy_get_init(self, file_path, file_id, block_size):
        method = 'get_init'
        params = {
            'file_path' : file_path,
            'file_id' : file_id,
            'block_size' : block_size,
        }
        job = self._jsonrpc.request(method, params)
        return job

    def _legacy_get_base64(self, file_id, idx):
        method = 'get'
        params = {
            'file_id' : file_id,
            'idx' : idx,
        }
        job = self._jsonrpc.request(method, params)
        return job

    def _legacy_get_term(self, file_id):
        method = 'get_term'
        params = {
            'file_id' : file_id,
        }
        job = self._jsonrpc.request(method, params)
        return job


class _BirdWingProfile(conveyor.machine.Profile):

    @staticmethod
    def _create(name, driver, json_profile):
        xsize = json_profile.values['axes']['X']['platform_length']
        ysize = json_profile.values['axes']['Y']['platform_length']
        zsize = json_profile.values['axes']['Z']['platform_length']
        can_print = True
        has_heated_platform = 0 != len(json_profile.values['heated_platforms'])
        number_of_tools = len(json_profile.values['tools'])
        profile = _BirdWingProfile(
            name, driver, xsize, ysize, zsize, json_profile, can_print,
            has_heated_platform, number_of_tools)
        return profile

    def __init__(self, name, driver, xsize, ysize, zsize, json_profile,
            can_print, has_heated_platform, number_of_tools):
        conveyor.machine.Profile.__init__(
            self, name, driver, xsize, ysize, zsize, json_profile, can_print,
            has_heated_platform, number_of_tools)
        self.start_x = 0
        self.start_y = 0
        self.start_z = 0

    def _check_port(self, port):
        result = port.machine_type == self.json_profile.values['type']
        return result
