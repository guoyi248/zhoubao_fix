const pending = new WeakSet<Element>();

export async function knowledgeDiagramImage(source: string): Promise<string | null> {
  // Large graphs can monopolize the layout engine. Their source remains readable.
  if (!source.trim() || source.length > 16_000 || source.split("\n").length > 200
      || (source.match(/--|==|-\./g)?.length ?? 0) > 250) return null;
  try {
    const { renderMermaidSVG } = await import("beautiful-mermaid");
    // Mermaid accepts A -.label.-> B, while the layout library requires spaces.
    const diagram = source.replace(
      /^(\s*[\w-]+\s+)-\.([^|.\n]*?\S)\.->(?=\s+[\w-]+)/gm,
      "$1-. $2 .->",
    );
    const svg = renderMermaidSVG(diagram, {
      font: "Arial", bg: "#f8fbf7", fg: "#25382c", line: "#62806b",
    }).replace(/^\s*@import url\('https:\/\/fonts\.googleapis\.com\/[^'\n]*'\);/gm, "");
    if (/^\s*(?:graph|flowchart)\b/i.test(diagram) && !svg.includes('class="node"')) return null;
    // SVG image mode isolates the drawing from the document and disables scripts
    // and external resources. Do not insert renderer output as HTML.
    return "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
  } catch {
    return null;
  }
}

export async function renderKnowledgeDiagrams(container: HTMLElement) {
  for (const code of container.querySelectorAll<HTMLElement>("pre > code.language-mermaid")) {
    const block = code.parentElement;
    if (!block || !container.contains(block) || pending.has(block) || block.closest(".knowledge-diagram")) continue;
    pending.add(block);
    try {
      const uri = await knowledgeDiagramImage(code.textContent || "");
      if (!uri || !container.contains(block)) continue;
      const doc = container.ownerDocument;
      const picture = doc.createElement("img");
      picture.alt = "Mermaid 图表，可展开查看源码";
      picture.src = uri;
      await picture.decode();
      if (!container.contains(block)) continue;

      const figure = doc.createElement("figure");
      figure.className = "knowledge-diagram";
      const details = doc.createElement("details");
      const summary = doc.createElement("summary");
      summary.textContent = "查看图表源码";
      block.replaceWith(figure);
      details.append(summary, block);
      figure.append(picture, details);
    } catch {
      // Leave the original fenced code visible when a browser cannot decode SVG.
    } finally {
      pending.delete(block);
    }
  }
}
