import { describe, expect, it } from "vitest";
import { MOCK_CATALOG } from "./mock";
import { PROPOSED_N, clusters, interestLevels, pickTop, rankCategories, weightsFromTop } from "./onboarding";

const { values, categories, category_values } = MOCK_CATALOG;

describe("онбординг: ценности", () => {
  it("пять выбранных = 5, остальные = 2", () => {
    const top = ["Творчество", "Покой", "Семья", "Природа", "Смысл"];
    const w = weightsFromTop(values, top);
    expect(Object.values(w).filter((x) => x === 5)).toHaveLength(5);
    expect(Object.values(w).filter((x) => x === 2)).toHaveLength(values.length - 5);
  });
  it("pickTop принимает ровно пять известных без повторов", () => {
    expect(pickTop(values, ["Творчество", "Покой", "Семья", "Природа", "Смысл"])).toHaveLength(5);
    expect(pickTop(values, ["Творчество", "Покой", "Семья", "Природа"])).toBeNull();
    expect(pickTop(values, ["Творчество", "Творчество", "Семья", "Природа", "Смысл"])).toBeNull();
    expect(pickTop(values, ["Творчество", "Покой", "Семья", "Природа", "Нет такой"])).toBeNull();
  });
  it("19 ценностей в четырёх группах", () => {
    const g = clusters(values, MOCK_CATALOG.value_clusters);
    expect(g).toHaveLength(4);
    expect(g.flatMap(([, v]) => v)).toHaveLength(19);
    expect(clusters(values, undefined)).toEqual([["Ценности", values]]);
  });
});

describe("онбординг: восемь направлений", () => {
  it("ранжирует по таблице каталога, при равенстве держит порядок каталога", () => {
    const v = weightsFromTop(values, ["Творчество", "Красота/эстетика", "Инновации/новизна", "Исследования", "Смысл"]);
    const ranked = rankCategories(categories, v, category_values);
    expect(ranked).toHaveLength(categories.length);
    expect(ranked[0]).toBe("Современное искусство");
    expect(rankCategories(categories, {}, category_values)).toEqual(categories);
  });
  it("без таблицы порядок задают текущие интересы", () => {
    const ranked = rankCategories(["А", "Б", "В"], {}, undefined, { "В": 3, "А": 1 });
    expect(ranked).toEqual(["В", "А", "Б"]);
  });
  it("уровни: первые пять — 3, ещё три — 2, выключенное — 0, прочие — 1", () => {
    const ranked = categories;
    const levels = interestLevels(ranked, new Set(ranked.slice(0, PROPOSED_N).filter((c) => c !== ranked[1])));
    expect(levels[ranked[0]]).toBe(3);
    expect(levels[ranked[1]]).toBe(0);
    expect(levels[ranked[5]]).toBe(2);
    expect(levels[ranked[PROPOSED_N]]).toBe(1);
  });
});
