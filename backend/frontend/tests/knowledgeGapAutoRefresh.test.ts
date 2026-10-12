import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

// No component-rendering harness in this suite (see sessionExpiry.test.ts),
// so this verifies the wiring by source, the same way that file does.
const panelSource = readFileSync(
  new URL("../src/features/admin/KnowledgeGapPanel.tsx", import.meta.url),
  "utf8",
);

test("the list polls on an interval while monitoring a live pilot", () => {
  assert.match(panelSource, /AUTO_REFRESH_INTERVAL_MS\s*=\s*20_000/);
  assert.match(panelSource, /window\.setInterval\(\s*\(\)\s*=>\s*\{[\s\S]*?setRefreshKey/);
});

test("the poll is paused while the detail dialog is open, so it can't yank it away mid-review", () => {
  const pollingEffect = panelSource.slice(
    panelSource.indexOf("// While monitoring a pilot in progress"),
    panelSource.indexOf("function openGap"),
  );
  assert.match(pollingEffect, /if \(selected\) return;/);
  assert.match(pollingEffect, /\}, \[selected\]\);/);
});

test("a background poll never flips on the full-page loading/error state", () => {
  const fetchEffect = panelSource.slice(
    panelSource.indexOf("useEffect(() => {\n    let active = true;"),
    panelSource.indexOf("// While monitoring"),
  );
  assert.match(fetchEffect, /if \(!background\) \{ setLoading\(true\); setError\(null\); \}/);
  assert.match(fetchEffect, /active && !background/);
});
