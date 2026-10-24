import { createHmac, timingSafeEqual } from "node:crypto";

/** Проверка подписи Telegram Mini App initData (https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app). */

export const INIT_DATA_MAX_AGE_SEC = 24 * 60 * 60;
const FUTURE_SKEW_SEC = 60;

export type TelegramUser = {
  id: number;
  first_name?: string;
  last_name?: string;
  username?: string;
  language_code?: string;
};

export type InitDataResult =
  | { ok: true; user: TelegramUser; authDate: number }
  | { ok: false; reason: "empty" | "no_hash" | "bad_signature" | "no_auth_date" | "expired" | "future" | "no_user" | "no_token" };

/** Секрет подписи: HMAC_SHA256(key="WebAppData", data=bot_token). */
export function secretKey(botToken: string): Buffer {
  return createHmac("sha256", "WebAppData").update(botToken).digest();
}

/** Подпись initData: строка проверки — все поля кроме hash, «ключ=значение», по алфавиту, через \n. */
export function signInitData(params: URLSearchParams, botToken: string): string {
  const pairs: string[] = [];
  params.forEach((v, k) => {
    if (k !== "hash") pairs.push(`${k}=${v}`);
  });
  pairs.sort();
  return createHmac("sha256", secretKey(botToken)).update(pairs.join("\n")).digest("hex");
}

export function verifyInitData(
  initData: string | null | undefined,
  botToken: string | undefined,
  opts: { now?: number; maxAgeSec?: number } = {},
): InitDataResult {
  if (!botToken) return { ok: false, reason: "no_token" };
  if (!initData) return { ok: false, reason: "empty" };

  const params = new URLSearchParams(initData);
  const hash = params.get("hash");
  if (!hash) return { ok: false, reason: "no_hash" };

  const expected = Buffer.from(signInitData(params, botToken), "hex");
  const given = /^[0-9a-f]{64}$/i.test(hash) ? Buffer.from(hash, "hex") : null;
  if (!given || given.length !== expected.length || !timingSafeEqual(given, expected)) {
    return { ok: false, reason: "bad_signature" };
  }

  // Подпись верна — дальше проверяем содержимое.
  const authDate = Number(params.get("auth_date"));
  if (!Number.isInteger(authDate) || authDate <= 0) return { ok: false, reason: "no_auth_date" };
  const now = opts.now ?? Math.floor(Date.now() / 1000);
  const maxAge = opts.maxAgeSec ?? INIT_DATA_MAX_AGE_SEC;
  if (now - authDate > maxAge) return { ok: false, reason: "expired" };
  if (authDate - now > FUTURE_SKEW_SEC) return { ok: false, reason: "future" };

  let user: TelegramUser | null = null;
  try {
    const raw = params.get("user");
    user = raw ? (JSON.parse(raw) as TelegramUser) : null;
  } catch {
    user = null;
  }
  if (!user || !Number.isSafeInteger(user.id) || user.id <= 0) return { ok: false, reason: "no_user" };
  return { ok: true, user, authDate };
}
