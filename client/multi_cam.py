#Copyright (c) 2015 3D Control Systems LTD

#3DPrinterOS client is free software: you can redistribute it and/or modify
#it under the terms of the GNU Affero General Public License as published by
#the Free Software Foundation, either version 3 of the License, or
#(at your option) any later version.

#3DPrinterOS client is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#GNU Affero General Public License for more details.

#You should have received a copy of the GNU Affero General Public License
#along with 3DPrinterOS client.  If not, see <http://www.gnu.org/licenses/>.

# Author: Vladimir Avdeev <another.vic@yandex.ru>

from dual_cam import DualCameraMaster

class MultiCameraMaster(DualCameraMaster):

    def search_cameras(self):
        self.indexes = []
        DualCameraMaster.search_cameras(self)

    def init_capture(self, capture):
        DualCameraMaster.init_capture(self, capture)
        index = self.captures.index(capture)
        self.indexes.append(index)
        capture.release()

    def make_shot(self, capture):
        index = self.indexes[self.captures.index(capture)]
        del(capture)
        try:
            capture = self.cv2.VideoCapture(index)
        except Exception as e:
            self.logger.warning("Error while opening video capture: " + str(e))
        else:
            if capture.isOpened():
                self.captures[index] = capture
                frame = DualCameraMaster.make_shot(self, capture)
                capture.release()
                return frame


if __name__ == "__main__":
    MultiCameraMaster()