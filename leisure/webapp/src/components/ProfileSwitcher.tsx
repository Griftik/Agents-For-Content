"use client";

import { useRef } from "react";
import { createProfileAction, switchProfileAction } from "@/app/actions";
import type { AccountProfile } from "@/lib/api-types";

const KIND_LABEL: Record<string, string> = { self: "я", parent: "родитель", child: "ребёнок", other: "" };
const initial = (name: string) => (name.trim().charAt(0) || "Я").toUpperCase();

/** Чип в шапке: инициал и имя активного профиля; нижний лист со списком профилей и «+ Новый профиль». */
export function ProfileSwitcher({ profiles, activeId }: { profiles: AccountProfile[]; activeId: number }) {
  const dlg = useRef<HTMLDialogElement>(null);
  const newDlg = useRef<HTMLDialogElement>(null);
  const active = profiles.find((p) => p.id === activeId) ?? profiles[0];
  const name = active?.name || "я";
  return (
    <>
      <button type="button" className="pswitch" onClick={() => dlg.current?.showModal()} aria-haspopup="dialog" aria-label={`Профиль: ${name}`}>
        <span className="ava" aria-hidden="true">{initial(name)}</span>
        <span className="nm">{name}</span>
      </button>
      <dialog ref={dlg} className="sheet" aria-labelledby="psw-h">
        <h2 id="psw-h">Профиль</h2>
        <ul className="plist" role="listbox" aria-label="Профили">
          {profiles.map((p) => (
            <li key={p.id} role="option" aria-selected={p.id === activeId} aria-current={p.id === activeId ? "true" : undefined}>
              <button type="button" onClick={() => void switchProfileAction(p.id)}>
                <span className="ava" aria-hidden="true">{initial(p.name)}</span>
                {p.id === activeId ? "● " : ""}{p.name}
                <span className="svc kind">{KIND_LABEL[p.kind] ?? ""}</span>
              </button>
            </li>
          ))}
          <li>
            <button type="button" onClick={() => { dlg.current?.close(); newDlg.current?.showModal(); }}>
              <span className="ava" aria-hidden="true">+</span>Новый профиль
            </button>
          </li>
        </ul>
        <div className="row"><button type="button" className="btn quiet" onClick={() => dlg.current?.close()}>Закрыть</button></div>
      </dialog>
      <dialog ref={newDlg} className="sheet" aria-labelledby="pnew-h">
        <h2 id="pnew-h">Новый профиль</h2>
        <form action={createProfileAction} className="stack" style={{ gap: 12 }}>
          <label className="stack" style={{ gap: 4 }}>
            <span className="svc">Имя</span>
            <input name="pname" type="text" maxLength={40} required autoComplete="off" placeholder="Мама" style={{ minHeight: 48, font: "16px var(--body)", padding: "10px 12px", border: "1px solid var(--line)", borderRadius: 10, background: "var(--bg)", color: "var(--fg)" }} />
          </label>
          <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
            <legend className="svc" style={{ marginBottom: 6 }}>Кто это</legend>
            <span className="seg wrapseg">
              {[["parent", "Родитель"], ["child", "Ребёнок"], ["other", "Другой"]].map(([v, l], i) => (
                <label key={v}><input type="radio" name="kind" value={v} defaultChecked={i === 2} /><span>{l}</span></label>
              ))}
            </span>
          </fieldset>
          <div className="row">
            <button type="submit" className="btn primary">Создать</button>
            <button type="button" className="btn quiet" onClick={() => newDlg.current?.close()}>Отмена</button>
          </div>
        </form>
      </dialog>
    </>
  );
}
