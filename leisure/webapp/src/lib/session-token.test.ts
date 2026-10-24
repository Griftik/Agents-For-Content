import { describe, expect, it } from "vitest";
import { SESSION_TTL_SEC, issueSession, parseDevUser, readSession, sessionSecret } from "./session-token";

const SECRET = "test-secret";
const NOW = 1_800_000_000;

describe("токен сессии", () => {
  it("выдаётся и читается", () => {
    const { token } = issueSession(777, SECRET, NOW);
    expect(readSession(token, SECRET, NOW + 10)).toBe(777);
  });

  it("истекает через сутки", () => {
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

  it("секрет берётся из SESSION_SECRET или выводится из токена бота", () => {
    expect(sessionSecret({ SESSION_SECRET: "s" })).toBe("s");
    const derived = sessionSecret({ LEISURE_BOT_TOKEN: "1:abc" });
    expect(derived).toMatch(/^[0-9a-f]{64}$/);
    expect(derived).not.toBe("1:abc");
    expect(sessionSecret({})).toBeNull();
  });

  it("dev-пользователь — только цифры", () => {
    expect(parseDevUser("777")).toBe(777);
    expect(parseDevUser("7a")).toBeNull();
    expect(parseDevUser("0")).toBeNull();
    expect(parseDevUser("")).toBeNull();
  });
});
