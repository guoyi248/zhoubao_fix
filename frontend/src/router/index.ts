/**
 * Vue Router 路由配置。
 * /login 不需要鉴权，其余路由均需登录。
 */
import { createRouter, createWebHistory } from "vue-router";
import { useUserStore } from "@/stores/user";

const routes = [
  {
    path: "/login",
    name: "login",
    component: () => import("@/views/auth/LoginView.vue"),
  },
  {
    path: "/activate",
    name: "activate",
    component: () => import("@/views/auth/ActivateView.vue"),
  },
  // ── 成员 ──────────────────────────────────────────────
  {
    path: "/",
    name: "dashboard",
    component: () => import("@/views/member/DashboardView.vue"),
  },
  {
    path: "/reports/current",
    name: "current-report",
    component: () => import("@/views/member/ReportEditorView.vue"),
  },
  {
    path: "/reports",
    name: "my-reports",
    component: () => import("@/views/member/MyReportsView.vue"),
  },
  {
    path: "/private-plans",
    name: "private-plans",
    component: () => import("@/views/member/PrivatePlansView.vue"),
  },
  { path: "/reminders", name: "reminders", component: () => import("@/views/member/RemindersView.vue") },
  { path: "/analysis", name: "analysis", component: () => import("@/views/member/AnalysisView.vue") },
  { path: "/knowledge", name: "knowledge", component: () => import("@/views/member/KnowledgeBaseView.vue") },
  { path: "/admin/presentation", name: "presentation", component: () => import("@/views/admin/MeetingModeView.vue") },
  { path: "/admin/settings", name: "system-settings", component: () => import("@/views/admin/SystemSettingsView.vue") },
  // ── 管理员 ────────────────────────────────────────────
  {
    path: "/admin/reports",
    name: "admin-reports",
    component: () => import("@/views/admin/AllReportsView.vue"),
  },
  {
    path: "/admin/meetings/:id",
    name: "meeting-mode",
    component: () => import("@/views/admin/MeetingModeView.vue"),
  },
  {
    path: "/admin/members",
    name: "member-management",
    component: () => import("@/views/admin/MemberManagementView.vue"),
  },
  {
    path: "/admin/audit",
    name: "audit-log",
    component: () => import("@/views/admin/AuditLogView.vue"),
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) return savedPosition;
    if (to.path !== from.path && !to.hash) return { top: 0 };
  },
});

router.beforeEach(async (to) => {
  if (to.name === "login" || to.name === "activate") return;
  const store = useUserStore();
  const adminPage = to.path.startsWith("/admin/");
  if (!store.isAuthenticated || adminPage) await store.fetchMe();
  if (!store.isAuthenticated) return { name: "login", query: { next: to.fullPath }, replace: true };
  if (adminPage && !store.isAdmin) return { name: "dashboard", replace: true };
});

export default router;
