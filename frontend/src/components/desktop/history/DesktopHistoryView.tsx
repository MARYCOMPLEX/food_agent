import { useEffect } from 'react'
import { Table, Typography, Tag, Button, Popconfirm, Flex, Space } from 'antd'
import { DeleteOutlined, SearchOutlined, ExclamationCircleOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useHistoryStore } from '@/stores/historyStore'
import { useSearchStore } from '@/stores/searchStore'
import { formatDate } from '@/utils/format'
import type { HistoryItem } from '@/types/user'

const { Title } = Typography

export function DesktopHistoryView() {
  const navigate = useNavigate()
  const { items, loading, fetchHistory, deleteItem, clearAll } = useHistoryStore()
  const search = useSearchStore((s) => s.search)

  useEffect(() => {
    fetchHistory()
  }, [fetchHistory])

  const handleReSearch = (query: string) => {
    search(query)
    navigate('/')
  }

  const columns = [
    {
      title: '搜索内容',
      dataIndex: 'query',
      key: 'query',
      ellipsis: true,
    },
    {
      title: '结果数',
      dataIndex: 'resultsCount',
      key: 'resultsCount',
      width: 90,
      render: (count: number) => (
        <Tag color={count > 0 ? 'blue' : 'default'}>{count} 家</Tag>
      ),
    },
    {
      title: '时间',
      dataIndex: 'createdAt',
      key: 'createdAt',
      width: 130,
      render: (date: string) => formatDate(date),
    },
    {
      title: '操作',
      key: 'actions',
      width: 160,
      render: (_: unknown, record: HistoryItem) => (
        <Space>
          <Button
            type="link"
            size="small"
            icon={<SearchOutlined />}
            onClick={() => handleReSearch(record.query)}
          >
            重新搜索
          </Button>
          <Popconfirm
            title="确定删除这条记录？"
            icon={<ExclamationCircleOutlined style={{ color: '#ff4d4f' }} />}
            onConfirm={() => deleteItem(record.id)}
            okText="删除"
            cancelText="取消"
          >
            <Button type="link" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ padding: 24, maxWidth: 960, margin: '0 auto' }}>
      <Flex justify="space-between" align="center" style={{ marginBottom: 24 }}>
        <Title level={3} style={{ margin: 0 }}>搜索历史</Title>
        {items.length > 0 && (
          <Popconfirm
            title="确定清空所有历史记录？"
            icon={<ExclamationCircleOutlined style={{ color: '#ff4d4f' }} />}
            onConfirm={clearAll}
            okText="清空"
            cancelText="取消"
          >
            <Button danger size="small">清空全部</Button>
          </Popconfirm>
        )}
      </Flex>

      <Table
        dataSource={items}
        columns={columns}
        rowKey="id"
        loading={loading}
        pagination={{ pageSize: 15, showSizeChanger: false }}
        locale={{ emptyText: '暂无搜索历史' }}
      />
    </div>
  )
}
