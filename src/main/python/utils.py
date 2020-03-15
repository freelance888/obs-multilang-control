import socket
from pathlib import Path


def is_open(ip, port, timeout=2):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(timeout)
        s.connect((ip, int(port)))
        s.shutdown(2)
        return True
    except:
        return False
    finally:
        s.close()


def rm_tree(pth: Path):
    for child in pth.glob("*"):
        if child.is_file():
            child.unlink()
        else:
            rm_tree(child)
    pth.rmdir()
