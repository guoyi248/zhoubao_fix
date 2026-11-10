/**
 * 应用入口：Element Plus + Pinia + Vue Router。
 */
import { createApp } from "vue";
import { createPinia } from "pinia";
import ElementPlus from "element-plus";
import { autoAnimatePlugin } from "@formkit/auto-animate/vue";
import "element-plus/dist/index.css";
import zhCn from "element-plus/es/locale/lang/zh-cn";
import "./style.css";
import App from "./App.vue";
import router from "./router";

const app = createApp(App);

app.use(createPinia());
app.use(router);
app.use(ElementPlus, { locale: zhCn });
app.use(autoAnimatePlugin, { duration: 170, easing: "ease-out" });

void router.isReady().then(() => app.mount("#app"));
