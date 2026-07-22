"""Protobuf 编解码

Aily Workbench WebSocket 使用自定义 protobuf frame 协议（subprotocol: pbbp2）。
本模块实现 frame 的手工编解码，无需依赖 protobuf 库。

Frame 结构（field_num → 含义）：
  1 (varint)  → seq_id
  2 (varint)  → log_id
  3 (varint)  → service
  4 (varint)  → method
  5 (bytes)   → headers (repeated, 每项为子消息: 1→key, 2→value)
  6 (bytes)   → payload
  12 (varint) → frame_type
"""


def encode_varint(value: int) -> bytes:
    """编码 varint"""
    buf = bytearray()
    while value > 0:
        b = value & 0x7F
        value >>= 7
        if value > 0:
            b |= 0x80
        buf.append(b)
    if not buf:
        buf.append(0)
    return bytes(buf)


def decode_varint(data: bytes, offset: int) -> tuple:
    """解码 varint，返回 (value, next_offset)"""
    result = 0
    shift = 0
    while offset < len(data):
        b = data[offset]
        result |= (b & 0x7F) << shift
        offset += 1
        if not (b & 0x80):
            break
        shift += 7
    return result, offset


def encode_tag(field_num: int, wire_type: int) -> bytes:
    """编码 field tag"""
    return encode_varint((field_num << 3) | wire_type)


def encode_frame(
    seq_id=None,
    log_id=None,
    service=None,
    method=None,
    headers=None,
    payload=None,
    frame_type=None,
) -> bytes:
    """编码完整 frame 为 bytes"""
    parts = []
    if seq_id is not None:
        parts.append(encode_tag(1, 0) + encode_varint(seq_id))
    if log_id is not None:
        parts.append(encode_tag(2, 0) + encode_varint(log_id))
    if service is not None:
        parts.append(encode_tag(3, 0) + encode_varint(service))
    if method is not None:
        parts.append(encode_tag(4, 0) + encode_varint(method))
    if headers:
        for h in headers:
            sub = bytearray()
            key = (
                h.get("key", "").encode("utf-8")
                if isinstance(h.get("key"), str)
                else b""
            )
            val = (
                h.get("value", "").encode("utf-8")
                if isinstance(h.get("value"), str)
                else b""
            )
            sub += encode_tag(1, 2) + encode_varint(len(key)) + key
            sub += encode_tag(2, 2) + encode_varint(len(val)) + val
            parts.append(encode_tag(5, 2) + encode_varint(len(sub)) + bytes(sub))
    if payload:
        parts.append(encode_tag(6, 2) + encode_varint(len(payload)) + payload)
    if frame_type is not None:
        parts.append(encode_tag(12, 0) + encode_varint(frame_type))
    return b"".join(parts)


def decode_frame(data: bytes) -> dict:
    """解码 bytes 为 frame dict"""
    frame = {"headers": []}
    offset = 0
    while offset < len(data):
        tag, offset = decode_varint(data, offset)
        field_num = tag >> 3
        wire_type = tag & 7
        if wire_type == 0:
            val, offset = decode_varint(data, offset)
            if field_num == 1:
                frame["seq_id"] = val
            elif field_num == 2:
                frame["log_id"] = val
            elif field_num == 3:
                frame["service"] = val
            elif field_num == 4:
                frame["method"] = val
            elif field_num == 12:
                frame["frame_type"] = val
        elif wire_type == 2:
            length, offset = decode_varint(data, offset)
            raw = data[offset : offset + length]
            offset += length
            if field_num == 5:
                header = {}
                ho = 0
                while ho < len(raw):
                    htag, ho = decode_varint(raw, ho)
                    hfn = htag >> 3
                    hwt = htag & 7
                    if hwt == 2:
                        hlen, ho = decode_varint(raw, ho)
                        hval = raw[ho : ho + hlen]
                        ho += hlen
                        if hfn == 1:
                            header["key"] = hval.decode("utf-8", errors="replace")
                        elif hfn == 2:
                            header["value"] = hval.decode("utf-8", errors="replace")
                    elif hwt == 0:
                        hval, ho = decode_varint(raw, ho)
                        if hfn == 1:
                            header["key"] = str(hval)
                        elif hfn == 2:
                            header["value"] = str(hval)
                frame["headers"].append(header)
            elif field_num == 6:
                frame["payload"] = raw
        elif wire_type == 5:
            offset += 4
        elif wire_type == 1:
            offset += 8
        else:
            break
    return frame
