<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref } from "vue";
import { ArrowDown, ChatDotRound, Close, Minus, Promotion } from "@element-plus/icons-vue";
import axios from "axios";
import api from "@/utils/api";
import WhalePetArt from "@/components/WhalePetArt.vue";
import { petActions, type PetActionId, type PetActionRequest } from "@/components/whalePetActions";

interface Turn { question: string; reply: string; error: string }
interface Message { role: "user" | "assistant"; content: string }

const open = ref(false);
const compact = ref(false);
try { compact.value = localStorage.getItem("weekly.compactPet") === "1"; } catch { /* Session only. */ }
const turns = ref<Turn[]>([]);
const draft = ref("");
const busy = ref(false);
const launcher = ref<HTMLButtonElement>();
const actionToggle = ref<HTMLButtonElement>();
const showActions = ref(false);
const actionRequest = ref<PetActionRequest>();
const panel = ref<HTMLElement>();
const input = ref<HTMLTextAreaElement>();
const transcript = ref<HTMLElement>();
let request: AbortController | undefined;

function setCompact(value: boolean) {
  compact.value = value;
  try { localStorage.setItem("weekly.compactPet", value ? "1" : "0"); } catch { /* Session only. */ }
}

async function scrollToLatest() {
  await nextTick();
  if (transcript.value) transcript.value.scrollTop = transcript.value.scrollHeight;
}
async function closeChat() {
  showActions.value = false;
  open.value = false;
  await nextTick();
  launcher.value?.focus({ preventScroll: true });
}
function playAction(id: PetActionId) {
  actionRequest.value = { id, sequence: (actionRequest.value?.sequence ?? 0) + 1 };
}
function selectAction(id: PetActionId) {
  playAction(id);
  showActions.value = false;
  actionToggle.value?.focus({ preventScroll: true });
}
function onEscape() {
  if (showActions.value) {
    showActions.value = false;
    actionToggle.value?.focus({ preventScroll: true });
  } else if (open.value) {
    void closeChat();
  }
}
async function toggleChat() {
  if (open.value) return closeChat();
  if (compact.value) setCompact(false);
  open.value = true;
  await scrollToLatest();
  const target = window.matchMedia("(pointer: coarse)").matches ? panel.value : input.value;
  target?.focus({ preventScroll: true });
}
function minimize() {
  setCompact(true);
  void closeChat();
}

// The service accepts four complete turns plus the new question, up to 6000 characters.
function contextFor(question: string): Message[] {
  const messages: Message[] = [{ role: "user", content: question }];
  let length = Array.from(question).length;
  for (let i = turns.value.length - 1; i >= 0 && messages.length < 9; i--) {
    const turn = turns.value[i]!;
    if (!turn.reply) continue;
    length += Array.from(turn.question).length + Array.from(turn.reply).length;
    if (length > 6000) break;
    messages.unshift({ role: "user", content: turn.question }, { role: "assistant", content: turn.reply });
  }
  return messages;
}
async function ask(retry = false) {
  if (busy.value) return;
  const previous = turns.value.at(-1);
  if (retry) {
    if (!previous?.error) return;
    previous.error = "";
  } else {
    const question = draft.value.trim();
    if (!question || question.length > 2000) return;
    turns.value.push({ question, reply: "", error: "" });
    draft.value = "";
  }
  const turn = turns.value.at(-1)!;
  const controller = new AbortController();
  request = controller;
  busy.value = true;
  void scrollToLatest();
  try {
    const { data } = await api.post<{ reply: string }>("/pet/chat", { messages: contextFor(turn.question) },
      { signal: controller.signal, timeout: 125000 });
    if (typeof data.reply !== "string" || !data.reply.trim()) throw new Error("Empty reply");
    turn.reply = data.reply.trim();
    playAction("reply");
  } catch (err) {
    if (controller.signal.aborted) return;
    const detail = axios.isAxiosError<{ message?: string }>(err) ? err.response?.data?.message : "";
    turn.error = detail || "暂时没有收到回复，请稍后重试。";
  } finally {
    request = undefined;
    busy.value = false;
    void scrollToLatest();
  }
}
function onEnter(event: KeyboardEvent) {
  if (event.shiftKey || event.isComposing || event.keyCode === 229) return;
  event.preventDefault();
  void ask();
}
onBeforeUnmount(() => request?.abort());
</script>

<template>
  <aside class="whale-pet" aria-label="大肥鱼桌宠" :class="{ 'is-open': open, 'is-compact': compact }"
    @keydown.esc="onEscape">
    <Transition name="pet-panel">
      <section v-if="open" id="whale-pet-dialog" ref="panel" class="pet-chat" role="dialog"
        aria-labelledby="whale-pet-title" tabindex="-1">
        <header class="pet-head">
          <h2 id="whale-pet-title">大肥鱼</h2>
          <button ref="actionToggle" type="button" class="pet-action-toggle" :aria-expanded="showActions"
            :aria-controls="showActions ? 'whale-pet-actions' : undefined" @click="showActions = !showActions">
            换个动作 <el-icon aria-hidden="true"><ArrowDown /></el-icon>
          </button>
          <button class="pet-icon" type="button" aria-label="关闭对话" title="关闭对话" @click="closeChat"><el-icon><Close /></el-icon></button>
        </header>
        <div v-if="showActions" id="whale-pet-actions" class="pet-actions" role="group" aria-label="选择桌宠动作">
          <button v-for="action in petActions" :key="action.id" type="button" @click="selectAction(action.id)">
            {{ action.label }}
          </button>
        </div>
        <div ref="transcript" class="pet-transcript" role="log" aria-label="聊天记录" aria-live="polite" tabindex="0">
          <p v-if="!turns.length" class="pet-bubble">今天想聊些什么？</p>
          <div v-for="(turn, index) in turns" :key="index" class="pet-turn">
            <p class="pet-bubble from-user"><span class="sr-only">你：</span>{{ turn.question }}</p>
            <p v-if="turn.reply" class="pet-bubble"><span class="sr-only">大肥鱼：</span>{{ turn.reply }}</p>
            <div v-else-if="turn.error" class="pet-failure">
              {{ turn.error }}
              <button v-if="index === turns.length - 1" type="button" class="retry" @click="ask(true)">重试</button>
            </div>
            <span v-else class="pet-thinking" role="status">正在思考…</span>
          </div>
        </div>
        <form class="pet-composer" @submit.prevent="ask()">
          <textarea ref="input" v-model="draft" aria-label="给大肥鱼发消息" placeholder="给大肥鱼发消息…"
            rows="2" maxlength="2000" @keydown.enter="onEnter"></textarea>
          <button class="pet-send" type="submit" title="发送" aria-label="发送消息" :disabled="busy || !draft.trim()">
            <el-icon><Promotion /></el-icon>
          </button>
        </form>
        <footer><a href="/pet-artwork.html" target="_blank" rel="noopener">角色来源</a></footer>
      </section>
    </Transition>
    <div class="pet-stand">
      <button ref="launcher" type="button" class="pet-launcher" :title="open ? '关闭对话' : '和大肥鱼聊天'"
        :aria-label="open ? '收起大肥鱼对话' : '和大肥鱼聊天'" aria-haspopup="dialog"
        :aria-controls="open ? 'whale-pet-dialog' : undefined" :aria-expanded="open" @click="toggleChat">
        <el-icon v-if="compact" class="compact-icon"><ChatDotRound /></el-icon>
        <WhalePetArt v-else :thinking="busy" :action-request="actionRequest" />
      </button>
      <button v-if="!compact && !open" type="button" class="pet-minimize" aria-label="缩小桌宠" title="缩小桌宠" @click="minimize">
        <el-icon><Minus /></el-icon>
      </button>
    </div>
  </aside>
</template>

<style scoped>
.whale-pet {
  --pet-bottom:max(12px,env(safe-area-inset-bottom));
  --pet-side:max(16px,env(safe-area-inset-right));
  --pet-size:128px;
  position:fixed; right:var(--pet-side); bottom:var(--pet-bottom); z-index:7;
  display:flex; flex-direction:column; align-items:flex-end; gap:8px; pointer-events:none;
}
.shell:has(.submit-bar) .whale-pet { --pet-bottom:calc(76px + env(safe-area-inset-bottom)); }
.pet-stand { position:relative; width:var(--pet-size); height:var(--pet-size); pointer-events:auto; }
.pet-launcher { display:grid; place-items:center; width:100%; height:100%; padding:0; background:none; border:0; border-radius:42%; touch-action:manipulation; }
.pet-launcher > :first-child { width:100%; height:100%; pointer-events:none; }
.pet-minimize,.pet-icon,.pet-send { display:grid; place-items:center; border:0; padding:0; touch-action:manipulation; }
.pet-minimize,.is-compact .pet-launcher { border:1px solid rgb(255 255 255 / 78%); background:#ecf5ed; color:#28583f; box-shadow:0 2px 10px #183b3033; }
.pet-minimize { position:absolute; top:0; right:-2px; border-radius:50%; width:25px; height:25px; font-size:13px; }
@media (hover:hover) {
  .pet-stand:not(:hover):not(:focus-within) .pet-minimize { opacity:0; }
}
.is-compact { --pet-size:42px; }
.is-compact .pet-launcher { border-radius:50%; }
.pet-launcher .compact-icon { width:21px; height:21px; }
.pet-chat {
  pointer-events:auto; display:flex; flex-direction:column; width:min(334px,calc(100vw - 2 * var(--pet-side)));
  max-height:calc(100dvh - var(--pet-size) - var(--pet-bottom) - 24px); min-height:0;
  color:#22392f; background:rgb(245 251 246 / 93%); border:1px solid var(--glass-edge);
  border-radius:19px; box-shadow:0 14px 48px -12px #102f254d, inset 0 1px 0 white;
  -webkit-backdrop-filter:var(--glass-filter); backdrop-filter:var(--glass-filter); overflow:auto;
}
.pet-head { display:flex; flex:none; align-items:center; gap:6px; padding:12px 12px 10px 16px; border-bottom:1px solid #48634d24; }
.pet-head h2 { flex:1; font-size:16px; line-height:1.4; }
.pet-action-toggle { display:inline-flex; align-items:center; gap:5px; padding:6px 9px; border:1px solid #a5bbac; border-radius:8px; color:#2a5540; background:transparent; font-size:12px; }
.pet-action-toggle[aria-expanded=true] .el-icon { transform:rotate(180deg); }
.pet-actions { display:grid; flex:none; grid-template-columns:repeat(3,minmax(0,1fr)); gap:6px; padding:10px 12px; border-bottom:1px solid #48634d24; }
.pet-actions button { padding:7px 2px; border:1px solid #c4d6c9; border-radius:8px; background:rgb(255 255 255 / 70%); color:#234a33; font-size:13px; }
.pet-actions button:hover,.pet-action-toggle:hover { background:#deecdf; }
.pet-thinking,.pet-chat footer a { color:#4d6456; font-size:12px; }
.pet-icon { width:32px; height:32px; background:transparent; color:#3a574a; border-radius:8px; font-size:16px; }
.pet-icon:hover { background:#deecdf; }
.pet-transcript { display:flex; flex-direction:column; gap:12px; min-height:0; padding:16px; overflow:auto; overscroll-behavior:contain; max-height:270px; }
.pet-turn { display:flex; flex-direction:column; align-items:flex-start; gap:9px; }
.pet-bubble { width:fit-content; max-width:95%; padding:9px 12px; border-radius:12px 12px 12px 3px; background:#fff; font-size:14px; line-height:1.6; white-space:pre-wrap; overflow-wrap:anywhere; }
.from-user { align-self:flex-end; border-radius:12px 12px 3px 12px; background:#dcecdf; color:#19442e; }
.pet-failure { color:#8c3e30; font-size:13px; line-height:1.6; overflow-wrap:anywhere; }
.retry { margin-left:4px; padding:3px; color:#205539; background:none; border:0; text-decoration:underline; }
.pet-composer { flex:none; display:flex; align-items:flex-end; gap:6px; margin:0 12px; padding:6px; border:1px solid #afc7b6; border-radius:13px; background:#fff; }
.pet-composer:focus-within { border-color:#45845f; box-shadow:0 0 0 2px #45845f29; }
.pet-composer textarea { flex:1; min-width:0; border:0; outline:0; padding:4px; border-radius:6px; color:#233c32; background:transparent; line-height:1.4; font-size:14px; resize:none; }
.pet-send { width:34px; height:34px; flex:none; border-radius:10px; background:#245f44; color:white; font-size:17px; }
.pet-send:disabled { background:#dee8df; color:#647d6c; }
.pet-chat footer { padding:4px 16px 8px; text-align:right; }
.pet-chat footer a { text-decoration:none; }
.pet-chat footer a:hover { text-decoration:underline; }
.sr-only { position:absolute; width:1px; height:1px; overflow:hidden; clip-path:inset(50%); }
@media (max-width:600px) {
  .whale-pet { --pet-size:82px; --pet-side:max(10px,env(safe-area-inset-right)); }
  .is-compact { --pet-size:38px; }
  .is-open .pet-stand { position:absolute; top:4px; left:7px; width:62px; height:64px; }
  .is-open .pet-head { min-height:72px; padding-left:77px; }
  .is-open .pet-chat { max-height:calc(100dvh - var(--pet-bottom) - 16px); }
  .pet-composer textarea { font-size:16px; }
}
@media (prefers-reduced-motion:no-preference) {
  .pet-panel-enter-active,.pet-panel-leave-active { transition:opacity .16s,transform .16s; }
  .pet-panel-enter-from,.pet-panel-leave-to { opacity:0; transform:translateY(6px); }
}
@media (prefers-reduced-transparency:reduce) { .pet-chat { background:#f5fbf6; } }
</style>
