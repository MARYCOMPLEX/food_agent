import React, { useState } from 'react'
import { Card, Table, Input, Tag, Button, Modal, Timeline, Space, Typography } from 'antd'
import {
  HistoryOutlined,
  SearchOutlined,
  CheckCircleOutlined,
  WarningOutlined,
  LoadingOutlined,
  RedoOutlined,
  StopOutlined,
  EyeOutlined,
} from '@ant-design/icons'
import { useToast } from '../../context/ToastContext'

interface ObservabilityTaskItem {
  taskId: string
  sessionId: string
  query: string
  type: string
  status: 'running' | 'succeeded' | 'partial' | 'failed'
  turnCount: number
  durationMs: number
  retryCount: number
  evidenceCount: number
  profileCount: number
  gapCount: number
  createdAt: string
  timeline: Array<{ time: string; action: string; status: string; detail?: string }>
}

export function TaskObservabilityPage() {
  const { showToast } = useToast()
  const [searchQuery, setSearchQuery] = useState<string>('')
  const [selectedTask, setSelectedTask] = useState<ObservabilityTaskItem | null>(null)

  const [tasks] = useState<ObservabilityTaskItem[]>([])

  const filteredTasks = tasks.filter(
    (t) =>
      t.taskId.toLowerCase().includes(searchQuery.toLowerCase()) ||
      t.query.toLowerCase().includes(searchQuery.toLowerCase()),
  )

  const handleRetryTask = (task: ObservabilityTaskItem) => {
    showToast(`已向调度器发送任务重试请求: ${task.taskId}`, 'info')
  }

  const handleCancelTask = (task: ObservabilityTaskItem) => {
    showToast(`已终止任务: ${task.taskId}`, 'warning')
  }

  const columns = [
    {
      title: 'Task ID / 创建时间',
      key: 'taskId',
      render: (_: any, record: ObservabilityTaskItem) => (
        <Space direction="vertical" size={1}>
          <Typography.Text code strong style={{ fontSize: 13 }}>
            {record.taskId}
          </Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 11 }}>
            {record.createdAt}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: '需求 Query 摘要',
      key: 'query',
      render: (_: any, record: ObservabilityTaskItem) => (
        <Space direction="vertical" size={1} style={{ maxWidth: 280 }}>
          <Typography.Text ellipsis style={{ fontSize: 13 }}>
            {record.query}
          </Typography.Text>
          <Typography.Text type="secondary" code style={{ fontSize: 10 }}>
            {record.sessionId}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: '执行状态',
      dataIndex: 'status',
      key: 'status',
      render: (status: string) => {
        if (status === 'succeeded') {
          return <Tag icon={<CheckCircleOutlined />} color="success">SUCCEEDED</Tag>
        }
        if (status === 'running') {
          return <Tag icon={<LoadingOutlined />} color="processing">RUNNING</Tag>
        }
        if (status === 'partial') {
          return <Tag icon={<WarningOutlined />} color="warning">PARTIAL</Tag>
        }
        return <Tag color="error">FAILED</Tag>
      },
    },
    {
      title: '耗时',
      dataIndex: 'durationMs',
      key: 'durationMs',
      render: (ms: number) => <Typography.Text code>{ms}ms</Typography.Text>,
    },
    {
      title: '产出指标',
      key: 'outputs',
      render: (_: any, record: ObservabilityTaskItem) => (
        <Space direction="vertical" size={2}>
          <span style={{ fontSize: 12 }}>
            {record.evidenceCount} 证据 / {record.profileCount} 档案
          </span>
          {record.gapCount > 0 && <Tag color="warning">{record.gapCount} 个缺口</Tag>}
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      render: (_: any, record: ObservabilityTaskItem) => (
        <Button
          size="small"
          icon={<EyeOutlined />}
          onClick={() => setSelectedTask(record)}
        >
          查看时间线
        </Button>
      ),
    },
  ]

  return (
    <Space direction="vertical" size="large" style={{ width: '100%' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <Typography.Title level={4} style={{ margin: 0 }}>
            <HistoryOutlined style={{ color: '#1677ff', marginRight: 8 }} />
            任务执行观测台
          </Typography.Title>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            全量调查任务链路流转、Temporal 状态、耗时与错误排查
          </Typography.Text>
        </div>

        <Input
          placeholder="搜索 Task ID 或 Query..."
          prefix={<SearchOutlined />}
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          style={{ width: 260 }}
          allowClear
        />
      </div>

      <Card>
        <Table
          dataSource={filteredTasks}
          columns={columns}
          rowKey="taskId"
          pagination={{ pageSize: 10 }}
          size="middle"
        />
      </Card>

      {/* Task Detail Modal */}
      <Modal
        open={!!selectedTask}
        onCancel={() => setSelectedTask(null)}
        title={
          selectedTask && (
            <Space>
              <HistoryOutlined style={{ color: '#1677ff' }} />
              <span>任务执行生命周期：{selectedTask.taskId}</span>
            </Space>
          )
        }
        footer={[
          <Button key="retry" icon={<RedoOutlined />} onClick={() => selectedTask && handleRetryTask(selectedTask)}>
            重新触发
          </Button>,
          selectedTask?.status === 'running' && (
            <Button key="cancel" danger icon={<StopOutlined />} onClick={() => handleCancelTask(selectedTask)}>
              终止任务
            </Button>
          ),
          <Button key="close" type="primary" onClick={() => setSelectedTask(null)}>
            关闭
          </Button>,
        ]}
        width={600}
      >
        {selectedTask && (
          <Space direction="vertical" size="middle" style={{ width: '100%', marginTop: 12 }}>
            <Card size="small" style={{ background: '#fafafa' }}>
              <Typography.Paragraph ellipsis={{ rows: 2 }} style={{ marginBottom: 0 }}>
                <strong>需求 Query：</strong>{selectedTask.query}
              </Typography.Paragraph>
            </Card>

            <Typography.Text strong style={{ fontSize: 13 }}>
              动作执行生命周期时间线
            </Typography.Text>

            <Timeline
              style={{ marginTop: 8 }}
              items={selectedTask.timeline.map((step) => ({
                color: step.status === 'done' ? 'green' : step.status === 'running' ? 'blue' : 'gray',
                dot: step.status === 'running' ? <LoadingOutlined /> : undefined,
                children: (
                  <Space direction="vertical" size={2}>
                    <Space size={8}>
                      <Typography.Text code style={{ fontSize: 11 }}>{step.time}</Typography.Text>
                      <Typography.Text strong>{step.action}</Typography.Text>
                      <Tag color={step.status === 'done' ? 'success' : 'processing'}>
                        {step.status}
                      </Tag>
                    </Space>
                    {step.detail && (
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        {step.detail}
                      </Typography.Text>
                    )}
                  </Space>
                ),
              }))}
            />
          </Space>
        )}
      </Modal>
    </Space>
  )
}
