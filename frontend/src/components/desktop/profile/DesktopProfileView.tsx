import { useState } from 'react'
import { Card, Typography, Collapse, Input, Button, Flex, Space, message } from 'antd'
import { InfoCircleOutlined, QuestionCircleOutlined, MessageOutlined } from '@ant-design/icons'

const { Title, Text, Paragraph } = Typography

const FAQ_ITEMS = [
  {
    key: '1',
    label: '食探是什么？',
    children: (
      <Text>
        食探是一款基于小红书笔记分析的美食推荐工具。我们通过交叉验证多篇笔记，
        帮你筛选出本地人真正爱去的餐厅，避开网红雷区。
      </Text>
    ),
  },
  {
    key: '2',
    label: '网红店评分是怎么计算的？',
    children: (
      <Text>
        我们综合分析笔记中的排队描述、拍照导向、服务评价、本地化提及等多个维度，
        通过 AI 模型对餐厅进行"网红度"评估，分为本地认证、可能本地、待验证、疑似网红、网红店五个等级。
      </Text>
    ),
  },
  {
    key: '3',
    label: '搜索结果的可信度代表什么？',
    children: (
      <Text>
        可信度反映了我们对该推荐的把握程度，综合考虑了数据来源数量、笔记一致性和交叉验证结果。
        可信度越高，推荐越靠谱。
      </Text>
    ),
  },
  {
    key: '4',
    label: '为什么有些餐厅没有地址信息？',
    children: (
      <Text>
        部分餐厅可能无法在 POI 数据库中精确匹配到，我们会持续完善数据覆盖。
        你可以尝试搜索更具体的关键词来提高匹配率。
      </Text>
    ),
  },
]

export function DesktopProfileView() {
  const [feedback, setFeedback] = useState('')

  const handleSubmit = () => {
    if (!feedback.trim()) return
    message.success('感谢你的反馈！')
    setFeedback('')
  }

  return (
    <div style={{ padding: 24, maxWidth: 720, margin: '0 auto' }}>
      {/* App info */}
      <Card style={{ textAlign: 'center', marginBottom: 24 }}>
        <div
          style={{
            width: 64, height: 64, borderRadius: 16,
            background: 'linear-gradient(135deg, #ff6b35, #f7c948)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            margin: '0 auto 16px', fontSize: 28, color: '#fff',
          }}
        >
          🍜
        </div>
        <Title level={3} style={{ margin: 0 }}>食探</Title>
        <Paragraph type="secondary" style={{ marginTop: 8 }}>
          发现本地人真正爱去的餐厅，远离网红雷区
        </Paragraph>
      </Card>

      {/* FAQ */}
      <Card
        title={<Space><QuestionCircleOutlined />常见问题</Space>}
        style={{ marginBottom: 24 }}
      >
        <Collapse ghost items={FAQ_ITEMS} />
      </Card>

      {/* Feedback */}
      <Card
        title={<Space><MessageOutlined />意见反馈</Space>}
        style={{ marginBottom: 24 }}
      >
        <Input.TextArea
          rows={4}
          placeholder="告诉我们你的想法或建议..."
          value={feedback}
          onChange={(e) => setFeedback(e.target.value)}
          style={{ marginBottom: 12 }}
        />
        <Flex justify="flex-end">
          <Button type="primary" onClick={handleSubmit} disabled={!feedback.trim()}>
            提交反馈
          </Button>
        </Flex>
      </Card>

      {/* Version */}
      <Text type="secondary" style={{ display: 'block', textAlign: 'center', fontSize: 12 }}>
        <InfoCircleOutlined style={{ marginRight: 4 }} />
        食探 v1.0.0
      </Text>
    </div>
  )
}
