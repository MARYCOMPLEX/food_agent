import { type RouteRecordRaw, createRouter, createWebHistory } from 'vue-router'
import UserShell from './UserShell.vue'
import OpsShell from './OpsShell.vue'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/app/explore',
  },
  {
    path: '/app',
    component: UserShell,
    children: [
      {
        path: '',
        redirect: '/app/explore',
      },
      {
        path: 'explore',
        name: 'Explore',
        component: () => import('../features/research/ExploreView.vue'),
        meta: { title: '美食探索' },
      },
      {
        path: 'sessions/:sessionId',
        name: 'ResearchSession',
        component: () => import('../features/research-session/SessionView.vue'),
        meta: { title: '研判会话' },
      },
      {
        path: 'favorites',
        name: 'Favorites',
        component: () => import('../features/favorites/FavoritesView.vue'),
        meta: { title: '我的收藏' },
      },
      {
        path: 'history',
        name: 'History',
        component: () => import('../features/history/HistoryView.vue'),
        meta: { title: '搜索历史' },
      },
      {
        path: 'accounts',
        name: 'Accounts',
        component: () => import('../features/platform-accounts/AccountsView.vue'),
        meta: { title: '平台账号' },
      },
      {
        path: 'me',
        name: 'Profile',
        component: () => import('../features/profile/ProfileView.vue'),
        meta: { title: '个人中心' },
      },
    ],
  },
  {
    path: '/ops',
    component: OpsShell,
    children: [
      {
        path: '',
        name: 'OpsOverview',
        component: () => import('../features/ops-overview/OpsOverviewView.vue'),
        meta: { title: '系统总览' },
      },
      {
        path: 'services',
        name: 'ServiceCatalog',
        component: () => import('../features/service-catalog/ServiceCatalogView.vue'),
        meta: { title: '服务接入' },
      },
      {
        path: 'services/:serviceId',
        name: 'ServiceDetail',
        component: () => import('../features/service-detail/ServiceDetailView.vue'),
        meta: { title: '服务详情' },
      },
      {
        path: 'tasks',
        name: 'TaskObservability',
        component: () => import('../features/task-observability/TaskObservabilityView.vue'),
        meta: { title: '任务观测' },
      },
      {
        path: 'evidence',
        name: 'EvidenceObservability',
        component: () => import('../features/evidence-observability/EvidenceObservabilityView.vue'),
        meta: { title: '证据观测' },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/app/explore',
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior() {
    return { top: 0 }
  },
})
