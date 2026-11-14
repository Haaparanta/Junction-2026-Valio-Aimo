/**
 * Checks before an upload, so an obviously wrong file gets the gateway's answer without a round trip. The gateway
 * stays the authority and checks everything again (type, size, rows); nothing here reads the file's contents.
 */
import { EMPTY_PHOTO, OLD_XLS, WRONG_IMAGE_TYPE, WRONG_SHEET_TYPE } from "./intakeApi";

const XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

/** The list picker's accept list: the two extensions, plus their MIME types for pickers that filter by type. */
export const SHEET_ACCEPT = `.xlsx,.csv,text/csv,${XLSX_TYPE}`;

export const ONE_FILE = "Drop one file at a time.";

/**
 * Why a file cannot be imported as a list, or null when it should go to the gateway. The extension decides,
 * because browsers report a .csv file as text/csv, application/vnd.ms-excel or nothing at all.
 */
export function sheetFileProblem(file: { name: string; type: string }): string | null {
  const name = file.name.trim().toLowerCase();
  if (name.endsWith(".xlsx") || name.endsWith(".csv")) return null;
  if (name.endsWith(".xls")) return OLD_XLS;
  const hasExtension = /\.[a-z0-9]{1,8}$/.test(name);
  if (!hasExtension && (file.type === "text/csv" || file.type === XLSX_TYPE)) return null;
  return WRONG_SHEET_TYPE;
}

// Photo formats a browser may decode, HEIC included (Safari): downscaleToJpeg makes every one of them a JPEG.
const IMAGE_EXTENSION = /\.(jpe?g|png|webp|gif|heic|heif|avif|bmp|tiff?)$/i;

/** Why a file cannot be sent as a photo of a list, or null. Browsers report HEIC as image/heic or as nothing. */
export function photoFileProblem(file: { name: string; type: string; size: number }): string | null {
  if (file.size === 0) return EMPTY_PHOTO;
  if (file.type.startsWith("image/") || IMAGE_EXTENSION.test(file.name.trim())) return null;
  return WRONG_IMAGE_TYPE;
}
