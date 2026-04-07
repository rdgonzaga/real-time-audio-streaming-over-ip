# Real-Time Audio Streaming over IP

**NSCOM01 Machine Project 2**  
**Authors:** Lance Chiu & Rainer Gonzaga

A peer-to-peer VoIP application implementing SIP for call signaling and RTP/RTCP for real-time audio streaming over UDP. Supports both WAV file streaming and live microphone communication with full bidirectional audio.

---

## Requirements

- **Python 3.10 or later**
- **Required packages:**
  - `numpy>=1.26.0`
  - `sounddevice>=0.4.7`
  - `soundfile>=0.12.1`

---

## Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/rdgonzaga/real-time-audio-streaming-over-ip.git
   cd real-time-audio-streaming-over-ip
   ```

2. **Create a virtual environment (recommended):**
   ```bash
   python -m venv .venv
   # On Windows:
   .venv\Scripts\activate
   # On macOS/Linux:
   source .venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

---

## Project Structure

```
real-time-audio-streaming-over-ip/
├── src/
│   ├── peer.py              # Main application and command loop
│   ├── audio.py             # Audio I/O (WAV files, microphone, playback)
│   ├── utils.py             # Helper functions (IP detection, logging)
│   ├── stats.py             # RTP statistics for RTCP reporting
│   ├── constants.py         # Configuration constants
│   ├── sip/
│   │   ├── messages.py      # SIP message builders (INVITE, ACK, BYE, 200 OK)
│   │   └── sdp.py           # SDP body generation and parsing
│   ├── rtp/
│   │   ├── packet.py        # RTP packet builder and parser
│   │   ├── sender.py        # RTP audio transmission loop
│   │   ├── receiver.py      # RTP audio reception and playback loop
│   │   └── jitter.py        # Jitter buffer for packet reordering
│   └── rtcp/
│       ├── packet.py        # RTCP packet structures
│       ├── reports.py       # SR and RR report builders
│       └── sender.py        # RTCP sender and receiver report loops
├── requirements.txt         # Python dependencies
└── README.md               # This file
```

---

## Running the Program

Each peer runs the same program. There is no separate server or client. Every instance can both initiate and receive calls.

### Start a peer

```bash
cd src
python peer.py
```

The program will:
1. Auto-detect your local IP address
2. Bind to a SIP port (default: 5060)
3. Display current settings

### Initial Output Example

```
Simple VoIP Peer
----------------
Local IP     : 192.168.1.100
SIP Port     : 5060
Mode         : file
Audio File   : sample.wav
Auto Answer  : off
Peer IP      : not set
Peer SIP Port: 5062
State        : IDLE
Type 'help' to see commands.

[SIP] Listening on 192.168.1.100:5060
voip>
```

---

## Commands

The application provides an interactive command-line interface:

| Command | Description |
|---------|-------------|
| `show` | Display current configuration and call state |
| `setup` | Interactive configuration wizard |
| `set <var> <value>` | Set individual configuration values |
| `call` | Call the configured peer |
| `call <ip> <port>` | Call a specific peer |
| `answer` | Accept an incoming call |
| `hangup` | Terminate the active call |
| `help` | Display command list |
| `quit` | Exit the program |

### Configuration Fields

- `local_ip`: Your local IP address
- `sip_port`: SIP listening port (default: 5060)
- `peer_ip`: Remote peer's IP address
- `peer_sip`: Remote peer's SIP port
- `mode`: Audio source: `file` or `mic`
- `audio`: WAV file path (when mode=file)
- `auto_answer`: Automatically accept calls: `on` or `off`

### Example Usage

```bash
# Configure peer settings
voip> set peer_ip 192.168.1.101
voip> set peer_sip 5060
voip> set mode mic

# Make a call
voip> call

# During a call
voip> hangup
```

---

## Implemented Features

### 1. **SIP Signaling**

Full SIP call control over UDP based on RFC 3261

**Supported Messages:**
- **INVITE**: Initiates a call with SDP body containing media parameters
- **200 OK**: Accepts call or acknowledges BYE
- **ACK**: Confirms call establishment after 200 OK
- **BYE**: Terminates an established call

**Required Headers (all included):**
- Via, From, To, Call-ID, CSeq, Contact, Content-Type, Content-Length

**Call Flow:**
```
Caller                           Callee
  |                                 |
  |------------ INVITE ------------→|
  |                                 |
  |←----------- 200 OK -------------|
  |                                 |
  |------------- ACK --------------→|
  |                                 |
  |←======== RTP/RTCP Media =======→|
  |                                 |
  |------------- BYE --------------→|
  |                                 |
  |←----------- 200 OK -------------|
```

### 2. **SDP Negotiation**

Session Description Protocol embedded in SIP messages based on RFC 4566

**SDP Format:**
```
v=0                                    (protocol version)
o=- <session-id> <version> IN IP4 <ip> (originator)
s=VoIP Call                            (session name)
c=IN IP4 <connection-ip>               (connection data)
t=0 0                                  (time: permanent)
m=audio <port> RTP/AVP 0               (media: G.711 PCMU)
a=rtpmap:0 PCMU/8000                   (codec mapping)
```

**Capabilities:**
- Negotiates RTP/RTCP port numbers
- Specifies G.711 μ-law codec (payload type 0)
- Defines sample rate (8000 Hz)
- Parsed from INVITE and 200 OK messages

### 3. **RTP Streaming**

Real-time Transport Protocol carries audio data over UDP based on RFC 3550.

**RTP Header (12 bytes):**
```
 0               1               2               3
 0 1 2 3 4 5 6 7 0 1 2 3 4 5 6 7 0 1 2 3 4 5 6 7 0 1 2 3 4 5 6 7
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|V=2|P|X|  CC   |M|     PT      |       Sequence Number         |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                           Timestamp                           |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|           Synchronization Source (SSRC) identifier            |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

**Audio Parameters:**
- **Codec:** G.711 μ-law (PCMU), payload type 0
- **Sample rate:** 8000 Hz, mono channel
- **Frame size:** 160 bytes (20 ms of audio)
- **Packet interval:** 20 ms (50 packets/second)
- **Timestamp increment:** 160 samples per packet

**Features:**
- Sequence number tracking with wraparound handling
- Timestamp synchronization
- Random SSRC per session
- Packet loss detection
- Jitter buffer for reordering out-of-sequence packets
- RFC 3550 compliant jitter calculation

### 4. **RTCP Reports**

RTP Control Protocol provides statistics and quality monitoring based on RFC 3550.

**Sender Reports (SR):**
- Sent every 5 seconds on RTCP port (RTP port + 1)
- Contains: SSRC, NTP timestamp, RTP timestamp, packet count, octet count

**Receiver Reports (RR):**
- Sent every 5 seconds when receiving RTP
- Contains: Fraction lost, cumulative lost, highest sequence, jitter

**Real-time Statistics:**
- Packet counts and loss rates
- Interarrival jitter measurement
- Synchronized via shared `RtpStats` object

### 5. **Audio Modes**

**File Mode (`mode=file`):**
- Reads WAV audio files
- Encodes to G.711 μ-law format
- Streams at 20 ms intervals
- Supports any WAV format (automatically converted)

**Microphone Mode (`mode=mic`):**
- Captures live audio from default input device
- Real-time encoding to G.711 μ-law
- Non-blocking queue-based delivery
- Supports two way communication

**Playback:**
- Decodes G.711 μ-law to PCM
- Real-time audio output
- Jitter buffering for smooth playback

### 6. **Two-Way Communication (Bonus Feature)**

Full-duplex/Two-way audio streaming:
- Simultaneous RTP send and receive
- Independent audio threads for each direction
- Separate RTCP SR and RR reporting
- Works with both file and microphone modes
- Thread-safe resource sharing

### 7. **Error Handling**

Robust error recovery:
- Handling of 4xx/5xx SIP errors
- Socket timeout handling
- No crashes on unexpected input
- Proper resource cleanup on errors

---
## Test Cases and Sample Outputs

### Test Setup

Two peers running on the same machine/local network:
- **Peer 1 (Caller):** IP `192.168.100.15`, SIP Port `5060`
- **Peer 2 (Callee):** IP `192.168.100.15`, SIP Port `6767`

---

### Test Case 1: File-to-File Call Establishment

**Peer 1 (Caller - Port 5060):**
```text
voip> set mode file
[APP] mode updated.
voip> call 192.168.100.15 6767

[SIP] INVITE sent to 192.168.100.15:6767
[SIP] 200 OK from 192.168.100.15:6767
[SIP] ACK sent to 192.168.100.15:6767
[MEDIA] Sending file audio to 192.168.100.15:25166
```

**Peer 2 (Callee - Port 6767):**
```text
voip> set mode file
[APP] mode updated.
[SIP] INVITE from 192.168.100.15:5060
[APP] Incoming call. Use 'answer' to accept.

voip> answer

[SIP] 200 OK sent to 192.168.100.15:5060
[SIP] Waiting for ACK...
[SIP] ACK from 192.168.100.15:5060
[MEDIA] Sending file audio to 192.168.100.15:26114
```

---

### Test Case 2: Call Termination (Hangup)

**Peer 1 (Initiates Hangup):**
```text
voip> hangup

[SIP] BYE sent to 192.168.100.15:6767
[SIP] 200 OK from 192.168.100.15:6767
[SIP] BYE completed.
```

**Peer 2 (Receives Hangup):**
```text
[SIP] BYE from 192.168.100.15:5060
[SIP] 200 OK sent to 192.168.100.15:5060
[APP] Call ended by remote side.
```

---

### Test Case 3: Two-Way Microphone Call

**Peer 1 (Caller - Port 5060):**
```text
voip> set mode mic
[APP] mode updated.
voip> call 192.168.100.15 6767

[SIP] INVITE sent to 192.168.100.15:6767
[SIP] 200 OK from 192.168.100.15:6767
[SIP] ACK sent to 192.168.100.15:6767
[MEDIA] Sending live microphone audio to 192.168.100.15:34430
```

**Peer 2 (Callee - Port 6767):**
```text
voip> set mode mic
[APP] mode updated.
[SIP] INVITE from 192.168.100.15:5060
[APP] Incoming call. Use 'answer' to accept.

voip> answer

[SIP] 200 OK sent to 192.168.100.15:5060
[SIP] Waiting for ACK...
[SIP] ACK from 192.168.100.15:5060
[MEDIA] Sending live microphone audio to 192.168.100.15:28542
```