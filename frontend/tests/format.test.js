import { describe, expect, it } from "vitest";

import {
  formatTime,
  loginStatusText,
  loginStatusTone,
  syncStatusText,
  syncStatusTone,
} from "../src/format.js";

describe("formatTime", () => {
  it("空值返回占位符", () => {
    expect(formatTime(null)).toBe("-");
    expect(formatTime("")).toBe("-");
  });

  it("无法解析的值原样返回，不显示 Invalid Date", () => {
    expect(formatTime("not-a-date")).toBe("not-a-date");
  });

  it("合法时间返回本地化文本", () => {
    expect(formatTime("2026-10-10T06:00:00+00:00")).toContain("2026");
  });
});

describe("同步状态文案", () => {
  it("三种状态都有对应文案与色调", () => {
    expect(syncStatusText("ok")).toBe("同步成功");
    expect(syncStatusText("unchanged")).toBe("无需同步");
    expect(syncStatusText("failed")).toBe("同步失败");
    expect(syncStatusTone("ok")).toBe("ok");
    expect(syncStatusTone("failed")).toBe("error");
  });

  it("未知状态有兜底，不会渲染出 undefined", () => {
    expect(syncStatusText(undefined)).toBe("-");
    expect(syncStatusTone("something-else")).toBe("muted");
  });
});

describe("登录状态文案", () => {
  it("已登录与等待扫码有对应文案", () => {
    expect(loginStatusText({ status: "logged_in" })).toBe("已登录");
    expect(loginStatusText({ status: "waiting_scan" })).toBe("等待扫码");
    expect(loginStatusTone({ status: "logged_in" })).toBe("ok");
    expect(loginStatusTone({ status: "failed" })).toBe("error");
  });

  it("没有状态时按未登录处理", () => {
    expect(loginStatusText(undefined)).toBe("未登录");
    expect(loginStatusTone(undefined)).toBe("muted");
  });
});
