/* The kit every mock app is written with: one way to build DOM, and the controls.

   Every control states its role and label in the DOM (role, aria-label, aria-checked), which is
   what the snapshot turns into the accessibility tree, so each app reports itself the same way.
   A control is built from plain elements: a native <select>, date input, alert or tooltip is
   drawn outside the page, where the adapter can neither see nor drive it.

   `key` names an element across renders: the page is rebuilt from the state after every change,
   and an element with the same key gets its focus, caret and scroll position back. */
"use strict";

const Kit = (function () {
  function h(tag, props, ...children) {
    const el = document.createElement(tag);
    for (const [name, value] of Object.entries(props || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (name === "class") el.className = value;
      else if (name === "style") el.setAttribute("style", value);
      else if (name === "key") el.dataset.key = value;
      else if (name === "value") el.value = value;
      else if (name.startsWith("on")) el.addEventListener(name.slice(2), value);
      else el.setAttribute(name, value === true ? "" : String(value));
    }
    append(el, children);
    return el;
  }

  function append(el, children) {
    for (const child of children) {
      if (child === null || child === undefined || child === false) continue;
      if (Array.isArray(child)) append(el, child);
      else el.appendChild(typeof child === "string" || typeof child === "number" ? document.createTextNode(String(child)) : child);
    }
  }

  // A click that is the control's own: it must not also reach a row or a backdrop under it.
  function own(fn) {
    return (event) => {
      event.stopPropagation();
      fn(event);
    };
  }

  function button({ label, onPress, primary, key, pointerOnly }) {
    // A pointer-only control answers to pointer events alone, as some web controls do: a press
    // through accessibility (a DOM click) lands and does nothing, so the loop has to fall back.
    const props = { class: primary ? "btn primary" : "btn", role: "button", key };
    if (pointerOnly) {
      let down = false;
      props.onpointerdown = () => (down = true);
      props.onpointerup = own(() => {
        if (down) onPress();
        down = false;
      });
      props.onclick = (event) => event.stopPropagation();
    } else {
      props.onclick = own(onPress);
    }
    return h("div", props, label);
  }

  function toggle({ label, on, onToggle, key }) {
    return h(
      "div",
      { class: "switch", role: "switch", "aria-checked": on ? "true" : "false", "aria-label": label, key, onclick: own(onToggle) },
      h("span", { class: "knob" }),
    );
  }

  function popup({ label, value, onOpen, key }) {
    return h(
      "div",
      { class: "popup", role: "button", "aria-haspopup": "menu", "aria-label": label, key, onclick: own((e) => onOpen(e.currentTarget)) },
      h("span", {}, value),
      h("span", { class: "chev" }, "⌄"),
    );
  }

  function radios({ label, options, value, onPick, key }) {
    return h(
      "div",
      { class: "radios", role: "radiogroup", "aria-label": label, key },
      options.map((option) =>
        h(
          "div",
          { class: "radio", role: "radio", "aria-checked": option === value ? "true" : "false", "aria-label": option, onclick: own(() => onPick(option)) },
          h("span", { class: "dot" }),
          h("span", {}, option),
        ),
      ),
    );
  }

  function textField({ label, placeholder, value, onInput, onKey, key, search, password }) {
    const field = h("input", {
      class: search ? "field search" : "field",
      type: password ? "password" : "text",
      role: search ? "searchbox" : "textbox",
      "aria-label": label,
      placeholder,
      value: value || "",
      key,
      spellcheck: "false",
      autocomplete: "off",
      oninput: (e) => onInput && onInput(e.target.value),
      onkeydown: (e) => onKey && onKey(e),
      onclick: (e) => e.stopPropagation(),
    });
    if (!search) return field;
    return h("div", { class: "search-wrap" }, h("span", { class: "glass", "aria-hidden": "true" }, "⌕"), field);
  }

  return { h, own, button, toggle, popup, radios, textField };
})();
