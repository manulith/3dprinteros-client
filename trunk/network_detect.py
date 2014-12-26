import time
import json
import socket
import logging
import threading

import config

class NetBroadcastScanner(threading.Thread):

    LISTEN_TIMEOUT = 3
    RETRIES = 1
    RETRY_TIMEOUT = 0.1

    def __init__(self, profile):
        self.logger = logging.getLogger('app.' + __name__)
        self.profile = profile
        network_profile = profile['network_detect']
        self.broadcast_port = network_profile.get('broadcast_port', None)
        self.listen_port = network_profile.get('listen_port', None)
        self.send_port = network_profile.get('sender_port', None)
        self.init_message(network_profile)
        self.response_addr_data_dict = {}
        self.discovered_printers = []
        self.module_already_imported = False
        self.printer_module = __import__(self.profile['driver'])
        super(NetBroadcastScanner, self).__init__()

    def check_profile(self):
        if not (self.broadcast_port and self.listen_port and self.message):
            error = "Error in config file. Section network_detect of profile: " + str(self.profile)
            self.logger.critical(error)
            raise RuntimeError(error)

    def init_message(self, network_profile):
        message = network_profile.get('message', None)
        if network_profile.get('json', None):
            message = str(json.dumps(message))
        self.message = message

    def run(self):
        bc_socket = self.init_socket(self.send_port)
        if not bc_socket: return
        ln_socket = self.init_socket(self.listen_port)
        if not ln_socket: return
        ln_socket.settimeout(self.LISTEN_TIMEOUT)
        attempt = 0
        self.logger.debug("Sending broadcast to port %d" % self.broadcast_port)
        while attempt < self.RETRIES:
            addr = None
            try:
                bc_socket.sendto(self.message, ('255.255.255.255', self.broadcast_port))
            except socket.error as e:
                self.logger.debug("Error sending broadcast", exc_info=True)
            try:
                data, addr = ln_socket.recvfrom(1024)
                self.logger.debug("Message received: " + str(data))
            except socket.timeout:
                pass
                #self.logger.debug("Timeout on port:" + str(self.listen_port))
            except socket.error:
                self.logger.debug("Error while receiving from port " + str(self.listen_port), exc_info=True)
            if addr:
                self.process_response(data, addr)
            attempt += 1
            time.sleep(self.RETRY_TIMEOUT)
        #self.logger.debug("Done listening to port: " + str(self.listen_port))
        self.module_specific_process_responce()
        bc_socket.close()
        ln_socket.close()

    def init_socket(self, port):
        #self.logger.debug("Creating broadcast socket")
        try:
            bc_or_ln_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            bc_or_ln_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            #bc_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            bc_or_ln_socket.bind(('0.0.0.0', int(port)))
        except socket.error as e:
            self.logger.debug("Socket init error. Port:" + str(port), exc_info=True)
        except ValueError as e:
            self.logger.debug("Not valid port number:" + str(port), exc_info=True)
        else:
            return bc_or_ln_socket

    def process_response(self, data, addr):
        if self.profile['network_detect']['json']:
            try:
                response = json.loads(data)
            except:
                self.logger.debug('Response from printer should be valid json. Its malformed or not json')
                return
        if addr not in self.response_addr_data_dict:
            self.logger.debug('Processing data form ' + str(addr) + " = " + str(data))
            self.response_addr_data_dict[addr] = response

    def module_specific_process_responce(self):
        for addr, data in self.response_addr_data_dict.iteritems():
            #self.logger.debug('Sending data to module ' +  self.profile['driver'] + ' for final processing:' + str(self.response_addr_data_dict))
            printer_data = self.printer_module.process_network_responses(addr, data)
            printer_data.update(self.profile)
            self.discovered_printers.append(printer_data)
        #self.logger.debug('Discovered network printers' + str(self.discovered_printers))

def get_printers():
    logger = logging.getLogger('app.' + __name__)
    #logger.setLevel(logging.DEBUG)
    #logging.basicConfig()
    logger.info('Scanning for network printers...')
    scanners = []
    printers = []
    for profile_name in config.config['profiles']:
        profile = config.config['profiles'][profile_name]
        if 'network_detect' in profile:
            scanner = NetBroadcastScanner(profile)
            scanner.start()
            scanners.append(scanner)
    timeout = (0.1 + NetBroadcastScanner.RETRY_TIMEOUT + NetBroadcastScanner.LISTEN_TIMEOUT) * NetBroadcastScanner.RETRIES
    for scanner in scanners:
        scanner.join(timeout)
        if scanner.is_alive():
            logger.error('Scanner still working(hanged): ' + scanner.profile['name'])
        for printer in scanner.discovered_printers:
            printers.append(printer)
    logger.info('Discovered network printers:\n' + str(printers))
    return printers

if __name__ == '__main__':
    printers = get_printers()
    print "Detected network printers: "
    print json.dumps(printers)


