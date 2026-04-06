import socket
from dataclasses import dataclass
from enum import Enum
import threading
import sys

import random

from audio import G711AudioPlayer, G711AudioSource, G711MicrophoneSource, validate_mode
from stats import RtpStats
from rtp import rtp_receive_loop, rtp_send_loop
from rtcp import rtcp_send_loop, rtcp_send_rr_loop
from sip import SipMessage, build_200_ok, build_200_ok_bye, build_ack, build_bye, build_invite, generate_call_id, generate_tag, parse_sdp, parse_sip_message
from utils import detect_local_ip, log

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
    mode: str = "file"          # "file" or "mic"
    audio_file: str = "sample.wav"
    auto_answer: bool = False
    peer_ip: str = ""
    peer_sip_port: int = 5062

class Peer:
    def __init__(self):
        self.config = Config(local_ip=detect_local_ip())
        self.state = CallState.IDLE
        self.running = True
        self.sip_socket = None
        self.sip_thread = None
        self.rtp_socket = None
        self.rtcp_socket = None
        self.media_stop = None
        self.media_threads = []
        self.rtp_stats = None
        self.invite_msg = None
        self.call = None
        self.audio_source = None
        self.audio_player = None

    def start(self):
        self._print_banner()
        self._start_sip_listener()
        self._command_loop()

    def _print_banner(self):
        print("\nSimple VoIP Peer")
        print("----------------")
        self._show_settings()
        print("Type 'help' to see commands.\n")

    def _show_settings(self):
        c = self.config
        print(f"Local IP     : {c.local_ip}")
        print(f"SIP Port     : {c.sip_port}")
        print(f"Mode         : {c.mode}")
        print(f"Audio File   : {c.audio_file}")
        print(f"Auto Answer  : {'on' if c.auto_answer else 'off'}")
        print(f"Peer IP      : {c.peer_ip or 'not set'}")
        print(f"Peer SIP Port: {c.peer_sip_port}")
        print(f"State        : {self.state.value}")
        if self.call:
            print(f"Local RTP    : {self.call['local_rtp_port']}")
            print(f"Local RTCP   : {self.call['local_rtcp_port']}")
            print(f"Remote RTP   : {self.call.get('remote_rtp_port', '-')}")
            print(f"Remote RTCP  : {self.call.get('remote_rtcp_port', '-')}")

    def _start_sip_listener(self):
        self._stop_sip_listener()
        self.sip_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sip_socket.bind((self.config.local_ip, self.config.sip_port))
        self.sip_thread = threading.Thread(target=self._listen_for_sip, daemon=True)
        self.sip_thread.start()
        log(f"[SIP] Listening on {self.config.local_ip}:{self.config.sip_port}")

    def _stop_sip_listener(self):
        if self.sip_socket:
            try:
                self.sip_socket.close()
            except OSError:
                pass
        self.sip_socket = None

    def _listen_for_sip(self):
        while self.running:
            try:
                data, addr = self.sip_socket.recvfrom(8192)
            except OSError:
                break

            msg = parse_sip_message(data.decode(errors="ignore"))
            if not msg:
                log(f"[SIP] Failed to parse packet from {addr}")
                continue
            self._handle_sip(msg, addr)

    def _handle_sip(self, msg: SipMessage, addr):
        log(f"\n[SIP] {msg.message_type} from {addr[0]}:{addr[1]}")

        if msg.message_type == "INVITE":
            self._handle_invite(msg, addr)
            return

        if msg.message_type == "ACK":
            if self.state == CallState.INCOMING:
                self.state = CallState.ESTABLISHED
                self._start_media(send_audio=(self.config.mode == "mic"))
            return

        if msg.message_type == "BYE":
            self._send_sip(build_200_ok_bye(msg), addr, "200 OK")
            self._stop_media()
            self._reset_call()
            log("[APP] Call ended by remote side.")
            return

        if msg.message_type in ("100 Trying", "180 Ringing"):
            log(f"[SIP] {msg.message_type}")
            return

        if msg.message_type == "200 OK":
            if "BYE" in msg.cseq:
                self._stop_media()
                self._reset_call()
                log("[SIP] BYE completed.")
            elif self.state == CallState.OUTGOING:
                self._handle_ok_for_invite(msg, addr)
            return

        if msg.message_type.startswith("4") or msg.message_type.startswith("5"):
            log(f"[SIP] Error received: {msg.message_type}")
            self._stop_media()
            self._reset_call()

    def _handle_invite(self, invite: SipMessage, addr):
        if self.state != CallState.IDLE:
            log("[SIP] Busy. Ignoring new INVITE.")
            return

        remote_sdp = parse_sdp(invite.body)
        if not remote_sdp:
            log("[SIP] INVITE missing valid SDP.")
            return

        local_rtp, local_rtcp = self._allocate_media_ports()
        self.invite_msg = invite
        self.call = {
            "call_id": invite.call_id,
            "remote_ip": addr[0],
            "remote_sip_port": addr[1],
            "remote_rtp_ip": remote_sdp.ip,
            "remote_rtp_port": remote_sdp.port,
            "remote_rtcp_port": remote_sdp.port + 1,
            "local_rtp_port": local_rtp,
            "local_rtcp_port": local_rtcp,
            "local_tag": generate_tag(),
            "dialog": None,
        }
        self.state = CallState.INCOMING
        log("[APP] Incoming call. Use 'answer' to accept.")
        if self.config.auto_answer:
            self.answer()

    def _handle_ok_for_invite(self, ok_msg: SipMessage, addr):
        remote_sdp = parse_sdp(ok_msg.body)
        if not remote_sdp or not self.call:
            log("[SIP] 200 OK missing valid SDP.")
            self._stop_media()
            self._reset_call()
            return

        self.call["remote_rtp_ip"] = remote_sdp.ip
        self.call["remote_rtp_port"] = remote_sdp.port
        self.call["remote_rtcp_port"] = remote_sdp.port + 1
        self.call["dialog"] = SipMessage(
            message_type="DIALOG",
            from_uri=ok_msg.from_uri,
            to_uri=ok_msg.to_uri,
            call_id=ok_msg.call_id,
            cseq=ok_msg.cseq,
            via=ok_msg.via,
            contact=ok_msg.contact,
        )

        ack = build_ack(
            ok_msg=ok_msg,
            local_ip=self.config.local_ip,
            local_port=self.config.sip_port,
            from_user="peer",
            remote_ip=addr[0],
            remote_port=addr[1],
            to_user="peer",
        )
        self._send_sip(ack, addr, "ACK")
        self.state = CallState.ESTABLISHED
        self._start_media(send_audio=(self.config.mode == "mic"))

    def call_peer(self, ip=None, port=None):
        if self.state != CallState.IDLE:
            log("[APP] Cannot start a new call right now.")
            return

        target_ip = ip or self.config.peer_ip
        target_port = int(port or self.config.peer_sip_port)
        if not target_ip:
            log("[APP] Peer IP not set.")
            return

        validate_mode(self.config.mode, self.config.audio_file)
        local_rtp, local_rtcp = self._allocate_media_ports()
        call_id = generate_call_id()
        tag = generate_tag()

        invite = build_invite(
            local_ip=self.config.local_ip,
            local_port=self.config.sip_port,
            remote_ip=target_ip,
            remote_port=target_port,
            from_user="peer",
            to_user="peer",
            rtp_port=local_rtp,
            call_id=call_id,
            tag=tag,
        )

        self.call = {
            "call_id": call_id,
            "remote_ip": target_ip,
            "remote_sip_port": target_port,
            "remote_rtp_ip": None,
            "remote_rtp_port": None,
            "remote_rtcp_port": None,
            "local_rtp_port": local_rtp,
            "local_rtcp_port": local_rtcp,
            "local_tag": tag,
            "dialog": None,
        }
        self.state = CallState.OUTGOING
        self._send_sip(invite, (target_ip, target_port), "INVITE")

    def answer(self):
        if self.state != CallState.INCOMING or not self.invite_msg or not self.call:
            log("[APP] No incoming call to answer.")
            return

        ok = build_200_ok(
            invite_msg=self.invite_msg,
            local_ip=self.config.local_ip,
            local_port=self.config.sip_port,
            to_user="peer",
            rtp_port=self.call["local_rtp_port"],
            tag=self.call["local_tag"],
        )

        self.call["dialog"] = SipMessage(
            message_type="DIALOG",
            from_uri=f"{self.invite_msg.to_uri};tag={self.call['local_tag']}",
            to_uri=self.invite_msg.from_uri,
            call_id=self.invite_msg.call_id,
            cseq=self.invite_msg.cseq,
            via=self.invite_msg.via,
            contact=self.invite_msg.contact,
        )
        self._send_sip(ok, (self.call["remote_ip"], self.call["remote_sip_port"]), "200 OK")
        log("[SIP] Waiting for ACK...")

    def hangup(self):
        if self.state not in (CallState.OUTGOING, CallState.ESTABLISHED) or not self.call:
            log("[APP] No active call to hang up.")
            return

        if not self.call.get("dialog"):
            self._stop_media()
            self._reset_call()
            return

        bye = build_bye(
            call_info=self.call["dialog"],
            local_ip=self.config.local_ip,
            local_port=self.config.sip_port,
            cseq_number=2,
        )
        self.state = CallState.TERMINATING
        self._send_sip(bye, (self.call["remote_ip"], self.call["remote_sip_port"]), "BYE")

    def _send_sip(self, raw_msg: str, addr, label: str):
        self.sip_socket.sendto(raw_msg.encode(), addr)
        log(f"[SIP] {label} sent to {addr[0]}:{addr[1]}")

    def _allocate_media_ports(self):
        self._close_media_sockets()
        for _ in range(40):
            base = random.randrange(20000, 40000, 2)
            rtp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            rtcp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                rtp.bind((self.config.local_ip, base))
                rtcp.bind((self.config.local_ip, base + 1))
                self.rtp_socket, self.rtcp_socket = rtp, rtcp
                return base, base + 1
            except OSError:
                rtp.close()
                rtcp.close()
        raise RuntimeError("Could not allocate RTP/RTCP sockets.")

    def _close_media_sockets(self):
        for sock in (self.rtp_socket, self.rtcp_socket):
            if sock:
                try:
                    sock.close()
                except OSError:
                    pass
        self.rtp_socket = None
        self.rtcp_socket = None

    def _start_media(self, send_audio: bool):
        if not self.call:
            return

        if self.rtp_socket is None or self.rtcp_socket is None:
            log("[MEDIA] RTP/RTCP sockets are not initialized.")
            return

        # stop only old threads if needed but DO NOT close sockets
        if self.media_stop:
            self.media_stop.set()

            if self.audio_source and hasattr(self.audio_source, "close"):
                try:
                    self.audio_source.close()
                except Exception:
                    pass
                self.audio_source = None

            for t in self.media_threads:
                t.join(timeout=0.2)

            if self.audio_player and hasattr(self.audio_player, "close"):
                try:
                    self.audio_player.close()
                except Exception:
                    pass
                self.audio_player = None

        self.media_stop = threading.Event()
        self.media_threads = []
        self.rtp_stats = RtpStats()

        remote_rtp = (self.call["remote_rtp_ip"], self.call["remote_rtp_port"])
        remote_rtcp = (self.call["remote_rtp_ip"], self.call["remote_rtcp_port"])

        self.audio_player = G711AudioPlayer(debug=False)

        recv_thread = threading.Thread(
            target=rtp_receive_loop,
            args=(self.rtp_socket, self.audio_player, self.media_stop, self.rtp_stats, False),
            daemon=True,
        )
        recv_thread.start()
        self.media_threads.append(recv_thread)

        rr_thread = threading.Thread(
            target=rtcp_send_rr_loop,
            args=(self.rtcp_socket, remote_rtcp, self.media_stop, self.rtp_stats),
            daemon=True,
        )
        rr_thread.start()
        self.media_threads.append(rr_thread)

        if send_audio and self.config.mode == "file":
            self.audio_source = G711AudioSource(self.config.audio_file)

            send_thread = threading.Thread(
                target=rtp_send_loop,
                args=(self.rtp_socket, remote_rtp, self.audio_source, self.media_stop, self.rtp_stats),
                daemon=True,
            )
            sr_thread = threading.Thread(
                target=rtcp_send_loop,
                args=(self.rtcp_socket, remote_rtcp, self.media_stop, self.rtp_stats),
                daemon=True,
            )
            send_thread.start()
            sr_thread.start()
            self.media_threads.extend([send_thread, sr_thread])

            log(f"[MEDIA] Sending file audio to {remote_rtp[0]}:{remote_rtp[1]}")

        elif send_audio and self.config.mode == "mic":
            self.audio_source = G711MicrophoneSource(debug=False)

            send_thread = threading.Thread(
                target=rtp_send_loop,
                args=(self.rtp_socket, remote_rtp, self.audio_source, self.media_stop, self.rtp_stats),
                daemon=True,
            )
            sr_thread = threading.Thread(
                target=rtcp_send_loop,
                args=(self.rtcp_socket, remote_rtcp, self.media_stop, self.rtp_stats),
                daemon=True,
            )
            send_thread.start()
            sr_thread.start()
            self.media_threads.extend([send_thread, sr_thread])

            log(f"[MEDIA] Sending live microphone audio to {remote_rtp[0]}:{remote_rtp[1]}")

        else:
            log(f"[MEDIA] Receive-only mode on RTP {self.call['local_rtp_port']}")

    def _stop_media(self):
        if self.media_stop:
            self.media_stop.set()

        if self.audio_source and hasattr(self.audio_source, "close"):
            try:
                self.audio_source.close()
            except Exception:
                pass
            self.audio_source = None

        self._close_media_sockets()

        for t in self.media_threads:
            t.join(timeout=0.2)

        if self.audio_player and hasattr(self.audio_player, "close"):
            try:
                self.audio_player.close()
            except Exception:
                pass
            self.audio_player = None

        self.media_stop = None
        self.media_threads = []
        self.rtp_stats = None

    def _reset_call(self):
        self.invite_msg = None
        self.call = None
        self.state = CallState.IDLE

    def setup(self):
        old_ip, old_sip = self.config.local_ip, self.config.sip_port
        c = self.config
        local_ip = input(f"Local IP [{c.local_ip}]: ").strip()
        sip_port = input(f"SIP Port [{c.sip_port}]: ").strip()
        mode = input(f"Mode (file/mic) [{c.mode}]: ").strip()
        audio = input(f"Audio File [{c.audio_file}]: ").strip()
        auto = input(f"Auto Answer (on/off) [{'on' if c.auto_answer else 'off'}]: ").strip()
        peer_ip = input(f"Peer IP [{c.peer_ip or ''}]: ").strip()
        peer_sip = input(f"Peer SIP Port [{c.peer_sip_port}]: ").strip()

        if local_ip: c.local_ip = local_ip
        if sip_port: c.sip_port = int(sip_port)
        if mode in ("file", "mic"): c.mode = mode
        if audio: c.audio_file = audio
        if auto.lower() in ("on", "off"): c.auto_answer = auto.lower() == "on"
        if peer_ip: c.peer_ip = peer_ip
        if peer_sip: c.peer_sip_port = int(peer_sip)

        if old_ip != c.local_ip or old_sip != c.sip_port:
            self._start_sip_listener()
        log("[APP] Settings updated.")

    def set_value(self, field: str, value: str):
        old_ip, old_sip = self.config.local_ip, self.config.sip_port
        c = self.config
        if field == "local_ip":
            c.local_ip = value
        elif field == "sip_port":
            c.sip_port = int(value)
        elif field == "peer_ip":
            c.peer_ip = value
        elif field == "peer_sip":
            c.peer_sip_port = int(value)
        elif field == "mode" and value in ("file", "mic"):
            c.mode = value
        elif field == "audio":
            c.audio_file = value
        elif field == "auto_answer":
            c.auto_answer = value.lower() == "on"
        else:
            log("[APP] Unknown setting.")
            return

        if old_ip != c.local_ip or old_sip != c.sip_port:
            self._start_sip_listener()
        log(f"[APP] {field} updated.")

    def print_help(self):
        print("""
Commands:
  show
  setup
  set <local_ip|sip_port|peer_ip|peer_sip|mode|audio|auto_answer> <value>
  call
  call <ip> <sip_port>
  answer
  hangup
  help
  quit
""")
        
    def _command_loop(self):
        while self.running:
            try:
                raw = input("voip> ").strip()
                if not raw:
                    continue
                parts = raw.split()
                cmd = parts[0].lower()

                if cmd == "help":
                    self.print_help()
                elif cmd == "show":
                    self._show_settings()
                elif cmd == "setup":
                    self.setup()
                elif cmd == "set" and len(parts) >= 3:
                    self.set_value(parts[1], " ".join(parts[2:]))
                elif cmd == "call" and len(parts) == 1:
                    self.call_peer()
                elif cmd == "call" and len(parts) == 3:
                    self.call_peer(parts[1], int(parts[2]))
                elif cmd == "answer":
                    self.answer()
                elif cmd == "hangup":
                    self.hangup()
                elif cmd == "quit":
                    self.running = False
                    self._stop_media()
                    self._stop_sip_listener()
                    log("[APP] Goodbye.")
                else:
                    log("[APP] Unknown command. Type 'help'.")
            except KeyboardInterrupt:
                self.running = False
                self._stop_media()
                self._stop_sip_listener()
                print("\n[APP] Interrupted. Exiting...")
                break
            except Exception as exc:
                log(f"[ERROR] {exc}")

if __name__ == "__main__":
    peer = Peer()

    if len(sys.argv) >= 2:
        peer.config.sip_port = int(sys.argv[1])

    peer.start()