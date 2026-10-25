// Коды приглашений и рекомендаций в ссылках приложения.

/** Код приглашения: 8 знаков в API, здесь допускаем 4–32 латинских букв и цифр (в путь и в запрос попадает только это). */
export const CODE_RE = /^[A-Za-z0-9]{4,32}$/;

/** Адрес страницы приглашения. */
export const inviteHref = (slug: string, code: string) => `/e/${encodeURIComponent(slug)}?inv=${encodeURIComponent(code)}`;
