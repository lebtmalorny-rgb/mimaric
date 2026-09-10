from ansible.errors import AnsibleConnectionFailure
from ansible.plugins.connection import ConnectionBase


class Connection(ConnectionBase):
    transport = 'firewall_unreachable'
    has_pipelining = False

    def _connect(self):
        raise AnsibleConnectionFailure('Deliberately unreachable fixture; no socket opened')

    def exec_command(self, cmd, in_data=None, sudoable=True):
        self._connect()

    def put_file(self, in_path, out_path):
        self._connect()

    def fetch_file(self, in_path, out_path):
        self._connect()

    def close(self):
        pass
