export interface Entry {
  id: string;
  title: string;
  module: string;
  position?: number;
  version: number;
  updated_at: string;
}

export interface Article extends Entry { markdown: string }
export interface Topic {
  id: string;
  name: string;
  parent: string | null;
  position?: number;
  version: number;
  documents: Entry[];
}

export function knowledgeLocation(moduleId: string, docId?: string) {
  return { path: "/knowledge", query: { module: moduleId, ...(docId && { doc: docId }) } };
}

export function indexKnowledge(topics: Topic[]) {
  const byId = new Map(topics.map(topic => [topic.id, topic]));
  const folders = new Map<string | null, Topic[]>();
  const byDocument = new Map<string, Entry>();
  for (const topic of topics) {
    const parent = topic.parent || null;
    if (!folders.has(parent)) folders.set(parent, []);
    folders.get(parent)!.push(topic);
    for (const doc of topic.documents) byDocument.set(doc.id, doc);
  }
  function path(id: string) {
    const result: Topic[] = [];
    let item = byId.get(id);
    while (item) {
      result.push(item);
      item = item.parent ? byId.get(item.parent) : undefined;
    }
    return result.reverse();
  }
  function children(id: string) {
    const subfolders = (folders.get(id) || []).map(topic => ({
      id: topic.id, title: topic.name, isFolder: true, module: topic.id, position: topic.position ?? 0,
    }));
    const docs = (byId.get(id)?.documents || []).map(doc => ({
      id: doc.id, title: doc.title, isFolder: false, module: id, position: doc.position ?? 0,
    }));
    return [...subfolders, ...docs].sort((a, b) => a.position - b.position);
  }
  const spaceSizes = new Map<string, { folders: number; documents: number }>();
  for (const topic of topics) {
    const rootId = path(topic.id)[0]!.id;
    const size = spaceSizes.get(rootId) || { folders: 0, documents: 0 };
    if (topic.parent) size.folders++;
    size.documents += topic.documents.length;
    spaceSizes.set(rootId, size);
  }
  return { byId, byDocument, roots: folders.get(null) || [], children, path, spaceSizes };
}

export type KnowledgeIndex = ReturnType<typeof indexKnowledge>;
