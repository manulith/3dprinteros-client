3DPrinterOS is the 3D Printer control software.
This is its client part.
Server part is located at cloud.3dprinteros.com.
It was writen on Python and if compatible with version 2.7(previous versions could be compatible, but not tested).
All needed libraries for MS Windows and Mac OS X are included
    (to use included libraries under MS Windows, you should run python32).
Under GNU/Linux you should install following libraries:
    opencv
    numpy
    pyusb
    libusb1.0

To run client:
    python launch.py
(for some OS you should type python2)

3DPrinterOS supports all Printrun compatible printers as well as Makerbots(not including 5th generation and Sailfish).
Also ZMorph is supported in experemental mode.

Configurations are stored in setting.json

License:

3DPrinterOS client is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

3DPrinterOS client is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with 3DPrinterOS.  If not, see <http://www.gnu.org/licenses/>.







