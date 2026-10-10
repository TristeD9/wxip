import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // 页面模块直接操作 document，用 jsdom 提供最小浏览器环境
    environment: "jsdom",
    include: ["tests/**/*.test.js"],
  },
});
