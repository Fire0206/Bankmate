import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

const vite = await createServer({
  appType: "custom",
  cacheDir: "../../.data/vite-test-cache",
  configLoader: "runner",
  logLevel: "error",
  server: { middlewareMode: true },
});

try {
  const { TaskResult } = await vite.ssrLoadModule(
    "/src/components/TaskResult.tsx",
  );
  const steps = [
    {
      id: "read-old",
      sequence: 1,
      status: "succeeded",
      tool_name: "investment.products",
      result_data: {
        items: [{ name: "旧产品", risk_level: 1, suitable: true }],
      },
    },
    {
      id: "read-compare",
      sequence: 2,
      status: "succeeded",
      tool_name: "investment.compare",
      result_data: {
        items: [
          { name: "安稳现金管理", risk_level: 1 },
          { name: "稳健短债组合", risk_level: 2 },
        ],
      },
    },
    {
      id: "write-1",
      sequence: 3,
      status: "succeeded",
      tool_name: "transfer.create",
      result_data: { transfer: { payee_name: "小林", amount_minor: 1200 } },
    },
    {
      id: "write-2",
      sequence: 4,
      status: "succeeded",
      tool_name: "transfer.create",
      result_data: { transfer: { payee_name: "小周", amount_minor: 3400 } },
    },
    {
      id: "read-new",
      sequence: 5,
      status: "succeeded",
      tool_name: "investment.products",
      result_data: {
        items: [{ name: "新产品", risk_level: 1, suitable: true }],
      },
    },
  ];
  const task = { request_text: "比较两款理财产品，再分别转账", steps };
  const html = renderToStaticMarkup(createElement(TaskResult, { task }));
  const visible = html.split('<details class="full-result-details">')[0];
  assert.match(visible, /小林/);
  assert.match(visible, /小周/);
  assert.match(visible, /¥12\.00/);
  assert.match(visible, /¥34\.00/);
  assert.ok(visible.indexOf("理财产品比较") < visible.indexOf("理财产品</h4>"));
  assert.equal((visible.match(/<h4>理财产品<\/h4>/g) ?? []).length, 1);
  assert.doesNotMatch(visible, /旧产品/);
  assert.match(visible, /新产品/);
  process.stdout.write("TaskResult financial result checks passed.\n");
} finally {
  await vite.close();
}
