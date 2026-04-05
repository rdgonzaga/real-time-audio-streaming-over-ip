import socket

def detect_local_ip() -> str:
    """
    Attempt to detect the machine's LAN IP.
    Falls back to localhost if detection fails.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except Exception:
        return "127.0.0.1"
    
def log(message: str) -> None:
    print(message)