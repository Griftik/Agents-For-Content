import { describe, expect, it } from "vitest";
import { CODE_RE, inviteHref } from "./start-param";

describe("коды приглашений", () => {
  it("принимает буквы и цифры 4–32 знаков", () => {
    for (const ok of ["k3m9x2ab", "AB12CD34", "abcd", "a".repeat(32)]) expect(CODE_RE.test(ok)).toBe(true);
  });
  it("отклоняет всё, что может попасть в путь или запрос", () => {
    for (const bad of ["", "abc", "a".repeat(33), "../etc", "ab cd12", "ab?x=1", "ab&c=d1", "АБВГД123"]) expect(CODE_RE.test(bad)).toBe(false);
  });
  it("собирает адрес приглашения", () => {
    expect(inviteHref("karmannyj-ongon", "ABCD1234")).toBe("/e/karmannyj-ongon?inv=ABCD1234");
  });
});
