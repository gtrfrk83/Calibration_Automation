"""Tests never touch a real person's data folder: everything goes to a throw-away folder."""
import os
import tempfile

os.environ.setdefault('CALSUITE_DATA', tempfile.mkdtemp(prefix='calsuite_test_data_'))
