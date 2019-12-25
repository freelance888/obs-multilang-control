import logging
import pathlib
import sys


from app import AppContext


def setup_logger(log_path: str = None, log_level=logging.INFO):
    if log_path is not None:
        log_path = pathlib.Path(log_path)
        if not log_path.is_dir():
            log_path.mkdir()
        log_path = log_path / "obs-control.log"

    logging.basicConfig(
        filename=log_path,
        level=log_level,
        format="[%(asctime)s] %(levelname).1s %(message)s",
        datefmt="%Y.%m.%d %H:%M:%S",
    )


def main(config=None):
    appctxt = AppContext()
    exit_code = appctxt.run()
    sys.exit(exit_code)


if __name__ == "__main__":
    setup_logger(log_level=logging.DEBUG)
    try:
        main()
    except Exception as e:
        logging.exception("Exception has been raised.")
