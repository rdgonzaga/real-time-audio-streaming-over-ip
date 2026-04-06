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

1. **Extract the project archive:**
   - Extract the downloaded ZIP file to a folder on your computer
   - Navigate to the extracted folder

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
  |←======= RTP/RTCP Media ========→|
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
- Comfort noise generation on timeout
- Supports full-duplex communication

**Playback:**
- Decodes G.711 μ-law to PCM
- Real-time audio output
- Jitter buffering for smooth playback

### 6. **Two-Way Communication (Bonus Feature)**

Full-duplex bidirectional audio streaming:
- Simultaneous RTP send and receive
- Independent audio threads for each direction
- Separate RTCP SR and RR reporting
- Works with both file and microphone modes
- Thread-safe resource sharing

### 7. **Error Handling**

Robust error recovery:
- Graceful handling of 4xx/5xx SIP errors
- Malformed packet detection and logging
- Socket timeout handling
- No crashes on unexpected input
- Proper resource cleanup on errors

---

## Test Cases and Sample Outputs

### Test Setup

Two peers running on the same machine:
- **Peer 1:** IP `192.168.1.100`, SIP Port `5060`
- **Peer 2:** IP `192.168.1.100`, SIP Port `5062`

---

### Test Case 1: SIP Call Establishment (INVITE, 200 OK, ACK)

**Peer 1 (Caller):**
```
voip> set peer_ip 192.168.1.100
[APP] peer_ip updated.
voip> set peer_sip 5062
[APP] peer_sip updated.
voip> set mode mic
[APP] mode updated.
voip> call

[SIP] INVITE sent to 192.168.1.100:5062

[SIP] 200 OK from 192.168.1.100:5062
[APP] Remote SDP: 192.168.1.100:24536
[SIP] ACK sent to 192.168.1.100:5062
[MEDIA] Starting media with send_audio=True
```

**Peer 2 (Callee):**
```
[SIP] INVITE from 192.168.1.100:5060
[APP] Incoming call. Use 'answer' to accept.

voip> answer

[SIP] 200 OK sent to 192.168.1.100:5060
[SIP] Waiting for ACK...

[SIP] ACK from 192.168.1.100:5060
[MEDIA] Starting media with send_audio=True
```

---

### Test Case 2: RTP Audio Streaming

**Peer 1 Output (during call):**
```
[MEDIA] Sending live microphone audio to 192.168.1.100:24536
[MEDIA] Receive-only mode on RTP 22748
[RTP RECV] Starting receive loop, listening for packets...
[RTP RECV] First packet received, starting sequence at 15234
[RTP RECV] Jitter buffer initialized with 5 packets, starting playback...
```

**Peer 2 Output (during call):**
```
[MEDIA] Sending live microphone audio to 192.168.1.100:22748
[MEDIA] Receive-only mode on RTP 24536
[RTP RECV] Starting receive loop, listening for packets...
[RTP RECV] First packet received, starting sequence at 8921
[RTP RECV] Jitter buffer initialized with 5 packets, starting playback...
```

---

### Test Case 3: RTCP Reporting

**RTCP Sender Report (every 5 seconds):**
```
[RTCP] Sending SR: SSRC=3845729184, packets=245, octets=39200
[RTCP] Sending SR: SSRC=3845729184, packets=492, octets=78720
```

**RTCP Receiver Report (every 5 seconds):**
```
[RTCP] Sending RR: sender_ssrc=2193847562, lost=0, jitter=2.3
[RTCP] Sending RR: sender_ssrc=2193847562, lost=0, jitter=1.8
```

---

### Test Case 4: Call Termination (BYE)

**Peer 1 (Initiates Hangup):**
```
voip> hangup

[SIP] BYE sent to 192.168.1.100:5062
[MEDIA] Media threads stopped
[MEDIA] RTP/RTCP sockets closed
[APP] Call state reset to IDLE

[SIP] 200 OK from 192.168.1.100:5062
[SIP] BYE completed.
```

**Peer 2 (Receives Hangup):**
```
[SIP] BYE from 192.168.1.100:5060
[SIP] 200 OK sent to 192.168.1.100:5060
[MEDIA] Media threads stopped
[MEDIA] RTP/RTCP sockets closed
[APP] Call ended by remote side.
```

---

### Test Case 5: Error Handling

**Scenario: Call to offline peer**
```
voip> call 192.168.1.200 5060

[SIP] INVITE sent to 192.168.1.200:5060
[SIP] Waiting for response...
(timeout after 30 seconds, no crash)
```

**Scenario: Malformed RTP packet**
```
[RTP RECV] Malformed packet: Invalid RTP version
(packet ignored, receiver continues)
```

---

## Testing Instructions

### Test 1: File-to-File Communication

1. **Peer 1:**
   ```bash
   voip> set mode file
   voip> set audio sample.wav
   voip> call 192.168.1.101 5062
   ```

2. **Peer 2:**
   ```bash
   voip> answer
   ```

3. **Expected:** Peer 2 hears audio from sample.wav

### Test 2: Two-Way Microphone Call

1. **Both peers:** 
   ```bash
   voip> set mode mic
   ```

2. **Peer 1:** 
   ```bash
   voip> call 192.168.1.101 5062
   ```

3. **Peer 2:** 
   ```bash
   voip> answer
   ```

4. **Expected:** Both peers can hear each other in real-time

### Test 3: Call Rejection

1. **Peer 1:** 
   ```bash
   voip> call 192.168.1.101 5062
   ```

2. **Peer 2:** Simply don't answer or quit

3. **Expected:** Call times out gracefully, no crash
