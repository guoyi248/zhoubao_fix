<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import workspaceVideo from "@/assets/wallpapers/workspace.mp4";
import workspacePoster from "@/assets/wallpapers/workspace-poster.webp";
import teamVideo from "@/assets/wallpapers/team.mp4";
import teamPoster from "@/assets/wallpapers/team-poster.webp";
import forest from "@/assets/wallpapers/forest.webp";

const sources = {
  workspace: { image: workspacePoster, video: workspaceVideo },
  team: { image: teamPoster, video: teamVideo },
  forest: { image: forest, video: undefined },
};
const props = defineProps<{ scene: keyof typeof sources; paused: boolean; reduced: boolean }>();
const emit = defineEmits<{ blocked: []; unavailable: [] }>();
const media = computed(() => sources[props.scene]);
const video = ref<HTMLVideoElement>();
const visible = ref(!document.hidden);
const failed = ref(false);
const shouldPlay = computed(() => !!media.value.video && visible.value && !props.paused && !props.reduced && !failed.value);
const requested = ref(false);

function syncVisibility() { visible.value = !document.hidden; }
function showPoster() {
  failed.value = true;
  emit("unavailable");
}
watch(shouldPlay, (play) => { if (play) requested.value = true; }, { immediate: true });
watch([video, shouldPlay], ([el, play], _, cleanup) => {
  if (!el) return;
  if (!play) { el.pause(); return; }
  let current = true;
  cleanup(() => { current = false; });
  el.muted = true;
  el.play().catch((error: DOMException) => {
    if (!current || error.name === "AbortError") return;
    if (error.name === "NotAllowedError") emit("blocked");
    else showPoster();
  });
}, { flush: "post" });
onMounted(() => document.addEventListener("visibilitychange", syncVisibility));
onUnmounted(() => document.removeEventListener("visibilitychange", syncVisibility));
</script>

<template>
  <div class="page-wallpaper" :data-scene="scene" aria-hidden="true">
    <img :src="media.image" alt="" />
    <video v-if="media.video && requested && !failed && !reduced" ref="video" :src="media.video" :poster="media.image"
      muted loop playsinline preload="metadata" disablepictureinpicture @error="showPoster"></video>
  </div>
</template>

<style scoped>
.page-wallpaper { position:fixed; z-index:-1; inset:0; pointer-events:none; background:#d3e0d0; }
.page-wallpaper img,.page-wallpaper video { position:absolute; inset:0; width:100%; height:100%; object-fit:cover; }
</style>
