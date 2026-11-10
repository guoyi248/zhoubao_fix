import assert from "node:assert/strict";
import test from "node:test";
import { renderKnowledgeMarkdown } from "../src/utils/knowledgeMarkdown.ts";

test("renders Markdown syntax while escaping raw HTML and rejecting active URL schemes", () => {
  const source = [
    "## 记录", "", "| 参数 | 值 |", "| --- | --- |", "| **样本** | 3 |", "",
    "- 项目", "", "`a < b`", "", "<img src=x onerror=alert(1)>", "",
    "[链接](javascript&#58;alert(1))", "", "![图](data:image/svg+xml;base64,AAA)", "",
    "[文档](https://example.org/guide)", "", "[运行](file:///tmp/test)",
  ].join("\n");
  const output = renderKnowledgeMarkdown(source);
  for (const element of ["h2", "table", "strong", "ul", "code"]) assert.match(output, new RegExp("<"+element+"(?: |>)"));
  assert.match(output, /&lt;img/);
  assert.match(output, /href="https:\/\/example.org\/guide"/);
  assert.doesNotMatch(output, /<img|(?:src|href)="(?:javascript|file|data):/i);
});

test("links Apifox Chinese anchors to unique page-scoped headings", () => {
  const source = [
    "# Java 学习笔记", "[跳转](#2-字面量进制与数据类型)", "# 2. 字面量、进制与数据类型",
    "# 再来", "# 再来", "# 再来-1", "# location",
  ].join("\n\n");
  const html = decodeURIComponent(renderKnowledgeMarkdown(source, "Java 学习笔记"));
  assert.match(html, /href="#kb-heading-2-字面量进制与数据类型"/);
  for (const id of ["2-字面量进制与数据类型", "再来", "再来-1", "再来-1-1", "location"]) {
    assert.match(html, new RegExp('id="kb-heading-' + id + '"'));
  }
  assert.doesNotMatch(html, /<h1[^>]*>Java 学习笔记/);
  assert.match(renderKnowledgeMarkdown(source, "", true), /id="kb-preview-location"/);
});
