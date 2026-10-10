import { describe, expect, it, vi } from "vitest";

vi.mock("../src/api.js", () => ({
  api: vi.fn(async (path) => {
    if (path === "/api/state") {
      return { wecom_login: { status: "logged_in", message: "已登录企业微信管理后台" } };
    }
    if (path === "/api/wecom/apps") {
      return {
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
      };
    }
    if (path === "/api/wecom/template") {
      return {
        configured: true,
        template: {
          method: "POST",
          url: "https://example.com/saveIpConfig",
          headers: {},
          body: "app_id={app_id}&ipList%5B%5D={ip}",
        },
        headers_preview: {},
      };
    }
    if (path === "/api/wecom/apps-url") {
      return { url: "https://work.weixin.qq.com/wework_admin/frame#apps" };
    }
    return {};
  }),
}));

import { renderWeComPage } from "../src/pages/wecom.js";

function buildContext() {
  return { refresh: vi.fn(), toast: vi.fn() };
}

async function renderToHtml() {
  const nodes = await renderWeComPage(buildContext());
  return nodes.map((node) => node.outerHTML).join("");
}

describe("企业微信页渲染", () => {
  it("展示应用清单与控制台应用编号", async () => {
    const html = await renderToHtml();

    expect(html).toContain("示例应用");
    expect(html).toContain("1230002");
    expect(html).toContain("5629500000000002");
  });

  it("不再提供手工导入清单的入口", async () => {
    const html = await renderToHtml();

    expect(html).not.toContain("手工导入");
    expect(html).not.toContain("导入清单");
  });

  it("不再显示已移除的「当前可信 IP」列", async () => {
    const html = await renderToHtml();

    expect(html).not.toContain("当前可信 IP");
  });

  it("渲染结果里不会漏出 undefined", async () => {
    const html = await renderToHtml();

    expect(html).not.toContain("undefined");
  });
});
