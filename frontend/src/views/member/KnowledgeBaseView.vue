<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { ArrowRight, Collection, Document, EditPen, Expand, Folder, MoreFilled, Plus, Search } from "@element-plus/icons-vue";
import KnowledgeDirectory from "@/components/KnowledgeDirectory.vue";
import KnowledgeEditor from "@/components/KnowledgeEditor.vue";
import KnowledgeMarkdown from "@/components/KnowledgeMarkdown.vue";
import { useUserStore } from "@/stores/user";
import api from "@/utils/api";
import { indexKnowledge, knowledgeLocation, type Article, type Entry, type Topic } from "@/utils/knowledgeTree";

const route = useRoute();
const router = useRouter();
const user = useUserStore();
const topics = ref<Topic[]>([]);
const catalog = computed(() => indexKnowledge(topics.value));
const catalogLoading = ref(true);
const catalogError = ref("");
const selected = computed(() => catalog.value.byDocument.get(String(route.query.doc || "")));
const topic = computed(() => catalog.value.byId.get(selected.value?.module || String(route.query.module || "")));
const path = computed(() => topic.value ? catalog.value.path(topic.value.id) : []);
const root = computed(() => path.value[0]);
const children = computed(() => topic.value ? catalog.value.children(topic.value.id) : []);
const article = ref<Article>();
const articleError = ref("");
const missing = computed(() => (route.query.doc && !selected.value) || (route.query.module && !topic.value));
const directoryOpen = ref(false);
const editor = ref<InstanceType<typeof KnowledgeEditor>>();
const searchInput = ref<HTMLInputElement>();
const query = ref("");
const term = computed(() => query.value.trim());
const results = ref<(Entry & {excerpt: string})[]>([]);
const hasMore = ref(false);
const searching = ref(false);
const searchError = ref("");
const searchRevision = ref(0);
let catalogRequest = 0;

function errorMessage(e: any) {
  return e.response?.data?.message || e.response?.data?.detail || e.message || "请求失败，请重试。";
}
async function loadCatalog() {
  const request = ++catalogRequest;
  catalogLoading.value = true;
  catalogError.value = "";
  try {
    const { data } = await api.get<Topic[]>("/knowledge/");
    if (request === catalogRequest) topics.value = data;
  } catch (e) { if (request === catalogRequest) catalogError.value = errorMessage(e); }
  finally { if (request === catalogRequest) catalogLoading.value = false; }
}
watch(selected, async (entry, _, cleanup) => {
  const ctl = new AbortController();
  cleanup(() => ctl.abort());
  article.value = undefined;
  articleError.value = "";
  if (!entry) return;
  try {
    const { data } = await api.get<Article>("/knowledge/documents/" + entry.id, { signal: ctl.signal });
    if (!ctl.signal.aborted) article.value = data;
  } catch (e) { if (!ctl.signal.aborted) articleError.value = errorMessage(e); }
}, { immediate: true });

watch([term, searchRevision], ([q], _, cleanup) => {
  results.value = [];
  hasMore.value = false;
  searchError.value = "";
  searching.value = !!q;
  if (!q) return;
  const ctl = new AbortController();
  const timer = window.setTimeout(async () => {
    try {
      const { data } = await api.get("/knowledge/search", { params: { q }, signal: ctl.signal });
      if (!ctl.signal.aborted) {
        results.value = data.results;
        hasMore.value = data.has_more;
      }
    } catch (e) { if (!ctl.signal.aborted) searchError.value = errorMessage(e); }
    finally { if (!ctl.signal.aborted) searching.value = false; }
  }, 220);
  cleanup(() => { clearTimeout(timer); ctl.abort(); });
});
watch(() => [route.query.module, route.query.doc], async () => {
  directoryOpen.value = false;
  query.value = "";
  await nextTick();
  window.scrollTo(0, 0);
});
async function saved(moduleId: string, docId?: string) {
  await loadCatalog();
  await router.replace(knowledgeLocation(moduleId, docId));
}
function folderAction(command: string) {
  const current = topic.value;
  if (!current) return;
  if (command === "folder") editor.value?.edit("folder", current.id);
  if (command === "document") editor.value?.edit("document", current.id);
  if (command === "edit") editor.value?.edit(current.parent ? "folder" : "space", current.parent || "", current);
  if (command === "remove") removeItem(false);
}
async function removeItem(isDoc: boolean) {
  const current = topic.value;
  const item = isDoc ? article.value : current;
  if (!current || !item) return;
  const label = isDoc ? "文档" : current.parent ? "目录" : "空间";
  const itemName = "title" in item ? item.title : item.name;
  try { await ElMessageBox.confirm("删除「" + itemName + "」？", "删除" + label,
    { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" }); }
  catch { return; }
  try {
    await api.delete((isDoc ? "/knowledge/documents/" : "/knowledge/modules/") + item.id, { data: { version: item.version } });
    const returnTo = isDoc ? current.id : current.parent;
    await loadCatalog();
    await router.replace(returnTo ? knowledgeLocation(returnTo) : { path: "/knowledge" });
    ElMessage.success(label + "已删除");
  } catch (e) { ElMessage.error(errorMessage(e)); await loadCatalog(); }
}
function updated(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", year: "numeric", month: "long", day: "numeric" }).format(new Date(value));
}
onMounted(loadCatalog);
</script>

<template>
  <div class="kb">
    <header class="page-heading kb-heading">
      <h1 class="page-title">组内知识库</h1>
      <div class="kb-tools">
        <label class="searchbox"><el-icon><Search /></el-icon>
          <input ref="searchInput" v-model="query" type="search" placeholder="搜索全部文档" aria-label="搜索全部文档" maxlength="160" @keydown.esc="query = ''" />
        </label>
        <el-button v-if="user.isAdmin && !topic && !term && !missing && !catalogLoading && !catalogError" :icon="Plus" @click="editor?.edit('space')">新建空间</el-button>
      </div>
    </header>
    <p v-if="catalogError" class="panel" role="alert">{{ catalogError }} <button type="button" class="link-button" @click="loadCatalog">重新载入</button></p>
    <p v-else-if="catalogLoading && !topics.length" class="panel empty-copy" role="status">正在读取知识目录…</p>
    <section v-else-if="term" class="panel search-results" aria-label="搜索结果">
      <header class="panel-head"><h2>搜索结果</h2><button type="button" class="link-button" @click="query = ''; searchInput?.focus()">清除搜索</button></header>
      <p v-if="searching" class="empty-copy" role="status">正在搜索…</p>
      <p v-else-if="searchError" class="empty-copy" role="alert">{{ searchError }} <button type="button" class="link-button" @click="searchRevision++">重试</button></p>
      <p v-else-if="!results.length" class="empty-copy">没有找到与“{{ term }}”匹配的文档。</p>
      <router-link v-for="item in results" :key="item.id" :to="knowledgeLocation(item.module, item.id)" class="result-link" @click="query = ''">
        <el-icon><Document /></el-icon><div><strong>{{ item.title }}</strong>
          <p class="location">{{ catalog.path(item.module).map(t => t.name).join(" / ") }}</p>
          <p v-if="item.excerpt" class="excerpt">{{ item.excerpt }}</p></div>
      </router-link>
      <p v-if="hasMore" class="muted">已显示前 50 篇，输入更具体的关键词可缩小范围。</p>
    </section>
    <p v-else-if="missing" class="panel empty-copy" role="status">找不到这个位置，内容可能已经移动或删除。<router-link to="/knowledge">返回全部空间</router-link></p>
    <section v-else-if="!topic || !root" aria-label="知识空间" class="space-home">
      <div v-if="catalog.roots.length" v-auto-animate class="space-grid">
        <router-link v-for="space in catalog.roots" :key="space.id" :to="knowledgeLocation(space.id)" class="glass-panel space-card">
          <span class="space-icon"><el-icon><Collection /></el-icon></span>
          <div><h2>{{ space.name }}</h2><p>{{ catalog.spaceSizes.get(space.id)?.folders }} 个目录 · {{ catalog.spaceSizes.get(space.id)?.documents }} 篇文档</p></div>
          <el-icon class="card-arrow"><ArrowRight /></el-icon>
        </router-link>
      </div>
      <p v-else class="panel empty-copy">暂无知识空间。</p>
    </section>
    <div v-else class="glass-panel library">
      <button type="button" class="directory-toggle" aria-controls="knowledge-directory" :aria-expanded="directoryOpen" @click="directoryOpen = !directoryOpen">
        <el-icon><Expand /></el-icon>{{ directoryOpen ? "收起空间目录" : "浏览空间目录" }}
      </button>
      <KnowledgeDirectory id="knowledge-directory" :class="{ opened: directoryOpen }"
        :catalog="catalog" :root="root" :topic-id="topic.id" :doc-id="selected?.id" @navigate="directoryOpen = false" />
      <section class="reading-pane" :aria-label="selected ? '文档阅读' : '目录内容'">
        <nav aria-label="当前位置" class="crumbs">
          <router-link to="/knowledge" aria-current-value="false">全部空间</router-link>
          <template v-for="(item, index) in path" :key="item.id"><el-icon><ArrowRight /></el-icon>
            <router-link :to="knowledgeLocation(item.id)" :aria-current="!selected && index === path.length-1 ? 'page' : undefined">{{ item.name }}</router-link>
          </template>
          <span v-if="selected" class="reader-only" aria-current="page">{{ selected.title }}</span>
        </nav>
        <article v-if="article" :key="article.id" class="article">
          <header class="content-head"><div><h2>{{ article.title }}</h2><time :datetime="article.updated_at">更新于 {{ updated(article.updated_at) }}</time></div>
            <div v-if="user.isAdmin" class="content-actions">
              <button class="link-button" type="button" @click="editor?.edit('document', article.module, article)"><el-icon><EditPen /></el-icon>编辑</button>
              <el-dropdown trigger="click" @command="removeItem(true)">
                <button class="icon-button" type="button" aria-label="更多文档操作"><el-icon><MoreFilled /></el-icon></button>
                <template #dropdown><el-dropdown-menu><el-dropdown-item>删除文档</el-dropdown-item></el-dropdown-menu></template>
              </el-dropdown>
            </div>
          </header>
          <KnowledgeMarkdown v-if="article.markdown.trim()" :source="article.markdown" :title="article.title" />
          <p v-else class="muted">这篇文档还没有正文。</p>
        </article>
        <p v-else-if="articleError" role="alert" class="empty-copy">{{ articleError }} <button class="link-button" @click="loadCatalog">重新载入</button></p>
        <p v-else-if="selected" role="status" class="empty-copy">正在打开文档…</p>
        <div v-else class="folder-overview">
          <header class="content-head"><div><h2>{{ topic.name }}</h2>
            <p>{{ children.filter(c => c.isFolder).length }} 个子目录 · {{ topic.documents.length }} 篇文档</p></div>
            <div v-if="user.isAdmin" class="content-actions">
              <el-dropdown trigger="click" @command="folderAction">
                <el-button :icon="Plus" type="primary" size="small">新建</el-button>
                <template #dropdown><el-dropdown-menu><el-dropdown-item command="folder">新建子目录</el-dropdown-item>
                  <el-dropdown-item command="document">新建文档</el-dropdown-item></el-dropdown-menu></template>
              </el-dropdown>
              <el-dropdown trigger="click" @command="folderAction">
                <button type="button" class="icon-button" aria-label="管理当前位置"><el-icon><MoreFilled /></el-icon></button>
                <template #dropdown><el-dropdown-menu><el-dropdown-item command="edit">编辑{{ topic.parent ? "目录" : "空间" }}</el-dropdown-item>
                  <el-dropdown-item command="remove" :disabled="children.length > 0">删除空{{ topic.parent ? "目录" : "空间" }}</el-dropdown-item></el-dropdown-menu></template>
              </el-dropdown>
            </div>
          </header>
          <router-link v-for="item in children" :key="item.id" class="child-link" :to="knowledgeLocation(item.module, item.isFolder ? undefined : item.id)">
            <el-icon :class="{ 'folder-ink': item.isFolder }"><component :is="item.isFolder ? Folder : Document" /></el-icon><span>{{ item.title }}</span>
            <small v-if="item.isFolder">{{ catalog.children(item.id).length }} 项内容</small>
            <small v-else-if="catalog.byDocument.has(item.id)">{{ updated(catalog.byDocument.get(item.id)!.updated_at) }}</small>
            <el-icon class="card-arrow"><ArrowRight /></el-icon>
          </router-link>
          <p v-if="!children.length" class="empty-copy">此位置还没有目录或文档。</p>
        </div>
      </section>
    </div>
    <KnowledgeEditor v-if="user.isAdmin" ref="editor" :catalog="catalog" @saved="saved" />
  </div>
</template>

<style scoped>
.kb { max-width:1370px; min-width:0; }
.kb-heading { margin-bottom:24px; }
.searchbox { display:flex; align-items:center; gap:9px; width:min(255px,100%); padding:8px 11px; border:1px solid var(--line); background:var(--glass-field); border-radius:8px; color:var(--muted); }
.searchbox:focus-within { border-color:var(--teal); outline:2px solid var(--soft); }
.searchbox input { flex:1; min-width:0; border:0; outline:0; background:none; color:var(--ink); font-size:14px; line-height:1.4; }
.kb-tools { display:flex; align-items:center; gap:9px; min-width:0; }
.reader-only { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip-path:inset(50%); white-space:nowrap; }
.space-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(min(100%,290px),1fr)); gap:13px; }
.space-card { display:flex; align-items:center; gap:15px; min-width:0; border:1px solid var(--glass-edge); border-radius:12px; color:var(--ink); text-decoration:none; padding:22px 18px; }
.space-card:hover { border-color:#83a78b; }
.space-icon { flex:none; display:grid; place-items:center; width:42px; height:48px; color:#40724f; background:#e6f0e2; border-radius:8px; font-size:23px; }
.space-card h2 { font-size:17px; line-height:1.45; overflow-wrap:anywhere; }
.space-card p, .content-head p, .content-head time { display:block; color:var(--muted); font-size:12px; margin-top:5px; }
.card-arrow { margin-left:auto; flex:none; font-size:12px; color:#718575; }
.library { display:grid; grid-template-columns:clamp(200px,22%,278px) minmax(0,1fr); border:1px solid var(--glass-edge); border-radius:12px; overflow:clip; min-height:min(63vh,540px); }
.directory-toggle { display:none; }
.reading-pane { min-width:0; padding:clamp(18px,2.8vw,42px); }
.crumbs { display:flex; flex-wrap:wrap; gap:5px 7px; align-items:center; margin-bottom:22px; color:var(--muted); font-size:12px; line-height:1.6; }
.crumbs a { text-decoration:none; color:#2c4437; }
.crumbs a:hover { text-decoration:underline; }
.crumbs .el-icon { font-size:9px; }
.crumbs span, .crumbs a { overflow-wrap:anywhere; }
.crumbs [aria-current=page] { color:var(--ink); }
.content-head { display:flex; flex-wrap:wrap; align-items:flex-start; justify-content:space-between; gap:8px; padding-bottom:18px; margin-bottom:18px; border-bottom:1px solid var(--line); }
.content-head h2 { font-size:clamp(21px,2vw,30px); line-height:1.45; overflow-wrap:anywhere; }
.content-actions { display:flex; flex:none; align-items:center; gap:9px; }
.child-link { display:flex; align-items:center; gap:12px; padding:12px 6px; border-bottom:1px solid #e9eee7; color:var(--ink); text-decoration:none; font-size:14px; overflow-wrap:anywhere; }
.child-link:hover, .result-link:hover { background:var(--glass-inset); }
.child-link > .el-icon:first-child { font-size:18px; color:#607467; flex:none; }
.child-link > .el-icon.folder-ink { color:#478057; }
.child-link small { margin-left:auto; flex:none; color:var(--muted); font-size:12px; }
.child-link .card-arrow { margin-left:0; }
.result-link { display:flex; gap:10px; padding:14px 8px; border-top:1px solid var(--line); color:var(--ink); text-decoration:none; overflow-wrap:anywhere; }
.result-link > .el-icon { flex:none; margin-top:3px; color:var(--teal); }
.result-link strong { font-size:15px; }
.location, .excerpt { font-size:12px; color:var(--muted); line-height:1.55; margin-top:4px; }
.excerpt { color:#455a4c; font-size:13px; white-space:normal; }
@media(max-width:780px) {
  .library { grid-template-columns:1fr; grid-template-rows:auto auto 1fr; align-content:start; min-height:370px; }
  #knowledge-directory { display:none; }
  #knowledge-directory.opened { display:block; padding-top:11px; }
  .directory-toggle { display:flex; gap:8px; align-items:center; padding:12px 15px; border:0; border-bottom:1px solid var(--line); color:var(--teal); background:var(--glass-inset); font-size:14px; text-align:left; }
  .reading-pane { grid-row:3; padding:18px 15px; }
  .crumbs { margin-bottom:16px; }
}
@media(max-width:540px) {
  .kb-heading { align-items:stretch; flex-direction:column; gap:13px; margin-bottom:17px; }
  .searchbox { width:100%; }
  .space-card { padding:16px 14px; }
}
</style>
