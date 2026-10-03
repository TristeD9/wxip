import { api } from "../api.js";
import { field, h, notice, panel } from "../dom.js";
import { icon } from "../icons.js";

const DEFAULT_SETTINGS = {
  configured: false,
  base_url: "http://192.168.1.1",
  username: "admin",
  password_set: false,
  verify_tls: true,
  timeout_seconds: 10,
};

export async function renderIKuaiPage(ctx) {
  const stored = await api("/api/ikuai/settings").catch(() => DEFAULT_SETTINGS);
  const settings = { ...DEFAULT_SETTINGS, ...stored };

  const baseUrlInput = h("input", { type: "text", value: settings.base_url, placeholder: "http://192.168.1.1" });
  const usernameInput = h("input", { type: "text", value: settings.username });
  const passwordInput = h("input", {
    type: "password",
    placeholder: settings.password_set ? "已保存，留空表示不修改" : "请输入 iKuai 登录密码",
  });
  const verifyTlsInput = h("input", { type: "checkbox", checked: Boolean(settings.verify_tls) });
  const timeoutInput = h("input", { type: "number", min: "1", max: "60", value: String(settings.timeout_seconds) });

  const saveButton = h("button", { class: "btn btn-primary", type: "button", onClick: save }, icon("save"), "保存");
  const testButton = h("button", { class: "btn", type: "button", onClick: test }, icon("zap"), "测试并读取公网 IP");
  const probeButton = h("button", { class: "btn", type: "button", onClick: probe }, icon("search"), "探测原始响应");
  const resultBox = h("div", { class: "empty", text: "尚未执行测试" });

  function readForm() {
    return {
      base_url: baseUrlInput.value.trim(),
      username: usernameInput.value.trim() || "admin",
      password: passwordInput.value,
      verify_tls: verifyTlsInput.checked,
      timeout_seconds: Number(timeoutInput.value) || 10,
    };
  }

  async function save() {
    saveButton.disabled = true;
    try {
      await api("/api/ikuai/settings", { method: "PUT", body: readForm() });
      ctx.toast("iKuai 配置已保存");
      ctx.refresh();
    } catch (error) {
      ctx.toast(error.message, "error");
    } finally {
      saveButton.disabled = false;
    }
  }

  async function test() {
    testButton.disabled = true;
    resultBox.replaceChildren(h("div", { class: "spinner" }));
    try {
      const result = await api("/api/ikuai/test", { method: "POST" });
      resultBox.replaceChildren(h("div", { class: "notice notice-info", text: `解析到公网 IP：${result.public_ip}` }));
    } catch (error) {
      resultBox.replaceChildren(h("div", { class: "notice notice-error", text: error.message }));
    } finally {
      testButton.disabled = false;
    }
  }

  async function probe() {
    probeButton.disabled = true;
    resultBox.replaceChildren(h("div", { class: "spinner" }));
    try {
      const result = await api("/api/ikuai/probe", { method: "POST" });
      resultBox.replaceChildren(
        h("pre", { class: "pre-block", text: JSON.stringify(result.probes, null, 2) }),
      );
    } catch (error) {
      resultBox.replaceChildren(h("div", { class: "notice notice-error", text: error.message }));
    } finally {
      probeButton.disabled = false;
    }
  }

  return [
    notice("iKuai 固件版本较多，如果测试失败请先执行「探测原始响应」，把返回内容用于适配。", "info"),
    panel({
      title: "iKuai 连接",
      subtitle: "用于读取路由器 WAN 口的公网 IP，登录信息只保存在本机数据库。",
      body: h(
        "div",
        { class: "stack" },
        h(
          "div",
          { class: "form-grid" },
          field("管理地址", baseUrlInput),
          field("用户名", usernameInput),
          field("密码", passwordInput),
          field("超时时间（秒）", timeoutInput),
        ),
        h("label", { class: "checkbox-row" }, verifyTlsInput, "校验 HTTPS 证书"),
        h("div", { class: "toolbar" }, saveButton, testButton, probeButton),
      ),
    }),
    panel({ title: "测试结果", body: resultBox }),
  ];
}
