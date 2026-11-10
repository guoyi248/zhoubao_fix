import MarkdownIt from "markdown-it";

// Render authored Markdown, never embedded HTML. Restrict URLs after the parser's
// own normalization, including its entity and percent-encoding handling.
const parser = new MarkdownIt({ html: false, linkify: false, typographer: false });
const defaultValidate = parser.validateLink.bind(parser);
parser.validateLink = (url: string) => {
  if (!defaultValidate(url)) return false;
  try {
    const target = new URL(url, "https://knowledge.invalid/");
    return ["http:", "https:", "mailto:"].includes(target.protocol);
  } catch {
    return false;
  }
};
const originalImage = parser.renderer.rules.image!;
parser.renderer.rules.image = (tokens, index, options, env, self) => {
  tokens[index].attrSet("loading", "lazy");
  tokens[index].attrSet("referrerpolicy", "no-referrer");
  return originalImage(tokens, index, options, env, self);
};

// Match the human-readable heading fragments in Apifox exports. Prefix DOM ids
// so authored headings cannot shadow application globals or editor controls.
export const headingPrefix = "kb-heading-";
const previewPrefix = "kb-preview-";
parser.core.ruler.after("inline", "knowledge_headings", state => {
  const prefix = state.env.preview ? previewPrefix : headingPrefix;
  const ids = new Set<string>();
  for (let i = 0; i < state.tokens.length; i++) {
    const token = state.tokens[i]!;
    if (token.type !== "heading_open") continue;
    const inline = state.tokens[i + 1]!;
    const title = (inline.children || []).map(t => t.content).join("").trim();
    const stem = title.toLowerCase().replace(/[^\p{L}\p{M}\p{N}\s_-]/gu, "").trim().replace(/\s+/g, "-") || "section";
    let slug = stem;
    for (let n = 1; ids.has(slug); n++) slug = stem + "-" + n;
    ids.add(slug);
    token.attrSet("id", prefix + slug);
    if (i === 0 && token.tag === "h1" && state.env.title === title) {
      token.type = "html_block";
      token.content = '<span aria-hidden="true" id="' + parser.utils.escapeHtml(prefix + slug) + '"></span>';
      state.tokens.splice(i + 1, 2);
    }
  }
  for (const token of state.tokens) {
    for (const child of token.children || []) {
      const href = child.attrGet("href");
      if (child.type !== "link_open" || !href?.startsWith("#")) continue;
      child.attrSet("href", "#" + prefix + href.slice(1));
    }
  }
});

export function renderKnowledgeMarkdown(source: string, title = "", preview = false) {
  return parser.render(source, { title, preview });
}
