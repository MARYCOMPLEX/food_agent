import React, { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Card, Table, Tag, Switch, Button, Space, Typography } from 'antd'
import {
  ArrowLeftOutlined,
  PlayCircleOutlined,
  ApiOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
} from '@ant-design/icons'
import { useToast } from '../../context/ToastContext'

interface ToolItem {
  toolName: string
  standardCapability: string
  description: string
  isReadOnly: boolean
  isAllowed: boolean
  callSuccessRate: string
  schemaFields: string[]
}

export function ServiceDetailPage() {
  const { serviceId } = useParams<{ serviceId: string }>()
  const navigate = useNavigate()
  const { showToast } = useToast()

  const [tools, setTools] = useState<ToolItem[]>([
    {
      toolName: 'xhs_search_notes',
      standardCapability: 'comment_collection.search_notes',
      description: '根据关键词与商圈检索小红书公开美食笔记，提取评论入口元数据',
      isReadOnly: true,
      isAllowed: true,
      callSuccessRate: '99.2%',
      schemaFields: ['keywords: string[]', 'city: string', 'limit: number'],
    },
    {
      toolName: 'xhs_fetch_comments',
      standardCapability: 'comment_collection.fetch_comments',
      description: '拉取指定笔记下的热门真实评论，按点赞与讨论深度过滤',
      isReadOnly: true,
      isAllowed: true,
      callSuccessRate: '98.7%',
      schemaFields: ['note_id: string', 'sort: "hot" | "latest"', 'max_depth: number'],
    },
    {
      toolName: 'dp_search_poi',
      standardCapability: 'shop_profile_enrichment.search_poi',
      description: '根据候选餐厅名称检索大众点评 POI 匹配项',
      isReadOnly: true,
      isAllowed: true,
      callSuccessRate: '94.5%',
      schemaFields: ['shop_name: string', 'city: string', 'district?: string'],
    },
    {
      toolName: 'dp_fetch_poi_detail',
      standardCapability: 'shop_profile_enrichment.fetch_detail',
      description: '拉取营业时间、人均价格带、精确地址、推荐菜列表',
      isReadOnly: true,
      isAllowed: true,
      callSuccessRate: '91.8%',
      schemaFields: ['poi_id: string'],
    },
    {
      toolName: 'dp_post_user_review',
      standardCapability: 'forbidden.write_action',
      description: '向大众点评写入用户评价（写操作）',
      isReadOnly: false,
      isAllowed: false,
      callSuccessRate: 'N/A',
      schemaFields: ['poi_id: string', 'content: string', 'rating: number'],
    },
  ])

  const toggleToolAllowed = (toolName: string) => {
    setTools(
      tools.map((t) => {
        if (t.toolName === toolName) {
          const next = !t.isAllowed
          showToast(`已${next ? '放行' : '禁用'}工具: ${toolName}`, 'info')
          return { ...t, isAllowed: next }
        }
        return t
      }),
    )
  }

  const handleTestInvoke = (toolName: string) => {
    showToast(`正在对 ${toolName} 进行沙箱测试调用...`, 'info')
    setTimeout(() => {
      showToast(`工具 ${toolName} 测试调用成功，输出符合 Schema 规范`, 'success')
    }, 1000)
  }

  const columns = [
    {
      title: '工具名称 / 标准映射',
      key: 'toolName',
      render: (_: any, record: ToolItem) => (
        <Space direction="vertical" size={2}>
          <Typography.Text code strong style={{ fontSize: 13 }}>
            {record.toolName}
          </Typography.Text>
          <Tag color="cyan" style={{ margin: 0, fontSize: 11 }}>
            {record.standardCapability}
          </Tag>
        </Space>
      ),
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      render: (val: string) => <span style={{ fontSize: 13 }}>{val}</span>,
    },
    {
      title: '读写属性',
      dataIndex: 'isReadOnly',
      key: 'isReadOnly',
      render: (isRead: boolean) =>
        isRead ? (
          <Tag color="blue">READ ONLY</Tag>
        ) : (
          <Tag color="error">SIDE EFFECT</Tag>
        ),
    },
    {
      title: '调用入参 Schema',
      dataIndex: 'schemaFields',
      key: 'schemaFields',
      render: (fields: string[]) => (
        <Space wrap size={[4, 4]}>
          {fields.map((f, i) => (
            <Typography.Text code key={i} style={{ fontSize: 11 }}>
              {f}
            </Typography.Text>
          ))}
        </Space>
      ),
    },
    {
      title: '成功率',
      dataIndex: 'callSuccessRate',
      key: 'callSuccessRate',
      render: (val: string) => <Typography.Text strong>{val}</Typography.Text>,
    },
    {
      title: '编排放行',
      key: 'isAllowed',
      render: (_: any, record: ToolItem) => (
        <Switch
          checked={record.isAllowed}
          checkedChildren="放行"
          unCheckedChildren="拦截"
          onChange={() => toggleToolAllowed(record.toolName)}
        />
      ),
    },
    {
      title: '沙箱调用',
      key: 'action',
      render: (_: any, record: ToolItem) => (
        <Button
          size="small"
          icon={<PlayCircleOutlined />}
          disabled={!record.isAllowed}
          onClick={() => handleTestInvoke(record.toolName)}
        >
          测试调用
        </Button>
      ),
    },
  ]

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <Space align="center" size={12}>
        <Button
          icon={<ArrowLeftOutlined />}
          onClick={() => navigate('/ops/services')}
        >
          返回服务目录
        </Button>
        <div>
          <Typography.Title level={4} style={{ margin: 0 }}>
            <ApiOutlined style={{ color: '#1677ff', marginRight: 8 }} />
            服务详情：{serviceId}
          </Typography.Title>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            标准能力映射、工具 Schema 检查及放行策略管理
          </Typography.Text>
        </div>
      </Space>

      <Card
        title={<span>暴露的 MCP 工具清单 ({tools.length})</span>}
        extra={<Typography.Text type="secondary">仅放行工具允许被 Agent 内部规划编排</Typography.Text>}
      >
        <Table
          dataSource={tools}
          columns={columns}
          rowKey="toolName"
          pagination={false}
          size="middle"
        />
      </Card>
    </Space>
  )
}
