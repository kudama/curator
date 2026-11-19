"""Validate the normalized, non-interlaced 8-bit PNGs produced by our editor."""

import base64
import struct
import zlib
from .errors import UserError


def editor_png(encoded, ratio=None, logo=False):
    try:
        data = base64.b64decode(encoded, validate=True)
    except (TypeError, ValueError):
        raise UserError('Choose a valid normalized PNG') from None
    if len(data) > 10 * 1024 * 1024 or not data.startswith(b'\x89PNG\r\n\x1a\n'):
        raise UserError('Editor images must be PNG under 10 MiB')
    pos, chunks, header, ended = 8, [], None, False
    while pos + 12 <= len(data):
        length = struct.unpack('>I', data[pos : pos + 4])[0]
        kind = data[pos + 4 : pos + 8]
        end = pos + 12 + length
        if end > len(data):
            raise UserError('Incomplete PNG image')
        body = data[pos + 8 : pos + 8 + length]
        if zlib.crc32(kind + body) & 0xFFFFFFFF != struct.unpack('>I', data[pos + 8 + length : end])[0]:
            raise UserError('Invalid PNG checksum')
        if kind == b'IHDR':
            if header is not None or length != 13 or pos != 8:
                raise UserError('Invalid PNG header')
            header = struct.unpack('>IIBBBBB', body)
        elif kind == b'IDAT':
            chunks.append(body)
        elif kind == b'IEND':
            ended = True
            break
        pos = end
    if not header or not ended:
        raise UserError('Incomplete PNG image')
    width, height, depth, color, compression, filtering, interlace = header
    if (
        not 1 <= width <= 4096
        or not 1 <= height <= 4096
        or width * height > 8_000_000
        or depth != 8
        or color not in {2, 6}
        or compression
        or filtering
        or interlace
    ):
        raise UserError('Use the editor to normalize the image format')
    if ratio:
        w, h = map(int, ratio.split(':'))
        if width * h != height * w:
            raise UserError('Image pixels do not match the selected artwork format')
    channels = 4 if color == 6 else 3
    stride = width * channels
    expected = (stride + 1) * height
    decoder = zlib.decompressobj()
    try:
        raw = decoder.decompress(b''.join(chunks), expected + 1)
    except zlib.error:
        raise UserError('Invalid PNG pixels') from None
    if len(raw) != expected or not decoder.eof:
        raise UserError('Invalid PNG pixel length')
    if any(raw[y * (stride + 1)] > 4 for y in range(height)):
        raise UserError('Invalid PNG filter')
    if logo:
        if channels != 4:
            raise UserError('A logo needs a transparent PNG background')
        previous = bytearray(stride)
        transparent = False
        visible = False
        for y in range(height):
            offset = y * (stride + 1)
            method = raw[offset]
            row = bytearray(raw[offset + 1 : offset + 1 + stride])
            if method > 4:
                raise UserError('Invalid PNG filter')
            for i in range(stride):
                left = row[i - channels] if i >= channels else 0
                up = previous[i]
                corner = previous[i - channels] if i >= channels else 0
                if method == 1:
                    predict = left
                elif method == 2:
                    predict = up
                elif method == 3:
                    predict = (left + up) // 2
                elif method == 4:
                    p = left + up - corner
                    a, b, c = abs(p - left), abs(p - up), abs(p - corner)
                    predict = left if a <= b and a <= c else up if b <= c else corner
                else:
                    predict = 0
                row[i] = (row[i] + predict) & 255
            if any(row[i] < 255 for i in range(3, stride, 4)):
                transparent = True
            if any(row[i] > 0 for i in range(3, stride, 4)):
                visible = True
            previous = row
        if not visible:
            raise UserError('This image has no visible pixels; choose a font or artwork that renders visible lettering')
        if not transparent:
            raise UserError('The logo is opaque; choose artwork with a transparent background')
    return dict(width=width, height=height, alpha=color == 6)
