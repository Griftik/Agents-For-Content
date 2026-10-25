import { describe, expect, it } from "vitest";
import { SESSION_TTL_SEC, issueProfile, issueSession, parseDevUser, readProfile, readSession, sessionSecret } from "./session-token";

const SECRET = "test-secret";
const NOW = 1_800_000_000;

describe("токен сессии", () => {
  it("выдаётся и читается", () => {
    const { token } = issueSession(777, SECRET, NOW);
    expect(readSession(token, SECRET, NOW + 10)).toBe(777);
  });

  it("истекает через 180 дней", () => {
    const { token } = issueSession(777, SECRET, NOW);
    expect(readSession(token, SECRET, NOW + SESSION_TTL_SEC + 1)).toBeNull();
  });

  it("не принимает подмену id, чужой секрет и мусор", () => {
    const { token } = issueSession(777, SECRET, NOW);
    const [, exp, sig] = token.split(".");
    expect(readSession(`1.${exp}.${sig}`, SECRET, NOW)).toBeNull();
    expect(readSession(token, "other", NOW)).toBeNull();
    expect(readSession("мусор", SECRET, NOW)).toBeNull();
    expect(readSession(undefined, SECRET, NOW)).toBeNull();
    expect(readSession(token, null, NOW)).toBeNull();
  });

  it("срок сессии — 180 дней", () => {
    expect(SESSION_TTL_SEC).toBe(180 * 86400);
    expect(issueSession(777, SECRET, NOW).exp).toBe(NOW + 180 * 86400);
  });

  it("секрет берётся только из SESSION_SECRET (от токена бота ничего не выводится)", () => {
    expect(sessionSecret({ SESSION_SECRET: "s" })).toBe("s");
    expect(sessionSecret({ LEISURE_BOT_TOKEN: "1:abc" })).toBeNull();
    expect(sessionSecret({})).toBeNull();
  });

  it("dev-пользователь — только цифры", () => {
    expect(parseDevUser("777")).toBe(777);
    expect(parseDevUser("7a")).toBeNull();
    expect(parseDevUser("0")).toBeNull();
    expect(parseDevUser("")).toBeNull();
  });
});

describe("активный профиль аккаунта", () => {
  it("читается только у своего аккаунта", () => {
    const t = issueProfile(55, 777, SECRET);
    expect(readProfile(t, 777, SECRET)).toBe(55);
    expect(readProfile(t, 778, SECRET)).toBeNull();
  });
  it("подмена профиля, чужой секрет и мусор отклоняются", () => {
    const t = issueProfile(55, 777, SECRET);
    const [, acc, sig] = t.split(".");
    expect(readProfile(`56.${acc}.${sig}`, 777, SECRET)).toBeNull();
    expect(readProfile(t, 777, "other")).toBeNull();
    expect(readProfile("мусор", 777, SECRET)).toBeNull();
    expect(readProfile(undefined, 777, SECRET)).toBeNull();
    expect(readProfile(t, 777, null)).toBeNull();
  });
  it("подпись профиля не годится как токен сессии", () => {
    const t = issueProfile(55, 777, SECRET);
    expect(readSession(t, SECRET, NOW)).toBeNull();
  });
});
