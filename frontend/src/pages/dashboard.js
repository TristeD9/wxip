import { api } from "../api.js";
import { badge, emptyRow, h, notice, panel } from "../dom.js";
import { formatTime, syncStatusText, syncStatusTone } from "../format.js";
import { icon } from "../icons.js";

export async function renderDashboardPage(ctx) {
  const [state, events] = await Promise.all([
    api("/api/state"),
    api("/api/sync/events?limit=5"),
  ]);
  const apps = state.apps || [];
  const latestIp = state.latest_public_ip?.ip || null;
  const syncedApps = apps.filter((app) => app.last_synced_ip === latestIp && !app.last_error);
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
      const summary = await api("/api/sync/run", { method: "POST" });
      ctx.toast(`${syncStatusText(summary.status)}：${summary.message}`, summary.status === "failed" ? "error" : "info");
      ctx.refresh();
    } catch (error) {
      ctx.toast(error.message, "error");
    } finally {
      runButton.disabled = false;
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
    h("div", { class: "row" }, runButton),
    h(
      "div",
      { class: "row" },
      h("label", { class: "checkbox-row" }, autoInput, "启用自动同步"),
      h("label", { class: "checkbox-row" }, "间隔（秒）", intervalInput),
      saveButton,
    ),
  );

  return panel({
    title: "同步控制",
    subtitle:
      "同步会用最新公网 IP 覆盖所有自建应用的可信 IP，仅保留最新一条；自动同步与「立即同步」每次都会全量重写。",
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
          h("td", { class: "mono", text: app.last_synced_ip || "-" }),
          h(
            "td",
            {},
            app.last_error
              ? badge("失败", "error")
              : app.last_synced_ip === latestIp && latestIp
                ? badge("已是最新", "ok")
                : badge("待同步", "muted"),
          ),
          h("td", { text: formatTime(app.last_synced_at) }),
          h("td", { class: "mono", text: app.last_error || "-" }),
        ),
      )
    : [emptyRow(6, "暂无应用数据")];

  return panel({
    title: "自建应用",
    subtitle: "可信 IP 状态来自最近一次成功写入的记录。",
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
            h("th", { text: "最近覆盖 IP" }),
            h("th", { text: "状态" }),
            h("th", { text: "覆盖时间" }),
            h("th", { text: "最近错误" }),
          ),
        ),
        h("tbody", {}, rows),
      ),
    ),
  });
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
