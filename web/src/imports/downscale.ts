/**
 * A photo of a list is made small before upload (docs/basket-plan.md M28.4). Current Claude models read images up to
 * 2576 px on the long edge and about 3.75 megapixels (the high-resolution limits in the official vision docs); a
 * larger photo only costs tokens and upload time. Re-encoding as JPEG also turns an iPhone HEIC photo into a JPEG,
 * puts transparency on white, and drops the EXIF metadata, location included.
 */
export const MAX_EDGE = 2576;
export const MAX_PIXELS = 3_750_000;
export const JPEG_QUALITY = 0.85;

export const UNREADABLE_PHOTO =
  "This browser cannot open this photo (an iPhone HEIC photo, for example). Choose a JPEG or PNG image instead.";
export const CANNOT_CONVERT = "The photo could not be prepared for upload. Choose a JPEG or PNG image instead.";

/** A photo the browser could not decode or re-encode; its message is meant for the buyer. */
export class PhotoReadError extends Error {
  override name = "PhotoReadError";
}

export type Fit = { width: number; height: number; scale: number };

/**
 * The size to draw an image at: never larger than the original, the long edge at most MAX_EDGE, the area at most
 * MAX_PIXELS, whole pixels and at least 1 px a side. Flooring keeps both limits after rounding.
 */
export function fitWithin(width: number, height: number): Fit {
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    throw new RangeError(`Not an image size: ${width} x ${height}`);
  }
  const scale = Math.min(1, MAX_EDGE / Math.max(width, height), Math.sqrt(MAX_PIXELS / (width * height)));
  const side = (n: number) => Math.max(1, Math.floor(n * scale + 1e-9)); // 1e-9: 2575.9999999 is 2576
  return { width: side(width), height: side(height), scale };
}

type Decoded = { image: CanvasImageSource; width: number; height: number; release: () => void };

/** createImageBitmap first; an <img> second, because Safari decodes iPhone HEIC that way (Chrome cannot at all). */
async function decode(file: Blob): Promise<Decoded> {
  if (typeof createImageBitmap === "function") {
    try {
      const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
      if (bitmap.width > 0 && bitmap.height > 0) {
        return { image: bitmap, width: bitmap.width, height: bitmap.height, release: () => bitmap.close() };
      }
      bitmap.close();
    } catch {
      /* not decodable this way: try an <img> */
    }
  }
  return new Promise<Decoded>((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    const done = () => {
      img.onload = null;
      img.onerror = null;
    };
    img.onload = () => {
      done();
      const { naturalWidth: width, naturalHeight: height } = img; // already turned upright (image-orientation)
      if (width > 0 && height > 0) {
        resolve({ image: img, width, height, release: () => URL.revokeObjectURL(url) });
      } else {
        URL.revokeObjectURL(url);
        reject(new PhotoReadError(UNREADABLE_PHOTO));
      }
    };
    img.onerror = () => {
      done();
      URL.revokeObjectURL(url);
      reject(new PhotoReadError(UNREADABLE_PHOTO));
    };
    img.decoding = "async";
    img.src = url;
  });
}

type Ctx2D = CanvasDrawImage & CanvasFillStrokeStyles & CanvasRect & CanvasImageSmoothing;

function paint(ctx: Ctx2D, image: CanvasImageSource, fit: Fit) {
  ctx.fillStyle = "#ffffff"; // JPEG has no alpha: a transparent screenshot would otherwise turn black
  ctx.fillRect(0, 0, fit.width, fit.height);
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(image, 0, 0, fit.width, fit.height);
}

// Canvases stay far inside iOS Safari's limits (16.7 megapixels for one canvas, a few hundred MB for all of them):
// ours is at most 3.75 megapixels, and it is shrunk to 0 x 0 right after use so iOS frees it at once.
async function encodeOffscreen(image: CanvasImageSource, fit: Fit): Promise<Blob | null> {
  if (typeof OffscreenCanvas !== "function") return null;
  const canvas = new OffscreenCanvas(fit.width, fit.height);
  try {
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    paint(ctx, image, fit);
    const blob = await canvas.convertToBlob({ type: "image/jpeg", quality: JPEG_QUALITY });
    return blob.type === "image/jpeg" ? blob : null;
  } finally {
    canvas.width = 0;
    canvas.height = 0;
  }
}

async function encodeElement(image: CanvasImageSource, fit: Fit): Promise<Blob> {
  const canvas = document.createElement("canvas");
  canvas.width = fit.width;
  canvas.height = fit.height;
  try {
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new PhotoReadError(CANNOT_CONVERT);
    paint(ctx, image, fit);
    return await new Promise<Blob>((resolve, reject) =>
      canvas.toBlob((b) => (b ? resolve(b) : reject(new PhotoReadError(CANNOT_CONVERT))), "image/jpeg", JPEG_QUALITY),
    );
  } finally {
    canvas.width = 0;
    canvas.height = 0;
  }
}

/**
 * Decode an image file (JPEG, PNG, WebP, GIF, or HEIC where the browser can read it), draw it at fitWithin's size
 * and re-encode it as a JPEG at quality 0.85. Bitmaps and object URLs are released before this returns.
 * Throws PhotoReadError with a message for the buyer when the browser cannot read or convert the file.
 */
export async function downscaleToJpeg(file: Blob): Promise<Blob> {
  const decoded = await decode(file);
  try {
    const fit = fitWithin(decoded.width, decoded.height);
    const fast = await encodeOffscreen(decoded.image, fit).catch(() => null);
    return fast ?? (await encodeElement(decoded.image, fit));
  } finally {
    decoded.release();
  }
}
