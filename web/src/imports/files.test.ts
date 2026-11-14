import { describe, expect, it } from "vitest";
import { SHEET_ACCEPT, photoFileProblem, sheetFileProblem } from "./files";
import { EMPTY_PHOTO, OLD_XLS, WRONG_IMAGE_TYPE, WRONG_SHEET_TYPE } from "./intakeApi";

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

describe("which files go to the photo import", () => {
  const photo = (name: string, type: string, size = 1000) => ({ name, type, size });

  it("takes any image the browser may decode, HEIC too, whatever the reported type", () => {
    expect(photoFileProblem(photo("IMG_0001.jpg", "image/jpeg"))).toBeNull();
    expect(photoFileProblem(photo("IMG_0002.HEIC", ""))).toBeNull(); // Chrome on Windows reports nothing
    expect(photoFileProblem(photo("IMG_0003.heic", "image/heic"))).toBeNull();
    expect(photoFileProblem(photo("lista", "image/png"))).toBeNull();
  });

  it("refuses an empty file and a file that is no image, in the gateway's words", () => {
    expect(photoFileProblem(photo("IMG_0001.jpg", "image/jpeg", 0))).toBe(EMPTY_PHOTO);
    expect(photoFileProblem(photo("tilaus.pdf", "application/pdf"))).toBe(WRONG_IMAGE_TYPE);
    expect(photoFileProblem(photo("tilaus.csv", "text/csv"))).toBe(WRONG_IMAGE_TYPE);
  });
});
