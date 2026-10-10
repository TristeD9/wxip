import { api } from "../api.js";
import { badge, emptyRow, field, h, notice, panel } from "../dom.js";
import { describeTrustedIps, formatTime, loginStatusText, loginStatusTone } from "../format.js";
import { icon } from "../icons.js";

const LOGIN_POLL_INTERVAL_MS = 2000;

export async function renderWeComPage(ctx) {
  const [state, appsPayload, templatePayload, appsUrlPayload] = await Promise.all([
    api("/api/state"),
    api("/api/wecom/apps"),
    api("/api/wecom/template"),
    api("/api/wecom/apps-url"),
  ]);
  return [
    loginPanel(state.wecom_login, ctx),
    appsPanel(appsPayload.apps || [], ctx),
    templatePanel({
      title: "可信 IP 写入模板",
      subtitle:
        "解析后会自动把 IP 替换为 {ip}，把应用编号替换为 {agent_id} 或 {app_id}；同步时按应用逐个重放。",
      curlPlaceholder:
        "在企业微信管理后台手动改一次可信 IP，然后在开发者工具里对该请求选择 Copy as cURL，粘贴到这里",
      parseUrl: "/api/wecom/template/parse",
      saveUrl: "/api/wecom/template",
      payload: templatePayload,
      ctx,
    }),
    appsUrlPanel(appsUrlPayload.url, ctx),
  ];
}

function loginPanel(loginState, ctx) {
  const statusBadge = badge(loginStatusText(loginState), loginStatusTone(loginState));
  const hint = h("div", { class: "kpi-hint", text: loginState.message || "登录态只保存在本服务内。" });
  const qrBox = h("div", { class: "qr-box", style: "min-height: 160px" }, h("p", { class: "empty", text: "需要重新登录时点击右侧按钮" }));
  const startButton = h(
    "button",
    { class: "btn btn-primary", type: "button", onClick: startLogin },
    icon("qrcode"),
    "重新扫码登录",
  );

  async function startLogin() {
    startButton.disabled = true;
    qrBox.replaceChildren(h("div", { class: "spinner" }));
    try {
      const state = await api("/api/auth/wecom/login", { method: "POST" });
      renderQr(state);
      const timer = window.setInterval(async () => {
        const latest = await api("/api/auth/wecom/login");
        renderQr(latest);
        if (latest.status === "logged_in") {
          window.clearInterval(timer);
          ctx.toast("企业微信管理后台登录成功");
          ctx.refresh();
        } else if (latest.status === "failed") {
          window.clearInterval(timer);
        }
      }, LOGIN_POLL_INTERVAL_MS);
      ctx.onCleanup(() => window.clearInterval(timer));
    } catch (error) {
      qrBox.replaceChildren(h("p", { class: "empty", text: error.message }));
      ctx.toast(error.message, "error");
    } finally {
      startButton.disabled = false;
    }
  }

  function renderQr(state) {
    hint.textContent = state.message || "";
    if (state.qr_png_base64) {
      qrBox.replaceChildren(
        h("img", { alt: "企业微信登录二维码", src: `data:image/png;base64,${state.qr_png_base64}` }),
      );
    }
  }

  return panel({
    title: "企业微信登录",
    subtitle: "通过管理后台扫码建立会话，写入可信 IP 时复用这个登录态；它与面板账号无关。",
    actions: [statusBadge, startButton],
    body: h("div", { class: "stack" }, qrBox, hint),
  });
}

function appsPanel(apps, ctx) {
  const discoverButton = h(
    "button",
    { class: "btn btn-primary", type: "button", onClick: discover },
    icon("search"),
    "自动发现应用",
  );
  async function discover() {
    discoverButton.disabled = true;
    try {
      const result = await api("/api/wecom/apps/discover", { method: "POST" });
      ctx.toast(`已发现 ${result.apps.length} 个自建应用`);
      ctx.refresh();
    } catch (error) {
      ctx.toast(error.message, "error");
    } finally {
      discoverButton.disabled = false;
    }
  }

  const rows = apps.length
    ? apps.map((app) =>
        h(
          "tr",
          {},
          h("td", { class: "mono", text: app.agent_id }),
          h("td", { text: app.name }),
          h("td", { class: "mono", text: app.console_app_id || "-" }),
          h(
            "td",
            {},
            h("div", { class: "mono", text: describeTrustedIps(app) }),
            h("div", {
              class: "kpi-hint",
              text: app.trusted_ip_checked_at
                ? `读取于 ${formatTime(app.trusted_ip_checked_at)}`
                : "尚未读取",
            }),
          ),
          h("td", { class: "mono", text: app.last_synced_ip || "-" }),
          h("td", { text: app.last_error || "-" }),
        ),
      )
    : [emptyRow(6, "暂无应用数据")];

  return panel({
    title: "自建应用清单",
    subtitle:
      "「自动发现应用」会连管理后台一起读取应用名称、AgentId 与控制台应用编号，无需手工维护。",
    actions: [discoverButton],
    body: h(
      "div",
      { class: "stack" },
      h(
        "div",
        { class: "table-wrap" },
        h(
          "table",
          {},
          h(
            "thead",
            {},
            h(
              "tr",
              {},
              h("th", { text: "AgentId" }),
              h("th", { text: "应用名称" }),
              h("th", { text: "控制台应用编号" }),
              h("th", { text: "当前可信 IP（企业微信）" }),
              h("th", { text: "最近覆盖 IP" }),
              h("th", { text: "最近错误" }),
            ),
          ),
          h("tbody", {}, rows),
        ),
      ),
    ),
  });
}

function templatePanel({ title, subtitle, curlPlaceholder, parseUrl, saveUrl, payload, ctx }) {
  const curlInput = h("textarea", {
    placeholder: curlPlaceholder,
  });
  const parseButton = h(
    "button",
    { class: "btn btn-primary", type: "button", onClick: parseCurl },
    icon("search"),
    "解析 cURL",
  );
  const warningsBox = h("div", { class: "stack" });
  const previewBox = h(
    "div",
    { class: "table-wrap" },
    h("p", {
      class: "empty",
      text: payload.configured ? "已保存模板，可重新解析覆盖" : "尚未录制模板",
    }),
  );
  const jsonInput = h("textarea", {
    value: payload.configured ? JSON.stringify(payload.template, null, 2) : "",
    placeholder: '{ "method": "POST", "url": "...", "headers": {}, "body": "..." }',
  });
  const saveButton = h("button", { class: "btn", type: "button", onClick: saveTemplate }, icon("save"), "保存模板");

  async function parseCurl() {
    if (!curlInput.value.trim()) {
      ctx.toast("请先粘贴 cURL 命令", "error");
      return;
    }
    parseButton.disabled = true;
    try {
      const result = await api(parseUrl, {
        method: "POST",
        body: { curl: curlInput.value },
      });
      jsonInput.value = JSON.stringify(result.template, null, 2);
      renderPreview(result.template);
      warningsBox.replaceChildren(...(result.warnings || []).map((text) => notice(text, "warn")));
    } catch (error) {
      ctx.toast(error.message, "error");
    } finally {
      parseButton.disabled = false;
    }
  }

  async function saveTemplate() {
    saveButton.disabled = true;
    try {
      const template = JSON.parse(jsonInput.value);
      const result = await api(saveUrl, { method: "PUT", body: template });
      warningsBox.replaceChildren(...(result.warnings || []).map((text) => notice(text, "warn")));
      ctx.toast("请求模板已保存");
      renderPreview(template);
    } catch (error) {
      ctx.toast(error instanceof SyntaxError ? "模板不是合法 JSON" : error.message, "error");
    } finally {
      saveButton.disabled = false;
    }
  }

  function renderPreview(template) {
    previewBox.replaceChildren(
      h(
        "table",
        {},
        h(
          "tbody",
          {},
          h("tr", {}, h("th", { text: "方法" }), h("td", { class: "mono", text: template.method })),
          h("tr", {}, h("th", { text: "地址" }), h("td", { class: "mono", text: template.url })),
          h("tr", {}, h("th", { text: "请求体" }), h("td", { class: "mono", text: template.body || "-" })),
        ),
      ),
    );
  }

  return panel({
    title,
    subtitle,
    actions: [parseButton],
    body: h(
      "div",
      { class: "stack" },
      h("div", { class: "field" }, h("label", { text: "粘贴 cURL" }), curlInput),
      warningsBox,
      h(
        "div",
        { class: "stack" },
        h("div", { class: "kpi-label", text: "解析结果" }),
        previewBox,
      ),
      h("div", { class: "field" }, h("label", { text: "模板 JSON（可手工修正占位符）" }), jsonInput),
      h("div", { class: "toolbar" }, saveButton),
    ),
  });
}

function appsUrlPanel(currentUrl, ctx) {
  const input = h("input", { type: "text", value: currentUrl });
  const saveButton = h("button", { class: "btn", type: "button", onClick: save }, icon("save"), "保存地址");

  async function save() {
    saveButton.disabled = true;
    try {
      await api("/api/wecom/apps-url", { method: "PUT", body: { url: input.value.trim() } });
      ctx.toast("应用管理页地址已保存");
    } catch (error) {
      ctx.toast(error.message, "error");
    } finally {
      saveButton.disabled = false;
    }
  }

  return panel({
    title: "应用管理页地址",
    subtitle: "企业微信后台改版导致自动发现失败时，可以在这里替换地址。",
    body: h("div", { class: "stack" }, field("页面地址", input), h("div", { class: "toolbar" }, saveButton)),
  });
}

