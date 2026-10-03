import { ApiError, clearToken, getToken } from "./api.js";
import { h, loadingBlock, toast } from "./dom.js";
import { icon } from "./icons.js";
import { renderDashboardPage } from "./pages/dashboard.js";
import { renderIKuaiPage } from "./pages/ikuai.js";
import { renderLoginPage } from "./pages/login.js";
import { renderLogsPage } from "./pages/logs.js";
import { renderWeComPage } from "./pages/wecom.js";
import { renderAccountPage } from "./pages/account.js";

const ROUTES = [
  { id: "dashboard", label: "仪表盘", iconName: "dashboard", render: renderDashboardPage },
  { id: "wecom", label: "企业微信", iconName: "boxes", render: renderWeComPage },
  { id: "ikuai", label: "iKuai", iconName: "router", render: renderIKuaiPage },
  { id: "logs", label: "同步日志", iconName: "logs", render: renderLogsPage },
  { id: "account", label: "账号", iconName: "user", render: renderAccountPage },
];

const root = document.getElementById("root");
const contentHost = h("div", { class: "content" });
const cleanups = [];

const ctx = {
  navigate(routeId) {
    window.location.hash = `#/${routeId}`;
  },
  refresh() {
    render();
  },
  onLoggedIn() {
    window.location.hash = "#/dashboard";
    render();
  },
  onCleanup(callback) {
    cleanups.push(callback);
  },
  toast,
};

function currentRouteId() {
  const raw = window.location.hash.replace(/^#\/?/, "");
  return ROUTES.some((route) => route.id === raw) ? raw : "dashboard";
}

function renderShell(activeRouteId) {
  const nav = h(
    "nav",
    { class: "nav" },
    ROUTES.map((route) =>
      h(
        "button",
        {
          class: `nav-item${route.id === activeRouteId ? " is-active" : ""}`,
          type: "button",
          onClick: () => ctx.navigate(route.id),
        },
        icon(route.iconName),
        route.label,
      ),
    ),
  );

  const sidebar = h(
    "aside",
    { class: "sidebar" },
    h(
      "div",
      { class: "brand" },
      h("div", { class: "brand-title", text: "可信 IP 维护" }),
      h("div", { class: "brand-subtitle", text: "企业微信 x iKuai" }),
    ),
    nav,
    h("div", { class: "sidebar-footer", text: "仅在本机保存登录态与配置" }),
  );

  const activeRoute = ROUTES.find((route) => route.id === activeRouteId);
  const topbar = h(
    "header",
    { class: "topbar" },
    h("h1", { text: activeRoute.label }),
    h(
      "div",
      { class: "topbar-actions" },
      h(
        "button",
        { class: "btn btn-icon", type: "button", title: "刷新", onClick: () => ctx.refresh() },
        icon("refresh"),
      ),
      h(
        "button",
        {
          class: "btn btn-icon",
          type: "button",
          title: "退出登录",
          onClick: () => {
            clearToken();
            ctx.refresh();
          },
        },
        icon("logout"),
      ),
    ),
  );

  return h("div", { class: "app-shell" }, sidebar, h("main", { class: "main" }, topbar, contentHost));
}

async function render() {
  while (cleanups.length > 0) {
    cleanups.pop()();
  }
  if (!getToken()) {
    root.replaceChildren(renderLoginPage(ctx));
    return;
  }

  const routeId = currentRouteId();
  root.replaceChildren(renderShell(routeId));
  contentHost.replaceChildren(loadingBlock());

  const route = ROUTES.find((item) => item.id === routeId);
  try {
    const nodes = await route.render(ctx);
    contentHost.replaceChildren(...nodes);
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      clearToken();
      toast("会话已过期，请重新扫码登录", "error");
      render();
      return;
    }
    contentHost.replaceChildren(
      h(
        "div",
        { class: "notice notice-error" },
        `${error.message || error}。可点击右上角刷新按钮重试。`,
      ),
    );
  }
}

window.addEventListener("hashchange", render);
render();
