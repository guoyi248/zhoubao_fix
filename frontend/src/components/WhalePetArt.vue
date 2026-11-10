<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, shallowRef, watch } from "vue";
import { petActions, type PetActionId, type PetActionRequest } from "./whalePetActions";

const props = defineProps<{ thinking?: boolean; actionRequest?: PetActionRequest | null }>();
const autoActions: PetActionId[] = ["snack", "dance", "play", "lion"];
const idleDurationMs = 10_000;
const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
const canAnimate = ref(!preference.matches && !document.hidden);
type Motion = PetActionId | "idle";
const current = ref<Motion>(canAnimate.value ? (props.thinking ? "think" : "snack") : "idle");
let serial = 0;
let autoIndex = 0;
let timer: number | undefined;

function frameFor(id: Motion, animated: boolean) {
  let name: string = id;
  if (!animated) name += "-pose";
  else if (id === "lion") name = "lion-dance";
  const url = new URL(`../assets/pet/${name}.webp`, import.meta.url);
  const key = ++serial;
  if (animated) url.hash = `take-${key}`;
  return { key, id, animated, src: url.href };
}
type Frame = ReturnType<typeof frameFor>;
const shown = shallowRef(frameFor("idle", false));
const incoming = shallowRef<Frame | null>(canAnimate.value ? frameFor(current.value, true) : null);
const layers = computed(() => incoming.value ? [shown.value, incoming.value] : [shown.value]);

function clearTimer() {
  window.clearTimeout(timer);
  timer = undefined;
}
function play(id: Motion) {
  clearTimer();
  current.value = id;
  incoming.value = frameFor(id, canAnimate.value);
  if (id !== "idle") {
    const index = autoActions.indexOf(id);
    if (index >= 0) autoIndex = index;
  }
}
function schedule(frame: Frame) {
  clearTimer();
  if (!canAnimate.value) return;
  if (frame.id === "idle") {
    if (!props.thinking) timer = window.setTimeout(() => play(autoActions[(autoIndex + 1) % autoActions.length]!), idleDurationMs);
    return;
  }
  const action = petActions.find(action => action.id === frame.id)!;
  timer = window.setTimeout(() => play("idle"), frame.animated ? action.durationMs : 1600);
}
async function showFrame(frame: Frame, event: Event) {
  if (incoming.value !== frame) return;
  const image = event.currentTarget as HTMLImageElement;
  try {
    await image.decode();
  } catch {
    failedFrame(frame);
    return;
  }
  if (incoming.value !== frame) return;
  // Commit the initial opacity even when the browser serves the image from memory.
  image.getBoundingClientRect();
  shown.value = frame;
  incoming.value = null;
  schedule(frame);
}
function failedFrame(frame: Frame) {
  if (incoming.value !== frame) return;
  if (frame.animated) {
    incoming.value = frameFor(frame.id, false);
  } else {
    incoming.value = null;
    schedule(frame);
  }
}
function syncPlayback() {
  const active = !preference.matches && !document.hidden;
  if (active === canAnimate.value) return;
  canAnimate.value = active;
  clearTimer();
  if (active) play("idle");
  else {
    current.value = "idle";
    shown.value = frameFor("idle", false);
    incoming.value = null;
  }
}
watch(() => props.thinking, thinking => {
  if (thinking) play("think");
  else if (current.value === "think") play("idle");
  else if (current.value === "idle" && !incoming.value) schedule(shown.value);
});
watch(() => props.actionRequest, request => { if (request) play(request.id); });
onMounted(() => {
  preference.addEventListener("change", syncPlayback);
  document.addEventListener("visibilitychange", syncPlayback);
});
onBeforeUnmount(() => {
  incoming.value = null;
  clearTimer();
  preference.removeEventListener("change", syncPlayback);
  document.removeEventListener("visibilitychange", syncPlayback);
});
</script>

<template>
  <span class="pet-art" :class="{ 'still-only': !canAnimate }" :data-action="current" aria-hidden="true">
    <TransitionGroup name="pet-blend" :css="canAnimate">
      <img v-for="frame in layers" :key="frame.key" :src="frame.src" :data-action="frame.id" :data-take="frame.key"
        class="pet-frame" :class="[frame.animated ? 'pet-motion' : 'pet-pose', { ready: shown === frame }]"
        alt="" draggable="false" @load="showFrame(frame, $event)" @error="failedFrame(frame)" />
    </TransitionGroup>
  </span>
</template>

<style scoped>
.pet-art { display:block; position:relative; isolation:isolate; }
.pet-frame {
  position:absolute; inset:0; width:100%; height:100%; object-fit:contain; object-position:center bottom;
  user-select:none; opacity:0; mix-blend-mode:plus-lighter; transition:opacity 240ms ease-in-out;
}
.pet-frame.ready { opacity:1; }
.pet-frame.pet-blend-leave-to { opacity:0; }
.still-only .pet-frame { transition:none; }
@media (prefers-reduced-motion:reduce) { .pet-frame { transition:none; } }
</style>
