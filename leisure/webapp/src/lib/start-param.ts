// Разбор start_param Telegram Mini App. Чистые функции: работают и на сервере, и в браузере, покрыты тестами.

export type StartParam = { kind: "inv" | "ref"; code: string };

/** Код приглашения: 8 знаков в API, здесь допускаем 4–32 латинских букв и цифр (в путь и в запрос попадает только это). */
export const CODE_RE = /^[A-Za-z0-9]{4,32}$/;

/** `inv_<код>` или `ref_<код>`; всё остальное (в том числе чужие start_param) — null. */
export function parseStartParam(raw: string | null | undefined): StartParam | null {
  if (!raw || raw.length > 512) return null;
  const m = /^(inv|ref)_(.+)$/.exec(raw.trim());
  if (!m || !CODE_RE.test(m[2])) return null;
  return { kind: m[1] as "inv" | "ref", code: m[2] };
}

/**
 * Где Telegram кладёт start_param: поле `start_param` в initData, `initDataUnsafe.start_param` SDK,
 * `tgWebAppStartParam` в хеше или запросе адреса. Берём первый непустой источник в таком порядке.
 */
export function findStartParam(src: { initData?: string; unsafe?: string; hash?: string; search?: string }): string | null {
  const fromQuery = (s: string | undefined, key: string) => {
    if (!s) return null;
    try {
      return new URLSearchParams(s.replace(/^[#?]/, "")).get(key) || null;
    } catch {
      return null;
    }
  };
  return (
    fromQuery(src.initData, "start_param") ||
    src.unsafe ||
    fromQuery(src.hash, "tgWebAppStartParam") ||
    fromQuery(src.search, "tgWebAppStartParam") ||
    null
  );
}

/** Адрес, на который ведёт start_param, когда слаг события уже известен. */
export const inviteHref = (slug: string, code: string) => `/e/${encodeURIComponent(slug)}?inv=${encodeURIComponent(code)}`;
