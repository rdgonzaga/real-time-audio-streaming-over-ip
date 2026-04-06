# SIP and SDP implementation

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional


DEFAULT_CODEC = "PCMU"
DEFAULT_PAYLOAD_TYPE = 0
DEFAULT_SAMPLE_RATE = 8000
DEFAULT_CHANNELS = 1

@dataclass
class SdpInfo:
    """sdp info"""
    ip: str
    port: int
    codec: str = DEFAULT_CODEC
    payload_type: int = DEFAULT_PAYLOAD_TYPE
    sample_rate: int = DEFAULT_SAMPLE_RATE
    channels: int = DEFAULT_CHANNELS


@dataclass
class SipMessage:
    """parsed SIP message structure"""
    message_type: str  # "INVITE", "200 OK", "ACK", "BYE", "100 Trying", "180 Ringing"
    from_uri: str
    to_uri: str
    call_id: str
    cseq: str
    via: str
    contact: Optional[str] = None
    content_type: Optional[str] = None
    content_length: int = 0
    body: str = ""
    raw: str = ""


def generate_call_id() -> str:
    """generate unique call id"""
    return f"{random.randint(100000, 999999)}@{random.randint(1000, 9999)}"


def generate_tag() -> str:
    """generate tag for From/To headers"""
    return f"{random.randint(1000000, 9999999)}"


def build_sdp(local_ip: str, rtp_port: int, codec: str = DEFAULT_CODEC,
              payload_type: int = DEFAULT_PAYLOAD_TYPE, sample_rate: int = DEFAULT_SAMPLE_RATE,
              channels: int = DEFAULT_CHANNELS) -> str:
    """ builds SDP body for media negotiation. """
    sdp_lines = [
        "v=0",  # protocol version
        f"o=- {random.randint(1000000, 9999999)} {random.randint(1000000, 9999999)} IN IP4 {local_ip}",
        "s=VoIP Call",  # session name
        f"c=IN IP4 {local_ip}",  # connection information
        "t=0 0",  # time description (0 0 = permanent session)
        f"m=audio {rtp_port} RTP/AVP {payload_type}",  # media description
        f"a=rtpmap:{payload_type} {codec}/{sample_rate}",  # RTP map attribute
    ]
    return "\r\n".join(sdp_lines) + "\r\n"


def parse_sdp(sdp_body: str) -> Optional[SdpInfo]:
    """ parse SDP body to extract media information """
    if not sdp_body:
        return None
    
    lines = sdp_body.strip().split("\r\n")
    ip = ""
    port = 0
    codec = DEFAULT_CODEC
    payload_type = DEFAULT_PAYLOAD_TYPE
    sample_rate = DEFAULT_SAMPLE_RATE
    channels = DEFAULT_CHANNELS
    
    for line in lines:
        line = line.strip()
        if line.startswith("c=IN IP4 "):
            ip = line.split()[-1]
        elif line.startswith("m=audio "):
            parts = line.split()
            if len(parts) >= 4:
                port = int(parts[1])
                payload_type = int(parts[3])
        elif line.startswith("a=rtpmap:"):
            # format is: a=rtpmap:<payload_type> <codec>/<sample_rate>
            parts = line.split()
            if len(parts) >= 2:
                codec_info = parts[1].split("/")
                if len(codec_info) >= 2:
                    codec = codec_info[0]
                    sample_rate = int(codec_info[1])
                if len(codec_info) >= 3:
                    channels = int(codec_info[2])
    
    if ip and port:
        return SdpInfo(ip=ip, port=port, codec=codec, 
                      payload_type=payload_type, sample_rate=sample_rate, channels=channels)
    return None


def _build_message(method: str, request_uri: str, headers: dict, body: str = "") -> str:
    """ build a complete sip message with headers and optional body. """
    lines = []
    
    # add request/status line
    if request_uri:
        lines.append(f"{method} {request_uri} SIP/2.0")
    else:
        lines.append(method)  # for responses, method contains full status line
    
    # add headers
    for key, value in headers.items():
        lines.append(f"{key}: {value}")
    
    # add content length header
    content_length = len(body.encode('utf-8'))
    lines.append(f"Content-Length: {content_length}")
    
    # add blank line separator
    lines.append("")
    
    # add body if present
    if body:
        lines.append(body)
    
    return "\r\n".join(lines)


def build_invite(local_ip: str, local_port: int, remote_ip: str, remote_port: int,
                 from_user: str, to_user: str, rtp_port: int,
                 call_id: Optional[str] = None, tag: Optional[str] = None) -> str:
    """ build sip invite message to initiate a call """

    if not call_id:
        call_id = generate_call_id()
    if not tag:
        tag = generate_tag()
    
    request_uri = f"sip:{to_user}@{remote_ip}:{remote_port}"
    
    headers = {
        "Via": f"SIP/2.0/UDP {local_ip}:{local_port};branch=z9hG4bK{random.randint(100000, 999999)}",
        "From": f"<sip:{from_user}@{local_ip}:{local_port}>;tag={tag}",
        "To": f"<sip:{to_user}@{remote_ip}:{remote_port}>",
        "Call-ID": call_id,
        "CSeq": "1 INVITE",
        "Contact": f"<sip:{from_user}@{local_ip}:{local_port}>",
        "Max-Forwards": "70",
        "Content-Type": "application/sdp",
    }
    
    sdp_body = build_sdp(local_ip, rtp_port)
    
    return _build_message("INVITE", request_uri, headers, sdp_body)


def build_200_ok(invite_msg: SipMessage, local_ip: str, local_port: int,
                 to_user: str, rtp_port: int, tag: Optional[str] = None) -> str:
    """ build SIP 200 OK response to accept an INVITE """

    if not tag:
        tag = generate_tag()
    
    status_line = "SIP/2.0 200 OK"
    
    headers = {
        "Via": invite_msg.via,
        "From": invite_msg.from_uri,
        "To": f"{invite_msg.to_uri};tag={tag}",
        "Call-ID": invite_msg.call_id,
        "CSeq": invite_msg.cseq,
        "Contact": f"<sip:{to_user}@{local_ip}:{local_port}>",
        "Content-Type": "application/sdp",
    }
    
    sdp_body = build_sdp(local_ip, rtp_port)
    
    return _build_message(status_line, "", headers, sdp_body)


def build_ack(ok_msg: SipMessage, local_ip: str, local_port: int,
              from_user: str, remote_ip: str, remote_port: int, to_user: str) -> str:
    """ build SIP ACK message to confirm call establishment """
    request_uri = f"sip:{to_user}@{remote_ip}:{remote_port}"
    
    headers = {
        "Via": f"SIP/2.0/UDP {local_ip}:{local_port};branch=z9hG4bK{random.randint(100000, 999999)}",
        "From": ok_msg.from_uri,
        "To": ok_msg.to_uri,
        "Call-ID": ok_msg.call_id,
        "CSeq": "1 ACK",
        "Max-Forwards": "70",
    }
    
    return _build_message("ACK", request_uri, headers)


def build_bye(call_info: SipMessage, local_ip: str, local_port: int, cseq_number: int = 2) -> str:
    """ build SIP BYE message to terminate a call. """

    # based sa rfc 3261, use contact header dapat from prev response as request uri
    # fall back to To header if Contact is not available
    if call_info.contact:
        contact_uri = call_info.contact
        if contact_uri.startswith("<") and ">" in contact_uri:
            request_uri = contact_uri[1:contact_uri.index(">")]
        else:
            request_uri = contact_uri.split(";")[0]
    else:
        # fallback: extract from To header
        to_uri = call_info.to_uri
        if to_uri.startswith("<") and ">" in to_uri:
            request_uri = to_uri[1:to_uri.index(">")]
        else:
            request_uri = to_uri.split(";")[0]
    
    headers = {
        "Via": f"SIP/2.0/UDP {local_ip}:{local_port};branch=z9hG4bK{random.randint(100000, 999999)}",
        "From": call_info.from_uri,
        "To": call_info.to_uri,
        "Call-ID": call_info.call_id,
        "CSeq": f"{cseq_number} BYE",
        "Max-Forwards": "70",
    }
    
    return _build_message("BYE", request_uri, headers)


def build_200_ok_bye(bye_msg: SipMessage) -> str:
    """Build SIP 200 OK response for BYE without SDP body."""
    status_line = "SIP/2.0 200 OK"

    headers = {
        "Via": bye_msg.via,
        "From": bye_msg.from_uri,
        "To": bye_msg.to_uri,
        "Call-ID": bye_msg.call_id,
        "CSeq": bye_msg.cseq,
    }

    return _build_message(status_line, "", headers)


def build_100_trying(invite_msg: SipMessage) -> str:
    """ build SIP 100 Trying response """
    status_line = "SIP/2.0 100 Trying"
    
    headers = {
        "Via": invite_msg.via,
        "From": invite_msg.from_uri,
        "To": invite_msg.to_uri,
        "Call-ID": invite_msg.call_id,
        "CSeq": invite_msg.cseq,
    }
    
    return _build_message(status_line, "", headers)


def build_180_ringing(invite_msg: SipMessage, tag: Optional[str] = None) -> str:
    """build SIP 180 Ringing response"""
    if not tag:
        tag = generate_tag()
    
    status_line = "SIP/2.0 180 Ringing"
    
    headers = {
        "Via": invite_msg.via,
        "From": invite_msg.from_uri,
        "To": f"{invite_msg.to_uri};tag={tag}",
        "Call-ID": invite_msg.call_id,
        "CSeq": invite_msg.cseq,
    }
    
    return _build_message(status_line, "", headers)


def parse_sip_message(data: str) -> Optional[SipMessage]:
    """ parse raw SIP message into structured format. """
    if not data:
        return None
    
    try:
        # split headers and body
        parts = data.split("\r\n\r\n", 1)
        header_section = parts[0]
        body = parts[1] if len(parts) > 1 else ""
        
        lines = header_section.split("\r\n")
        if not lines:
            return None
        
        # parse first line (request or status line)
        first_line = lines[0]
        message_type = ""
        
        if first_line.startswith("SIP/2.0"):
            # response (e.g., "SIP/2.0 200 OK")
            parts = first_line.split(None, 2)
            if len(parts) >= 3:
                message_type = f"{parts[1]} {parts[2]}"
            else:
                message_type = first_line
        else:
            # request (e.g., "INVITE sip:user@host SIP/2.0")
            parts = first_line.split()
            if parts:
                message_type = parts[0]
        
        # parse headers
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip().lower()] = value.strip()
        
        return SipMessage(
            message_type=message_type,
            from_uri=headers.get("from", ""),
            to_uri=headers.get("to", ""),
            call_id=headers.get("call-id", ""),
            cseq=headers.get("cseq", ""),
            via=headers.get("via", ""),
            contact=headers.get("contact"),
            content_type=headers.get("content-type"),
            content_length=int(headers.get("content-length", 0)),
            body=body.strip(),
            raw=data,
        )
    except Exception:
        return None