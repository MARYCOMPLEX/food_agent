import React from 'react'
import { Drawer, Tabs, Card, Typography, Space } from 'antd'
import { EvidenceTimeline } from '../../../../components/research-surface/EvidenceTimeline'
import { ControversyPanel } from '../../../../components/research-surface/ControversyPanel'
import type { RightPanelTab, AttachedContext } from '../../types'

interface MobileInspectorSheetProps {
  open: boolean
  onClose: () => void
  activeTab: RightPanelTab
  onChangeTab: (tab: RightPanelTab) => void
  evidenceItems: any[]
  recommendations: any[]
  controversies: any[]
  profiles: any[]
  selectedProfile: any
  onSetAttachedContext: (ctx: AttachedContext) => void
  onFocusTextarea: () => void
}

export function MobileInspectorSheet({
  open,
  onClose,
  activeTab,
  onChangeTab,
  evidenceItems,
  recommendations,
  controversies,
  profiles,
  selectedProfile,
  onSetAttachedContext,
  onFocusTextarea,
}: MobileInspectorSheetProps) {
  return (
    <Drawer
      open={open}
      onClose={onClose}
      placement="bottom"
      height="82vh"
      styles={{
        header: { padding: '10px 16px 6px', borderBottom: '1px solid #f0f0f0' },
        body: { padding: '10px 14px', overflowY: 'auto' },
        content: { borderRadius: '16px 16px 0 0', overflow: 'hidden' },
      }}
      title={
        <div style={{ width: '100%' }}>
          {/* Top handle bar */}
          <div
            style={{
              width: 36,
              height: 4,
              borderRadius: 2,
              backgroundColor: '#d9d9d9',
              margin: '0 auto 8px',
            }}
          />
          <Typography.Text strong style={{ fontSize: 15 }}>
            调研与事实核查检查器
          </Typography.Text>
        </div>
      }
    >
      <Tabs
        activeKey={activeTab}
        onChange={(key) => onChangeTab(key as RightPanelTab)}
        items={[
          {
            key: 'evidence',
            label: `评论证据 (${evidenceItems.length})`,
            children: (
              <EvidenceTimeline
                evidenceItems={evidenceItems}
                recommendations={recommendations}
              />
            ),
          },
          {
            key: 'controversies',
            label: `争议焦点 (${controversies.length})`,
            children: (
              <ControversyPanel
                controversies={controversies}
                evidenceItems={evidenceItems}
                onVerifyControversy={(c) => {
                  onSetAttachedContext({ type: 'controversy', title: c.topic })
                  onClose()
                  onFocusTextarea()
                }}
              />
            ),
          },
          {
            key: 'profile',
            label: '店铺档案',
            children: (
              <div>
                {(() => {
                  const p = selectedProfile || (profiles.length > 0 ? profiles[0] : null)
                  if (!p) {
                    return (
                      <div style={{ textAlign: 'center', padding: '36px 0', color: '#8c8c8c' }}>
                        点击推荐列表中的餐厅查看大众点评事实档案
                      </div>
                    )
                  }
                  return (
                    <Card title={p.name || '精选门店'} size="small" style={{ borderRadius: 10 }}>
                      <Space direction="vertical" size="small" style={{ width: '100%' }}>
                        <div>地址：{p.address || '暂无详细街道'}</div>
                        <div>营业时间：{p.openingHours || '暂未收录'}</div>
                        <div>人均消费：{p.averagePrice ? `￥${p.averagePrice}` : '暂无'}</div>
                        <div>综合评分：{p.rating ? `${p.rating} 分` : '暂无'}</div>
                      </Space>
                    </Card>
                  )
                })()}
              </div>
            ),
          },
        ]}
      />
    </Drawer>
  )
}
