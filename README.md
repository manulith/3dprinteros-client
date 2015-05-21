# About

3DPrinterOS is the 3D Printer control software. This is its client part. Server part is located at https://cloud.3dprinteros.com.

3DPrinterOS supports all Printrun compatible printers as well as Makerbots (not including 5th generation and Sailfish).
ZMorph is supported, but still experemental.

##### Features:
- Autodetection and autoconnection - no need to select port or baudrate, just printer type in some cases
- Multiprinting - several printer can be connected to the same machine
- Remote control of 3D printer throught the web site (the web site provides slicing, model fixing and other stuff that you could find useful - all in one place)
- Web Cameras support (as well as printers, you could use multiple cameras, but be warn that this requires high performance CPU)

# Getting 3DPrinterOS Client

The install packages for GNU/Linux, MS Windows, MacOS X at  https://cloud.3dprinteros.com
You can also download an image for Raspberry Pi there.
# Python!
3DPrinterOS client is written on Python.
It was tested on Python 2.7, but can you can try older versions too.
# Running from source
All needed libraries for MS Windows and Mac OS X are included (to use included libraries under MS Windows, you should run 32 bit version python).

For GNU/Linux you should install following libraries:
- opencv
- numpy
- pyusb
- libusb1.0
- xterm

To be able to print on GNU/Linux you must make sure that your user is in this groups:
- tty
- dialout(or uucp)

Under MS Windows libusb1.0 need root/admin rights to read printer serial number correctly.

Under GNU/Linux please add create file named 3dprinter.rules with following content in `/etc/udev/rules.d/`:
```
SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", MODE="0664", GROUP="usbusers"
```
Then execute following to activate the rules:
```
useradd -G usbusers $USER
udevadm control --reload-rules
```
###### Launching:
```
python launch.py
```
(or ```python2``` for some OSs. Also make sure that you had python added to your ```PATH``` under MS Windows)

## License
>3DPrinterOS client is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

>3DPrinterOS client is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

>You should have received a copy of the GNU Affero General Public License
along with 3DPrinterOS.  If not, see <http://www.gnu.org/licenses/>.
