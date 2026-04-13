import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  UtensilsCrossed, ChevronDown, Send,
  CheckCircle2, HelpCircle, MessageSquare,
} from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { MobilePage } from '@/components/mobile/MobilePage'

const FAQ_ITEMS = [
  { q: '数据来自哪里？', a: '所有推荐基于真实小红书笔记分析，经过交叉验证和网红店过滤，确保推荐质量。' },
  { q: '怎么判断是不是网红店？', a: '通过分析笔记的商业合作痕迹、评论真实度、多源一致性等维度综合评估。' },
  { q: '支持哪些城市？', a: '目前支持全国主要城市，搜索时会自动识别你提到的城市。' },
  { q: '搜索结果不准确怎么办？', a: '可以尝试更具体的描述，比如加上地点、菜系、口味偏好等关键词。' },
]

function FAQItem({ q, a }: { q: string; a: string }) {
  const [open, setOpen] = useState(false)
  return (
    <button
      className="w-full text-left border-b border-border last:border-0 py-3"
      onClick={() => setOpen(!open)}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium text-foreground">{q}</span>
        <ChevronDown
          size={15}
          className={`shrink-0 text-muted-foreground transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </div>
      <AnimatePresence>
        {open && (
          <motion.p
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="text-xs text-muted-foreground leading-relaxed mt-2 overflow-hidden"
          >
            {a}
          </motion.p>
        )}
      </AnimatePresence>
    </button>
  )
}

export function MobileProfileView() {
  const [feedback, setFeedback] = useState('')
  const [submitted, setSubmitted] = useState(false)

  const handleSubmit = () => {
    if (!feedback.trim()) return
    setSubmitted(true)
    setFeedback('')
    setTimeout(() => setSubmitted(false), 3000)
  }

  return (
    <MobilePage subtitle="食探 Food Agent">
      <div className="px-4 pb-6 space-y-4">
        <Card>
          <CardContent className="p-5 flex items-center gap-4">
            <div className="w-12 h-12 rounded-xl bg-primary/10 flex items-center justify-center shrink-0">
              <UtensilsCrossed size={22} className="text-primary" />
            </div>
            <div className="min-w-0">
              <h2 className="text-base font-display font-semibold text-foreground">食探</h2>
              <p className="text-xs text-muted-foreground mt-0.5">基于小红书笔记的智能美食推荐</p>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="px-4 py-3.5">
            <div className="flex items-center gap-2 mb-1">
              <HelpCircle size={14} className="text-muted-foreground" />
              <h3 className="text-sm font-semibold text-foreground">常见问题</h3>
            </div>
            <div>
              {FAQ_ITEMS.map((item) => (
                <FAQItem key={item.q} q={item.q} a={item.a} />
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-2 mb-3">
              <MessageSquare size={14} className="text-muted-foreground" />
              <h3 className="text-sm font-semibold text-foreground">意见反馈</h3>
            </div>
            <textarea
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              placeholder="告诉我们你的想法或建议..."
              rows={3}
              className="w-full rounded-lg border border-border bg-transparent px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 outline-none focus:ring-2 focus:ring-ring focus:ring-offset-1 resize-none"
            />
            <div className="flex justify-end mt-2">
              {submitted ? (
                <motion.div
                  initial={{ opacity: 0, scale: 0.9 }}
                  animate={{ opacity: 1, scale: 1 }}
                  className="flex items-center gap-1.5 text-xs text-emerald-600"
                >
                  <CheckCircle2 size={14} />
                  感谢反馈
                </motion.div>
              ) : (
                <Button size="sm" onClick={handleSubmit} disabled={!feedback.trim()} className="gap-1.5">
                  <Send size={14} />
                  提交
                </Button>
              )}
            </div>
          </CardContent>
        </Card>

        <p className="text-center text-[10px] text-muted-foreground/50 pt-2">
          v1.0 · XHS Food Agent
        </p>
      </div>
    </MobilePage>
  )
}
