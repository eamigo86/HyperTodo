import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import {pathToFileURL} from "node:url";

const editorPath = process.env.HXML_EDITOR_JS;
if (!editorPath) {
  throw new Error("HXML_EDITOR_JS is required");
}
const {default: editorApi} = await import(pathToFileURL(editorPath));

test("a real HyperTodo template formats idempotently without losing semantics", async () => {
  const templatePath = path.resolve("hyperview/screens/about.xml");
  const realTemplate = await readFile(templatePath, "utf8");
  const content = await readFile(path.resolve("hyperview/partials/about_content.xml"), "utf8");
  for (const part of [realTemplate, content]) {
    const formatted = editorApi.formatHxml(part);
    assert.equal(formatted.ok, true);
    assert.deepEqual(editorApi.formatHxml(formatted.value), formatted);
  }
  // Also check the actual include's content in both balanced branches. Keep the
  // existing text/translation/whitespace oracles across the template graph.
  const source = realTemplate.replaceAll(
    '{% include "partials/about_content.xml" %}', content,
  ).replace(
    "</body>",
    '<text preformatted="true">  significant  spaces  </text></body>',
  );

  const first = editorApi.formatHxml(source);
  const second = editorApi.formatHxml(first.value);

  assert.equal(first.ok, true);
  assert.deepEqual(second, first);
  assert.match(first.value, /<text preformatted="true">  significant  spaces  <\/text>/);
  assert.match(first.value, /{% load i18n %}/);
  assert.match(first.value, /{{ app_version }}/);
  assert.match(first.value, /{% translate "A calm, server-driven place to organize tasks, categories, and the work that matters\." %}/);
});
