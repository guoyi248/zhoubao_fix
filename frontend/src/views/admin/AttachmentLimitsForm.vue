<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import api from "@/utils/api";

interface Limits { file_bytes: number; total_bytes: number; count: number }
interface Policy { limits: Limits; ceilings: Limits; source: string; version: number }
const fields = [
  { key: "file_bytes", label: "单个文件大小", unit: "MiB", divisor: 1048576 },
  { key: "total_bytes", label: "每份周报附件合计", unit: "MiB", divisor: 1048576 },
  { key: "count", label: "每份周报附件数", unit: "个", divisor: 1 },
] as const;
const endpoint = "/admin/config/attachment-limits";
const policy = ref<Policy>();
const form = ref<Limits>({ file_bytes:0, total_bytes:0, count:0 });
const busy = ref(false);
const error = ref("");
function accept(data: Policy) {
  policy.value = data;
  for (const field of fields) form.value[field.key] = data.limits[field.key] / field.divisor;
}
const edited = computed(() => {
  const changes: Partial<Limits> = {};
  for (const {key, divisor} of fields) {
    const value = Math.round(form.value[key] * divisor);
    if (value !== policy.value?.limits[key]) changes[key] = value;
  }
  return changes;
});
async function load() {
  busy.value = true;
  error.value = "";
  try { const {data} = await api.get<Policy>(endpoint); accept(data); }
  catch (e:any) { error.value = e.message || "读取附件限制失败"; }
  finally { busy.value = false; }
}
async function save(reset = false) {
  if (!policy.value || busy.value) return;
  if (reset) {
    try {
      await ElMessageBox.confirm("恢复后将使用当前部署的附件上限。", "恢复环境默认值", {confirmButtonText:"恢复",cancelButtonText:"取消"});
    } catch { return; }
  }
  busy.value = true;
  error.value = "";
  try {
    const {data} = await api.patch<Policy>(endpoint, {version:policy.value.version,...(reset ? {reset:true} : {values:edited.value})});
    accept(data);
    ElMessage.success("附件限制已保存");
  } catch (e:any) { error.value = e.message || "保存失败"; }
  finally { busy.value = false; }
}
onMounted(load);
</script>

<template>
  <form class="panel limits-form" aria-label="周报附件限制" @submit.prevent="save()">
    <p>适用于新上传和替换的附件。</p>
    <fieldset v-if="policy" :disabled="busy">
      <label v-for="field in fields" :key="field.key">
        <strong>{{ field.label }}</strong>
        <span class="number-field"><input v-model.number="form[field.key]" type="number" required
          :step="field.key==='count' ? '1':'any'" :min="1/field.divisor"
          :max="policy.ceilings[field.key]/field.divisor" :aria-label="field.label + '（' + field.unit + '）'" :aria-describedby="'ceiling-' + field.key"><span>{{ field.unit }}</span></span>
        <small :id="'ceiling-' + field.key">部署上限 {{ policy.ceilings[field.key]/field.divisor }} {{ field.unit }}</small>
      </label>
    </fieldset>
    <p v-if="error" class="problem" role="alert">{{ error }} <button type="button" class="link-button" @click="load">重新载入</button></p>
    <p v-else-if="!policy" role="status">正在读取附件限制…</p>
    <footer v-if="policy">
      <span>{{ policy.source==='database' ? '当前使用管理员配置' : '当前使用环境默认值' }}</span>
      <div><button v-if="policy.source==='database'" type="button" class="link-button" :disabled="busy" @click="save(true)">恢复环境默认值</button>
      <button class="save" type="submit" :disabled="busy || !Object.keys(edited).length">{{ busy ? '处理中…' : '保存' }}</button></div>
    </footer>
  </form>
</template>

<style scoped>
.limits-form{max-width:860px;padding:clamp(18px,3vw,32px)}p,small{color:var(--muted);font-size:13px;margin:0;line-height:1.6}
fieldset{padding:0 0 20px;margin:18px 0 16px;border:0;border-bottom:1px solid var(--line);display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px;min-width:0}
label{display:grid;gap:6px;font-size:14px}small{margin:0}.number-field{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--muted)}
input{width:100%;min-width:0;padding:9px;border:1px solid #a7b9ad;color:var(--ink);border-radius:6px;min-height:38px;background:rgb(255 255 255 / 68%)}
input:focus-visible,button:focus-visible{outline:2px solid #41815f;outline-offset:2px}footer,footer div{display:flex;align-items:center;gap:14px;flex-wrap:wrap}footer{justify-content:space-between;font-size:13px}
.save{background:#276447;border:0;color:white;border-radius:7px;padding:9px 17px;font-weight:650}.save:disabled{background:#dae4dc;color:#627169}.problem{color:#9e3529;margin:10px 0}
@media(max-width:620px){fieldset{grid-template-columns:1fr}}
</style>
