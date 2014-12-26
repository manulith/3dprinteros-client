# vim:ai:et:ff=unix:fileencoding=utf-8:sw=4:ts=4:
# conveyor/src/main/python/conveyor/stoppable.py
#
# conveyor - Printing dispatch engine for 3D objects and their friends.
# Copyright 2013 MakerBot Industries, LLC
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

import datetime
import threading
import socket
import json
import struct
import errno
import sys
import threading
import time
import random
import select

import conveyor.machine.port.network
import conveyor.stoppable
import conveyor.util

class NetworkedMachineDetector(conveyor.stoppable.StoppableThread):

    _instance = None

    @staticmethod
    def get_instance():
        if None is NetworkedMachineDetector._instance:
            NetworkedMachineDetector._instance = NetworkedMachineDetector()
        return NetworkedMachineDetector._instance

    def __init__(self):
        """
        TODO: This class needs a rename to BirdwingManagerё
        Manager that manages connections to birdwing machines.  Both Ethernet
        AND USB machines need additional logic (such as constant pings to make sure
        they are still up and running) to manager their connections and make
        sure they don't get into a bad state.  This class does that.
        """
        conveyor.stoppable.StoppableThread.__init__(self)
        self._log = conveyor.log.getlogger(self)
        self._interval = 3
        # For waiting
        self._wait_condition = threading.Condition()
        # Ping condition for iterating through all connections
        self.ping_condition = threading.Condition()
        self.detector_thread = None
        self.port_attached = conveyor.event.Event('port_attached') # Argument is a port
        self.port_detached = conveyor.event.Event('port_detached') # Argument is a machine_name
        self.port_attached.attach(self._port_attached)
        self.port_detached.attach(self._port_detached)
        self._discovered_ports = {}
        self._machines = set([])

        # Ethernet Logic
        self._to_add_condition = threading.Condition()
        self._to_add = set([])
        self._to_remove_condition = threading.Condition()
        self._to_remove = set([])

        # USB Logic
        # Objects can take this condition so they can manipulate the various
        # sets and guarantee their modifications take place before they continue
        self.usb_check_condition = threading.Condition()
        self._usb_hotplugs = set([])
        self._usb_to_add_condition = threading.Condition()
        self._usb_to_add = set([])
        self._usb_to_remove_condition = threading.Condition()
        self._usb_to_remove = set([])

        self._stop = False

        self._firmware_upload_jobs = {}

    def register_firmware_upload_job(self, job):
        """
        Registers a firmware upload job.  This job is saved, and injected
        into the machine with the same hash upon reconnet. We can only
        have one firmware upload job at the same time, so we use the machine
        hash.
        """
        self._firmware_upload_jobs[job.machine.get_port().machine_hash] = job

    def get_firmware_upload_job(self, machine):
        """
        Sets the firmware upload job for this machine.

        TODO: This shouldn't care if there is a USB or network connection
        """
        machine_hash = machine.get_port().machine_hash
        return self._firmware_upload_jobs.pop(machine_hash)

    def register_usb_hotplug(self, machine):
        self._log.info("Added to hotplug list\n%r", machine.get_info())
        with self._usb_to_add_condition:
            self._usb_to_add.add(machine)

    def remove_usb_hotplug(self, machine):
        self._log.info("Removed from hotplug list\n%r", machine.get_info())
        with self._usb_to_remove_condition:
            self._usb_to_remove.add(machine)

    def check_usb_hotplugs(self):
        """
        This will test all machines to see which USB devices are fully up
        (i.e. kaiten is running properly).  If a ping returns correctly, we
        know the machine is up, and we can being communicating with it.
        """
        with self.usb_check_condition:
            with self._usb_to_add_condition:
                self._usb_hotplugs = self._usb_hotplugs.union(self._usb_to_add)
                self._usb_to_add.clear()

            with self._usb_to_remove_condition:
                self._usb_hotplugs = self._usb_hotplugs.difference(
                    self._usb_to_remove)
                self._usb_to_remove.clear()

            for machine in self._usb_hotplugs:
                try:
                    self._ping_machine(machine)
                except Exception as e:
                    # Exceptions mean this device is not ready to connect
                    pass
                else:
                    self._log.info("USB Machine responded, ready to connect")
                    # Add it to the store of machines that need to be "ping'd"
                    # Notify clients that this machine is usable.  This should
                    # happen before we actually connect, to mimick the actual
                    # course of events
                    self.port_attached(machine.get_port())
                    # Once the ping command returns, we can assume the machine
                    # is connected and "sync it"
                    # The machine adds/removes itself from the manager
                    machine.sync_usb_machine()

    def _ping_machine(self, machine):
        machine.ping()

    def register_networked_machine(self, machine):
        self._log.info("Adding %r to network machine detector",
            machine.name)
        with self._to_add_condition:
            self._to_add.add(machine)

    def remove_networked_machine(self, machine):
        self._log.info("Removing %r from the network machine detector",
            machine.name)
        with self._to_remove_condition:
            self._to_remove.add(machine)

    def ping_machines(self):
        with self.ping_condition:
            with self._to_add_condition:
                self._machines = self._machines.union(self._to_add)
                self._to_add.clear()
            with self._to_remove_condition:
                self._machines = self._machines.difference(self._to_remove)
                self._to_remove.clear()

            for machine in self._machines:
                print("PING MACHINES:" + str(machine))
                # Added the stop condition to prevent this thread from stopping
                # service shutdown on Windows.
                if machine.should_ping() and not self._stop:
                    try:
                        self._ping_machine(machine)
                    except Exception as e:
                        self._log.info("{0}: Ping request error".format(machine.name))
                        machine.increment_disconnect_count()
                        if machine.should_disconnect():
                            self._log.info("Machine has reached its disconnect "
                                           "limit, disconnected {0}".format(
                                           machine.name))
                            try:
                                machine.disconnect()
                            except Exception as e2:
                                # Don't allow a failure in disconnect to
                                # kill this thread
                                self._log.error('disconnect error', exc_info=True)

                    else:
                        machine.reset_disconnect_count()

    def stop(self):
        self._stop = True
        if self.detector_thread:
            self.detector_thread.stop()
        with self._wait_condition:
            self._wait_condition.notify_all()

    def run(self):
        if not self.detector_thread:
            self._log.debug("starting detection thread")
            try:
                self.detector_thread = BotDiscoverer(self)
                self.detector_thread.start()
            except Exception as e:
                self._log.info("Error detecting machines", exc_info=True)
        while not self._stop:
            try:
                self.check_usb_hotplugs()
                self.ping_machines()
            except Exception as e:
                self._log.info("Error pinging machines", exc_info=True)
                raise
            with self._wait_condition:
                self._wait_condition.wait(self._interval)

    def _port_attached(self, port):
        print("_port_attached" + str(port))
        self._discovered_ports[port.get_machine_hash()] = object()

    def _port_detached(self, port):
        self._log.info("detaching %s", port)
        self._discovered_ports.pop(port.get_machine_hash())

    def port_already_discovered(self, indata):
        machine_name = conveyor.machine.port.network.NetworkPort.create_machine_name(
            indata['ip'], indata['port'], indata["vid"],
            indata["pid"], indata["iserial"])
        machine_hash = conveyor.machine.port.network.NetworkPort.create_machine_hash(machine_name)
        return machine_hash in self._discovered_ports

    def clear_bots_for_rescan(self):
        # disconnect all unauthenticated bots to be rescanned
        for machine in self._machines:
            print("Clear_bots_for_rescan" + str(machine))
            if not machine.authenticated:
                machine.disconnect()

class Broadcaster(threading.Thread):
    """
    This is responsible for all bot detection activity on a single interface.
    """
    def __init__(self, ip_address):
        threading.Thread.__init__(self)
        self._log = conveyor.log.getlogger(self)

        self._wait_condition = threading.Condition()

        broadcast_dict = {"command" : "broadcast"}
        self.broadcast_message = json.dumps(broadcast_dict)
        self.broadcastPort = 12307
        self.ip_address = ip_address

        # This does not get used and I am sad that we need it
        self.dummyPort = 12309

        try:
            self.broadcastSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.broadcastSocket.bind((self.ip_address, self.dummyPort))
            self.broadcastSocket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        except Exception as ex:
            self._log.debug("ERROR: error creating broadcast sockets", exc_info=True)
            raise

        # Make sure that we send immediately once when conveyor starts up
        self._send_delay = datetime.timedelta(0)
        self.last_broadcast_time = None

        self._stop = False

        # TODO: This _should_ default to False, but first we have to implement
        # per client scan mode enable/disable
        self.scan_mode = False

        # Be sure to list the lower bound first
        self.remote_broadcast_scan_mode_bounds    = (1400.0, 1600.0)
        self.local_broadcast_scan_mode_bounds     = (1000.0, 1200.0)
        self.remote_broadcast_passive_mode_bounds = (120000.0, 121000.0)
        self.local_broadcast_passive_mode_bounds  = (100000.0, 101000.0)

    def run(self):
        self._log.debug("starting broadcast loop")
        while not self._stop:
            self.do_wait()
            if self._stop: break
            self._log.debug("Sending broadcast on %s", self.ip_address)
            try:
                self.broadcastSocket.sendto(self.broadcast_message,
                                            ('255.255.255.255 ', self.broadcastPort))
                self.recalculate_delay(True)
                self.last_broadcast_time = datetime.datetime.now()
            except Exception as ex:
                self._log.info("ERROR: Broadcasting on %s", self.ip_address, exc_info=True)
                self.stop()

        self._log.info("broadcaster stopped")
        self.broadcastSocket.shutdown(socket.SHUT_RDWR)
        self.broadcastSocket.close()

    def stop(self):
        self._log.info("stopping broadcaster")
        self._stop = True
        with self._wait_condition:
           self._wait_condition.notify_all()

    def enter_active_scan_mode(self):
        self.scan_mode = True
        self.recalculate_delay(False)
        with self._wait_condition:
            self._wait_condition.notify_all()

    def end_active_scan_mode(self):
        self.scan_mode = False

    def recalculate_delay(self, local_broadcast):
        if self.scan_mode:
            if local_broadcast:
                bounds = self.local_broadcast_scan_mode_bounds
            else:
                bounds = self.remote_broadcast_scan_mode_bounds
        else:
            if local_broadcast:
                bounds = self.local_broadcast_passive_mode_bounds
            else:
                bounds = self.remote_broadcast_passive_mode_bounds
        self._send_delay = datetime.timedelta(milliseconds=random.randrange(*bounds))

    def do_wait(self):
        if None is self.last_broadcast_time: return
        while not self._stop:
            next_send = self.last_broadcast_time + self._send_delay
            now = datetime.datetime.now()
            if next_send < now: break
            delay = (next_send - now).total_seconds()
            with self._wait_condition:
                self._wait_condition.wait(delay)

class BroadcastListener(threading.Thread):
    """
    Listen for broadcasts from other conveyor instances
    """
    def __init__(self, broadcasters):
        threading.Thread.__init__(self)
        self._stop = False
        self._broadcasters =  broadcasters
        self._log = conveyor.log.getlogger(self)

        # Context addresses as integers for fast subnet_dist computation
        self._int_addrs = [self.get_int_addr(ctx.ip_address) for ctx in self._broadcasters]

        self.broadcastPort = 12307

        self.broadcastListenerSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.broadcastListenerSocket.bind(('0.0.0.0', self.broadcastPort ))
        self.broadcastListenerSocket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    @staticmethod
    def get_int_addr(addr):
        """
        Convert an IPv4 to a integer so we can compute the subnet distance
        """
        return struct.unpack(b'>I',socket.inet_aton(addr))[0]

    @staticmethod
    def subnet_dist(x, y):
        """
        Compute the subnet distance between two addresses that have been
        converted to integers.  (The subnet distance is the size of the
        smallest subnet that can contain both addresses, where "size" means
        the base 2 log of the number of addresses in the subnet.)
        """
        # floor(log_base_2(bitwise_xor(x, y)))
        return ([0]+[z+1 for z in xrange(32) if (1<<z) <= (x^y)])[-1]

    def run(self):
        self._log.debug("starting BroadcastListener")
        while  not self._stop:
            self._int_addrs = [self.get_int_addr(ctx.ip_address) for ctx in self._broadcasters]

            is_readable = [self.broadcastListenerSocket]
            is_writable = []
            is_error = []
            # TODO: replace the timeout with one end of an os.pipe(), write to the
            # other end when we stop.  Until then, DO NOT decrease the timeout.
            r, w, e = select.select(is_readable, is_writable, is_error, 3.0)
            if not r: continue
            try:
                data, addr = self.broadcastListenerSocket.recvfrom(1024)
                # If this did not come directly from us, we defer all broadcasters
                # which _must_ be on the same subnet as the sender.  Assuming that
                # one broadcaster X must be on the same subnet as the sender Y, we
                # know that all broadcasters with a subnet distance to Y less than
                # that of X to Y must all be on the same subnet.  So we defer all
                # broadcasters that share the minimum distance.
                # If the broadcast did come from us, defer nothing.
                int_addr = self.get_int_addr(addr[0])
                #we don't have anty network interfaces broadcasting
                if not self._int_addrs: continue
                dist_list = [self.subnet_dist(int_addr, x) for x in self._int_addrs]
                min_dist = min(dist_list)
                if min_dist == 0: continue  # Broadcast came from us
                for ctx, dist in zip(self._broadcasters, dist_list):
                    if dist != min_dist: continue
                    self._log.debug("bcast on %s deferring %s", addr[0], ctx.ip_address)
                    ctx.recalculate_delay(False)
                    ctx.last_broadcast_time = datetime.datetime.now()
            except Exception as ex:
                self._log.info("ERROR: listening for others broadcasting", exc_info=True)
                # TODO: should we stop our broadcasters if we cannot listen?
                self.stop()
        self._log.info("broadcast listener stopped")


    def stop(self):
        self._stop = True


class Listener(threading.Thread):
    """
    Listen for response broadcasts from bots
    """
    def __init__(self, detector):
        threading.Thread.__init__(self)

        self.listenPort = 12308
        self._detector = detector

        self.listenSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.listenSocket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.listenPort.settimeout(3)
        self.listenSocket.bind(('0.0.0.0',  self.listenPort))

        self._stop = False
        self._log = conveyor.log.getlogger(self)

    def run(self):
        self._log.debug("starting listen loop")
        print ("Starting Listener")
        while not self._stop:
            #is_readable = [self.listenSocket]
            #is_writable = []
            #is_error = []
            # print ("pre select")
            # r, w, e = select.select(is_readable, is_writable, is_error, 3.0)
            # print ("post select")
            print("Receiving")
            try:
                print("Run")
                data, addr = self.listenSocket.recvfrom(1024)
                self._log.debug("received message: %s", data)
                print("!!!received message:" + data)
                self._evalresponse(data, addr)
            except socket.error as e:
                print("!!!error listening:" + str(e))
                self._log.info("ERROR: receiving from listen socket")
                #TODO: need to pass error up the stack so we can retry again.
        print ("Stop Listener")
        self._log.info("listener stopped")

    @staticmethod
    def _parse_multicast_response(data):
        """
        We expect a json serializable dict as a response
        The dict will have at least:
            {
                ip: <str>,
                port: 9999,
                machine_type: tinkerbell|platypus|moose
                machine_name: <str>
            }
        """
        data_dict = json.loads(data)
        return data_dict

    def _evalresponse(self, data, server):
        """
        #AnotherConveyorRaceCondition: This is what seemingly happens:
            * Get UDP response
            * Machine turns off
            * Remove machine from list of ports
            * Process UDP response
            * Try to connect
            * Fail to make a connection
        """
        print("_evalresponse")
        try:
            data = self._parse_multicast_response(data)
            if not self._detector.port_already_discovered(data):
                newport = conveyor.machine.port.network.NetworkPort(data)
                newport.disconnected_callbacks.append(self._detector.port_detached)
                self._detector.port_attached(newport)
            else:
                self._log.debug("already know about %s", data)
        except Exception as e:
            # Logging here could potentially be too spammy...for now
            pass

    def stop(self):
        self._stop = True

class BroadcastManager(threading.Thread):

    def __init__(self,broadcasters):
        threading.Thread.__init__(self)
        self._log = conveyor.log.getlogger(self)
        #self._detector = detector
        #self._broadcasters = []

        self._broadcasters = broadcasters
        self._ips = self.get_ip_addresses()
        self._log.info("BotDiscoverer will search on: " + ", ".join(self._ips))
        self._stop = False
        self._wait_condition = threading.Condition()
        self._delay = 5

    def get_ip_addresses(self):
        try:
            ips = socket.gethostbyname_ex(socket.gethostname())
            return set(ips[2])
        except Exception as e:
            self._log.debug("ERROR: error getting ip addresses", exc_info=True)

    def run(self):
         while not self._stop:
            self._ips = self.get_ip_addresses()

            current_bcast_ips = set([broadcaster.ip_address for broadcaster in self._broadcasters])

            new_ips_for_bcast = self._ips - current_bcast_ips
            for new_ip in new_ips_for_bcast:
                self._log.info("found new interface %s ", new_ip)
            try:
                    broadcaster_to_add = Broadcaster(new_ip)
                    broadcaster_to_add.start()
                    self._broadcasters.append(broadcaster_to_add)
            except Exception as ex:
                    self._log.info("ERROR: error creating broadcaster for %s", new_ip, exc_info=True)

            ips_to_remove = current_bcast_ips - self._ips
            broadcasters_to_remove = [broadcaster for broadcaster in self._broadcasters if broadcaster.ip_address in ips_to_remove]
            for broadcaster in broadcasters_to_remove:
                self._log.info("removing interface %s ", broadcaster.ip_address)
                self._broadcasters.remove(broadcaster)
                broadcaster.stop()
            self.do_wait()

         self._log.info("broadcast manager stopped")

    def stop(self):
        self._log.info("stopping broadcaster")
        self._stop = True
        with self._wait_condition:
             self._wait_condition.notify_all()
        self._log.info("stopping all broadcasters")
        for broadcaster in self._broadcasters:
             broadcaster.stop()


    def enter_active_scan_mode(self):
        for broadcaster in self._broadcasters:
             broadcaster.enter_active_scan_mode()

    def end_active_scan_mode(self):
        for broadcaster in self._broadcasters:
             broadcaster.end_active_scan_mode()

    def do_wait(self):
        with self._wait_condition:
             self._wait_condition.wait(self._delay)

class BotDiscoverer():
    """
    Find all network interfaces and create a BroadcastContext for bot
    discovery on each interface.
    """
    def __init__(self, detector):
        self._log = conveyor.log.getlogger(self)
        self._detector = detector
        self._broadcasters = []

    def start(self):

        self._listener_thread = Listener(self._detector)
        self._listener_thread.start()

        try:
            self._broadcast_manager_thread = BroadcastManager(self._broadcasters)
            self._broadcast_manager_thread.start()
        except Exception as e:
            self._log.debug("ERROR: error starting broadcast manager", exc_info=True)

        self._broadcast_listener_thread = BroadcastListener(self._broadcasters)
        self._broadcast_listener_thread.start()

    def stop(self):
        self._listener_thread.stop()
        self._broadcast_listener_thread.stop()
        self._broadcast_manager_thread.stop()

    def enter_active_scan_mode(self):
        self._broadcast_manager_thread.enter_active_scan_mode()

    def end_active_scan_mode(self):
        self._broadcast_manager_thread.end_active_scan_mode()
