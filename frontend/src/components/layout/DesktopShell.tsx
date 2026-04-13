import { type ReactNode } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { Layout, Menu, ConfigProvider } from 'antd'
import { SearchOutlined, HeartOutlined, HistoryOutlined, InfoCircleOutlined } from '@ant-design/icons'

const { Sider, Content } = Layout

const menuItems = [
  { key: '/', icon: <SearchOutlined />, label: '探索' },
  { key: '/favorites', icon: <HeartOutlined />, label: '收藏' },
  { key: '/history', icon: <HistoryOutlined />, label: '历史' },
  { key: '/profile', icon: <InfoCircleOutlined />, label: '关于' },
]

const theme = {
  token: {
    colorPrimary: '#c2410c',
    borderRadius: 10,
    fontFamily: '"DM Sans", "Noto Sans SC", "PingFang SC", sans-serif',
    colorBgContainer: '#ffffff',
    colorBgLayout: '#faf9f7',
    colorBorder: '#e7e5e4',
    colorText: '#18181b',
    colorTextSecondary: '#78716c',
  },
  components: {
    Menu: { itemBg: 'transparent', itemSelectedBg: '#f5f3f0', itemSelectedColor: '#c2410c' },
    Table: { headerBg: '#faf9f7', rowHoverBg: '#faf9f7' },
  },
}

export function DesktopShell({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
  const location = useLocation()

  return (
    <ConfigProvider theme={theme}>
      <Layout style={{ minHeight: '100vh' }}>
        <Sider
          width={200}
          theme="light"
          style={{ borderRight: '1px solid #e7e5e4', background: '#faf9f7' }}
        >
          <div style={{ padding: '20px 16px 24px', fontWeight: 700, fontSize: 18, color: '#c2410c', fontFamily: '"Playfair Display", serif' }}>
            食探
          </div>
          <Menu
            mode="inline"
            selectedKeys={[location.pathname]}
            items={menuItems}
            onClick={({ key }) => navigate(key)}
            style={{ border: 'none', background: 'transparent' }}
          />
        </Sider>
        <Content style={{ padding: 24, background: '#faf9f7', overflow: 'auto' }}>
          <div style={{ maxWidth: 960, margin: '0 auto' }}>{children}</div>
        </Content>
      </Layout>
    </ConfigProvider>
  )
}
