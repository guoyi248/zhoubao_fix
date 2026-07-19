/**
 * Axios 封装：统一 CSRF、错误处理和取消请求。
 * 关键：CSRF token 缺失时自动获取后重试。
 */
import axios, { type AxiosError, type InternalAxiosRequestConfig } from "axios";

// ── CSRF Token 管理 ────────────────────────────────────

function getCookie(name: string): string | null {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop()?.split(";").shift() || null;
  return null;
}

let csrfPromise: Promise<string> | null = null;

async function ensureCsrf(): Promise<string> {
  // 先尝试从 cookie 读
  const existing = getCookie("csrftoken");
  if (existing) return existing;

  // 没有就请求一个
  if (!csrfPromise) {
    csrfPromise = axios
      .get("/api/v1/auth/csrf", { withCredentials: true })
      .then(() => {
        const token = getCookie("csrftoken");
        if (!token) throw new Error("CSRF cookie not set");
        return token;
      })
      .finally(() => {
        csrfPromise = null;
      });
  }
  return csrfPromise;
}

// ── Axios 实例 ─────────────────────────────────────────

const api = axios.create({
  baseURL: "/api/v1",
  withCredentials: true,
  headers: { "Content-Type": "application/json" },
});

// ── 请求拦截：确保 CSRF token 存在 ─────────────────────

api.interceptors.request.use(async (config: InternalAxiosRequestConfig) => {
  if (config.method && ["post", "put", "patch", "delete"].includes(config.method)) {
    try {
      const token = await ensureCsrf();
      config.headers["X-CSRFToken"] = token;
    } catch {
      // CSRF 不可用，让请求发出去看服务器怎么说
    }
  }
  return config;
});

// ── 响应拦截：403 CSRF 失败时自动刷新 token 重试 ──────

let isRefreshingCsrf = false;
let failedQueue: Array<{ resolve: (v: any) => void; reject: (e: any) => void }> = [];

function processQueue(error: any, token: string | null = null) {
  failedQueue.forEach(({ resolve, reject }) => {
    if (error) reject(error);
    else resolve(token);
  });
  failedQueue = [];
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError<{ code?: string; message?: string; detail?: string }>) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean };
    const detail = error.response?.data;

    // 403 CSRF 失败 → 刷新 token 重试一次
    if (error.response?.status === 403 && !originalRequest._retry) {
      const msg = detail?.detail || detail?.message || "";
      if (msg.includes("CSRF") || msg.includes("csrf")) {
        if (isRefreshingCsrf) {
          return new Promise((resolve, reject) => {
            failedQueue.push({ resolve, reject });
          }).then((token) => {
            originalRequest.headers["X-CSRFToken"] = token;
            originalRequest._retry = true;
            return api(originalRequest);
          });
        }

        isRefreshingCsrf = true;
        originalRequest._retry = true;

        try {
          await axios.get("/api/v1/auth/csrf", { withCredentials: true });
          const newToken = getCookie("csrftoken");
          originalRequest.headers["X-CSRFToken"] = newToken;
          processQueue(null, newToken);
          return api(originalRequest);
        } catch (refreshError) {
          processQueue(refreshError, null);
          return Promise.reject(refreshError);
        } finally {
          isRefreshingCsrf = false;
        }
      }
    }

    // 401 → 跳转登录
    if (error.response?.status === 401 && window.location.pathname !== "/login") {
      window.location.href = "/login";
    }

    // 提取业务错误消息
    if (detail?.code) {
      error.message = detail.message || detail.code;
    }

    return Promise.reject(error);
  },
);

export default api;
