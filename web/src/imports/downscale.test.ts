import { afterEach, describe, expect, it, vi } from "vitest";
import { JPEG_QUALITY, MAX_EDGE, MAX_PIXELS, PhotoReadError, UNREADABLE_PHOTO, downscaleToJpeg, fitWithin } from "./downscale";

describe("fitWithin", () => {
  it("keeps a small image as it is: never upscales", () => {
    expect(fitWithin(640, 480)).toEqual({ width: 640, height: 480, scale: 1 });
    expect(fitWithin(1, 1)).toEqual({ width: 1, height: 1, scale: 1 });
    expect(fitWithin(10, 3)).toEqual({ width: 10, height: 3, scale: 1 });
  });

  it("shrinks a 12 MP phone photo below the area limit, portrait and landscape alike", () => {
    const portrait = fitWithin(3024, 4032);
    expect(portrait).toMatchObject({ width: 1677, height: 2236 });
    expect(fitWithin(4032, 3024)).toMatchObject({ width: 2236, height: 1677 });
    expect(portrait.width * portrait.height).toBeLessThanOrEqual(MAX_PIXELS);
  });

  it("shrinks a square to the area limit", () => {
    expect(fitWithin(4000, 4000)).toMatchObject({ width: 1936, height: 1936 }); // 1936² = 3,748,096
  });

  it("lets the long edge limit bind on a wide image", () => {
    expect(fitWithin(5152, 2000)).toEqual({ width: 2576, height: 1000, scale: 0.5 });
    expect(fitWithin(2577, 100)).toMatchObject({ width: 2576, height: 99 });
  });

  it("lets the area limit bind when the long edge is already fine", () => {
    const f = fitWithin(2500, 2000); // 5 MP
    expect(f.width).toBeLessThan(2500);
    expect(f.width * f.height).toBeLessThanOrEqual(MAX_PIXELS);
    expect(f.width * f.height).toBeGreaterThan(MAX_PIXELS * 0.998);
  });

  it("keeps images exactly at the limits", () => {
    expect(fitWithin(2576, 1455)).toEqual({ width: 2576, height: 1455, scale: 1 }); // 3,748,080 px
    expect(fitWithin(1500, 2500)).toEqual({ width: 1500, height: 2500, scale: 1 }); // exactly 3,750,000 px
    expect(fitWithin(MAX_EDGE, 1)).toEqual({ width: MAX_EDGE, height: 1, scale: 1 });
  });

  it("shrinks an image one pixel over a limit", () => {
    const f = fitWithin(2576, 1456); // 3,750,656 px
    expect(f.scale).toBeLessThan(1);
    expect(f.width * f.height).toBeLessThanOrEqual(MAX_PIXELS);
    expect(fitWithin(2577, 1000).width).toBe(MAX_EDGE);
  });

  it("brings a huge image down to the limits", () => {
    expect(fitWithin(20000, 15000)).toMatchObject({ width: 2236, height: 1677 });
    expect(fitWithin(100000, 10)).toMatchObject({ width: 2576, height: 1 }); // never below 1 px
  });

  it("refuses sizes that are not an image", () => {
    for (const [w, h] of [[0, 100], [100, 0], [-5, 10], [Number.NaN, 10], [10, Number.POSITIVE_INFINITY]] as const) {
      expect(() => fitWithin(w, h)).toThrow(RangeError);
    }
  });

  it("keeps every limit and the shape for any size", () => {
    const sides = [1, 2, 7, 99, 100, 1455, 1456, 1936, 1937, 2575, 2576, 2577, 3000, 4032, 6048, 8000, 12000, 50000];
    for (const w of sides) {
      for (const h of sides) {
        const f = fitWithin(w, h);
        expect(Number.isInteger(f.width) && Number.isInteger(f.height)).toBe(true);
        expect(f.width).toBeGreaterThanOrEqual(1);
        expect(f.height).toBeGreaterThanOrEqual(1);
        expect(f.width).toBeLessThanOrEqual(w); // never upscale
        expect(f.height).toBeLessThanOrEqual(h);
        expect(Math.max(f.width, f.height)).toBeLessThanOrEqual(MAX_EDGE);
        expect(f.width * f.height).toBeLessThanOrEqual(MAX_PIXELS);
        expect(Math.abs(f.width - w * f.scale)).toBeLessThan(1); // one scale for both sides: the shape is kept
        expect(Math.abs(f.height - h * f.scale)).toBeLessThan(1);
      }
    }
  });
});

// ---- downscaleToJpeg, with the browser's image APIs replaced by fakes (jsdom has no canvas) ----

type Call = [string, ...unknown[]];

function fakeContext(calls: Call[]) {
  return {
    fillStyle: "",
    imageSmoothingEnabled: false,
    imageSmoothingQuality: "low",
    fillRect: (...a: unknown[]) => calls.push(["fillRect", ...a]),
    drawImage: (...a: unknown[]) => calls.push(["drawImage", ...a]),
  };
}

class FakeOffscreenCanvas {
  static made: FakeOffscreenCanvas[] = [];
  calls: Call[] = [];
  ctx = fakeContext(this.calls);
  options: { type?: string; quality?: number } | null = null;
  constructor(public width: number, public height: number) {
    FakeOffscreenCanvas.made.push(this);
    this.calls.push(["size", width, height]);
  }
  getContext() {
    return this.ctx;
  }
  convertToBlob(options: { type?: string; quality?: number }) {
    this.options = options;
    return Promise.resolve(new Blob(["jpeg bytes"], { type: options.type ?? "image/png" }));
  }
}

function fakeBitmap(width: number, height: number) {
  return { width, height, close: vi.fn() };
}

const urls = { created: [] as string[], revoked: [] as string[] };
const realCreate = URL.createObjectURL;
const realRevoke = URL.revokeObjectURL;

function stubObjectUrls() {
  URL.createObjectURL = (() => {
    const u = `blob:fake-${urls.created.length}`;
    urls.created.push(u);
    return u;
  }) as typeof URL.createObjectURL;
  URL.revokeObjectURL = ((u: string) => void urls.revoked.push(u)) as typeof URL.revokeObjectURL;
}

/** An <img> that loads with the given natural size, or fails when the size is null. */
function fakeImage(size: { width: number; height: number } | null) {
  return class {
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    decoding = "";
    naturalWidth = 0;
    naturalHeight = 0;
    set src(_: string) {
      queueMicrotask(() => {
        if (!size) return this.onerror?.();
        this.naturalWidth = size.width;
        this.naturalHeight = size.height;
        this.onload?.();
      });
    }
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  FakeOffscreenCanvas.made = [];
  urls.created = [];
  urls.revoked = [];
  URL.createObjectURL = realCreate;
  URL.revokeObjectURL = realRevoke;
});

describe("downscaleToJpeg", () => {
  const photo = new Blob(["raw photo"], { type: "image/jpeg" });

  it("decodes upright, draws at the fitted size on white and encodes a 0.85 JPEG", async () => {
    const bitmap = fakeBitmap(4032, 3024);
    const createImageBitmap = vi.fn().mockResolvedValue(bitmap);
    vi.stubGlobal("createImageBitmap", createImageBitmap);
    vi.stubGlobal("OffscreenCanvas", FakeOffscreenCanvas);

    const out = await downscaleToJpeg(photo);

    expect(out.type).toBe("image/jpeg");
    expect(createImageBitmap).toHaveBeenCalledWith(photo, { imageOrientation: "from-image" });
    const canvas = FakeOffscreenCanvas.made[0]!;
    expect(canvas.calls).toEqual([
      ["size", 2236, 1677],
      ["fillRect", 0, 0, 2236, 1677],
      ["drawImage", bitmap, 0, 0, 2236, 1677],
    ]);
    expect(canvas.ctx.fillStyle).toBe("#ffffff");
    expect(canvas.options).toEqual({ type: "image/jpeg", quality: JPEG_QUALITY });
    expect(bitmap.close).toHaveBeenCalledOnce(); // released
    expect([canvas.width, canvas.height]).toEqual([0, 0]); // canvas memory freed for iOS
  });

  it("re-encodes a small image too, at its own size", async () => {
    vi.stubGlobal("createImageBitmap", vi.fn().mockResolvedValue(fakeBitmap(800, 600)));
    vi.stubGlobal("OffscreenCanvas", FakeOffscreenCanvas);
    await downscaleToJpeg(new Blob(["png"], { type: "image/png" }));
    expect(FakeOffscreenCanvas.made[0]!.calls[0]).toEqual(["size", 800, 600]);
  });

  it("falls back to an <img> when createImageBitmap cannot decode (Safari and HEIC), and revokes its URL", async () => {
    vi.stubGlobal("createImageBitmap", vi.fn().mockRejectedValue(new DOMException("cannot decode")));
    vi.stubGlobal("OffscreenCanvas", FakeOffscreenCanvas);
    vi.stubGlobal("Image", fakeImage({ width: 3024, height: 4032 }));
    stubObjectUrls();

    const out = await downscaleToJpeg(new Blob(["heic"], { type: "image/heic" }));

    expect(out.type).toBe("image/jpeg");
    expect(FakeOffscreenCanvas.made[0]!.calls[0]).toEqual(["size", 1677, 2236]);
    expect(urls.revoked).toEqual(urls.created);
    expect(urls.created).toHaveLength(1);
  });

  it("asks for a JPEG or PNG when the browser cannot read the photo at all (HEIC in Chrome)", async () => {
    vi.stubGlobal("createImageBitmap", vi.fn().mockRejectedValue(new DOMException("cannot decode")));
    vi.stubGlobal("OffscreenCanvas", FakeOffscreenCanvas);
    vi.stubGlobal("Image", fakeImage(null));
    stubObjectUrls();

    const failure = downscaleToJpeg(new Blob(["heic"], { type: "image/heic" }));
    await expect(failure).rejects.toBeInstanceOf(PhotoReadError);
    await expect(failure).rejects.toThrow(UNREADABLE_PHOTO);
    expect(UNREADABLE_PHOTO).toMatch(/JPEG or PNG/);
    expect(urls.revoked).toEqual(urls.created);
    expect(FakeOffscreenCanvas.made).toHaveLength(0);
  });

  it("uses a canvas element when OffscreenCanvas is missing", async () => {
    const bitmap = fakeBitmap(5152, 2000);
    vi.stubGlobal("createImageBitmap", vi.fn().mockResolvedValue(bitmap));
    vi.stubGlobal("OffscreenCanvas", undefined);
    const calls: Call[] = [];
    const element = {
      width: 0,
      height: 0,
      getContext: () => {
        calls.push(["size", element.width, element.height]);
        return fakeContext(calls);
      },
      toBlob: (cb: (b: Blob | null) => void, type: string, quality: number) => {
        calls.push(["toBlob", type, quality]);
        cb(new Blob(["jpeg"], { type }));
      },
    };
    const realCreateElement = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation(((tag: string) =>
      tag === "canvas" ? element : realCreateElement(tag)) as unknown as typeof document.createElement);

    const out = await downscaleToJpeg(photo);

    expect(out.type).toBe("image/jpeg");
    expect(calls).toEqual([
      ["size", 2576, 1000],
      ["fillRect", 0, 0, 2576, 1000],
      ["drawImage", bitmap, 0, 0, 2576, 1000],
      ["toBlob", "image/jpeg", JPEG_QUALITY],
    ]);
    expect([element.width, element.height]).toEqual([0, 0]);
    expect(bitmap.close).toHaveBeenCalledOnce();
  });
});
