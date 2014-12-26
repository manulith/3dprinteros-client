import usb
import utils
import logging

class Printer:

    READ_TIMEOUT = 100

    def __init__(self, profile):
        self.logger = logging.getLogger('app.' + __name__)
        self.profile = profile
        # find our device
        int_vid = int(self.profile['VID'], 16)
        int_pid = int(self.profile['PID'], 16)
        backend_from_our_directory = usb.backend.libusb1.get_backend(find_library=utils.get_libusb_path)
        dev = usb.core.find(idVendor=int_vid, idProduct=int_pid, backend=backend_from_our_directory)
        # set the active configuration. With no arguments, the first
        # configuration will be the active one
        self.dev = dev
        self.read_length = 128

    def default_configuration(self):
        self.dev.set_configuration()
        # get an endpoint instance
        cfg = self.dev.get_active_configuration()
        intf = cfg[(0,0)]
        ep_out = usb.util.find_descriptor(
            intf,
            # match the first OUT endpoint
            custom_match = \
            lambda e: \
                usb.util.endpoint_direction(e.bEndpointAddress) == \
                usb.util.ENDPOINT_OUT)
        ep_in = usb.util.find_descriptor(
            intf,
            # match the first in endpoint
            custom_match = \
            lambda e: \
                usb.util.endpoint_direction(e.bEndpointAddress) == \
                usb.util.ENDPOINT_IN)
        # Verify that the end points exist
        assert ep_out is not None
        assert ep_in is not None

        self.ep_out = ep_out
        self.ep_in = ep_in

    def set_read_length(self, length):
        self.read_length = length

    def ep_read(self):
        ret = self.ep_in.read(self.read_length, self.READ_TIMEOUT)
        sret = ''.join([chr(x) for x in ret])
        return sret

    def ep_write(self, data):
        self.ep_in.write(data)

    def enqueue(self, gcodes):
        self.gcodes