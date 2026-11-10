<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { ArrowRight, Collection, Document, Folder, FolderOpened, House } from "@element-plus/icons-vue";
import { knowledgeLocation, type KnowledgeIndex, type Topic } from "@/utils/knowledgeTree";

const props = defineProps<{ catalog: KnowledgeIndex; root: Topic; topicId: string; docId?: string }>();
const emit = defineEmits<{ navigate: [] }>();
const router = useRouter();
const expanded = ref(new Set<string>());
watch(() => [props.topicId, props.docId, props.catalog] as const, () => {
  for (const ancestor of props.catalog.path(props.topicId)) expanded.value.add(ancestor.id);
}, { immediate: true });

const rows = computed(() => {
  type Row = ReturnType<KnowledgeIndex["children"]>[number] & {depth: number};
  const visible: Row[] = [];
  function visit(id: string, depth: number) {
    for (const child of props.catalog.children(id)) {
      visible.push({ ...child, depth });
      if (child.isFolder && expanded.value.has(child.id)) visit(child.id, depth + 1);
    }
  }
  visit(props.root.id, 0);
  return visible;
});
function toggle(id: string) {
  if (expanded.value.has(id)) expanded.value.delete(id);
  else expanded.value.add(id);
}
function switchSpace(event: Event) {
  const id = (event.target as HTMLSelectElement).value;
  router.push(id ? knowledgeLocation(id) : { path: "/knowledge" });
}
</script>

<template>
  <aside class="directory">
    <label class="space-switch"><el-icon><Collection /></el-icon>
      <select :value="root.id" aria-label="切换知识空间" @change="switchSpace">
        <option value="">全部空间</option>
        <option v-for="item in catalog.roots" :key="item.id" :value="item.id">{{ item.name }}</option>
      </select></label>
    <nav aria-label="空间目录" class="tree-nav">
      <router-link :to="knowledgeLocation(root.id)" class="root-link" :aria-current="root.id === topicId && !docId ? 'page' : undefined" @click="emit('navigate')">
        <el-icon><House /></el-icon><span>空间首页</span>
      </router-link>
      <div v-for="row in rows" :key="row.id" class="tree-row"
        :class="{ current: row.isFolder ? topicId === row.id && !docId : docId === row.id }"
        :style="{ paddingInlineStart: Math.min(row.depth, 8) * 10 + 'px' }">
        <button v-if="row.isFolder" type="button" class="branch" :aria-expanded="expanded.has(row.id)"
          :aria-label="(expanded.has(row.id) ? '收起' : '展开') + row.title" @click="toggle(row.id)">
          <el-icon><ArrowRight /></el-icon></button>
        <router-link :to="knowledgeLocation(row.module, row.isFolder ? undefined : row.id)"
          :class="{ 'doc-link': !row.isFolder }" @click="emit('navigate')"
          :aria-current="(row.isFolder ? row.id === topicId && !docId : row.id === docId) ? 'page' : undefined" :title="row.title">
          <el-icon><component :is="row.isFolder ? (expanded.has(row.id) ? FolderOpened : Folder) : Document" /></el-icon>
          <span>{{ row.title }}</span>
        </router-link>
      </div>
      <p v-if="!rows.length" class="tree-empty">空间目录为空</p>
    </nav>
  </aside>
</template>

<style scoped>
.directory { min-width:0; background:var(--glass-inset); border-right:1px solid var(--line); }
.space-switch { display:flex; align-items:center; gap:9px; margin:17px 13px 12px; padding:8px 9px; background:var(--glass-field); border:1px solid var(--line); border-radius:6px; color:var(--teal); }
.space-switch select { width:100%; min-width:0; color:var(--ink); font-size:14px; font-weight:630; border:0; background:transparent; cursor:pointer; }
.tree-nav { position:sticky; top:8px; max-height:calc(100dvh - 24px); overflow:auto; scrollbar-width:thin; padding:0 7px 16px; }
.tree-row, .root-link { display:flex; align-items:stretch; border-radius:5px; margin:1px 0; }
.tree-row:hover, .root-link:hover { background:rgb(198 221 195 / 40%); }
.root-link, .tree-row a { display:flex; align-items:flex-start; gap:7px; min-width:0; text-decoration:none; color:#405549; font-size:13px; line-height:1.5; }
.root-link { padding:8px 10px; margin-bottom:5px; }
.tree-row a { flex:1; padding:6px 5px 6px 0; }
.tree-row a.doc-link { padding-left:20px; }
.tree-row a span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.tree-row .el-icon, .root-link .el-icon { flex:none; margin-top:2px; font-size:15px; }
.tree-row.current, .root-link[aria-current] { background:rgb(193 218 191 / 61%); }
.tree-row.current a, .root-link[aria-current] { color:#235f38; font-weight:650; }
.branch { flex:0 0 20px; display:grid; place-items:center; padding:0; border:0; background:transparent; color:#617365; }
.branch .el-icon { font-size:10px; margin:0; }
.branch[aria-expanded=true] .el-icon { transform:rotate(90deg); }
.tree-empty { padding:9px 12px; color:var(--muted); font-size:13px; }
@media(max-width:780px) {
  .directory { border:0; border-bottom:1px solid var(--line); }
  .tree-nav { position:static; max-height:48dvh; }
  .space-switch { margin-top:0; }
  .tree-row a { padding-block:9px; }
  .branch { flex-basis:32px; }
  .tree-row a.doc-link { padding-left:32px; }
}
</style>
