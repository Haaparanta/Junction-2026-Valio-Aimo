"""M28.1: read_image() takes the type and the pixel size from the bytes, never from the name or the Content-Type.

Every sample is built here by hand, with no binary files and no Pillow: small, well-formed headers and a
token body, since read_image() reads headers only. The route tests can import these builders.
"""

import base64
import inspect
import random
import struct
import zlib

import pytest
from app.images import MAX_IMAGE_BYTES, MAX_SIDE, ImageError, read_image

MEDIA_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
CUT_SHORT = "could not read"


def refused(data: bytes) -> ImageError:
    """The ImageError that read_image() raises for `data`."""
    with pytest.raises(ImageError) as e:
        read_image(data)
    return e.value


def outcome(data: bytes) -> int:
    """200 for a photo read within the limits, else the ImageError's status. Any other exception fails the test."""
    try:
        media_type, width, height = read_image(data)
    except ImageError as e:
        assert e.status_code in (413, 415, 422) and e.message and str(e) == e.message
        return e.status_code
    assert media_type in MEDIA_TYPES and 1 <= width <= MAX_SIDE and 1 <= height <= MAX_SIDE
    return 200


# ---- JPEG ------------------------------------------------------------------------------------------


def segment(marker: int, payload: bytes) -> bytes:
    """0xFF, the marker, a big-endian length that counts itself, then the payload."""
    return bytes([0xFF, marker]) + struct.pack(">H", len(payload) + 2) + payload


def frame(width: int, height: int, marker: int = 0xC0) -> bytes:
    """A frame header (SOFn) for 8-bit YCbCr: precision, lines (the height), samples per line (the width)."""
    components = b"\x01\x22\x00\x02\x11\x01\x03\x11\x01"  # Y sampled 2 x 2, Cb and Cr 1 x 1
    return segment(marker, struct.pack(">BHHB", 8, height, width, 3) + components)


JFIF = segment(0xE0, b"JFIF\x00\x01\x02\x00\x00\x01\x00\x01\x00\x00")
DQT = segment(0xDB, b"\x00" + bytes(range(1, 65)))
DHT = segment(0xC4, b"\x00" + bytes([0, 1, 5, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0]) + bytes(range(12)))
SOS = segment(0xDA, b"\x03\x01\x00\x02\x11\x03\x11\x00\x3f\x00")
SCAN = b"\xfa\x28\xa2\xff\x00\x8a\x28\xa0\x0f"  # entropy-coded data: a 0xFF in it is stuffed as FF 00
EOI = b"\xff\xd9"
ICC = segment(0xE2, b"ICC_PROFILE\x00\x01\x01" + bytes(500))  # APP2
COM = segment(0xFE, b"lista")
DRI = segment(0xDD, b"\x00\x10")  # restart interval


def jpeg(width: int, height: int, *, head: bytes = JFIF + DQT, marker: int = 0xC0) -> bytes:
    """SOI, the segments in `head`, the frame header, a Huffman table, one scan, EOI."""
    return b"\xff\xd8" + head + frame(width, height, marker) + DHT + SOS + SCAN + EOI


def exif(thumbnail: bytes) -> bytes:
    """APP1 EXIF: a big-endian TIFF header, IFD0 with an orientation, IFD1 pointing at a JPEG thumbnail."""
    ifd0 = struct.pack(">HHHII", 1, 0x0112, 3, 1, 6 << 16) + struct.pack(">I", 26)  # rotated 90 degrees
    ifd1 = struct.pack(">HHHIIHHII", 2, 0x0201, 4, 1, 56, 0x0202, 4, 1, len(thumbnail)) + struct.pack(">I", 0)
    return segment(0xE1, b"Exif\x00\x00" + b"MM\x00\x2a" + struct.pack(">I", 8) + ifd0 + ifd1 + thumbnail)


EXIF = exif(jpeg(160, 120))  # the thumbnail has a frame header of its own, which must not count


# ---- PNG -------------------------------------------------------------------------------------------

PNG = b"\x89PNG\r\n\x1a\n"


def chunk(kind: bytes, payload: bytes) -> bytes:
    """Length, type, data, and the CRC-32 of the type and the data."""
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))


def ihdr(width: int, height: int, depth=8, colour=2, compression=0, filtering=0, interlace=0) -> bytes:
    return chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, colour, compression, filtering, interlace))


IDAT = chunk(b"IDAT", zlib.compress(bytes(16)))
IEND = chunk(b"IEND", b"")


def png(width: int, height: int, *, depth=8, colour=2, interlace=0, extra: bytes = b"") -> bytes:
    """Signature, IHDR, any extra chunks, a token IDAT, IEND."""
    return PNG + ihdr(width, height, depth, colour, interlace=interlace) + extra + IDAT + IEND


def padded_png(total: int) -> bytes:
    """A 640 x 480 PNG of exactly `total` bytes: a private ancillary chunk after IHDR takes up the rest."""
    base = png(640, 480)
    return base[:33] + chunk(b"paDd", bytes(total - len(base) - 12)) + base[33:]


# ---- GIF -------------------------------------------------------------------------------------------


def gif(width: int, height: int, version: bytes = b"89a", *, frames: int = 1) -> bytes:
    """Signature, Logical Screen Descriptor with a 2-colour table, `frames` 1 x 1 images, trailer."""
    screen = struct.pack("<HHBBB", width, height, 0x80, 0, 0) + b"\x00\x00\x00\xff\xff\xff"
    image = b"\x2c" + struct.pack("<HHHHB", 0, 0, 1, 1, 0) + b"\x02\x02\x44\x01\x00"
    if frames > 1:  # a looping animation, each frame with a Graphic Control Extension
        screen += b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00"
        image = b"\x21\xf9\x04\x00\x0a\x00\x00\x00" + image
    return b"GIF" + version + screen + image * frames + b"\x3b"


# ---- WebP ------------------------------------------------------------------------------------------


def riff(*chunks: bytes) -> bytes:
    """RIFF, the size of what follows, WEBP, the chunks."""
    body = b"WEBP" + b"".join(chunks)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def webp_chunk(fourcc: bytes, payload: bytes) -> bytes:
    """FourCC, little-endian size, payload, and a pad byte when the size is odd."""
    return fourcc + struct.pack("<I", len(payload)) + payload + bytes(len(payload) % 2)


def vp8(width: int, height: int, *, tag: int = 1 << 4 | 24 << 5, start: bytes = b"\x9d\x01\x2a") -> bytes:
    """A lossy key frame: frame tag (key frame, profile 0, shown, a 24-byte first partition), start code, size."""
    return webp_chunk(b"VP8 ", tag.to_bytes(3, "little") + start + struct.pack("<HH", width, height) + bytes(24))


def vp8l(width: int, height: int, *, signature: int = 0x2F, alpha: bool = False, version: int = 0) -> bytes:
    """A lossless image: signature, then 14 bits each of width - 1 and height - 1, an alpha bit, a version."""
    bits = (width - 1) | (height - 1) << 14 | int(alpha) << 28 | version << 29
    return webp_chunk(b"VP8L", bytes([signature]) + struct.pack("<I", bits) + bytes(8))


def vp8x(width: int, height: int, flags: int = 0) -> bytes:
    """The extended header: flags, 3 reserved bytes, 24 bits each of canvas width - 1 and height - 1."""
    canvas = (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    return webp_chunk(b"VP8X", bytes([flags, 0, 0, 0]) + canvas)


def webp_lossy(width: int, height: int) -> bytes:
    return riff(vp8(width, height))


def webp_lossless(width: int, height: int) -> bytes:
    return riff(vp8l(width, height))


def webp_extended(width: int, height: int) -> bytes:
    """VP8X with an ICC profile and alpha, then the lossless image."""
    return riff(vp8x(width, height, 0x30), webp_chunk(b"ICCP", bytes(20)), vp8l(width, height, alpha=True))


def webp_animated(width: int, height: int, frames: int = 2) -> bytes:
    """VP8X with the animation flag, ANIM, then one ANMF per frame: offset, size, duration, flags, image."""
    size = (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    anmf = webp_chunk(b"ANMF", bytes(6) + size + (100).to_bytes(3, "little") + b"\x00" + vp8l(width, height))
    return riff(vp8x(width, height, 0x12), webp_chunk(b"ANIM", bytes(6)), anmf * frames)


# ---- formats that are refused ------------------------------------------------------------------------


def ftyp(major: bytes, *compatible: bytes) -> bytes:
    """An ISO-BMFF file: the ftyp box (major brand, minor version, compatible brands), then a meta box."""
    box = b"ftyp" + major + bytes(4) + b"".join(compatible)
    return struct.pack(">I", 4 + len(box)) + box + struct.pack(">I", 12) + b"meta" + bytes(4)


def bmp(width: int, height: int) -> bytes:
    """BITMAPFILEHEADER, a 40-byte BITMAPINFOHEADER, 24-bit rows padded to 4 bytes."""
    pixels = bytes((width * 3 + 3) // 4 * 4 * height)
    info = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0, len(pixels), 2835, 2835, 0, 0)
    return b"BM" + struct.pack("<IHHI", 14 + len(info) + len(pixels), 0, 0, 14 + len(info)) + info + pixels


HEIC = ftyp(b"heic", b"mif1", b"MiHE", b"miaf", b"MiHB", b"heic")  # the brands an iPhone writes
AVIF = ftyp(b"avif", b"avif", b"mif1", b"miaf", b"MA1B")
PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
SVG = b'<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20"/>\n'


# ---- what is read ----------------------------------------------------------------------------------

READ = [
    pytest.param(jpeg(640, 480), ("image/jpeg", 640, 480), id="jpeg-jfif"),
    pytest.param(jpeg(4032, 3024, head=EXIF + DQT), ("image/jpeg", 4032, 3024), id="jpeg-exif-app1-first"),
    pytest.param(
        jpeg(4032, 3024, head=EXIF + DQT, marker=0xC2), ("image/jpeg", 4032, 3024), id="jpeg-exif-progressive-sof2"
    ),
    pytest.param(jpeg(800, 600, head=JFIF + bytes(3) + DQT), ("image/jpeg", 800, 600), id="jpeg-stray-bytes"),
    pytest.param(jpeg(800, 600, head=JFIF + DQT + b"\xff\xff\xff"), ("image/jpeg", 800, 600), id="jpeg-fill-bytes"),
    pytest.param(jpeg(800, 600, head=JFIF + b"\xff\x01\xff\xd0" + DQT), ("image/jpeg", 800, 600), id="jpeg-standalone"),
    pytest.param(jpeg(800, 600, head=JFIF + ICC + COM + DQT + DRI), ("image/jpeg", 800, 600), id="jpeg-icc-com-dri"),
    pytest.param(jpeg(640, 480, head=segment(0xFE, b"x") * 200), ("image/jpeg", 640, 480), id="jpeg-200-comments"),
    pytest.param(jpeg(1, 1, head=b""), ("image/jpeg", 1, 1), id="jpeg-frame-right-after-soi"),
    pytest.param(png(640, 480), ("image/png", 640, 480), id="png-rgb"),
    pytest.param(png(1, 1, depth=1, colour=0), ("image/png", 1, 1), id="png-1-bit-grey"),
    pytest.param(png(300, 200, depth=16, colour=6, interlace=1), ("image/png", 300, 200), id="png-rgba-16-interlaced"),
    pytest.param(
        png(100, 50, depth=4, colour=3, extra=chunk(b"PLTE", bytes(48))), ("image/png", 100, 50), id="png-palette"
    ),
    pytest.param(
        png(400, 300, extra=chunk(b"acTL", struct.pack(">II", 3, 0))), ("image/png", 400, 300), id="png-animated"
    ),
    pytest.param(gif(320, 240, b"87a"), ("image/gif", 320, 240), id="gif87a"),
    pytest.param(gif(320, 240), ("image/gif", 320, 240), id="gif89a"),
    pytest.param(gif(480, 270, frames=3), ("image/gif", 480, 270), id="gif-animated"),
    pytest.param(webp_lossy(1024, 768), ("image/webp", 1024, 768), id="webp-vp8"),
    pytest.param(riff(vp8(0xC000 | 640, 0x4000 | 480)), ("image/webp", 640, 480), id="webp-vp8-scale-bits"),
    pytest.param(webp_lossless(300, 200), ("image/webp", 300, 200), id="webp-vp8l"),
    pytest.param(riff(vp8l(1, 1, alpha=True)), ("image/webp", 1, 1), id="webp-vp8l-1x1-alpha"),
    pytest.param(webp_extended(4000, 3000), ("image/webp", 4000, 3000), id="webp-vp8x"),
    pytest.param(webp_animated(480, 270), ("image/webp", 480, 270), id="webp-vp8x-animated"),
    pytest.param(webp_lossless(300, 200) + b"trailing", ("image/webp", 300, 200), id="webp-trailing-bytes"),
]


@pytest.mark.parametrize(("data", "expected"), READ)
def test_reads_the_type_and_the_size(data, expected):
    assert read_image(data) == expected


@pytest.mark.parametrize(
    "marker",
    [0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF],
    ids=lambda m: f"SOF{m - 0xC0}",
)
def test_every_kind_of_frame_header_gives_the_size(marker):
    assert read_image(jpeg(1600, 1200, marker=marker)) == ("image/jpeg", 1600, 1200)


@pytest.mark.parametrize("marker", [0xC4, 0xC8, 0xCC], ids=["DHT", "JPG", "DAC"])
def test_tables_in_the_frame_range_are_skipped(marker):
    decoy = segment(marker, struct.pack(">BHHB", 8, 7, 9, 1) + b"\x01\x11\x00")  # shaped like a 9 x 7 frame
    assert read_image(jpeg(640, 480, head=JFIF + decoy + DQT)) == ("image/jpeg", 640, 480)


def test_the_exif_thumbnail_is_not_the_photo():
    thumbnail_only = b"\xff\xd8" + EXIF  # no frame header outside the thumbnail
    assert read_image(jpeg(4032, 3024, head=EXIF)) == ("image/jpeg", 4032, 3024)
    assert refused(thumbnail_only).status_code == 415


# ---- the size limit --------------------------------------------------------------------------------


def test_exactly_max_image_bytes_is_read():
    data = padded_png(MAX_IMAGE_BYTES)
    assert len(data) == MAX_IMAGE_BYTES and len(base64.b64encode(data)) == 10_000_000  # the API's 10 MB
    assert read_image(data) == ("image/png", 640, 480)


def test_one_byte_more_is_413():
    e = refused(padded_png(MAX_IMAGE_BYTES + 1))
    assert e.status_code == 413 and e.message.startswith("The photo is too large.") and "7.5 MB" in e.message


def test_the_size_is_checked_before_the_type():
    assert refused(bytes(MAX_IMAGE_BYTES + 1)).status_code == 413


def test_empty_is_413():
    e = refused(b"")
    assert e.status_code == 413 and "empty" in e.message


# ---- width and height ------------------------------------------------------------------------------

BUILDERS = [jpeg, png, gif, webp_lossy, webp_lossless, webp_extended]


@pytest.mark.parametrize("build", BUILDERS, ids=lambda b: b.__name__)
def test_8000_by_8000_is_read(build):
    assert read_image(build(MAX_SIDE, MAX_SIDE))[1:] == (MAX_SIDE, MAX_SIDE)


@pytest.mark.parametrize("size", [(MAX_SIDE + 1, 600), (800, MAX_SIDE + 1)], ids=["wide", "tall"])
@pytest.mark.parametrize("build", BUILDERS, ids=lambda b: b.__name__)
def test_a_side_over_8000_is_422(build, size):
    e = refused(build(*size))
    assert e.status_code == 422 and "8000 pixels" in e.message


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(jpeg(65535, 65535), id="jpeg-max"),
        pytest.param(png(1 << 31, 1), id="png-2-to-the-31"),
        pytest.param(png(0xFFFFFFFF, 0xFFFFFFFF), id="png-max"),
        pytest.param(gif(65535, 1), id="gif-max"),
        pytest.param(riff(vp8(16383, 600)), id="webp-vp8-max"),
        pytest.param(riff(vp8l(16384, 16384)), id="webp-vp8l-max"),
        pytest.param(riff(vp8x(1 << 24, 1 << 24)), id="webp-vp8x-max"),
    ],
)
def test_the_largest_sizes_each_header_can_say_are_422(data):
    assert refused(data).status_code == 422


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(jpeg(0, 480), id="jpeg-width"),
        pytest.param(jpeg(640, 0), id="jpeg-height"),  # 0 lines would be set later by a DNL marker
        pytest.param(png(0, 480), id="png-width"),
        pytest.param(png(640, 0), id="png-height"),
        pytest.param(gif(0, 240), id="gif-width"),
        pytest.param(gif(320, 0), id="gif-height"),
        pytest.param(riff(vp8(0, 480)), id="webp-width"),
        pytest.param(riff(vp8(640, 0)), id="webp-height"),
    ],
)
def test_a_side_of_0_is_422(data):
    e = refused(data)
    assert e.status_code == 422 and "0 pixels" in e.message


# ---- types that are refused ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(HEIC, id="heic-iphone"),
        pytest.param(ftyp(b"heix", b"mif1", b"heix"), id="heix"),
        pytest.param(ftyp(b"hevc", b"msf1", b"hevc"), id="hevc-sequence"),
        pytest.param(ftyp(b"mif1", b"mif1", b"heic"), id="heif-mif1"),
        pytest.param(ftyp(b"msf1", b"msf1"), id="heif-msf1"),
        pytest.param(ftyp(b"MiHE", b"heic"), id="heic-as-a-compatible-brand"),
    ],
)
def test_heic_and_heif_are_415_with_the_way_out(data):
    e = refused(data)
    assert e.status_code == 415 and e.message.startswith("HEIC") and "converts them to JPEG" in e.message


def test_avif_is_415_and_not_called_heic():
    e = refused(AVIF)
    assert e.status_code == 415 and "AVIF" in e.message and "HEIC" not in e.message


@pytest.mark.parametrize(
    ("data", "named"),
    [
        pytest.param(PDF, "PDF", id="pdf"),
        pytest.param(b"\r\n" * 10 + b"%PDF-1.4\n", "PDF", id="pdf-after-junk"),
        pytest.param(SVG, "SVG", id="svg"),
        pytest.param(b"\xef\xbb\xbf \n" + SVG, "SVG", id="svg-bom-and-whitespace"),
        pytest.param(b'<!-- lista -->\n<svg xmlns="http://www.w3.org/2000/svg"/>', "SVG", id="svg-after-a-comment"),
        pytest.param(bmp(4, 4), "BMP", id="bmp"),
        pytest.param(b"II*\x00\x08\x00\x00\x00" + bytes(16), "TIFF", id="tiff-little-endian"),
        pytest.param(b"MM\x00*\x00\x00\x00\x08" + bytes(16), "TIFF", id="tiff-big-endian"),
        pytest.param(b"II+\x00\x08\x00\x00\x00" + bytes(16), "TIFF", id="bigtiff"),
        pytest.param(ftyp(b"isom", b"isom", b"mp41"), "not a supported image", id="mp4-video"),
        pytest.param(ftyp(b"qt  ", b"qt  "), "not a supported image", id="quicktime"),
        pytest.param(b"PK\x03\x04\x14\x00" + bytes(24), "not a supported image", id="zip-or-docx"),
        pytest.param(b"\x00\x00\x01\x00\x01\x00\x10\x10" + bytes(16), "not a supported image", id="ico"),
        pytest.param(b"\xff\x0a\xfa\x7f" + bytes(16), "not a supported image", id="jpeg-xl"),
        pytest.param(b"\x00\x00\x00\x0cjP  \r\n\x87\n" + bytes(16), "not a supported image", id="jpeg-2000"),
        pytest.param(b"RIFF\x24\x00\x00\x00WAVEfmt " + bytes(28), "not a supported image", id="wav"),
        pytest.param(b"\x1f\x8b\x08\x00" + bytes(16), "not a supported image", id="gzip-or-svgz"),
        pytest.param(b"BMW 320d, 2 kpl\n", "not a supported image", id="text-that-starts-with-bm"),
        pytest.param(b"maito 20 l\nvoi 5 kg\n", "not a supported image", id="text"),
        pytest.param(b"<html><body>maito 20 l</body></html>", "not a supported image", id="html"),
        pytest.param(b"GIF88a" + bytes(16), "not a supported image", id="gif-unknown-version"),
    ],
)
def test_other_types_are_415_and_named(data, named):
    e = refused(data)
    assert e.status_code == 415 and named in e.message and "JPEG" in e.message


# ---- headers that are cut short or malformed: 415 "could not read" --------------------------------

BROKEN = [
    pytest.param(b"\xff\xd8\xff", id="jpeg-soi-only"),
    pytest.param(b"\xff\xd8" + JFIF + DQT, id="jpeg-no-frame-header"),
    pytest.param(b"\xff\xd8" + JFIF + DQT + SOS + SCAN + EOI, id="jpeg-scan-before-the-frame"),
    pytest.param(b"\xff\xd8" + JFIF + EOI, id="jpeg-eoi-before-the-frame"),
    pytest.param(b"\xff\xd8\xff\xd8" + JFIF + frame(640, 480), id="jpeg-second-soi"),
    pytest.param(b"\xff\xd8\xff\xe0\x00\x01" + bytes(20), id="jpeg-segment-length-1"),
    pytest.param(b"\xff\xd8\xff\xe0\x00\x00" + bytes(20), id="jpeg-segment-length-0"),
    pytest.param(
        b"\xff\xd8" + JFIF + segment(0xC0, struct.pack(">BHHB", 8, 480, 640, 3) + b"\x01\x22\x00") + SOS + EOI,
        id="jpeg-frame-length-not-8-plus-3-per-component",
    ),
    pytest.param(b"\xff\xd8" + JFIF + segment(0xC0, struct.pack(">BHHB", 8, 480, 640, 0)), id="jpeg-no-components"),
    pytest.param(
        b"\xff\xd8" + JFIF + segment(0xC0, struct.pack(">BHHB", 0, 480, 640, 1) + b"\x01\x11\x00"),
        id="jpeg-precision-0",
    ),
    pytest.param(b"\xff\xd8" + JFIF + segment(0xE1, bytes(100))[:50], id="jpeg-cut-inside-app1"),
    pytest.param(b"\xff\xd8" + b"\xff" * 1000, id="jpeg-fill-bytes-to-the-end"),
    pytest.param(jpeg(640, 480, head=segment(0xFE, b"x") * 20_000), id="jpeg-frame-after-20000-segments"),
    pytest.param(PNG, id="png-signature-only"),
    pytest.param(png(640, 480)[:32], id="png-cut-in-the-ihdr-crc"),
    pytest.param(PNG + ihdr(640, 480)[:-4] + b"\x00\x00\x00\x00" + IDAT + IEND, id="png-wrong-ihdr-crc"),
    pytest.param(PNG + chunk(b"CgBI", b"\x50\x00\x20\x06") + ihdr(640, 480) + IDAT + IEND, id="png-ihdr-not-first"),
    pytest.param(PNG + chunk(b"IHDR", struct.pack(">IIBBBBBB", 640, 480, 8, 2, 0, 0, 0, 0)) + IEND, id="png-ihdr-14"),
    pytest.param(PNG + ihdr(640, 480, depth=4, colour=2) + IDAT + IEND, id="png-rgb-at-4-bits"),
    pytest.param(PNG + ihdr(640, 480, colour=5) + IDAT + IEND, id="png-colour-type-5"),
    pytest.param(PNG + ihdr(640, 480, compression=1) + IDAT + IEND, id="png-compression-1"),
    pytest.param(PNG + ihdr(640, 480, filtering=1) + IDAT + IEND, id="png-filter-method-1"),
    pytest.param(PNG + ihdr(640, 480, interlace=2) + IDAT + IEND, id="png-interlace-2"),
    pytest.param(b"GIF89a", id="gif-signature-only"),
    pytest.param(gif(320, 240)[:12], id="gif-cut-in-the-screen-descriptor"),
    pytest.param(webp_lossless(300, 200)[:-1], id="webp-shorter-than-its-riff-size"),
    pytest.param(b"RIFF" + struct.pack("<I", 4) + b"WEBP" + vp8l(300, 200), id="webp-riff-size-too-small"),
    pytest.param(b"RIFF" + struct.pack("<I", 0xFFFFFFFF) + b"WEBP" + vp8l(300, 200), id="webp-riff-size-huge"),
    pytest.param(riff(b"VP8L" + struct.pack("<I", 1000) + vp8l(300, 200)[8:]), id="webp-chunk-past-the-riff"),
    pytest.param(riff(webp_chunk(b"ALPH", bytes(10)), vp8(640, 480)), id="webp-first-chunk-alph"),
    pytest.param(riff(webp_chunk(b"VP8 ", bytes(5))), id="webp-vp8-too-small"),
    pytest.param(riff(vp8(640, 480, start=b"\x9d\x01\x2b")), id="webp-vp8-wrong-start-code"),
    pytest.param(riff(vp8(640, 480, tag=1 | 1 << 4 | 24 << 5)), id="webp-vp8-not-a-key-frame"),
    pytest.param(riff(vp8(640, 480, tag=4 << 1 | 1 << 4 | 24 << 5)), id="webp-vp8-profile-4"),
    pytest.param(riff(vp8(640, 480, tag=24 << 5)), id="webp-vp8-not-shown"),
    pytest.param(riff(vp8(640, 480, tag=1 << 4 | 34 << 5)), id="webp-vp8-partition-past-the-chunk"),
    pytest.param(riff(vp8l(300, 200, signature=0x2E)), id="webp-vp8l-wrong-signature"),
    pytest.param(riff(vp8l(300, 200, version=1)), id="webp-vp8l-version-1"),
    pytest.param(riff(webp_chunk(b"VP8L", b"\x2f\x00\x00")), id="webp-vp8l-too-small"),
    pytest.param(riff(webp_chunk(b"VP8X", bytes(12))), id="webp-vp8x-not-10-bytes"),
    pytest.param(b"\xff", id="jpeg-first-byte"),
    pytest.param(b"\xff\xd8", id="jpeg-soi-without-a-marker"),
    pytest.param(b"\x89PNG\r\n", id="png-part-of-the-signature"),
    pytest.param(b"GIF8", id="gif-part-of-the-signature"),
    pytest.param(b"RIF", id="riff-part-of-the-signature"),
    pytest.param(b"RIFF\x10\x00\x00\x00WEB", id="webp-part-of-the-signature"),
]


@pytest.mark.parametrize("data", BROKEN)
def test_cut_short_or_malformed_headers_are_415(data):
    e = refused(data)
    assert e.status_code == 415 and CUT_SHORT in e.message


def test_megabytes_of_padding_are_refused():
    assert refused(b"\xff\xd8" + b"\xff" * (MAX_IMAGE_BYTES - 2)).status_code == 415
    assert refused(b"\xff\xd8" + b"\xff\xfe\x00\x02" * ((MAX_IMAGE_BYTES - 2) // 4)).status_code == 415


# ---- fuzzing: cut, flipped and random bytes give an image or an ImageError, nothing else -----------

# name: (data, where its header ends; None when the RIFF size covers the whole file)
SAMPLES = {
    "jpeg": (jpeg(640, 480), 2 + len(JFIF + DQT + frame(640, 480))),
    "jpeg-exif-progressive": (
        jpeg(4032, 3024, head=EXIF + DQT, marker=0xC2),
        2 + len(EXIF + DQT + frame(4032, 3024, 0xC2)),
    ),
    "png": (png(640, 480, extra=chunk(b"tEXt", b"Comment\x00lista")), 33),
    "gif87a": (gif(320, 240, b"87a"), 13),
    "gif89a-animated": (gif(320, 240, frames=3), 13),
    "webp-lossy": (webp_lossy(1024, 768), None),
    "webp-lossless": (webp_lossless(300, 200), None),
    "webp-extended": (webp_extended(4000, 3000), None),
    "webp-animated": (webp_animated(480, 270), None),
}


@pytest.mark.parametrize("name", SAMPLES)
def test_every_cut_is_refused_until_the_header_is_whole_and_read_after(name):
    data, header_end = SAMPLES[name]
    header_end = header_end or len(data)
    whole = read_image(data)
    for n in range(1, len(data)):
        if n < header_end:
            e = refused(data[:n])
            assert e.status_code == 415 and CUT_SHORT in e.message, n
        else:
            assert read_image(data[:n]) == whole, n


@pytest.mark.parametrize("name", SAMPLES)
def test_flipped_bytes_give_an_image_or_an_image_error(name):
    data, _ = SAMPLES[name]
    seen = set()
    for at in range(len(data)):
        for mask in (0x01, 0x10, 0x80, 0xFF):
            flipped = bytearray(data)
            flipped[at] ^= mask
            seen.add(outcome(bytes(flipped)))
    assert {200, 415} <= seen


def test_random_damage_gives_an_image_or_an_image_error():
    rng = random.Random(281)  # noqa: S311 (reproducible fuzzing, not security)
    samples = [data for data, _ in SAMPLES.values()]
    seen = set()
    for _ in range(3000):
        data = bytearray(rng.choice(samples))
        for _ in range(rng.randint(1, 6)):
            op, at = rng.randrange(4), rng.randrange(len(data) + 1)
            if op == 0 and at < len(data):
                data[at] = rng.randrange(256)
            elif op == 1:
                data[at:at] = rng.randbytes(rng.randint(1, 8))
            elif op == 2:
                del data[at : at + rng.randint(1, 8)]
            else:
                del data[at:]
        seen.add(outcome(bytes(data)))
    assert {200, 415} <= seen


PREFIXES = [
    b"",
    b"\xff\xd8\xff",
    b"\xff\xd8\xff\xc0",
    PNG,
    PNG + b"\x00\x00\x00\x0dIHDR",
    b"GIF87a",
    b"GIF89a",
    b"RIFF",
    b"RIFF\x40\x00\x00\x00WEBP",
    b"RIFF\x40\x00\x00\x00WEBPVP8 ",
    b"RIFF\x40\x00\x00\x00WEBPVP8L",
    b"RIFF\x40\x00\x00\x00WEBPVP8X",
    b"\x00\x00\x00\x18ftyp",
    b"%PDF-",
    b"BM",
    b"II*\x00",
    b"<",
]


def test_random_bytes_after_a_magic_number_give_an_image_or_an_image_error():
    rng = random.Random(2026)  # noqa: S311 (reproducible fuzzing, not security)
    for _ in range(5000):
        outcome(rng.choice(PREFIXES) + rng.randbytes(rng.randrange(96)))


def test_random_jpeg_segments_give_an_image_or_an_image_error():
    rng = random.Random(1992)  # noqa: S311 (reproducible fuzzing, not security)
    seen = set()
    for _ in range(3000):
        parts = [b"\xff\xd8"]
        for _ in range(rng.randrange(10)):
            marker, kind = rng.randrange(256), rng.randrange(4)
            if kind == 0:
                parts.append(bytes([0xFF, marker]))
            elif kind == 1:
                parts.append(segment(marker, rng.randbytes(rng.randrange(24))))
            elif kind == 2:
                parts.append(frame(rng.randrange(1 << 16), rng.randrange(1 << 16), marker))
            else:
                parts.append(rng.randbytes(rng.randrange(8)))
        seen.add(outcome(b"".join(parts)))
    assert {200, 415, 422} <= seen


# ---- what the client says does not count -----------------------------------------------------------


def test_the_filename_and_the_content_type_do_not_count():
    """read_image() never sees them. The client's claims below are what a lying upload would send."""
    assert list(inspect.signature(read_image).parameters) == ["data"]
    uploads = [
        ("IMG_0001.JPG", "image/jpeg", png(640, 480), ("image/png", 640, 480)),
        ("lista.png", "image/png", jpeg(1200, 1600), ("image/jpeg", 1200, 1600)),
        ("kuva.gif", "image/gif", webp_lossless(300, 200), ("image/webp", 300, 200)),
    ]
    for _filename, _content_type, data, expected in uploads:
        assert read_image(data) == expected
    refusals = [("lista.png", "image/png", PDF, "PDF"), ("IMG_0002.JPG", "image/jpeg", HEIC, "HEIC")]
    for _filename, _content_type, data, named in refusals:
        e = refused(data)
        assert e.status_code == 415 and named in e.message


def test_each_refusal_is_one_short_plain_english_sentence_or_two():
    samples = [
        b"",
        bytes(MAX_IMAGE_BYTES + 1),
        HEIC,
        AVIF,
        PDF,
        SVG,
        bmp(2, 2),
        b"II*\x00" + bytes(8),
        b"maito 20 l",
        b"\x89PNG",
        png(0, 1),
        png(MAX_SIDE + 1, 1),
    ]
    errors = [refused(data) for data in samples]
    assert len({e.message for e in errors}) == len(samples)  # each says what is wrong with this file
    for e in errors:
        assert isinstance(e, Exception) and str(e) == e.message
        assert e.message.isascii() and e.message[0].isupper() and e.message.endswith(".") and len(e.message) <= 130
