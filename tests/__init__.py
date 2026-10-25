"""Tests never touch a real person's data folder: everything goes to a throw-away folder."""
import os
import tempfile

os.environ.setdefault('CALSUITE_DATA', tempfile.mkdtemp(prefix='calsuite_test_data_'))
os.environ.setdefault('CALSUITE_LAYOUTS', '0')            # window layouts are only remembered in the tests that ask for it
os.environ.setdefault('CALSUITE_DEPTH', '0')              # shadows are only on in the tests that ask for them
