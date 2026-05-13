import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  UtensilsCrossed,
  ChevronDown,
  Send,
  CheckCircle2,
  HelpCircle,
  MessageSquare,
} from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Separator } from '@/components/ui/separator'
import { MobilePage } from '@/components/mobile/MobilePage'
import { cn } from '@/lib/utils'

interface FaqItem {
  q: string
  a: string
}

const FEEDBACK_MAX_LENGTH = 500

const FAQ_ITEMS: readonly FaqItem[] = [
  { q: '数据来自哪里？', a: '所有推荐基于真实小红书笔记分析，经过交叉验证和网红店过滤，确保推荐质量。' },
  { q: '怎么判断是不是网红店？', a: '通过分析笔记的商业合作痕迹、评论真实度、多源一致性等维度综合评估。' },
  { q: '支持哪些城市？', a: '目前支持全国主要城市，搜索时会自动识别你提到的城市。' },
  { q: '搜索结果不准确怎么办？', a: '可以尝试更具体的描述，比如加上地点、菜系、口味偏好等关键词。' },
]

interface FAQItemProps {
  q: string
  a: string
}

function FAQItem({ q, a }: FAQItemProps) {
  const [open, setOpen] = useState(false)
  return (
    <button
      type="button"
      className={cn(
        'w-full text-left py-3 pl-3 -ml-3 transition-all',
        open && 'border-l-2 border-brand',
      )}
      onClick={() => setOpen(!open)}
      aria-expanded={open}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium text-foreground">{q}</span>
        <ChevronDown
          className={cn(
            'size-4 shrink-0 text-muted-foreground transition-transform',
            open && 'rotate-180',
          )}
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

export function ProfileView() {
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
      <div className="px-4 md:px-6 pb-6 space-y-4 max-w-2xl mx-auto w-full">
        <Card className="bg-gradient-to-br from-orange-50 to-amber-50">
          <CardContent className="p-5 flex items-center gap-4">
            <Avatar className="size-12 rounded-xl">
              <AvatarFallback className="rounded-xl bg-primary/10 text-primary">
                <UtensilsCrossed className="size-5" />
              </AvatarFallback>
            </Avatar>
            <div className="min-w-0">
              <h2 className="text-base md:text-lg font-display font-semibold text-foreground">
                食探
              </h2>
              <p className="text-xs md:text-sm text-muted-foreground mt-0.5">
                基于小红书笔记的智能美食推荐
              </p>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="px-4 py-3.5">
            <div className="flex items-center gap-2 mb-1">
              <HelpCircle className="size-3.5 text-muted-foreground" />
              <h3 className="text-sm font-semibold text-foreground">常见问题</h3>
            </div>
            <div className="divide-y divide-border">
              {FAQ_ITEMS.map((item) => (
                <FAQItem key={item.q} q={item.q} a={item.a} />
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-4">
            <div className="flex items-center gap-2 mb-3">
              <MessageSquare className="size-3.5 text-muted-foreground" />
              <h3 className="text-sm font-semibold text-foreground">意见反馈</h3>
            </div>
            <Textarea
              value={feedback}
              onChange={(e) => {
                if (e.target.value.length <= FEEDBACK_MAX_LENGTH) {
                  setFeedback(e.target.value)
                }
              }}
              placeholder="告诉我们你的想法或建议..."
              rows={3}
              maxLength={FEEDBACK_MAX_LENGTH}
              className="resize-none text-sm"
            />
            <p className="text-right text-[11px] text-muted-foreground mt-1">
              {feedback.length}/{FEEDBACK_MAX_LENGTH}
            </p>
            <Separator className="my-3" />
            <div className="flex justify-end">
              {submitted ? (
                <motion.div
                  initial={{ opacity: 0, scale: 0.9 }}
                  animate={{ opacity: 1, scale: 1 }}
                  className="flex items-center gap-1.5 text-xs text-emerald-600"
                >
                  <CheckCircle2 className="size-3.5" />
                  感谢反馈
                </motion.div>
              ) : (
                <Button
                  size="sm"
                  onClick={handleSubmit}
                  disabled={!feedback.trim()}
                  className="gap-1.5"
                >
                  <Send className="size-3.5" />
                  提交
                </Button>
              )}
            </div>
          </CardContent>
        </Card>

        <p className="text-center text-[10px] text-muted-foreground/50 pt-2">
          v1.0 · Made with ❤️ by 食探团队
        </p>
      </div>
    </MobilePage>
  )
}
