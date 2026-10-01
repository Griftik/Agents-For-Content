/* Мини-приложение «Заявка на разбор». Экран целиком определяет сервер (/api/state),
   здесь только отрисовка и отправка действий. Тексты приходят из content/*.yaml. */
(function () {
  "use strict";
  var tg = window.Telegram && window.Telegram.WebApp;
  var app = document.getElementById("app");
  var toastEl = document.getElementById("toast");
  var initData = (tg && tg.initData) || "";
  var state = null;
  var busy = false;
  var mainHandler = null;
  var backHandler = null;
  var lastScreenKey = "";
  var navDir = "fwd";

  // ---------- Telegram ----------
  if (tg) {
    tg.ready();
    tg.expand();
    try { tg.setHeaderColor("secondary_bg_color"); tg.setBackgroundColor("secondary_bg_color"); } catch (e) {}
  }
  function haptic(kind) {
    try {
      if (!tg || !tg.HapticFeedback) return;
      if (kind === "select") tg.HapticFeedback.selectionChanged();
      else if (kind === "error") tg.HapticFeedback.notificationOccurred("error");
      else tg.HapticFeedback.impactOccurred("light");
    } catch (e) {}
  }
  function setMain(text, fn) {
    if (!tg) return;
    if (mainHandler) tg.MainButton.offClick(mainHandler);
    mainHandler = null;
    if (!text) { tg.MainButton.hide(); return; }
    mainHandler = function () { if (!busy) fn(); };
    tg.MainButton.setText(text);
    tg.MainButton.onClick(mainHandler);
    tg.MainButton.show();
  }
  function setBack(fn) {
    if (!tg) return;
    if (backHandler) tg.BackButton.offClick(backHandler);
    backHandler = null;
    if (!fn) { tg.BackButton.hide(); return; }
    backHandler = function () { if (!busy) fn(); };
    tg.BackButton.onClick(backHandler);
    tg.BackButton.show();
  }
  function openUrl(url) {
    if (!url) return;
    if (tg && /^https:\/\/t\.me\//.test(url)) tg.openTelegramLink(url);
    else if (tg) tg.openLink(url);
    else window.open(url, "_blank");
  }

  // ---------- сеть ----------
  function call(path, body) {
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Init-Data": initData },
      body: JSON.stringify(body || {})
    }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }
  function act(body, dir) {
    if (busy) return Promise.resolve();
    busy = true;
    if (tg) tg.MainButton.showProgress(false);
    return call("api/action", body).then(function (s) {
      busy = false;
      if (tg) tg.MainButton.hideProgress();
      navDir = dir || "fwd";
      render(s);
      if (s.toast) toast(s.toast);
      if (s.open_url) openUrl(s.open_url);
      if (s.invoice && tg) {
        tg.openInvoice(s.invoice, function (status) {
          if (status === "paid") { haptic("ok"); setTimeout(refresh, 1500); }
        });
      }
      return s;
    }).catch(function () {
      busy = false;
      if (tg) tg.MainButton.hideProgress();
      toast("Нет связи. Попробуйте ещё раз.");
    });
  }
  function refresh() { return call("api/state").then(render).catch(function () { toast("Нет связи. Попробуйте ещё раз."); }); }

  // ---------- мелочи ----------
  function h(tag, attrs, children) {
    var el = document.createElement(tag);
    if (attrs) for (var k in attrs) {
      if (k === "class") el.className = attrs[k];
      else if (k === "text") el.textContent = attrs[k];
      else if (k.slice(0, 2) === "on") el.addEventListener(k.slice(2), attrs[k]);
      else el.setAttribute(k, attrs[k]);
    }
    (children || []).forEach(function (c) { if (c) el.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return el;
  }
  function paras(text, cls) {
    var box = h("div", { class: cls || "" });
    String(text || "").split(/\n+/).forEach(function (line) { if (line.trim()) box.appendChild(h("p", { text: line.trim() })); });
    return box;
  }
  var toastTimer = null;
  function toast(text) {
    toastEl.textContent = text;
    toastEl.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.classList.remove("show"); }, 2600);
  }
  var CHECK = '<svg viewBox="0 0 14 14" fill="none"><path d="M2.5 7.5l3 3 6-7" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" color="var(--accent-text)"/></svg>';

  // ---------- экраны ----------
  var screens = {
    welcome: function (s) {
      var lines = String(s.text).split("\n");
      var consent = h("button", { class: "consent" + (s.consent ? " on" : ""), type: "button", role: "checkbox",
        "aria-checked": String(!!s.consent) });
      var box = h("span", { class: "check" }); box.innerHTML = CHECK;
      consent.appendChild(box);
      consent.appendChild(h("span", { class: "label", text: s.consent_label }));
      consent.addEventListener("click", function (e) {
        if (e.target.classList.contains("more")) return;
        haptic("select");
        act({ type: "consent", value: !s.consent }, "none");
      });
      var more = h("span", { class: "more", text: s.more, onclick: function () { openUrl(s.links.consent); } });
      consent.appendChild(more);
      setBack(null);
      setMain(s.start_button, function () {
        if (!s.consent) { haptic("error"); consent.classList.remove("shake"); void consent.offsetWidth; consent.classList.add("shake"); toast(s.consent_needed); return; }
        act({ type: "start" });
      });
      var initials = String(s.owner || "").split(/\s+/).map(function (w) { return w.charAt(0); }).join("").slice(0, 2);
      return h("div", {}, [
        h("div", { class: "who" }, [h("span", { class: "avatar", text: initials }),
          h("div", {}, [h("div", { class: "name", text: s.owner }), h("div", { class: "hint", text: s.channel })])]),
        h("div", { class: "hero" }, [h("h1", { text: lines[0] }), paras(lines.slice(1).join("\n"), "lead")]),
        consent,
        tg ? null : h("button", { class: "btn", text: s.start_button, onclick: function () { s.consent ? act({ type: "start" }) : toast(s.consent_needed); } })
      ]);
    },

    question: function (s) {
      var q = s.question;
      var opts = h("div", { class: "options" });
      q.options.forEach(function (o) {
        var b = h("button", { class: "opt" + (q.selected === o.code ? " selected" : "") + (o.code === "skip" ? " skip" : ""), type: "button" },
          [h("span", { text: o.text }), h("span", { class: "dot" })]);
        b.addEventListener("click", function () {
          if (busy) return;
          haptic("select");
          Array.prototype.forEach.call(opts.children, function (x) { x.classList.remove("selected"); });
          b.classList.add("selected");
          setTimeout(function () { act({ type: "answer", q: q.code, a: o.code }); }, 140);
        });
        opts.appendChild(b);
      });
      setMain(null);
      setBack(q.can_back ? function () { act({ type: "back" }, "back"); } : null);
      var head = q.total
        ? h("div", { class: "progress" }, [h("div", { class: "bar" }, [h("i", { style: "width:" + Math.round(100 * q.n / q.total) + "%" })]), h("span", { text: q.progress })])
        : null;
      return h("div", {}, [head, h("div", { class: "question", text: q.text }), opts,
        (!tg && q.can_back) ? h("button", { class: "btn ghost", text: s.labels.back, onclick: function () { act({ type: "back" }, "back"); } }) : null]);
    },

    contact: function (s) {
      var list = h("div", { class: "card" }, [h("h2", { text: s.teaser_intro })]);
      s.insights.forEach(function (t, i) { list.appendChild(h("div", { class: "insight" }, [h("b", { text: String(i + 1) }), h("div", { text: t })])); });
      var share = h("button", { class: "btn", type: "button", text: s.contact_button, onclick: function () {
        if (!tg || !tg.requestContact) { toast("Обновите Telegram, чтобы поделиться номером"); return; }
        tg.requestContact(function (ok) { if (ok) act({ type: "contact_check" }); });
      } });
      setBack(null);
      setMain(null);
      return h("div", {}, [list, h("div", { class: "card" }, [paras(s.ask_contact), h("div", { style: "height:14px" }), share,
        h("button", { class: "btn ghost", type: "button", text: s.skip_button, onclick: function () { act({ type: "contact_skip" }); } })])]);
    },

    company: function (s) {
      var input = h("input", { class: "text", type: "text", maxlength: "256", placeholder: s.placeholder, autocomplete: "organization", enterkeyhint: "done" });
      var send = function () { act({ type: "company", text: input.value }); };
      input.addEventListener("keydown", function (e) { if (e.key === "Enter") { input.blur(); send(); } });
      setBack(null);
      setMain(s.labels.next, send);
      return h("div", {}, [h("div", { class: "hero" }, [h("h1", { text: s.text })]), input, h("div", { style: "height:8px" }),
        h("button", { class: "btn ghost", type: "button", text: s.skip_button, onclick: function () { act({ type: "company", text: "" }); } }),
        tg ? null : h("button", { class: "btn", text: s.labels.next, onclick: send })]);
    },

    specialist: function (s) {
      setBack(null);
      setMain(null);
      return h("div", {}, [
        h("div", { class: "card" }, [paras(s.docs), h("p", { class: "hint", text: s.docs_sent })]),
        h("div", { class: "card" }, [paras(s.channel_text), h("div", { style: "height:12px" }),
          h("button", { class: "btn", type: "button", text: s.channel_button, onclick: function () { openUrl(s.links.channel); } })]),
        h("div", { class: "card" }, [paras(s.training_ask), h("div", { style: "height:12px" }),
          h("button", { class: "btn", type: "button", text: s.yes, onclick: function () { act({ type: "training", value: true }); } }),
          h("button", { class: "btn ghost", type: "button", text: s.no, onclick: function () { act({ type: "training", value: false }); } })])
      ]);
    },

    home: function (s) {
      var m = s.menu;
      setBack(null);
      setMain(null);
      var parts = [h("div", { class: "card status" }, [h("span", { class: "icon", text: "✓" }), paras(s.status)])];
      if (s.offer) parts.push(h("div", { class: "card" }, [paras(s.offer.text), h("div", { style: "height:12px" }),
        h("button", { class: "btn", type: "button", text: s.offer.button, onclick: function () { act({ type: "book" }); } })]));
      if (s.subscription) {
        var sub = s.subscription;
        var c = h("div", { class: "card" }, [h("h2", { text: sub.title })]);
        if (sub.active) c.appendChild(h("p", { text: sub.active }));
        if (sub.pitch) c.appendChild(paras(sub.pitch));
        c.appendChild(h("div", { style: "height:12px" }));
        c.appendChild(h("button", { class: "btn", type: "button", text: sub.button, onclick: function () { act({ type: "invoice" }); } }));
        if (sub.offer_url) c.appendChild(h("button", { class: "btn ghost", type: "button", text: "Условия подписки", onclick: function () { openUrl(sub.offer_url); } }));
        parts.push(c);
      }
      var sw = h("span", { class: "switch" + (m.notify_on ? " on" : "") });
      parts.push(h("div", { class: "list" }, [
        h("button", { class: "row", type: "button", onclick: function () { act({ type: "book" }); } }, [h("span", { text: m.booking }), h("span", { class: "chev", text: "›" })]),
        h("button", { class: "row", type: "button", onclick: function () { act({ type: "restart" }); } }, [h("span", { text: m.restart }), h("span", { class: "chev", text: "›" })]),
        h("button", { class: "row", type: "button", onclick: function () { haptic("select"); act({ type: "notify", value: !m.notify_on }, "none"); } }, [h("span", { text: m.notify }), sw]),
        h("button", { class: "row danger", type: "button", onclick: function () {
          var go = function (ok) { if (ok) act({ type: "delete" }); };
          if (tg && tg.showConfirm) tg.showConfirm(m.delete_confirm, go); else go(window.confirm(m.delete_confirm));
        } }, [h("span", { text: m.delete })])
      ]));
      parts.push(h("div", { class: "foot" }, [h("a", { href: "#", text: s.labels.policy, onclick: function (e) { e.preventDefault(); openUrl(s.links.privacy); } })]));
      return h("div", { class: "hero-less" }, parts);
    }
  };

  function render(s) {
    state = s;
    var draw = screens[s.screen];
    if (!draw) return;
    var key = s.screen + ":" + (s.question ? s.question.code : "");
    var node = draw(s);
    var animate = key !== lastScreenKey && navDir !== "none";
    node.className = (node.className + " screen" + (animate ? "" : " still") + (navDir === "back" ? " back" : "")).trim();
    if (!animate) node.style.animation = "none";
    lastScreenKey = key;
    app.replaceChildren(node);
    if (animate) window.scrollTo(0, 0);
  }

  // ---------- старт ----------
  if (!initData) {
    app.replaceChildren(h("div", { class: "hero" }, [h("h1", { text: "Откройте в Telegram" }),
      h("p", { class: "hint", text: "Это мини-приложение работает внутри Telegram." })]));
    return;
  }
  refresh();
})();
