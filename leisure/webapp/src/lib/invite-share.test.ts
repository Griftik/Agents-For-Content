import { describe, expect, it } from "vitest";
import { copyText, shareLink, splitShare } from "./invite-share";

const link = "https://dosug.example/e/karmannyj-ongon?inv=k3m9x2ab";
const text = `Иду на «Карманный онгон»: суббота, 24 окт, 13:00–15:00, Ателье ГЭС-2.\nПойдёшь со мной? ${link}`;

describe("поделиться", () => {
  it("убирает ссылку из текста, чтобы в чате она не стояла дважды", () => {
    const s = splitShare(text, link);
    expect(s.url).toBe(link);
    expect(s.text).not.toContain(link);
    expect(s.text.endsWith("Пойдёшь со мной?")).toBe(true);
  });
  it("в буфер ссылка попадает один раз", () => {
    expect(copyText(text, link).split(link).length - 1).toBe(1);
    expect(copyText("Без ссылки", link)).toBe(`Без ссылки\n${link}`);
  });
  it("ссылка — адрес приложения (web_url), url из API — запасной", () => {
    expect(shareLink({ web_url: link, url: "https://x" })).toBe(link);
    expect(shareLink({ web_url: "", url: "https://x" })).toBe("https://x");
    expect(shareLink({})).toBe("");
  });
});
