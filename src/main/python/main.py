import logging
import pathlib
import sys
import tempfile

from app import AppContext


def setup_logger(log_path: str = None, log_level=logging.INFO):
    if log_path is not None:
        log_path = pathlib.Path(log_path)
        if not log_path.parent.is_dir():
            log_path.parent.mkdir()
        print(f"Log file is here {log_path}")

    logging.basicConfig(
        filename=log_path,
        level=log_level,
        format="[%(asctime)s] %(levelname).1s %(message)s",
        datefmt="%Y.%m.%d %H:%M:%S",
    )


def main():
    appctxt = AppContext()
    exit_code = appctxt.run()
    sys.exit(exit_code)


if __name__ == "__main__":
    log_path = pathlib.Path(tempfile.gettempdir()) / "obs-control.log"
    setup_logger(log_path=None, log_level=logging.DEBUG)
    try:
        main()
    except Exception as e:
        logging.exception(e)
        logging.error(f"Detailed logs could be found here: {log_path}")
