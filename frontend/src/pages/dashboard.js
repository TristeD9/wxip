import { api } from "../api.js";
import { badge, emptyRow, h, notice, panel } from "../dom.js";
import { describeTrustedIps, formatTime, syncStatusText, syncStatusTone } from "../format.js";
import { icon } from "../icons.js";

export async function renderDashboardPage(ctx) {
  const [state, events] = await Promise.all([
    api("/api/state"),
    api("/api/sync/events?limit=5"),
  ]);
  const apps = state.apps || [];
  const latestIp = state.latest_public_ip?.ip || null;
  const syncedApps = apps.filter((app) => isTrustedIpCurrent(app, latestIp));
  const nodes = [];

  if (state.wecom_login.status !== "logged_in") {
    nodes.push(notice("企业微信管理后台尚未登录，请到「企业微信」页面扫码登录。", "warn"));
  }
  if (!state.ikuai.configured) {
    nodes.push(notice("尚未配置 iKuai 连接参数，暂时只能依赖外部回显服务获取公网 IP。", "warn"));
  }
  if (!state.template_configured) {
    nodes.push(notice("尚未录制可信 IP 请求模板，自动同步不会执行。", "warn"));
  }
  if (!state.read_template_configured) {
    nodes.push(
      notice(
        "尚未录制「读取可信 IP 模板」，应用列表无法显示企业微信里的当前可信 IP（显示为未知）。",
        "info",
      ),
    );
  }
  if (apps.length === 0) {
    nodes.push(notice("尚未获取自建应用清单，请在「企业微信」页面自动发现或手工导入。", "info"));
  }

  nodes.push(
    h(
      "div",
      { class: "kpi-grid" },
      kpi(
        "当前公网 IP",
        latestIp || "-",
        state.latest_public_ip
          ? `来源：${state.latest_public_ip.source} · ${formatTime(state.latest_public_ip.checked_at)}`
          : "尚无观测记录",
      ),
      kpi("自建应用", String(apps.length), `已覆盖 ${syncedApps.length} 个`),
      kpi(
        "自动同步",
        state.sync_settings.auto_enabled ? "已开启" : "已关闭",
        `间隔 ${state.sync_settings.interval_seconds} 秒 · 调度器${state.scheduler_running ? "运行中" : "未运行"}`,
      ),
      kpi(
        "最近一次同步",
        syncStatusText(state.last_sync?.status),
        state.last_sync
          ? `${state.last_sync.message} · ${formatTime(state.last_sync.finished_at)}`
          : "尚无同步记录",
      ),
    ),
  );

  nodes.push(syncPanel(state, ctx));
  nodes.push(appsPanel(apps, latestIp));
  nodes.push(recentEventsPanel(events));
  return nodes;
}

function kpi(label, value, hint) {
  return h(
    "article",
    { class: "kpi" },
    h("div", { class: "kpi-label", text: label }),
    h("div", { class: "kpi-value", text: value }),
    h("div", { class: "kpi-hint", text: hint }),
  );
}

function syncPanel(state, ctx) {
  const runButton = h(
    "button",
    { class: "btn btn-primary", type: "button", onClick: runSync },
    icon("play"),
    "立即同步",
  );
  const refreshButton = h(
    "button",
    { class: "btn", type: "button", onClick: refreshTrustedIps },
    icon("refresh"),
    "获取当前可信 IP",
  );
  const autoInput = h("input", { type: "checkbox", checked: state.sync_settings.auto_enabled });
  const intervalInput = h("input", {
    type: "number",
    min: "30",
    max: "86400",
    step: "30",
    value: String(state.sync_settings.interval_seconds),
  });
  const saveButton = h(
    "button",
    { class: "btn", type: "button", onClick: saveSettings },
    icon("save"),
    "保存设置",
  );

  async function runSync() {
    runButton.disabled = true;
    try {
      const summary = await api("/api/sync/run", {
        method: "POST",
        body: { force: true },
      });
      ctx.toast(`${syncStatusText(summary.status)}：${summary.message}`, summary.status === "failed" ? "error" : "info");
      ctx.refresh();
    } catch (error) {
      ctx.toast(error.message, "error");
    } finally {
      runButton.disabled = false;
    }
  }

  async function refreshTrustedIps() {
    refreshButton.disabled = true;
    try {
      const result = await api("/api/sync/refresh-trusted-ips", { method: "POST" });
      ctx.toast(result.message, result.failed ? "error" : "info");
      ctx.refresh();
    } catch (error) {
      ctx.toast(error.message, "error");
    } finally {
      refreshButton.disabled = false;
    }
  }

  async function saveSettings() {
    saveButton.disabled = true;
    try {
      await api("/api/sync/settings", {
        method: "PUT",
        body: {
          auto_enabled: autoInput.checked,
          interval_seconds: Number(intervalInput.value),
        },
      });
      ctx.toast("自动同步设置已保存");
      ctx.refresh();
    } catch (error) {
      ctx.toast(error.message, "error");
    } finally {
      saveButton.disabled = false;
    }
  }

  const body = h(
    "div",
    { class: "stack" },
    h("div", { class: "row" }, runButton, refreshButton),
    h(
      "div",
      { class: "row" },
      h("label", { class: "checkbox-row" }, autoInput, "启用自动同步"),
      h("label", { class: "checkbox-row" }, "间隔（秒）", intervalInput),
      saveButton,
    ),
    h("div", {
      class: "kpi-hint",
      text:
        "「获取当前可信 IP」只读不写，随时核对；关闭自动同步后仍会按间隔读取当前可信 IP，" +
        "但不会自动覆盖。",
    }),
  );

  return panel({
    title: "同步控制",
    subtitle:
      "「立即同步」先读取各应用当前可信 IP，只覆盖与最新公网 IP 不一致的应用，最终只保留最新一条。",
    body,
  });
}

function appsPanel(apps, latestIp) {
  const rows = apps.length
    ? apps.map((app) =>
        h(
          "tr",
          {},
          h("td", { text: app.name }),
          h("td", { class: "mono", text: app.agent_id }),
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
          h("td", {}, appStatusBadge(app, latestIp)),
          h("td", { class: "mono", text: app.last_synced_ip || "-" }),
          h("td", { text: formatTime(app.last_synced_at) }),
          h("td", { class: "mono", text: app.last_error || "-" }),
        ),
      )
    : [emptyRow(7, "暂无应用数据")];

  return panel({
    title: "自建应用",
    subtitle: "「当前可信 IP」是企业微信后台的真实读数；未配置读取模板或读取失败时显示为未知。",
    body: h(
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
            h("th", { text: "应用名称" }),
            h("th", { text: "AgentId" }),
            h("th", { text: "当前可信 IP（企业微信）" }),
            h("th", { text: "状态" }),
            h("th", { text: "最近覆盖 IP" }),
            h("th", { text: "覆盖时间" }),
            h("th", { text: "最近错误" }),
          ),
        ),
        h("tbody", {}, rows),
      ),
    ),
  });
}

function isTrustedIpCurrent(app, latestIp) {
  if (!latestIp) return false;
  if (Array.isArray(app.current_trusted_ips)) {
    return app.current_trusted_ips.length === 1 && app.current_trusted_ips[0] === latestIp;
  }
  // 还没读到真实值时退回本地记录，避免未配置读取模板的部署显示成"全部未覆盖"
  return app.last_synced_ip === latestIp;
}

function appStatusBadge(app, latestIp) {
  if (app.last_error) return badge("失败", "error");
  if (!Array.isArray(app.current_trusted_ips)) return badge("未知", "muted");
  return isTrustedIpCurrent(app, latestIp) ? badge("已最新", "ok") : badge("待更新", "warn");
}

function recentEventsPanel(events) {
  const rows = events.length
    ? events.map((event) =>
        h(
          "tr",
          {},
          h("td", { text: formatTime(event.finished_at) }),
          h("td", { class: "mono", text: event.public_ip || "-" }),
          h("td", {}, badge(syncStatusText(event.status), syncStatusTone(event.status))),
          h("td", { text: event.message }),
        ),
      )
    : [emptyRow(4, "暂无同步记录")];

  return panel({
    title: "最近同步",
    body: h(
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
            h("th", { text: "时间" }),
            h("th", { text: "公网 IP" }),
            h("th", { text: "结果" }),
            h("th", { text: "说明" }),
          ),
        ),
        h("tbody", {}, rows),
      ),
    ),
  });
}

