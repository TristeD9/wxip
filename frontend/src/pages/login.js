import { api, setToken } from "../api.js";
import { field, h, notice } from "../dom.js";
import { icon } from "../icons.js";

export function renderLoginPage(ctx) {
  const formHost = h("div", { class: "stack" });
  const statusLine = h("div", { class: "kpi-hint" });

  const screen = h(
    "div",
    { class: "login-screen" },
    h(
      "div",
      { class: "login-panel" },
      h(
        "div",
        {},
        h("h1", { text: "企业微信可信 IP 自动维护" }),
        h("div", { class: "kpi-hint", text: "面板账号与企业微信登录是两回事，分别管理。" }),
      ),
      formHost,
      statusLine,
    ),
  );

  loadSetupStatus();
  return screen;

  async function loadSetupStatus() {
    formHost.replaceChildren(h("div", { class: "empty" }, h("div", { class: "spinner" })));
    try {
      const status = await api("/api/auth/setup/status", { auth: false });
      renderForm(Boolean(status.initialized));
    } catch (error) {
      formHost.replaceChildren(notice(`无法读取初始化状态：${error.message}`, "error"));
    }
  }

  function renderForm(initialized) {
    const usernameInput = h("input", {
      type: "text",
      autocomplete: "username",
      placeholder: initialized ? "请输入管理员用户名" : "例如 admin",
    });
    const passwordInput = h("input", {
      type: "password",
      autocomplete: initialized ? "current-password" : "new-password",
      placeholder: initialized ? "请输入密码" : "至少 8 位",
    });
    const confirmInput = initialized
      ? null
      : h("input", {
          type: "password",
          autocomplete: "new-password",
          placeholder: "再输入一次密码",
        });
    const submitButton = h(
      "button",
      { class: "btn btn-primary btn-block", type: "submit" },
      icon(initialized ? "logout" : "plus"),
      initialized ? "登录" : "创建管理员账号",
    );

    const form = h(
      "form",
      { class: "stack", onSubmit: submit },
      h(
        "div",
        {},
        initialized
          ? h("div", { class: "kpi-hint", text: "使用管理员账号登录面板。" })
          : notice("首次部署：请先创建管理员账号，企业微信扫码在登录后的「企业微信」页面进行。", "info"),
      ),
      field("用户名", usernameInput),
      field("密码", passwordInput),
      confirmInput ? field("确认密码", confirmInput) : null,
      submitButton,
    );
    formHost.replaceChildren(form);
    usernameInput.focus();

    async function submit(event) {
      event.preventDefault();
      submitButton.disabled = true;
      statusLine.textContent = initialized ? "正在登录…" : "正在创建账号…";
      try {
        const payload = initialized
          ? { username: usernameInput.value.trim(), password: passwordInput.value }
          : {
              username: usernameInput.value.trim(),
              password: passwordInput.value,
              password_confirm: confirmInput.value,
            };
        const session = await api(initialized ? "/api/auth/login" : "/api/auth/setup", {
          method: "POST",
          auth: false,
          body: payload,
        });
        setToken(session.token);
        statusLine.textContent = `已登录：${session.username}`;
        ctx.onLoggedIn();
      } catch (error) {
        statusLine.textContent = error.message;
        submitButton.disabled = false;
      }
    }
  }
}

