import { describe, expect, it } from "vitest";
import { SHEET_ACCEPT, sheetFileProblem } from "./files";
import { OLD_XLS, WRONG_SHEET_TYPE } from "./intakeApi";

const file = (name: string, type = "") => ({ name, type });

describe("which files go to the list import", () => {
  it("accepts .xlsx and .csv by extension, whatever type the browser reports", () => {
    expect(sheetFileProblem(file("tilaus.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))).toBeNull();
    expect(sheetFileProblem(file("TILAUS.CSV"))).toBeNull();
    expect(sheetFileProblem(file("lista.csv", "application/vnd.ms-excel"))).toBeNull(); // Windows with Excel
    expect(sheetFileProblem(file("lista.csv", "text/csv"))).toBeNull();
  });

  it("refuses an old .xls with the gateway's words", () => {
    expect(sheetFileProblem(file("vanha.xls", "application/vnd.ms-excel"))).toBe(OLD_XLS);
    expect(OLD_XLS).toMatch(/\.xlsx or \.csv/);
  });

  it("refuses other types with the gateway's words", () => {
    for (const name of ["kuva.jpg", "tilaus.pdf", "tilaus.numbers", "tilaus.xlsm", "lista.txt", "lista.tsv"]) {
      expect(sheetFileProblem(file(name))).toBe(WRONG_SHEET_TYPE);
    }
  });

  it("lets a sheet type without an extension through, for the gateway to judge", () => {
    expect(sheetFileProblem(file("tilaus", "text/csv"))).toBeNull();
    expect(sheetFileProblem(file("tilaus"))).toBe(WRONG_SHEET_TYPE);
  });

  it("offers both extensions in the picker", () => {
    expect(SHEET_ACCEPT.split(",")).toEqual(expect.arrayContaining([".xlsx", ".csv"]));
  });
});
