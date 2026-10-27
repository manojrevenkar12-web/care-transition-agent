import { codePointToUnit, segments, toOriginal } from "./highlight";

describe("segments", () => {
  it("cuts overlapping marks into segments that carry every covering mark", () => {
    const segs = segments("abcdefgh", [
      { start: 1, end: 5, kind: "evidence" },
      { start: 3, end: 7, kind: "tag" },
    ]);
    expect(segs.map((s) => [s.text, s.marks.map((m) => m.kind).join("+")])).toEqual([
      ["a", ""],
      ["bc", "evidence"],
      ["de", "evidence+tag"],
      ["fg", "tag"],
      ["h", ""],
    ]);
  });

  it("ignores empty and out-of-range marks", () => {
    expect(segments("abc", [{ start: 2, end: 2, kind: "tag" }, { start: 9, end: 12, kind: "tag" }])).toHaveLength(1);
  });
});

describe("toOriginal", () => {
  const reps = [{ start: 5, end: 15, out_start: 5, out_end: 14, kind: "name", tag: "«Patient»" }];
  it("shifts spans after a replacement by the length difference", () => {
    expect(toOriginal(20, 25, reps)).toEqual([21, 26]);
  });
  it("snaps a span inside a tag to the replaced original text", () => {
    expect(toOriginal(7, 9, reps)).toEqual([5, 15]);
  });
});

describe("codePointToUnit", () => {
  it("maps Python code-point offsets to UTF-16 indexes past astral characters", () => {
    const text = "a😀b";
    expect(text.slice(codePointToUnit(text)(2), codePointToUnit(text)(3))).toBe("b");
  });
});
