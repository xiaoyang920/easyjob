import { createApp } from 'vue'
import './style.css'
import App from './App.vue'
import router from './router'
import 'element-plus/theme-chalk/base.css'
import 'element-plus/theme-chalk/el-message.css'
import 'element-plus/theme-chalk/el-message-box.css'
import 'element-plus/theme-chalk/el-notification.css'
import lazyload from './directives/lazyload'
import { startAuthRenewal } from './utils/authSession'

const app = createApp(App)

// 注册懒加载指令
app.directive('lazyload', lazyload)

app.use(router)
// Avoid exposing interactive navigation before the initial route is resolved.
void router.isReady().then(() => { app.mount('#app'); startAuthRenewal() })
