export function h(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "html") node.innerHTML = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === "value") node.value = value;
    else if (key === "checked" || key === "disabled" || key === "selected") node[key] = value;
    else node.setAttribute(key, value);
  }
  appendChildren(node, children);
  return node;
}

export function appendChildren(node, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

export function panel({ title, subtitle, actions, body }) {
  const header = h(
    "div",
    { class: "panel-header" },
    h("div", {}, h("h2", { text: title }), subtitle ? h("p", { text: subtitle }) : null),
    actions ? h("div", { class: "toolbar" }, actions) : null,
  );
  return h("section", { class: "panel" }, header, h("div", { class: "panel-body" }, body));
}

export function field(label, input) {
  return h("div", { class: "field" }, h("label", { text: label }), input);
}

export function badge(text, tone = "muted") {
  return h("span", { class: `badge badge-${tone}`, text });
}

export function notice(message, tone = "info") {
  return h("div", { class: `notice notice-${tone}`, text: message });
}

export function emptyRow(columnCount, message) {
  return h(
    "tr",
    {},
    h("td", { colspan: String(columnCount), class: "empty", text: message }),
  );
}

export function spinner() {
  return h("div", { class: "spinner" });
}

export function loadingBlock() {
  return h("div", { class: "empty" }, spinner());
}

export function toast(message, tone = "info") {
  let host = document.querySelector(".toast-host");
  if (!host) {
    host = h("div", { class: "toast-host" });
    document.body.append(host);
  }
  const node = h("div", { class: `toast${tone === "error" ? " is-error" : ""}`, text: message });
  host.append(node);
  window.setTimeout(() => node.remove(), 4200);
}

