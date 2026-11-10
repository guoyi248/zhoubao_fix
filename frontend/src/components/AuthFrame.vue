<template>
  <main class="auth-bg">
    <section class="auth-shell" aria-labelledby="auth-title">
      <div class="wordmark"><span class="brand-mark" aria-hidden="true"></span>周报空间</div>
      <div class="auth-form"><slot /></div>
    </section>
  </main>
</template>

<style scoped>
.auth-bg {
  min-height:100dvh;
  display:grid;
  place-items:center;
  padding:clamp(16px,3vw,36px);
  background:#e4eee3 url("../assets/wallpapers/forest.webp") center / cover no-repeat;
}
.auth-shell {
  width:min(410px,100%);
  min-width:0;
  padding:clamp(24px,4vw,38px);
  border:1px solid var(--glass-edge, rgb(255 255 255 / 76%));
  border-radius:20px;
  background:#f5f9f4;
  box-shadow:var(--glass-shadow, 0 18px 56px -20px rgb(17 44 33 / 40%));
}
@supports ((backdrop-filter:blur(1px)) or (-webkit-backdrop-filter:blur(1px))) {
  .auth-shell {
    background:var(--glass-fill, rgb(244 251 245 / 66%));
    -webkit-backdrop-filter:var(--glass-filter, blur(18px) saturate(116%));
    backdrop-filter:var(--glass-filter, blur(18px) saturate(116%));
  }
}
.wordmark { gap:8px; font-size:15px; }
.auth-form :deep(h1) { margin:22px 0; color:#193a2c; font-size:27px; line-height:1.3; }
.auth-form :deep(.el-input__wrapper) { min-height:43px; background:rgb(255 255 255 / 90%); }
.auth-form :deep(.el-button) { width:100%; height:43px; }
.auth-form :deep(.el-form-item__label) { color:#254434; font-weight:600; }
.auth-form :deep(.el-form-item:last-child) { margin:18px 0 0; }
.auth-form :deep(.el-alert) { margin:12px 0; }
@media (max-width:620px) {
  .auth-bg { background-position:78% center; }
  .auth-shell { padding:clamp(22px,6vw,30px); }
}
@media (prefers-reduced-transparency:reduce) {
  .auth-shell { background:#f5f9f4; -webkit-backdrop-filter:none; backdrop-filter:none; }
}
</style>
