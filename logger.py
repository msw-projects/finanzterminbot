import logging
import sys

def _init():
    app_logger = logging.getLogger('app')
    app_logger.setLevel(logging.INFO)

    formatter = logging.Formatter('[%(asctime)s] %(levelname)s %(module)s %(message)s')

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setLevel(logging.DEBUG)
    stream_handler.setFormatter(formatter)
    app_logger.addHandler(stream_handler)

    file_handler = logging.FileHandler('errors.log')
    file_handler.setLevel(logging.ERROR)
    file_handler.setFormatter(formatter)
    app_logger.addHandler(file_handler)

_init()
log = logging.getLogger('app')