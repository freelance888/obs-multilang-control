import socket


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
