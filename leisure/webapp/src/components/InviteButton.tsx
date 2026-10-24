"use client";

import { useEffect, useRef, useState } from "react";
import { createInviteAction } from "@/app/actions";
import { copyToClipboard } from "@/lib/clipboard";
import { copyText, splitShare, tgShareLink } from "@/lib/invite-share";
import { inTelegram, openTelegramLink } from "@/lib/tg-client";

type Share = { url: string; text: string };

/**
 * «Позвать друга» (T-INVITE-SHARE, FLOW-INVITE И1–И2): нажатие создаёт приглашение (server action → POST /api/invites)
 * и открывает окно с текстом, который уйдёт от имени человека. «Поделиться» — в Telegram openTelegramLink на t.me/share/url,
 * вне Telegram Web Share API; «Скопировать» — запасной вариант с подтверждением. Системный выбор чата открывается по второму нажатию,
 * то есть в свежем жесте: Safari не пускает navigator.share после ожидания ответа сервера.
 */
export function InviteButton({ slug, day, small = true }: { slug: string; day: string | null; small?: boolean }) {
  const dlg = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false);
  const [share, setShare] = useState<Share | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [shareAvailable, setShareAvailable] = useState(false);

  useEffect(() => {
    setShareAvailable(inTelegram() || typeof navigator.share === "function");
  }, []);

  async function open() {
    if (busy) return;
    setBusy(true);
    setError("");
    setStatus("");
    try {
      const r = await createInviteAction(slug, day);
      if (!r.ok) {
        setError(r.error);
        return;
      }
      setShare({ url: r.url, text: r.shareText });
      dlg.current?.showModal();
    } catch {
      setError("Не получилось создать приглашение, попробуй ещё раз.");
    } finally {
      setBusy(false);
    }
  }

  async function doShare() {
    if (!share) return;
    const { text, url } = splitShare(share.text, share.url);
    if (inTelegram()) {
      openTelegramLink(tgShareLink(url, text));
      dlg.current?.close();
      return;
    }
    try {
      await navigator.share({ text, url });
      dlg.current?.close();
    } catch (e) {
      if (!(e instanceof DOMException && e.name === "AbortError")) await doCopy();
    }
  }

  async function doCopy() {
    if (!share) return;
    const ok = await copyToClipboard(copyText(share.text, share.url));
    setStatus(ok ? "Приглашение скопировано. Вставь его в чат с другом." : "Не вышло, выдели текст выше и скопируй.");
  }

  const preview = share ? splitShare(share.text, share.url) : null;
  return (
    <>
      <button type="button" className={`btn${small ? " small" : ""}`} onClick={open} disabled={busy} aria-haspopup="dialog">
        Позвать друга
      </button>
      {error ? <span role="alert" className="copy-status" style={{ color: "var(--warn-ink)" }}>{error}</span> : null}
      <dialog ref={dlg} className="sheet" aria-labelledby={`sheet-${slug}`} onClose={() => setStatus("")}>
        <h2 id={`sheet-${slug}`}>Позвать друга</h2>
        {preview ? (
          <p className="sheet-text" tabIndex={0}>
            {preview.text}
            <br />
            <span className="muted">{preview.url}</span>
          </p>
        ) : null}
        <div className="row">
          {shareAvailable ? <button type="button" className="btn primary" onClick={doShare}>Поделиться</button> : null}
          <button type="button" className={`btn${shareAvailable ? "" : " primary"}`} onClick={doCopy}>Скопировать</button>
          <button type="button" className="btn quiet" onClick={() => dlg.current?.close()}>Закрыть</button>
        </div>
        <p className="copy-status" role="status" aria-live="polite">{status}</p>
      </dialog>
    </>
  );
}
