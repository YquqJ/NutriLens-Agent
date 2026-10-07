import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import { useAuthStore } from './stores/auth'
import './styles/index.scss'
// MessageBox is created programmatically, so its style is not discovered by
// the template-based Element Plus resolver.
import 'element-plus/es/components/message-box/style/css'

const app = createApp(App)

app.use(createPinia())
app.use(router)

// 启动时校验 token（有效则回填用户，无效清空），随后再挂载
const auth = useAuthStore()
auth.bootstrap().finally(() => app.mount('#app'))
