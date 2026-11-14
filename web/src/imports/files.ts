/**
 * Checks before an upload, so an obviously wrong file gets the gateway's answer without a round trip. The gateway
 * stays the authority and checks everything again (type, size, rows); nothing here reads the file's contents.
 */
import { OLD_XLS, WRONG_SHEET_TYPE } from "./intakeApi";

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
