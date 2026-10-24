import { describe, expect, it } from "vitest";
import { createHmac } from "node:crypto";
import { INIT_DATA_MAX_AGE_SEC, signInitData, verifyInitData } from "./telegram";

const TOKEN = "123456:TEST-bot-token";
const NOW = 1_800_000_000;
const user = { id: 424242, first_name: "Евгений", username: "evg", language_code: "ru" };

/** Собирает initData так, как это делает Telegram. */
function make(fields: Record<string, string>, token = TOKEN): string {
  const p = new URLSearchParams(fields);
  p.set("hash", signInitData(p, token));
  return p.toString();
}
const base = (over: Record<string, string> = {}) => ({
  auth_date: String(NOW - 60),
  query_id: "AAH-test",
  user: JSON.stringify(user),
  ...over,
});

describe("verifyInitData", () => {
  it("принимает корректно подписанные данные и достаёт user.id", () => {
    const r = verifyInitData(make(base()), TOKEN, { now: NOW });
    expect(r).toMatchObject({ ok: true, user: { id: 424242, username: "evg" }, authDate: NOW - 60 });
  });

  it("сверяет подпись с эталонной схемой Telegram: HMAC(HMAC('WebAppData', token), строка проверки)", () => {
    const params = new URLSearchParams(base());
    const secret = createHmac("sha256", "WebAppData").update(TOKEN).digest();
    const check = [...params.entries()].map(([k, v]) => `${k}=${v}`).sort().join("\n");
    params.set("hash", createHmac("sha256", secret).update(check).digest("hex"));
    expect(verifyInitData(params.toString(), TOKEN, { now: NOW }).ok).toBe(true);
  });

  it("отклоняет испорченную подпись", () => {
    const good = new URLSearchParams(make(base()));
    const hash = good.get("hash")!;
    good.set("hash", (hash[0] === "0" ? "1" : "0") + hash.slice(1));
    expect(verifyInitData(good.toString(), TOKEN, { now: NOW })).toEqual({ ok: false, reason: "bad_signature" });
  });

  it("отклоняет подпись не того формата и пустой hash", () => {
    const p = new URLSearchParams(base());
    p.set("hash", "abc");
    expect(verifyInitData(p.toString(), TOKEN, { now: NOW })).toEqual({ ok: false, reason: "bad_signature" });
    p.delete("hash");
    expect(verifyInitData(p.toString(), TOKEN, { now: NOW })).toEqual({ ok: false, reason: "no_hash" });
  });

  it("отклоняет подмену данных при прежней подписи (чужой user.id)", () => {
    const p = new URLSearchParams(make(base()));
    p.set("user", JSON.stringify({ ...user, id: 1 }));
    expect(verifyInitData(p.toString(), TOKEN, { now: NOW })).toEqual({ ok: false, reason: "bad_signature" });
  });

  it("отклоняет данные, подписанные другим токеном бота", () => {
    expect(verifyInitData(make(base(), "999:OTHER"), TOKEN, { now: NOW })).toEqual({ ok: false, reason: "bad_signature" });
  });

  it("отклоняет устаревший auth_date (старше суток), но принимает ровно сутки", () => {
    const old = make(base({ auth_date: String(NOW - INIT_DATA_MAX_AGE_SEC - 1) }));
    expect(verifyInitData(old, TOKEN, { now: NOW })).toEqual({ ok: false, reason: "expired" });
    const edge = make(base({ auth_date: String(NOW - INIT_DATA_MAX_AGE_SEC) }));
    expect(verifyInitData(edge, TOKEN, { now: NOW }).ok).toBe(true);
  });

  it("отклоняет auth_date из будущего", () => {
    expect(verifyInitData(make(base({ auth_date: String(NOW + 3600) })), TOKEN, { now: NOW })).toEqual({ ok: false, reason: "future" });
  });

  it("отклоняет отсутствующий или нечисловой auth_date", () => {
    const { auth_date: _drop, ...rest } = base();
    void _drop;
    expect(verifyInitData(make(rest), TOKEN, { now: NOW })).toEqual({ ok: false, reason: "no_auth_date" });
    expect(verifyInitData(make(base({ auth_date: "вчера" })), TOKEN, { now: NOW })).toEqual({ ok: false, reason: "no_auth_date" });
  });

  it("отклоняет данные без пользователя или с кривым user", () => {
    const { user: _u, ...rest } = base();
    void _u;
    expect(verifyInitData(make(rest), TOKEN, { now: NOW })).toEqual({ ok: false, reason: "no_user" });
    expect(verifyInitData(make(base({ user: "{не json" })), TOKEN, { now: NOW })).toEqual({ ok: false, reason: "no_user" });
    expect(verifyInitData(make(base({ user: JSON.stringify({ id: "abc" }) })), TOKEN, { now: NOW })).toEqual({ ok: false, reason: "no_user" });
  });

  it("не работает без токена бота и без данных", () => {
    expect(verifyInitData(make(base()), undefined, { now: NOW })).toEqual({ ok: false, reason: "no_token" });
    expect(verifyInitData("", TOKEN, { now: NOW })).toEqual({ ok: false, reason: "empty" });
    expect(verifyInitData(null, TOKEN, { now: NOW })).toEqual({ ok: false, reason: "empty" });
  });

  it("поле signature входит в строку проверки, как требует Telegram", () => {
    const f = base({ signature: "c2lnbmF0dXJl" });
    expect(verifyInitData(make(f), TOKEN, { now: NOW }).ok).toBe(true);
    const p = new URLSearchParams(make(f));
    p.set("signature", "ZGlmZmVyZW50");
    expect(verifyInitData(p.toString(), TOKEN, { now: NOW }).ok).toBe(false);
  });
});
