# Main logic and command loop
# REMARK: I think for the implementation of bonus, having one "peer" program is much better than having separate caller and callee programs.
# Supported features should be: 
    # a) file mode 
    # b) mic mode
    # c) call or answer a callable
    # d) one-way or two-way streaming

# program would have commands like:
# a) call (ip) (port)
# b) answer
# c) hangup
# mode file (filename)  - use file as source
# mode mic              - use mic as soruce
# quit
# help                  - display commands ofc
# setup                 - setup params like sip port and rtp port and stuff (in hindsight having a set (var) (val) command would also be nice)
# show                  - display settings (and maybe current state?)

import socket
from dataclasses import dataclass
from enum import Enum

class CallState(Enum):
    IDLE = "IDLE"
    INCOMING = "INCOMING"
    OUTGOING = "OUTGOING"
    ESTABLISHED = "ESTABLISHED"
    TERMINATING = "TERMINATING"

@dataclass
class Config:
    local_ip: str = ""
    sip_port: int = 5060
    rtp_port: int = 7000
    rtcp_port: int = 7001
    mode: str = "file"          # "file" or "mic"
    audio_file: str = "sample.wav"
    auto_answer: bool = False
    peer_ip: str = ""
    peer_sip_port: int = 5062

class Peer:
    def __init__(self):
        self.config = Config()
        self.config.local_ip = self.detect_local_ip()
        self.state = CallState.IDLE
        self.running = True
        self.sip_socket = None
        self.sip_thread = None
        self.incoming_call = None   # store (addr, parsed_msg) or whatever later
        self.current_call = None    # store SIP/session info later

    # Attempt to detect local IP. Fallback to localhost if unsuccessful.
    def detect_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"
        
    def log(self, msg):
        print(msg)

    def start(self):
        self.start_sip_listener()
        self.print_banner()
        self.command_loop()

    def print_banner(self):
        print("\nSimple VoIP Peer")
        print("----------------")
        self.show_settings()
        print("Type 'help' to see commands.\n")

    # Subject to change. But gets mo ba yung startup flow type shit
    def show_settings(self):
        print(f"Local IP     : {self.config.local_ip}")
        print(f"SIP Port     : {self.config.sip_port}")
        print(f"RTP Port     : {self.config.rtp_port}")
        print(f"RTCP Port    : {self.config.rtcp_port}")
        print(f"Mode         : {self.config.mode}")
        print(f"Audio File   : {self.config.audio_file}")
        print(f"Auto Answer  : {'on' if self.config.auto_answer else 'off'}")
        print(f"Peer IP      : {self.config.peer_ip or 'not set'}")
        print(f"Peer SIP Port: {self.config.peer_sip_port}")
        print(f"State        : {self.state.value}")

    def start_sip_listener(self): ...
    def restart_sip_listener(self): ...
    def listen_for_sip(self): ...
    def handle_sip_packet(self, data, addr): ...
    def call(self, ip, port): ...
    def answer(self): ...
    def hangup(self): ...
    def start_media(self): ...
    def stop_media(self): ...
    def setup(self): ...
    def set_value(self): ...

if __name__ == "__main__":
    peer = Peer()
    peer.start()