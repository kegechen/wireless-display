"""
Wireless Display Protocol
=========================
Message format: [4-byte big-endian length][1-byte type][payload]

Message types:
  0x01 = VIDEO_FRAME  (JPEG data, server -> client)
  0x02 = CONTROL      (JSON, bidirectional)
  0x03 = INPUT_EVENT  (JSON, client -> server)
  0x04 = CURSOR_POS   (8 bytes: 2x float32 rel_x, rel_y, server -> client)
"""

import struct
import json

# Message types
MSG_VIDEO_FRAME = 0x01
MSG_CONTROL = 0x02
MSG_INPUT = 0x03
MSG_CURSOR_POS = 0x04


def pack_cursor_pos(rel_x, rel_y):
    """Pack cursor position as 2x float32 (8 bytes)."""
    return struct.pack('>ff', rel_x, rel_y)


def unpack_cursor_pos(data):
    """Unpack cursor position. Returns (rel_x, rel_y) in 0~1 range."""
    return struct.unpack('>ff', data)

HEADER_SIZE = 5
MAX_MESSAGE_SIZE = 10 * 1024 * 1024  # 10 MB


def recv_exactly(sock, n):
    """Receive exactly n bytes from socket."""
    data = bytearray()
    while len(data) < n:
        chunk = sock.recv(min(n - len(data), 262144))
        if not chunk:
            raise ConnectionError("Connection closed")
        data.extend(chunk)
    return bytes(data)


def recv_message(sock):
    """Receive a complete framed message. Returns (msg_type, payload)."""
    header = recv_exactly(sock, HEADER_SIZE)
    length, msg_type = struct.unpack('>IB', header)
    if length > MAX_MESSAGE_SIZE:
        raise ValueError(f"Message too large: {length}")
    payload = recv_exactly(sock, length) if length > 0 else b''
    return msg_type, payload


def send_message(sock, msg_type, payload):
    """Send a framed message."""
    if isinstance(payload, str):
        payload = payload.encode('utf-8')
    header = struct.pack('>IB', len(payload), msg_type)
    sock.sendall(header + payload)


def make_input_event(event_type, **kwargs):
    """Create an input event JSON payload."""
    event = {'type': event_type}
    event.update(kwargs)
    return json.dumps(event, separators=(',', ':')).encode('utf-8')


def parse_input_event(data):
    """Parse an input event from bytes."""
    return json.loads(data.decode('utf-8'))


def make_control_msg(cmd, **kwargs):
    """Create a control JSON payload."""
    msg = {'cmd': cmd}
    msg.update(kwargs)
    return json.dumps(msg, separators=(',', ':')).encode('utf-8')


def parse_control_msg(data):
    """Parse a control message from bytes."""
    return json.loads(data.decode('utf-8'))
