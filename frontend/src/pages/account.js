import { api } from "../api.js";
import { field, h, notice, panel } from "../dom.js";
import { icon } from "../icons.js";

export async function renderAccountPage(ctx) {
  const me = await api("/api/auth/me");

  const currentInput = h("input", { type: "password", autocomplete: "current-password" });
  const newInput = h("input", { type: "password", autocomplete: "new-password", placeholder: "至少 8 位" });
  const confirmInput = h("input", { type: "password", autocomplete: "new-password" });
  const saveButton = h(
    "button",
    { class: "btn btn-primary", type: "button", onClick: save },
    icon("save"),
    "保存新密码",
  );
  const resultBox = h("div", { class: "stack" });

  async function save() {
    resultBox.replaceChildren();
    saveButton.disabled = true;
    try {
      await api("/api/auth/password", {
        method: "POST",
        body: {
          current_password: currentInput.value,
          new_password: newInput.value,
          new_password_confirm: confirmInput.value,
        },
      });
      currentInput.value = "";
      newInput.value = "";
      confirmInput.value = "";
      ctx.toast("密码已更新");
      resultBox.replaceChildren(notice("密码修改成功，下次登录请使用新密码。", "info"));
    } catch (error) {
      resultBox.replaceChildren(notice(error.message, "error"));
    } finally {
      saveButton.disabled = false;
    }
  }

  return [
    panel({
      title: "当前账号",
      subtitle: "面板唯一的管理员账号。",
      body: h(
        "div",
        { class: "stack" },
        h("div", { class: "row" }, h("span", { class: "kpi-label", text: "用户名" }), h("strong", { text: me.username })),
        notice(
          "忘记用户名或密码时，可在服务器上执行 python -m app.cli reset-admin 清空账号后重新创建，详见 README。",
          "info",
        ),
      ),
    }),
    panel({
      title: "修改密码",
      body: h(
        "div",
        { class: "stack" },
        h(
          "div",
          { class: "form-grid" },
          field("当前密码", currentInput),
          field("新密码", newInput),
          field("确认新密码", confirmInput),
        ),
        h("div", { class: "toolbar" }, saveButton),
        resultBox,
      ),
    }),
  ];
}
