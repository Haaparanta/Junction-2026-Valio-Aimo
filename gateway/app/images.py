"""Uploaded photos for the photo-to-basket import (docs/basket-plan.md M28.1).

read_image() decides the media type and the pixel size from the bytes alone: the magic numbers and the
image headers. The filename and the Content-Type are the client's word and are never used. There is no
image library: the headers are parsed in pure Python and every read is bounds-checked, so any input
either parses or raises ImageError, whose short English message the route may pass on to the buyer.

The limits are the Claude API's (https://platform.claude.com/docs/en/build-with-claude/vision): JPEG,
PNG, GIF and WebP, and of an animation only the first frame is used; at most 10 MB per image once
base64-encoded, so 7,500,000 raw bytes; at most 8000 x 8000 px. Current models read up to a 2576 px
long edge and the API downscales larger images itself. The web app downscales and re-encodes as JPEG
before upload (M28.4), which also turns iPhone HEIC photos into JPEG.
"""

import re
import zlib
from typing import Literal

MAX_IMAGE_BYTES = 7_500_000  # 10 MB once base64-encoded: the Claude API's limit per image
MAX_SIDE = 8000  # px, for the width and the height alike


class ImageError(Exception):
    """A photo that is not sent on to Claude. The route turns it into HTTPException(status_code, message)."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message  # short, safe English: with passthrough errors the buyer may see or hear it


_EMPTY = "The photo is empty. Please take or choose the photo again."
_TOO_LARGE = f"The photo is too large. The limit is {MAX_IMAGE_BYTES / 1_000_000:g} MB."
_UNREADABLE = (
    "We could not read this photo: the file looks damaged or cut short. "
    "Please send it again, or save it as JPEG or PNG."
)
_NO_PIXELS = "The photo has a width or height of 0 pixels. Please take or choose the photo again."
_TOO_MANY_PIXELS = f"The photo is wider or taller than {MAX_SIDE} pixels. Please send a smaller photo."
_HEIC = (
    "HEIC photos are not supported. The web app converts them to JPEG automatically; "
    "otherwise save the photo as JPEG or PNG."
)
_AVIF = (
    "AVIF images are not supported. The web app converts them to JPEG automatically; "
    "otherwise save the image as JPEG or PNG."
)
_PDF = "PDF files are not supported. Please send a photo or a screenshot of the list as JPEG or PNG."
_SVG = "SVG images are not supported. Please save the image as JPEG or PNG."
_BMP = "BMP images are not supported. Please save the image as JPEG or PNG."
_TIFF = "TIFF images are not supported. Please save the image as JPEG or PNG."
_OTHER = "This file is not a supported image. Please send the photo as JPEG, PNG, WebP or GIF."


def read_image(data: bytes) -> tuple[str, int, int]:
    """The media type and the width and height in pixels of an uploaded photo, from its bytes alone.

    The media type is image/jpeg, image/png, image/gif or image/webp, and the size is as stored (an EXIF
    rotation is not applied). Raises ImageError: 413 when the data is empty or over MAX_IMAGE_BYTES (so
    read at most MAX_IMAGE_BYTES + 1 bytes of an upload), 415 for any other type and for headers that
    are cut short or malformed, 422 for a width or height of 0 or over MAX_SIDE.
    """
    if not data:
        raise ImageError(413, _EMPTY)
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageError(413, _TOO_LARGE)
    media_type, width, height = _sniff(data)
    if width == 0 or height == 0:
        raise ImageError(422, _NO_PIXELS)
    if width > MAX_SIDE or height > MAX_SIDE:
        raise ImageError(422, _TOO_MANY_PIXELS)
    return media_type, width, height


def _sniff(data: bytes) -> tuple[str, int, int]:
    if data.startswith(_JPEG_SOI):
        return "image/jpeg", *_jpeg_size(data)
    if data.startswith(_PNG_SIGNATURE):
        return "image/png", *_png_size(data)
    if data.startswith(_GIF_SIGNATURES):
        return "image/gif", *_gif_size(data)
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp", *_webp_size(data)
    raise ImageError(415, _not_supported(data))


def _unreadable() -> ImageError:
    return ImageError(415, _UNREADABLE)


def _uint(data: bytes, offset: int, size: int, order: Literal["big", "little"] = "big") -> int:
    """An unsigned integer from data[offset:offset + size]. A read past the end means the file is cut short."""
    if offset + size > len(data):
        raise _unreadable()
    return int.from_bytes(data[offset : offset + size], order)


# ---- JPEG ------------------------------------------------------------------------------------------

_JPEG_SOI = b"\xff\xd8\xff"  # SOI, then the 0xFF of the first marker
# Frame headers (SOFn), which carry the size: baseline, extended, progressive and lossless, and their
# differential and arithmetic-coded kinds. C4 (DHT), C8 (JPG) and CC (DAC) share the range but are no frames.
_JPEG_FRAMES = frozenset({0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF})
_JPEG_NO_LENGTH = frozenset({0x00, 0x01, *range(0xD0, 0xD8)})  # a stuffed FF 00, TEM and RST0-7 stand alone
_JPEG_NO_FRAME = frozenset({0xD8, 0xD9, 0xDA})  # SOI again, EOI, or SOS (a scan) before any frame header
_JPEG_MAX_MARKERS = 10_000  # a real photo has a few dozen before its frame header
_NOT_FF = re.compile(rb"[^\xff]")


def _jpeg_size(data: bytes) -> tuple[int, int]:
    """Walk the markers after SOI to the first frame header and read its width and height.

    Every other segment (APPn with EXIF and its thumbnail, ICC profiles, tables, comments) is skipped by
    its length, so a thumbnail's own frame header is never taken for the photo's. As in libjpeg, stray
    bytes between segments and 0xFF fill bytes before a marker are skipped.
    """
    i = 2
    for _ in range(_JPEG_MAX_MARKERS):
        i = data.find(b"\xff", i)
        found = _NOT_FF.search(data, i) if i >= 0 else None  # the marker byte after any fill bytes
        if found is None:
            raise _unreadable()
        marker, i = data[found.start()], found.start() + 1
        if marker in _JPEG_NO_LENGTH:
            continue
        if marker in _JPEG_NO_FRAME:
            raise _unreadable()
        length = _uint(data, i, 2)  # counts its own two bytes
        if marker in _JPEG_FRAMES:
            # Lf (2 bytes), P = precision (1), Y = lines (2), X = samples per line (2), Nf = components (1),
            # then 3 bytes per component.
            precision, components = _uint(data, i + 2, 1), _uint(data, i + 7, 1)
            if not 2 <= precision <= 16 or components == 0 or length != 8 + 3 * components:
                raise _unreadable()
            if i + length > len(data):
                raise _unreadable()
            return _uint(data, i + 5, 2), _uint(data, i + 3, 2)
        if length < 2:
            raise _unreadable()
        i += length
    raise _unreadable()


# ---- PNG -------------------------------------------------------------------------------------------

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_DEPTHS = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}  # by colour type


def _png_size(data: bytes) -> tuple[int, int]:
    """The IHDR chunk, which must come first: length 13, type, width, height, five one-byte fields, CRC."""
    crc = _uint(data, 29, 4)  # the chunk's last field: proves that all of it is there
    if _uint(data, 8, 4) != 13 or data[12:16] != b"IHDR" or zlib.crc32(data[12:29]) != crc:
        raise _unreadable()
    depth, colour, compression, filtering, interlace = data[24:29]
    if depth not in _PNG_DEPTHS.get(colour, ()) or compression != 0 or filtering != 0 or interlace > 1:
        raise _unreadable()
    return _uint(data, 16, 4), _uint(data, 20, 4)


# ---- GIF -------------------------------------------------------------------------------------------

_GIF_SIGNATURES = (b"GIF87a", b"GIF89a")


def _gif_size(data: bytes) -> tuple[int, int]:
    """The Logical Screen Descriptor after the signature: width and height (little-endian), then 3 bytes."""
    if len(data) < 13:
        raise _unreadable()
    return _uint(data, 6, 2, "little"), _uint(data, 8, 2, "little")


# ---- WebP ------------------------------------------------------------------------------------------


def _webp_size(data: bytes) -> tuple[int, int]:
    """The RIFF size, WEBP, then the first chunk: VP8 (lossy), VP8L (lossless) or VP8X (extended).

    The RIFF size must fit in the data, so a WebP cut short is refused here, as libwebp refuses to decode it.
    """
    riff_end = 8 + _uint(data, 4, 4, "little")
    if riff_end < 20 or riff_end > len(data):
        raise _unreadable()
    fourcc, size = data[12:16], _uint(data, 16, 4, "little")
    if 20 + size > riff_end:
        raise _unreadable()
    if fourcc == b"VP8 " and size >= 10:
        # Frame tag: bit 0 clear for a key frame, 3 bits of profile, a show bit, 19 bits of first partition
        # size. Then the start code 9D 01 2A and 14 bits each of width and height (the top 2 bits scale).
        tag = _uint(data, 20, 3, "little")
        key_frame, profile, shown, first_partition = not (tag & 1), (tag >> 1) & 7, (tag >> 4) & 1, tag >> 5
        if key_frame and profile <= 3 and shown and first_partition < size and data[23:26] == b"\x9d\x01\x2a":
            return _uint(data, 26, 2, "little") & 0x3FFF, _uint(data, 28, 2, "little") & 0x3FFF
    elif fourcc == b"VP8L" and size >= 5:
        # Signature 2F, then 14 bits of width - 1, 14 bits of height - 1, an alpha bit, 3 bits of version (0).
        bits = _uint(data, 21, 4, "little")
        if _uint(data, 20, 1) == 0x2F and bits >> 29 == 0:
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    elif fourcc == b"VP8X" and size == 10:
        # Flags (1 byte), reserved (3), then 24 bits each of canvas width - 1 and canvas height - 1.
        return _uint(data, 24, 3, "little") + 1, _uint(data, 27, 3, "little") + 1
    raise _unreadable()


# ---- everything else: a 415 that names the format when it is a common one ---------------------------

_SUPPORTED_MAGIC = (_JPEG_SOI, _PNG_SIGNATURE, *_GIF_SIGNATURES, b"RIFF")
# ISO-BMFF brands in the ftyp box. AVIF is HEIF with AV1 inside and carries HEIF brands too: it is checked first.
_AVIF_BRANDS = frozenset({b"avif", b"avis", b"avio"})
_HEIF_BRANDS = frozenset(
    {b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"hevm", b"hevs", b"mif1", b"msf1", b"mif2", b"miaf"}
)
_TIFF_SIGNATURES = (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+")  # little- and big-endian; classic and BigTIFF
_BMP_HEADER_SIZES = frozenset({12, 16, 40, 52, 56, 64, 108, 124})  # BITMAPCOREHEADER to BITMAPV5HEADER


def _not_supported(data: bytes) -> str:
    """The message for data that is no JPEG, PNG, GIF or WebP."""
    if any(len(data) < len(magic) and magic.startswith(data) for magic in _SUPPORTED_MAGIC) or (
        data.startswith(b"RIFF") and len(data) < 12
    ):
        return _UNREADABLE  # the start of a supported image, cut short
    if data[4:8] == b"ftyp":  # ISO-BMFF: HEIC or HEIF from a phone, AVIF, or a video
        brands = _ftyp_brands(data)
        if brands & _AVIF_BRANDS:
            return _AVIF
        if brands & _HEIF_BRANDS:
            return _HEIC
    if b"%PDF-" in data[:1024]:
        return _PDF
    if data.startswith(_TIFF_SIGNATURES):
        return _TIFF
    if data.startswith(b"BM") and int.from_bytes(data[14:18], "little") in _BMP_HEADER_SIZES:
        return _BMP
    head = data[:4096].removeprefix(b"\xef\xbb\xbf").lstrip()
    if head.startswith(b"<") and b"<svg" in head.lower():
        return _SVG
    return _OTHER


def _ftyp_brands(data: bytes) -> set[bytes]:
    """The major brand and the compatible brands of the ftyp box that opens an ISO-BMFF file."""
    end = min(len(data), max(int.from_bytes(data[:4], "big"), 16), 1024)
    return {data[8:12], *(data[i : i + 4] for i in range(16, end - 3, 4))}
