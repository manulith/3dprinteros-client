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