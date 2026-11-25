<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { onBeforeRouteLeave, onBeforeRouteUpdate } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import KnowledgeMarkdown from "@/components/KnowledgeMarkdown.vue";
import type { Article, KnowledgeIndex, Topic } from "@/utils/knowledgeTree";
import api from "@/utils/api";
import { useUserStore } from "@/stores/user";
const props = defineProps<{
    catalog: KnowledgeIndex;
}>();
const emit = defineEmits<{
    saved: [
        moduleId: string,
        docId?: string
    ];
}>();
type Mode = "space" | "folder" | "document";
const mode = ref<Mode>("document");
const open = ref(false);
const saving = ref(false);
const preview = ref(false);
const name = ref("");
const markdown = ref("");
const originallyEmpty = ref(false);
const parent = ref("");
const id = ref("");
const version = ref(0);
const error = ref("");
const conflicted = ref(false);
const fileInput = ref<HTMLInputElement>();
const snapshot = ref("");
const imageInput = ref<HTMLInputElement>();
const textarea = ref<HTMLTextAreaElement>();
const uploadingImage = ref(false);
const draftSaved = ref(false);
const recoverable = ref<{
    name: string;
    markdown: string;
    parent: string;
}>();
const user = useUserStore();
const draftKey = () => `weekly.knowledge.draft.${user.user?.id}.${id.value || 'new-' + parent.value}`;
function persistDraft() {
    if (!open.value || mode.value !== "document" || uploadingImage.value || snapshot.value === signature())
        return;
    try {
        localStorage.setItem(draftKey(), JSON.stringify({ name: name.value, markdown: markdown.value, parent: parent.value }));
        draftSaved.value = true;
    }
    catch {
        draftSaved.value = false;
    }
}
let draftTimer: ReturnType<typeof setTimeout> | undefined;
watch([name, markdown, parent], () => {
    draftSaved.value = false;
    clearTimeout(draftTimer);
    draftTimer = setTimeout(persistDraft, 450);
});
window.addEventListener("beforeunload", persistDraft);
onBeforeUnmount(() => {
    persistDraft();
    clearTimeout(draftTimer);
    window.removeEventListener("beforeunload", persistDraft);
});
function recoverDraft() {
    if (!recoverable.value)
        return;
    name.value = recoverable.value.name;
    markdown.value = recoverable.value.markdown;
    parent.value = recoverable.value.parent;
    recoverable.value = undefined;
}
function clearDraft() {
    try {
        localStorage.removeItem(draftKey());
    }
    catch { /* 本机存储可能不可用。 */
    }
    recoverable.value = undefined;
    draftSaved.value = false;
}
let importRequest = 0;
const signature = () => JSON.stringify([name.value, parent.value, markdown.value]);
const itemLabel = computed(() => ({ space: "空间", folder: "目录", document: "文档" })[mode.value]);
const preserveEmpty = computed(() => !!id.value && originallyEmpty.value && markdown.value === "");
const locations = computed(() => Array.from(props.catalog.byId.values()).map(item => {
    const path = props.catalog.path(item.id);
    return { id: item.id, title: path.map(t => t.name).join(" / "), path };
}).filter(item => mode.value === "document" || !item.path.some(item => item.id === id.value))
    .sort((a, b) => a.title.localeCompare(b.title, "zh-CN")));
function edit(type: Mode, parentId = "", item?: Topic | Article) {
    mode.value = type;
    name.value = item ? ("title" in item ? item.title : item.name) : "";
    markdown.value = item && "markdown" in item ? item.markdown : "";
    originallyEmpty.value = !!item && "markdown" in item && item.markdown === "";
    parent.value = parentId;
    id.value = item?.id || "";
    version.value = item?.version || 0;
    snapshot.value = signature();
    error.value = "";
    conflicted.value = preview.value = false;
    open.value = true;
    draftSaved.value = false;
    recoverable.value = undefined;
    try {
        const saved = JSON.parse(localStorage.getItem(draftKey()) || "null");
        if (saved && typeof saved.name === "string" && typeof saved.markdown === "string" && typeof saved.parent === "string" && JSON.stringify([saved.name, saved.parent, saved.markdown]) !== signature())
            recoverable.value = saved;
    }
    catch { /* 忽略无法读取的本机草稿。 */
    }
    importRequest++;
}
defineExpose({ edit });
async function discard() {
    if (saving.value || uploadingImage.value)
        return false;
    if (!open.value || snapshot.value === signature())
        return true;
    try {
        await ElMessageBox.confirm("放弃本次修改？", "尚未保存", {
            confirmButtonText: "放弃修改", cancelButtonText: "继续编辑",
        });
        clearDraft();
        return true;
    }
    catch {
        return false;
    }
}
async function close() {
    if (!await discard())
        return false;
    importRequest++;
    open.value = false;
    return true;
}
onBeforeRouteLeave(() => open.value ? close() : true);
onBeforeRouteUpdate(() => open.value ? close() : true);
async function importFile(event: Event) {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = "";
    if (!file)
        return;
    const request = ++importRequest;
    error.value = "";
    if (!/\.(md|markdown)$/i.test(file.name)) {
        error.value = "请选择 .md 或 .markdown 文档。";
        return;
    }
    if (file.size > 1000000) {
        error.value = "文件超过 1 MB，请拆分为多篇文档。";
        return;
    }
    try {
        const source = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer());
        if (!open.value || request !== importRequest)
            return;
        if (!source.trim() || source.includes("\0") || source.length > 250000) {
            error.value = "文件需要包含正文，且每篇不超过 25 万字符。";
            return;
        }
        markdown.value = source;
        if (!name.value.trim())
            name.value = file.name.replace(/\.(md|markdown)$/i, "").slice(0, 160);
        preview.value = true;
    }
    catch {
        if (request === importRequest)
            error.value = "无法读取文件，请用 UTF-8 编码保存后重试。";
    }
}
async function insertImage(file?: File) {
    if (!file || uploadingImage.value)
        return;
    if (!file.type.startsWith("image/")) {
        error.value = "请选择图片文件";
        return;
    }
    uploadingImage.value = true;
    error.value = "";
    preview.value = false;
    const marker = `![图片](upload-${Date.now()})`;
    const start = textarea.value?.selectionStart ?? markdown.value.length;
    const end = textarea.value?.selectionEnd ?? start;
    markdown.value = markdown.value.slice(0, start) + marker + markdown.value.slice(end);
    try {
        const body = new FormData();
        body.append("file", file);
        const { data } = await api.post("/knowledge/assets", body, { headers: { "Content-Type": "multipart/form-data" } });
        markdown.value = markdown.value.replace(marker, `![图片](${data.url})`);
        await nextTick();
        textarea.value?.focus();
    }
    catch (e: any) {
        markdown.value = markdown.value.replace(marker, "");
        error.value = e.response?.data?.message || e.message || "图片上传失败";
    }
    finally {
        uploadingImage.value = false;
        persistDraft();
    }
}
function chooseImage(event: Event) {
    const input = event.target as HTMLInputElement;
    void insertImage(input.files?.[0]);
    input.value = "";
}
function pasteImage(event: ClipboardEvent) {
    const file = Array.from(event.clipboardData?.files || []).find(file => file.type.startsWith("image/"));
    if (file) {
        event.preventDefault();
        void insertImage(file);
    }
}
function dropImage(event: DragEvent) {
    const file = event.dataTransfer?.files[0];
    if (file) {
        event.preventDefault();
        void insertImage(file);
    }
}
function keepCopy() {
    id.value = "";
    conflicted.value = false;
    error.value = "";
    name.value = name.value.slice(0, 154) + "（副本）";
}
async function save() {
    if (saving.value || uploadingImage.value)
        return;
    saving.value = true;
    error.value = "";
    const isDoc = mode.value === "document";
    try {
        const payload = isDoc ? { module: parent.value, title: name.value.trim(), markdown: markdown.value }
            : { name: name.value.trim(), parent: parent.value || null };
        const path = isDoc ? "/knowledge/documents/" : "/knowledge/modules/";
        const { data } = id.value
            ? await api.put(path + id.value, { ...payload, version: version.value })
            : await api.post(isDoc ? "/knowledge/documents" : "/knowledge/", payload);
        clearDraft();
        open.value = false;
        importRequest++;
        emit("saved", isDoc ? data.module : data.id, isDoc ? data.id : undefined);
        ElMessage.success(itemLabel.value + "已保存");
    }
    catch (e: any) {
        const detail = e.response?.data;
        const field = detail && Object.values(detail).find(Array.isArray);
        error.value = detail?.message || (Array.isArray(field) && field.join(" ")) || e.message || "保存失败";
        conflicted.value = isDoc && !!id.value && e.response?.status === 409;
    }
    finally {
        saving.value = false;
    }
}
</script>

<template>
  <el-dialog v-model="open" :before-close="close" :close-on-click-modal="false"
    :width="mode === 'document' ? 'min(920px,96vw)' : 'min(430px,96vw)'" :title="(id ? '编辑' : '新建') + itemLabel" :close-on-press-escape="!saving&&!uploadingImage" :show-close="!saving&&!uploadingImage">
    <form id="knowledge-editor" class="knowledge-editor" @submit.prevent="save">
      <label>{{ itemLabel }}{{ mode === 'document' ? '标题' : '名称' }}
        <input v-model="name" required :maxlength="mode === 'document' ? 160 : 64" :disabled="saving" />
      </label>
      <label v-if="mode !== 'space' || id">所属位置
        <select v-model="parent" :required="mode === 'document'" :disabled="saving">
          <option v-if="mode !== 'document'" value="">顶层（独立空间）</option>
          <option v-for="item in locations" :key="item.id" :value="item.id">{{ item.title }}</option>
        </select>
      </label>
      <template v-if="mode === 'document'">
        <div v-if="recoverable" class="draft-notice">有一份本机未保存草稿 <button type="button" class="link-button" @click="recoverDraft">恢复草稿</button></div>
        <div class="editor-actions">
          <div class="editor-modes" role="group" aria-label="正文视图"><button type="button" :aria-pressed="!preview" @click="preview = false">写正文</button>
            <button type="button" :aria-pressed="preview" @click="preview = true">预览</button></div>
          <div class="editor-modes"><button type="button" class="link-button" :disabled="saving||uploadingImage" @click="imageInput?.click()">{{ uploadingImage?'上传图片中…':'插入图片' }}</button><button type="button" class="link-button" :disabled="saving||uploadingImage" @click="fileInput?.click()">导入 .md</button></div>
          <input ref="imageInput" type="file" hidden accept="image/png,image/jpeg,image/gif,image/webp" @change="chooseImage" />
          <input ref="fileInput" type="file" hidden accept=".md,.markdown,text/markdown" @change="importFile" />
        </div>
        <div v-if="preview" class="edit-preview"><KnowledgeMarkdown v-if="markdown.trim()" :source="markdown" preview />
          <p v-else class="muted">输入正文后可预览。</p></div>
        <textarea v-else ref="textarea" v-model="markdown" aria-label="Markdown 正文" placeholder="输入 Markdown，可直接粘贴或拖入图片" :required="!preserveEmpty" maxlength="250000" rows="16" :disabled="saving||uploadingImage" @paste="pasteImage" @drop="dropImage" @dragover.prevent></textarea>
        <small v-if="draftSaved" class="muted" role="status">草稿已保存到此浏览器</small>
      </template>
      <p v-if="error" role="alert" class="form-error">{{ error }} <button v-if="conflicted" type="button" class="link-button" @click="keepCopy">另存为新文档</button></p>
    </form>
    <template #footer><el-button :disabled="saving||uploadingImage" @click="close">取消</el-button>
      <el-button type="primary" form="knowledge-editor" native-type="submit" :loading="saving"
        :disabled="uploadingImage||!name.trim() || (mode === 'document' && ((!markdown.trim() && !preserveEmpty) || !parent))">保存</el-button></template>
  </el-dialog>
</template>

<style scoped>
.knowledge-editor { display:grid; gap:15px; }
.knowledge-editor label { display:grid; gap:6px; font-size:13px; font-weight:600; }
.knowledge-editor input:not([type=file]), .knowledge-editor select, .knowledge-editor textarea { width:100%; min-width:0; padding:9px 11px; color:var(--ink); border:1px solid #a7b9ad; border-radius:6px; background:rgb(255 255 255 / 72%); }
.knowledge-editor textarea { font:14px/1.65 "IBM Plex Mono",Consolas,"Microsoft YaHei",monospace; resize:vertical; }
.editor-actions, .editor-modes { display:flex; align-items:center; gap:7px; }
.editor-actions { justify-content:space-between; }
.editor-modes button { background:transparent; color:var(--muted); border:0; border-radius:4px; padding:6px 8px; font-size:13px; }
.editor-modes button[aria-pressed=true] { background:#e4efe2; color:#245d38; font-weight:650; }
.edit-preview { padding:15px; min-height:190px; max-height:45vh; overflow:auto; border:1px solid var(--line); border-radius:6px; background:rgb(255 255 255 / 32%); }
.form-error { color:#9b352b; font-size:13px; }
</style>
