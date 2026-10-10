import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../src/api.js", () => ({
  api: vi.fn(async (path) => {
    if (path === "/api/state") return buildState();
    if (path.startsWith("/api/sync/events")) return [];
    if (path === "/api/sync/run") {
      return { status: "ok", message: "已覆盖 1/1 个应用的可信 IP" };
    }
    return {};
  }),
}));

import { api } from "../src/api.js";
import { renderDashboardPage } from "../src/pages/dashboard.js";

function buildState() {
  return {
    ikuai: { configured: true },
    wecom_login: { status: "logged_in", message: "已登录企业微信管理后台" },
    template_configured: true,
    apps: [
      {
        agent_id: "1230002",
        name: "示例应用",
        console_app_id: "5629500000000002",
        last_synced_ip: "223.5.5.5",
        last_synced_at: "2026-10-10T06:00:00+00:00",
        last_error: null,
      },
    ],
    sync_settings: { auto_enabled: true, interval_seconds: 300 },
    latest_public_ip: {
      ip: "223.5.5.5",
      source: "ikuai",
      checked_at: "2026-10-10T06:00:00+00:00",
    },
    last_sync: {
      started_at: "2026-10-10T06:00:00+00:00",
      finished_at: "2026-10-10T06:00:01+00:00",
      public_ip: "223.5.5.5",
      status: "ok",
      message: "已覆盖 1/1 个应用的可信 IP",
      results: [],
    },
    scheduler_running: true,
  };
}

function buildContext() {
  return { refresh: vi.fn(), toast: vi.fn() };
}

function renderToHtml(nodes) {
  return nodes.map((node) => node.outerHTML).join("");
}

function findButton(nodes, label) {
  for (const node of nodes) {
    for (const button of node.querySelectorAll("button")) {
      if (button.textContent.includes(label)) return button;
    }
  }
  return null;
}

beforeEach(() => {
  api.mockClear();
});

describe("仪表盘渲染", () => {
  it("展示应用、当前公网 IP 与最近同步结果", async () => {
    const html = renderToHtml(await renderDashboardPage(buildContext()));

    expect(html).toContain("示例应用");
    expect(html).toContain("223.5.5.5");
    expect(html).toContain("已是最新");
    expect(html).toContain("已覆盖 1/1 个应用的可信 IP");
  });

  it("不再出现已移除的「当前可信 IP」入口", async () => {
    const html = renderToHtml(await renderDashboardPage(buildContext()));

    expect(html).not.toContain("获取当前可信 IP");
    expect(html).not.toContain("当前可信 IP");
  });

  it("渲染结果里不会漏出 undefined", async () => {
    const html = renderToHtml(await renderDashboardPage(buildContext()));

    expect(html).not.toContain("undefined");
  });
});

describe("同步控制", () => {
  it("点「立即同步」会调用 /api/sync/run", async () => {
    const ctx = buildContext();
    const nodes = await renderDashboardPage(ctx);
    const button = findButton(nodes, "立即同步");

    expect(button).not.toBeNull();
    button.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    await vi.waitFor(() => {
      expect(api).toHaveBeenCalledWith("/api/sync/run", { method: "POST" });
    });
    expect(ctx.refresh).toHaveBeenCalled();
  });
});
