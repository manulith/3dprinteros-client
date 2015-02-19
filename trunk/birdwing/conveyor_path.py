import time
import logging

import utils
import conveyor_from_py as conveyor_loader
import conveyor_from_egg

@utils.singleton
class ConveyorService:
    def __init__(self):
        self.server = None
        self.logger = logging.getLogger('main')
        self.start()

    def start(self):
        self.logger.info('Trying to start conveyor service')
        conveyor_loader.prepare_conveyor_import()
        self.server = conveyor_loader.start_conveyor_service()
        if self.server:
            self.logger.info('Conveyor server successfully started')
            time.sleep(3)
        else:
            self.logger.critical('Conveyor server start fail')
            raise EnvironmentError('Can`t start conveyor server')

    def close(self):
        if self.server:
            self.server.terminate()

if __name__ == "__main__":
    try:
        conveyor_svc = ConveyorService()
        time.sleep(360)
    finally:
        conveyor_svc.close()
