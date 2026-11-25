<script setup lang="ts">
import { computed, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import api from "@/utils/api";
import KnowledgeMarkdown from "./KnowledgeMarkdown.vue";
import type { Article, KnowledgeIndex } from "@/utils/knowledgeTree";
const props = defineProps<{
    catalog: KnowledgeIndex;
}>();
const emit = defineEmits<{
    restored: [
        moduleId: string,
        docId: string
    ];
}>();
interface Revision {
    id: string;
    version: number;
    title: string;
    created_at: string;
    editor: string;
}
interface Deleted {
    id: string;
    title: string;
    module: string | null;
    version: number;
    deleted_at: string;
    deleted_from: string;
}
const open = ref(false);
const mode = ref<"history" | "trash">("history");
const document = ref<Article>();
const revisions = ref<Revision[]>([]);
const trash = ref<Deleted[]>([]);
const targets = ref<Record<string, string>>({});
const chosen = ref<string>("");
const preview = ref<{
    title: string;
    markdown: string;
    version: number;
}>();
const loading = ref(false);
const saving = ref(false);
const error = ref("");
let request = 0;
const folders = computed(() => Array.from(props.catalog.byId.values()).map(folder => ({ id: folder.id, name: props.catalog.path(folder.id).map(node => node.name).join(" / ") })));
const stamp = (value: string) => new Date(value).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false });
const message = (e: any) => e.response?.data?.message || e.message || "操作失败，请重试";
async function selectRevision(id: string) {
    const current = ++request;
    chosen.value = id;
    preview.value = undefined;
    error.value = "";
    try {
        const { data } = await api.get(`/knowledge/documents/${document.value!.id}/history/${id}`);
        if (current === request && open.value)
            preview.value = data;
    }
    catch (e) {
        if (current === request)
            error.value = message(e);
    }
}
async function showHistory(doc: Article) {
    request++;
    mode.value = "history";
    document.value = doc;
    open.value = true;
    loading.value = true;
    error.value = "";
    revisions.value = [];
    preview.value = undefined;
    const current = request;
    try {
        revisions.value = (await api.get<Revision[]>(`/knowledge/documents/${doc.id}/history`)).data;
        if (current !== request || !open.value)
            return;
        if (revisions.value[0])
            await selectRevision(revisions.value[0].id);
    }
    catch (e) {
        error.value = message(e);
    }
    finally {
        loading.value = false;
    }
}
async function showTrash() {
    request++;
    mode.value = "trash";
    open.value = true;
    loading.value = true;
    error.value = "";
    try {
        trash.value = (await api.get<Deleted[]>("/knowledge/trash")).data;
        targets.value = Object.fromEntries(trash.value.map(doc => [doc.id, doc.module && props.catalog.byId.has(doc.module) ? doc.module : ""]));
    }
    catch (e) {
        error.value = message(e);
    }
    finally {
        loading.value = false;
    }
}
async function restoreRevision() {
    if (!document.value || !preview.value || saving.value)
        return;
    try {
        await ElMessageBox.confirm(`恢复到第 ${preview.value.version} 版？当前正文会保留在历史版本中。`, "恢复历史版本", { confirmButtonText: "恢复", cancelButtonText: "取消" });
    }
    catch {
        return;
    }
    saving.value = true;
    error.value = "";
    try {
        const { data } = await api.post(`/knowledge/documents/${document.value.id}/history/${chosen.value}`, { version: document.value.version });
        open.value = false;
        emit("restored", data.module, data.id);
        ElMessage.success("已恢复为新版本");
    }
    catch (e) {
        error.value = message(e);
    }
    finally {
        saving.value = false;
    }
}
async function restoreDeleted(doc: Deleted) {
    if (!targets.value[doc.id] || saving.value)
        return;
    saving.value = true;
    error.value = "";
    try {
        const { data } = await api.post(`/knowledge/trash/${doc.id}/restore`, { version: doc.version, module: targets.value[doc.id] });
        open.value = false;
        emit("restored", data.module, data.id);
        ElMessage.success("文档已恢复");
    }
    catch (e) {
        error.value = message(e);
    }
    finally {
        saving.value = false;
    }
}
defineExpose({ showHistory, showTrash });
</script>

<template>
  <el-dialog v-model="open" :title="mode==='history'?'历史版本':'回收站'" width="min(960px,96vw)" :close-on-click-modal="false" :show-close="!saving" :close-on-press-escape="!saving" @closed="request++">
    <div v-loading="loading" class="history-content">
      <el-alert v-if="error" type="error" :title="error" :closable="false" />
      <template v-if="mode==='history'">
        <div v-if="revisions.length" class="revision-layout">
          <nav aria-label="版本列表"><button v-for="revision in revisions" :key="revision.id" :class="{chosen:chosen===revision.id}" @click="selectRevision(revision.id)"><strong>第 {{ revision.version }} 版</strong><small>{{ stamp(revision.created_at) }}</small><small>{{ revision.editor }}</small></button></nav>
          <div class="revision-preview"><KnowledgeMarkdown v-if="preview" :source="preview.markdown" :title="preview.title" preview /><p v-else class="muted">正在读取版本…</p></div>
        </div>
        <p v-else-if="!loading" class="muted">暂无历史版本。</p>
      </template>
      <template v-else>
        <div v-for="doc in trash" :key="doc.id" class="trash-row"><div><strong>{{ doc.title }}</strong><small>{{ doc.deleted_from }} · {{ stamp(doc.deleted_at) }}</small></div><label>恢复到<select v-model="targets[doc.id]" :aria-label="doc.title+'的恢复位置'"><option value="" disabled>选择目录</option><option v-for="folder in folders" :key="folder.id" :value="folder.id">{{ folder.name }}</option></select></label><el-button :loading="saving" :disabled="!targets[doc.id]" @click="restoreDeleted(doc)">恢复文档</el-button></div>
        <p v-if="!loading&&!trash.length" class="empty-copy">回收站为空。</p>
      </template>
    </div>
    <template #footer><el-button :disabled="saving" @click="open=false">关闭</el-button><el-button v-if="mode==='history'" type="primary" :loading="saving" :disabled="!preview||preview.version===document?.version" @click="restoreRevision">恢复此版本</el-button></template>
  </el-dialog>
</template>

<style scoped>
.history-content{min-height:150px}.revision-layout{display:grid;grid-template-columns:170px minmax(0,1fr);gap:22px;margin-top:12px}.revision-layout nav{max-height:60vh;overflow:auto}.revision-layout nav button{display:grid;gap:4px;width:100%;text-align:left;border:0;border-radius:8px;background:transparent;padding:12px;color:var(--ink);cursor:pointer}.revision-layout nav button.chosen{background:var(--soft);color:var(--teal)}small{display:block;color:var(--muted);font-size:12px;line-height:1.5}.revision-preview{max-height:60vh;overflow:auto;border-left:1px solid var(--line);padding-left:20px;min-width:0}.trash-row{display:flex;align-items:center;gap:14px;padding:14px 0;border-bottom:1px solid var(--line)}.trash-row>div{flex:1;min-width:0;overflow-wrap:anywhere}.trash-row label{display:grid;gap:4px;font-size:12px;color:var(--muted)}.trash-row select{max-width:240px;background:var(--glass-field);border:1px solid var(--line);border-radius:6px;padding:7px;color:var(--ink)}@media(max-width:650px){.revision-layout{grid-template-columns:1fr}.revision-layout nav{display:flex;max-height:110px}.revision-layout nav button{min-width:150px}.revision-preview{border:0;padding:0}.trash-row{flex-wrap:wrap}.trash-row>div{flex-basis:100%}}
</style>
