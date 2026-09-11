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

  const [tasks] = useState<ObservabilityTaskItem[]>([
    {
      taskId: 'task_cd_hotpot_001',
      sessionId: 'session_demo_cd_hotpot',
      query: '周六晚在成都玉林，三个人想吃串串，人均 100 以内...',
      type: 'research',
      status: 'succeeded',
      turnCount: 2,
      durationMs: 4200,
      retryCount: 0,
      evidenceCount: 18,
      profileCount: 4,
      gapCount: 0,
      createdAt: '2026-09-11 01:12:30',
      timeline: [
        { time: '01:12:30', action: 'intent_parsed', status: 'done', detail: '识别地点: 成都玉林, 预算: 100, 排除: 纯网红' },
        { time: '01:12:31', action: 'comment_collection.search_notes', status: 'done', detail: '抓取 12 篇笔记元数据' },
        { time: '01:12:32', action: 'comment_collection.fetch_comments', status: 'done', detail: '抓取 84 条评论并清洗' },
        { time: '01:12:33', action: 'shop_profile_enrichment.search_poi', status: 'done', detail: '大众点评完成 4 家门店 POI 绑定' },
        { time: '01:12:34', action: 'recommendation_synthesized', status: 'done', detail: '输出综合研判报告' },
      ],
    },
    {
      taskId: 'task_gz_morningtea_002',
      sessionId: 'session_demo_gz_morningtea',
      query: '广州越秀或荔湾区，两个人周末上午喝早茶，人均 80 左右...',
      type: 'research',
      status: 'partial',
      turnCount: 1,
      durationMs: 3800,
      retryCount: 1,
      evidenceCount: 12,
      profileCount: 3,
      gapCount: 1,
      createdAt: '2026-09-11 01:05:10',
      timeline: [
        { time: '01:05:10', action: 'intent_parsed', status: 'done', detail: '识别地点: 广州越秀/荔湾, 预算: 80' },
        { time: '01:05:11', action: 'comment_collection.fetch_comments', status: 'done', detail: '抓取 46 条小红书早茶真实口碑' },
        { time: '01:05:12', action: 'shop_profile_enrichment.fetch_detail', status: 'partial', detail: '大众点评要求滑块验证，保留评论候选' },
      ],
    },
    {
      taskId: 'task_sh_dating_003',
      sessionId: 'session_demo_sh_dating',
      query: '上海静安寺附近，两人约会，人均 180 左右...',
      type: 'research',
      status: 'running',
      turnCount: 1,
      durationMs: 1200,
      retryCount: 0,
      evidenceCount: 6,
      profileCount: 1,
      gapCount: 0,
      createdAt: '2026-09-11 01:28:40',
      timeline: [
        { time: '01:28:40', action: 'intent_parsed', status: 'done', detail: '识别地点: 上海静安寺' },
        { time: '01:28:41', action: 'comment_collection.search_notes', status: 'running', detail: '正在搜索小酒馆/意面笔记' },
      ],
    },
  ])

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
