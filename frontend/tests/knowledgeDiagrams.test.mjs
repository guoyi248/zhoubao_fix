import assert from "node:assert/strict";
import test from "node:test";
import { knowledgeDiagramImage } from "../src/utils/knowledgeDiagrams.ts";

test("renders the compact dotted labels used in imported WeKnora diagrams locally", async () => {
  const image = await knowledgeDiagramImage("flowchart LR\n A[输入] --> B[解析]\n B -.可选.-> C[结果]");
  assert.ok(image?.startsWith("data:image/svg+xml;charset=utf-8,"));
  const svg = decodeURIComponent(image.slice(image.indexOf(",") + 1));
  assert.equal((svg.match(/class="node"/g) || []).length, 3);
  assert.equal((svg.match(/class="edge"/g) || []).length, 2);
  assert.match(svg, /data-label="可选"/);
  assert.doesNotMatch(svg, /@import|fonts\.googleapis/i);
});

test("keeps the source when the drawing is invalid, empty or exceeds the layout limit", async () => {
  for (const source of ["", "unknown diagram\n > A", "flowchart LR", "A".repeat(16_001)]) {
    assert.equal(await knowledgeDiagramImage(source), null);
  }
});
