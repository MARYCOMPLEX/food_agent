import { useState } from 'react'
import { motion } from 'framer-motion'
import { submitFeedback } from '../api/userApi'

const FAQS = [
  { q: '食探是什么？', a: '食探通过分析小红书评论，帮你发现本地人真正推荐的地道餐厅，过滤网红打卡店。' },
  { q: '推荐结果可靠吗？', a: '我们使用三角验证法：至少2篇笔记提及、本地人正面评价、无严重差评，确保推荐质量。' },
  { q: '支持哪些城市？', a: '理论上支持所有有小红书美食笔记的城市。热门城市（成都、重庆、广州等）效果最佳。' },
  { q: '什么是"网红店"标记？', a: '我们通过评论分析判断店铺是本地人常去的老店还是游客打卡的网红店，帮你避坑。' },
]

export function ProfilePage() {
  const [feedbackText, setFeedbackText] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const [openFaq, setOpenFaq] = useState<number | null>(null)

  const handleFeedback = async () => {
    if (!feedbackText.trim()) return
    try {
      await submitFeedback('other', feedbackText)
      setSubmitted(true)
      setFeedbackText('')
      setTimeout(() => setSubmitted(false), 3000)
    } catch { /* ignore */ }
  }

  return (
    <div className="px-4 py-4 space-y-6">
      {/* Profile header */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className="bg-white rounded-2xl border border-border p-5 text-center"
      >
        <div className="w-16 h-16 rounded-full bg-cream-dark flex items-center justify-center mx-auto mb-3 text-3xl">
          🥘
        </div>
        <h2 className="font-display text-lg font-bold text-ink">
          <span className="text-ember">食</span>探用户
        </h2>
        <p className="text-xs text-muted mt-1">发现本地人才知道的地道美食</p>
      </motion.div>

      {/* FAQ */}
      <div>
        <h3 className="font-display text-sm font-semibold text-ink mb-3">常见问题</h3>
        <div className="space-y-2">
          {FAQS.map((faq, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.05 }}
              className="bg-white rounded-xl border border-border overflow-hidden"
            >
              <button
                onClick={() => setOpenFaq(openFaq === i ? null : i)}
                className="w-full flex items-center justify-between px-4 py-3 text-left"
              >
                <span className="text-sm font-medium text-ink">{faq.q}</span>
                <span className="text-muted text-xs">{openFaq === i ? '−' : '+'}</span>
              </button>
              {openFaq === i && (
                <motion.div
                  initial={{ height: 0 }}
                  animate={{ height: 'auto' }}
                  className="px-4 pb-3"
                >
                  <p className="text-xs text-muted leading-relaxed">{faq.a}</p>
                </motion.div>
              )}
            </motion.div>
          ))}
        </div>
      </div>

      {/* Feedback */}
      <div>
        <h3 className="font-display text-sm font-semibold text-ink mb-3">意见反馈</h3>
        <div className="bg-white rounded-xl border border-border p-4">
          <textarea
            value={feedbackText}
            onChange={(e) => setFeedbackText(e.target.value)}
            placeholder="告诉我们你的想法或建议..."
            rows={3}
            className="w-full text-sm text-ink bg-transparent outline-none resize-none placeholder:text-muted/50"
          />
          <div className="flex justify-between items-center mt-2">
            {submitted && (
              <span className="text-xs text-emerald-600">感谢你的反馈！</span>
            )}
            <button
              onClick={handleFeedback}
              disabled={!feedbackText.trim()}
              className="ml-auto px-4 py-1.5 text-xs font-medium bg-ember text-white rounded-full hover:bg-ember-light disabled:bg-stone-200 disabled:cursor-not-allowed transition-colors"
            >
              提交
            </button>
          </div>
        </div>
      </div>

      {/* Version info */}
      <p className="text-center text-[10px] text-muted/50 py-4">
        食探 v1.0 · 小红书美食智能推荐
      </p>
    </div>
  )
}
