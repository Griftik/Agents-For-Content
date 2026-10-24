import { describe, expect, it } from "vitest";
import { findStartParam, inviteHref, parseStartParam } from "./start-param";

describe("parseStartParam", () => {
  it("разбирает приглашение и рекомендацию", () => {
    expect(parseStartParam("inv_k3m9x2ab")).toEqual({ kind: "inv", code: "k3m9x2ab" });
    expect(parseStartParam("ref_AB12CD34")).toEqual({ kind: "ref", code: "AB12CD34" });
  });
  it("игнорирует чужие и повреждённые значения", () => {
    for (const bad of [null, undefined, "", "e_slug", "inv_", "inv", "inv_ab", "INV_ABCDEFGH", "inv_../etc/passwd", "inv_ab cd12", "ref_ABCD?x=1", "inv_" + "a".repeat(33), "x".repeat(600)]) {
      expect(parseStartParam(bad as string)).toBeNull();
    }
  });
  it("не принимает вложенный префикс", () => {
    expect(parseStartParam("inv_ref_ABCDEFGH")).toBeNull();
  });
});

describe("findStartParam", () => {
  it("берёт start_param из initData", () => {
    expect(findStartParam({ initData: "query_id=1&start_param=inv_ABCD1234&hash=x" })).toBe("inv_ABCD1234");
  });
  it("берёт из хеша адреса, если в initData нет", () => {
    expect(findStartParam({ hash: "#tgWebAppData=a%3Db&tgWebAppStartParam=ref_ABCD1234&tgWebAppVersion=8" })).toBe("ref_ABCD1234");
  });
  it("берёт из запроса адреса", () => {
    expect(findStartParam({ search: "?tgWebAppStartParam=inv_ABCD1234" })).toBe("inv_ABCD1234");
  });
  it("порядок источников: initData, SDK, хеш, запрос", () => {
    expect(findStartParam({ initData: "start_param=inv_AAAA1111", unsafe: "inv_BBBB2222", hash: "#tgWebAppStartParam=inv_CCCC3333" })).toBe("inv_AAAA1111");
    expect(findStartParam({ unsafe: "inv_BBBB2222", hash: "#tgWebAppStartParam=inv_CCCC3333" })).toBe("inv_BBBB2222");
  });
  it("пусто, если start_param нет", () => {
    expect(findStartParam({ initData: "query_id=1", hash: "", search: "" })).toBeNull();
    expect(findStartParam({})).toBeNull();
  });
  it("собирает адрес приглашения", () => {
    expect(inviteHref("karmannyj-ongon", "ABCD1234")).toBe("/e/karmannyj-ongon?inv=ABCD1234");
  });
});
