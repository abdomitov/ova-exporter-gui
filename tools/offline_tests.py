"""Run the regression suite with real network/process/profile access denied."""
import socket
import subprocess
import sys
import tempfile
import unittest
import unittest.mock  # Load asyncio's Windows Popen subclass before installing guards.
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'src'))


def denied(*args, **kwargs):
    raise RuntimeError('Offline test attempted real network, process or profile access.')


def run():
    socket.socket.connect = denied
    socket.socket.connect_ex = denied
    socket.create_connection = denied
    subprocess.Popen = denied
    # Keep scratch files inside the project to work with restricted environments.
    scratch = ROOT/'artifacts'/'test-temp'
    scratch.mkdir(parents=True,exist_ok=True)
    tempfile.tempdir = str(scratch)
    from connection_settings import ConnectionSettings
    original = ConnectionSettings.__init__
    def isolated_settings(self,directory=None,protector=None):
        if directory is None or protector is None:
            denied()
        original(self,directory,protector)
    ConnectionSettings.__init__ = isolated_settings
    suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_*.py')
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    return result.wasSuccessful()


if __name__=='__main__':
    raise SystemExit(0 if run() else 1)
