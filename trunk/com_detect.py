import sys
import usb_detect
import config


def detect(printer_type='RR'):
    devices = usb_detect.get_devices()
    printer = filter(lambda dev: dev['COM'] is not None, devices)
    if len(printer) == 0:
        return printer
    elif len(printer) >= 1:
        # Ivan has changed condition logic due to exception if there are more than one printer was loaded from config
        # It just gets info from 1st entry now
        # return printer
        # raise Exception('More than one serial device is found. Please unplug all serial devices except printer and retry.')
        # elif len(printer) == 1:
        if printer_type in config.config['profiles']:
            config.config['profiles'][printer_type]['vids_pids'].append([printer[0]['VID'], printer[0]['PID']])
            config.update_config(config.config)
        else:
            raise ValueError('Received non-existent printer type.')


if __name__ == '__main__':
    if len(sys.argv) > 1:
        detect(sys.argv[1])
    else:
        detect()
