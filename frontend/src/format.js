const SYNC_STATUS_TEXT = {
  ok: "同步成功",
  unchanged: "无需同步",
  failed: "同步失败",
};

const SYNC_STATUS_TONE = {
  ok: "ok",
  unchanged: "muted",
  failed: "error",
};

export function formatTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("zh-CN", { hour12: false });
}

export function syncStatusText(status) {
  return SYNC_STATUS_TEXT[status] || status || "-";
}

export function syncStatusTone(status) {
  return SYNC_STATUS_TONE[status] || "muted";
}

export function loginStatusText(state) {
  const map = {
    idle: "未登录",
    waiting_scan: "等待扫码",
    logged_in: "已登录",
    failed: "登录失败",
  };
  return map[state?.status] || "未登录";
}

export function loginStatusTone(state) {
  const map = { logged_in: "ok", waiting_scan: "warn", failed: "error" };
  return map[state?.status] || "muted";
}

export function describeTrustedIps(app) {
  if (!Array.isArray(app?.current_trusted_ips)) return "未知";
  return app.current_trusted_ips.length ? app.current_trusted_ips.join("、") : "未设置";
}
