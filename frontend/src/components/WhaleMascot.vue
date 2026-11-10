<script setup lang="ts">
import { onBeforeUnmount, ref } from "vue";
// Character reference: https://treapgogo.github.io/deepseek-whale-girl/ (Q 版大肥鱼).
import idleImage from "@/assets/whale-idle.webp";
import waveImage from "@/assets/whale-wave.webp";

defineProps<{ variant: "welcome" | "desk" }>();
const waving = ref(false);
let reset: number | undefined;

function greet() {
  if (waving.value) return;
  waving.value = true;
  reset = window.setTimeout(() => { waving.value = false; }, 950);
}
onBeforeUnmount(() => window.clearTimeout(reset));
</script>

<template>
  <button type="button" class="whale-mascot" :class="[variant, { 'is-greeting': waving }]"
    aria-label="和大肥鱼打招呼" title="和大肥鱼打招呼" @click="greet">
    <span class="whale-art" aria-hidden="true">
      <img class="idle" :src="idleImage" alt="" width="536" height="590" draggable="false" />
      <img class="wave" :src="waveImage" alt="" width="536" height="590" draggable="false" />
    </span>
    <span v-if="waving" class="bubbles" aria-hidden="true"><i></i><i></i><i></i></span>
  </button>
</template>

<style scoped>
.whale-mascot {
  position:relative; display:block; width:100%; height:100%; aspect-ratio:536/590; padding:0;
  appearance:none; border:0; background:transparent; border-radius:20%; touch-action:manipulation;
}
.whale-art { position:absolute; inset:0; display:block; transform-origin:50% 92%; pointer-events:none; }
.whale-art img { position:absolute; inset:0; width:100%; height:100%; object-fit:contain; user-select:none; }
.wave,.is-greeting .idle { visibility:hidden; }
.is-greeting .wave { visibility:visible; }
.bubbles { display:none; }
@media (prefers-reduced-motion:no-preference) {
  .whale-art { animation:whale-breathe 2s ease-in-out 2; }
  .is-greeting .whale-art { animation:whale-greet .95s ease-in-out; }
  .is-greeting .bubbles { display:block; position:absolute; inset:0; pointer-events:none; }
  .bubbles i { position:absolute; top:57%; left:12%; width:5%; aspect-ratio:1; border-radius:50%;
    border:1px solid #6ea7c0; background:radial-gradient(circle at 32% 28%,#fff 14%,#d4f4ffb3 29%,#90d1e880);
    opacity:0; animation:whale-bubble .66s ease-out .08s both; }
  .bubbles i:nth-child(2) { left:7%; top:50%; width:3.4%; animation-delay:.19s; }
  .bubbles i:nth-child(3) { left:17%; top:43%; width:3%; animation-delay:.29s; }
  @keyframes whale-breathe { 50% { transform:translateY(-1.25%) rotate(-.8deg); } }
  @keyframes whale-greet {
    0%,100% { transform:none; } 24% { transform:translateY(-4%) rotate(-3deg); }
    54% { transform:translateY(-2%) rotate(1.8deg); } 78% { transform:rotate(-.9deg); }
  }
  @keyframes whale-bubble {
    0% { opacity:0; transform:translateY(0) scale(.45); } 22% { opacity:.95; }
    100% { opacity:0; transform:translateY(-230%) scale(1.05); }
  }
}
</style>
