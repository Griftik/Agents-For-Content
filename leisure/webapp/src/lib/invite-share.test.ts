import { describe, expect, it } from "vitest";
import { buildShareText, copyText, miniAppLink, splitShare, tgShareLink } from "./invite-share";

const ev = { title: "Карманный онгон: вырезать деревянного духа-хранителя", venue: "Ателье ГЭС-2", why_fit_hint: "Вырезаешь сам, мастер рядом. Материалы включены.", start_time: "13:00", end_time: "15:00" };
const link = "https://t.me/dosug_bot/app?startapp=inv_k3m9x2ab";

describe("текст приглашения", () => {
  it("собирается по T-INVITE-SHARE", () => {
    expect(buildShareText(ev, "2026-10-24", link)).toBe(
      `Иду на «${ev.title}»: суббота, 24 окт, 13:00–15:00, Ателье ГЭС-2. Вырезаешь сам, мастер рядом.\nПойдёшь со мной? ${link}`,
    );
  });
  it("укладывается в 300 знаков при длинных полях", () => {
    const t = buildShareText({ ...ev, title: "Т".repeat(100), venue: "П".repeat(80), why_fit_hint: "Д".repeat(200) }, "2026-10-24", link);
    expect(t.length).toBeLessThanOrEqual(300);
    expect(t).toContain("…");
  });
  it("пропускает пустую строку «почему стоит» вместе с точкой", () => {
    expect(buildShareText({ ...ev, why_fit_hint: "" }, "2026-10-24", link).split("\n")[0]).toMatch(/Ателье ГЭС-2\.$/);
  });
});

describe("поделиться", () => {
  it("убирает ссылку из текста, чтобы в чате она не стояла дважды", () => {
    const t = buildShareText(ev, "2026-10-24", link);
    const s = splitShare(t, link);
    expect(s.url).toBe(link);
    expect(s.text).not.toContain(link);
    expect(s.text.endsWith("Пойдёшь со мной?")).toBe(true);
  });
  it("ссылка t.me/share/url кодирует адрес и текст", () => {
    const u = tgShareLink(link, "Привет & пока");
    expect(u).toBe(`https://t.me/share/url?url=${encodeURIComponent(link)}&text=${encodeURIComponent("Привет & пока")}`);
  });
  it("в буфер ссылка попадает один раз", () => {
    const t = buildShareText(ev, "2026-10-24", link);
    expect(copyText(t, link).split(link).length - 1).toBe(1);
    expect(copyText("Без ссылки", link)).toBe(`Без ссылки\n${link}`);
  });
  it("ссылка на Mini App: с коротким именем и без", () => {
    expect(miniAppLink("dosug_bot", "app", "inv", "ABCD1234")).toBe("https://t.me/dosug_bot/app?startapp=inv_ABCD1234");
    expect(miniAppLink("dosug_bot", "", "ref", "ABCD1234")).toBe("https://t.me/dosug_bot?startapp=ref_ABCD1234");
    expect(miniAppLink("", "app", "inv", "ABCD1234")).toBeNull();
  });
});
