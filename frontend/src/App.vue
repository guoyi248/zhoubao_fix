<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  Calendar, EditPen, Files, Lock, DataAnalysis, User, Tickets, Message, Reading,
  MagicStick, VideoCamera, VideoPlay, VideoPause, Expand, Fold, Close, SwitchButton, Setting,
} from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import { useUserStore } from "@/stores/user";
import { enterPresentationFullscreen } from "@/utils/presentation";
import PageWallpaper from "@/components/PageWallpaper.vue";

const WhalePet = defineAsyncComponent(() => import("@/components/WhalePet.vue"));

const route = useRoute();
const router = useRouter();
const store = useUserStore();
const mobileOpen = ref(false);
const menuButton = ref<HTMLButtonElement>();
const closeButton = ref<HTMLButtonElement>();
const rail = ref<HTMLElement>();
const workspace = ref<HTMLElement>();
const desktop = window.matchMedia("(min-width:781px)");
const isDesktop = ref(desktop.matches);
const compact = ref(false);
const wallpaper = computed(() => {
  if (["dashboard", "current-report", "private-plans"].includes(String(route.name))) return "workspace";
  if (route.name === "my-reports" || route.name === "admin-reports") return "team";
  return "forest";
});
const motionPreference = window.matchMedia("(prefers-reduced-motion: reduce)");
const reducedMotion = ref(motionPreference.matches);
function syncMotion() { reducedMotion.value = motionPreference.matches; }
onMounted(() => motionPreference.addEventListener("change", syncMotion));
onUnmounted(() => motionPreference.removeEventListener("change", syncMotion));
const wallpaperPaused = ref(false);
const wallpaperUnavailable = ref(false);
watch(wallpaper, () => { wallpaperUnavailable.value = false; });
const showPlayback = computed(() => wallpaper.value !== "forest" && !reducedMotion.value && !wallpaperUnavailable.value);
const playbackLabel = computed(() => wallpaperPaused.value ? "播放动态壁纸" : "暂停动态壁纸");
try { wallpaperPaused.value = localStorage.getItem("weekly.wallpaperPaused") === "1"; } catch { /* Private browsing. */ }
function toggleWallpaper() {
  wallpaperPaused.value = !wallpaperPaused.value;
  try { localStorage.setItem("weekly.wallpaperPaused", wallpaperPaused.value ? "1" : "0"); } catch { /* Session only. */ }
}
try { compact.value = localStorage.getItem("weekly.compactNav") === "1"; } catch { /* Storage can be disabled. */ }
function toggleCompact() {
  compact.value = !compact.value;
  try { localStorage.setItem("weekly.compactNav", compact.value ? "1" : "0"); } catch { /* Keep the session preference. */ }
}
const personal = [
  { path: "/", label: "本周工作台", icon: Calendar },
  { path: "/reports/current", label: "提交周报", icon: EditPen },
  { path: "/reports", label: "历史周报", icon: Files },
  { path: "/private-plans", label: "个人计划", icon: Lock },
];
const reports = [
  { path: "/knowledge", label: "组内知识库", icon: Reading },
  { path: "/analysis", label: "AI 周报解析", icon: MagicStick },
  { path: "/reminders", label: "邮箱提醒", icon: Message },
];
const team = [
  { path: "/admin/reports", label: "团队周报", icon: DataAnalysis },
  { path: "/admin/presentation", label: "组会展示", icon: VideoCamera },
  { path: "/admin/members", label: "用户管理", icon: User },
  { path: "/admin/audit", label: "操作记录", icon: Tickets },
  { path: "/admin/settings", label: "系统配置", icon: Setting },
];
const groups = computed(() => [
  { name: "个人空间", links: personal }, { name: "资料与工具", links: reports },
  ...(store.isAdmin ? [{ name: "团队管理", links: team }] : []),
]);
watch(() => route.fullPath, async () => {
  if (mobileOpen.value) {
    mobileOpen.value = false;
    await nextTick();
    workspace.value?.focus({ preventScroll: true });
  }
});
async function openMenu() {
  mobileOpen.value = true;
  await nextTick();
  closeButton.value?.focus();
}
async function closeMenu() {
  mobileOpen.value = false;
  await nextTick();
  menuButton.value?.focus();
}
function onLayoutChange() {
  isDesktop.value = desktop.matches;
  if (isDesktop.value) mobileOpen.value = false;
}
function keepMenuFocus(event: KeyboardEvent) {
  if (!mobileOpen.value || !rail.value) return;
  const items = Array.from(rail.value.querySelectorAll<HTMLElement>("a[href], button:not([disabled])"))
    .filter(item => item.getClientRects().length);
  const first = items[0], last = items.at(-1);
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
  if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
}
function navClick(event: MouseEvent, path: string) {
  if (path === "/admin/presentation") enterPresentationFullscreen(event);
  if (mobileOpen.value && route.path === path) closeMenu();
}
onMounted(() => desktop.addEventListener("change", onLayoutChange));
onUnmounted(() => desktop.removeEventListener("change", onLayoutChange));
async function logout() {
  try { await store.logout(); await router.replace("/login"); }
  catch { ElMessage.error("退出失败，请重试"); }
}
</script>
<template>
  <router-view v-if="!route.name || ['login','activate','meeting-mode','presentation'].includes(String(route.name))" />
  <div v-else class="shell" :class="{compact:compact && isDesktop}" @keydown.esc="mobileOpen && closeMenu()">
    <PageWallpaper :key="wallpaper" :scene="wallpaper" :paused="wallpaperPaused" :reduced="reducedMotion"
      @blocked="wallpaperPaused = true" @unavailable="wallpaperUnavailable = true" />
    <a class="skip-link" href="#workspace" @click.prevent="workspace?.focus()">跳到正文</a>
    <Transition name="scrim">
      <div v-if="mobileOpen" class="nav-scrim" aria-hidden="true" @click="closeMenu"></div>
    </Transition>
    <aside id="primary-rail" ref="rail" class="rail" :class="{opened:mobileOpen}" :inert="!isDesktop && !mobileOpen"
      :role="mobileOpen ? 'dialog' : undefined" :aria-modal="mobileOpen || undefined" aria-label="工作区导航" @keydown.tab="keepMenuFocus">
      <div class="rail-head">
        <router-link to="/" class="wordmark" aria-label="周报空间首页" @click="navClick($event, '/')"><span class="brand-mark" aria-hidden="true"></span><span class="brand-name">周报空间</span></router-link>
        <button class="icon-button rail-toggle" type="button" aria-controls="primary-links" :aria-expanded="!compact"
          :title="compact ? '展开侧栏' : '收起侧栏'" :aria-label="compact ? '展开侧栏' : '收起侧栏'" @click="toggleCompact"><el-icon><component :is="compact ? Expand : Fold" /></el-icon></button>
        <button ref="closeButton" class="icon-button rail-close" type="button" aria-label="关闭菜单" @click="closeMenu"><el-icon><Close /></el-icon></button>
      </div>
      <nav id="primary-links" aria-label="主导航">
        <section v-for="group in groups" :key="group.name">
          <h2 class="nav-caption">{{ group.name }}</h2>
          <router-link v-for="link in group.links" :key="link.path" :to="link.path" class="nav-link"
            :class="{selected:route.path===link.path}"
            :aria-label="link.label" :title="compact && isDesktop ? link.label : undefined"
            @click="navClick($event, link.path)">
            <el-icon><component :is="link.icon" /></el-icon><span class="nav-label">{{ link.label }}</span>
          </router-link>
        </section>
      </nav>
      <button v-if="showPlayback && isDesktop" class="wallpaper-control" type="button" :aria-label="playbackLabel"
        :title="playbackLabel" @click="toggleWallpaper">
        <el-icon><component :is="wallpaperPaused ? VideoPlay : VideoPause" /></el-icon><span class="nav-label">{{ playbackLabel }}</span>
      </button>
      <div class="rail-user">
        <span class="avatar" :title="store.user?.display_name">{{ store.user?.display_name.charAt(0) || '我' }}</span>
        <div><strong>{{ store.user?.display_name }}</strong><small>{{ store.isAdmin ? '管理员' : '普通用户' }}</small></div>
        <button class="icon-button logout" type="button" title="退出登录" aria-label="退出登录" @click="logout"><el-icon><SwitchButton /></el-icon></button>
      </div>
    </aside>
    <main id="workspace" ref="workspace" tabindex="-1" class="workspace scenic" :inert="mobileOpen || undefined">
      <header class="topline">
        <button ref="menuButton" class="icon-button menu-toggle" type="button" aria-label="打开导航" aria-controls="primary-rail" :aria-expanded="mobileOpen" @click="openMenu"><el-icon><Expand /></el-icon></button>
        <span class="wordmark"><span class="brand-mark" aria-hidden="true"></span>周报空间</span>
        <button v-if="showPlayback && !isDesktop" class="icon-button mobile-playback" type="button" :title="playbackLabel"
          :aria-label="playbackLabel" @click="toggleWallpaper"><el-icon><component :is="wallpaperPaused ? VideoPlay : VideoPause" /></el-icon></button>
      </header>
      <div :key="route.path" class="surface"><router-view /></div>
    </main>
    <WhalePet v-if="store.user" :key="store.user.id" :inert="mobileOpen || undefined" />
  </div>
</template>
