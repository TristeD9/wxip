import { api } from "../api.js";
import { badge, emptyRow, h, panel } from "../dom.js";
import { formatTime, syncStatusText, syncStatusTone } from "../format.js";

export async function renderLogsPage() {
  const events = await api("/api/sync/events?limit=100");
  const rows = events.length
    ? events.flatMap((event) => [eventRow(event), ...detailRows(event)])
    : [emptyRow(4, "暂无同步记录")];

  return [
    panel({
      title: "同步日志",
      subtitle: "保留最近 100 次同步，包括每次覆盖到哪些应用。",
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
              h("th", { text: "完成时间" }),
              h("th", { text: "公网 IP" }),
              h("th", { text: "结果" }),
              h("th", { text: "说明" }),
            ),
          ),
          h("tbody", {}, rows),
        ),
      ),
    }),
  ];
}

function eventRow(event) {
  return h(
    "tr",
    {},
    h("td", { text: formatTime(event.finished_at) }),
    h("td", { class: "mono", text: event.public_ip || "-" }),
    h("td", {}, badge(syncStatusText(event.status), syncStatusTone(event.status))),
    h("td", { text: event.message }),
  );
}

function detailRows(event) {
  if (!event.results || event.results.length === 0) return [];
  const items = event.results.map((result) =>
    h(
      "li",
      {},
      `${result.name}（${result.agent_id}）：${result.success ? "成功" : "失败"} - ${result.message}`,
    ),
  );
  return [
    h(
      "tr",
      {},
      h(
        "td",
        { colspan: "4" },
        h(
          "details",
          { class: "disclosure" },
          h("summary", { text: `查看 ${event.results.length} 个应用的处理明细` }),
          h("ul", {}, items),
        ),
      ),
    ),
  ];
}
