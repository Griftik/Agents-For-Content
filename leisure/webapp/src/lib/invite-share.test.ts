import { describe, expect, it } from "vitest";
import { copyText, miniAppLink, splitShare, tgShareLink } from "./invite-share";

const link = "https://t.me/dosug_bot/app?startapp=inv_k3m9x2ab";

describe("поделиться", () => {
  it("убирает ссылку из текста, чтобы в чате она не стояла дважды", () => {
    const t = `Иду на «Карманный онгон»: суббота, 24 окт, 13:00–15:00, Ателье ГЭС-2.\nПойдёшь со мной? ${link}`;
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
    const t = `Иду на «Карманный онгон»: суббота, 24 окт, 13:00–15:00, Ателье ГЭС-2.\nПойдёшь со мной? ${link}`;
    expect(copyText(t, link).split(link).length - 1).toBe(1);
    expect(copyText("Без ссылки", link)).toBe(`Без ссылки\n${link}`);
  });
  it("ссылка на Mini App: с коротким именем и без", () => {
    expect(miniAppLink("dosug_bot", "app", "inv", "ABCD1234")).toBe("https://t.me/dosug_bot/app?startapp=inv_ABCD1234");
    expect(miniAppLink("dosug_bot", "", "ref", "ABCD1234")).toBe("https://t.me/dosug_bot?startapp=ref_ABCD1234");
    expect(miniAppLink("", "app", "inv", "ABCD1234")).toBeNull();
  });
});
