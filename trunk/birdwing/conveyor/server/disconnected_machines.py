# Copyright 2014 MakerBot Industries

import conveyor.log

class DisconnectedMachines:
    """Keep track of disconnected machines

    Conveyor keeps track of connected machines via ports. When a port
    is detached the machine can no longer be found through the port.

    From the client's perspective, it's useful to keep track of
    disconnected printers (MW-2679). To address this requirement, when
    a machine port is detached the associated Machine moves into this
    container. The disconnected machines can then be reported back to
    clients. If the machine is re-attached, it is removed from this
    container.

    """

    def __init__(self):
        # Keys are machine hashes, values are Machines
        self._machines = {}
        self._log = conveyor.log.getlogger(self)

    def remember(self, machine):
        """Remember a machine in the disconnected state."""
        if machine:
            machine_hash = machine.get_hash()
            state = machine.get_state()

            if state == conveyor.machine.MachineState.DISCONNECTED:
                self._log.info(
                    'remembering disconnected machine: {}'.format(
                        machine_hash))
                self._machines[machine_hash] = machine
            else:
                self._log.error(
                    'expected disconnected machine: {} {}'.format(
                        machine_hash,
                        state))

    def forget_hash(self, machine_hash):
        """Forget about a machine using its machine hash."""
        self._machines.pop(machine_hash, None)

    def get_json_list(self):
        return [m.get_info() for m in self._machines.values()]
