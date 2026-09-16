import React, { useState } from 'react'
import { Typography, Card, Space, Flex } from 'antd'
import { RobotOutlined } from '@ant-design/icons'
import { MobileHeader } from './components/MobileHeader'
import { MobileSessionDrawer } from './components/MobileSessionDrawer'
import { MobileMessageBubble } from './components/MobileMessageBubble'
import { MobileInputBar } from './components/MobileInputBar'
import { MobileInspectorSheet } from './components/MobileInspectorSheet'
import { ShopProfileDrawer } from '../../../components/research-surface/ShopProfileDrawer'
import { RestaurantComparisonModal } from '../../../components/restaurant/RestaurantComparisonModal'
import { QrLoginModal } from '../../../components/auth/QrLoginModal'
import { platformAccountsApi } from '../../../features/platform-accounts/api/platformAccountsApi'
import type { SharedWorkbenchProps, RightPanelTab } from '../types'

export function MobileWorkbench(props: SharedWorkbenchProps) {
  const {
    currentSessionId,
    sessionTurns,
    isRunning,
    isNewSession,
    inputText,
    setInputText,
    attachedContext,
    setAttachedContext,
    handleSendMessage,
    handleStopInvestigation,
    handleStartNewChat,
    handleRetryLastTurn,
    historyList,
    handleSelectSession,
    handleDeleteSession,
    selectedModel,
    setSelectedModel,
    modelOptions,
    mcpServices,
    compareList,
    setCompareList,
    favorites,
    isCompareModalOpen,
    setIsCompareModalOpen,
    handleAddToCompare,
    handleToggleFavorite,
    accounts,
    setAccounts,
    loginModalPlatform,
    setLoginModalPlatform,
    rightPanelOpen,
    setRightPanelOpen,
    rightPanelTab,
    setRightPanelTab,
    openInspector,
    selectedProfile,
    selectedRec,
    isProfileDrawerOpen,
    setIsProfileDrawerOpen,
    openStandaloneProfile,
    feedbackRating,
    setFeedbackRating,
    hasCopied,
    handleCopyResponse,
    suggestions,
    recommendations,
    evidenceItems,
    controversies,
    profiles,
    chatBottomRef,
    textareaRef,
  } = props

  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false)

  return (
    <div
      style={{
        height: '100dvh',
        width: '100vw',
        display: 'flex',
        flexDirection: 'column',
        backgroundColor: '#f8f9fa',
        overflow: 'hidden',
      }}
    >
      {/* 1. Mobile Top App Bar */}
      <MobileHeader
        selectedModel={selectedModel}
        setSelectedModel={setSelectedModel}
        modelOptions={modelOptions}
        compareCount={compareList.length}
        evidenceCount={evidenceItems.length}
        onOpenSidebar={() => setMobileDrawerOpen(true)}
        onStartNewChat={handleStartNewChat}
        onOpenCompare={() => setIsCompareModalOpen(true)}
        onOpenInspector={() => openInspector('evidence')}
      />

      {/* 2. Scrollable Message Container */}
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '12px 12px 24px',
          display: 'flex',
          flexDirection: 'column',
          WebkitOverflowScrolling: 'touch',
        }}
      >
        {isNewSession ? (
          /* Mobile Empty State */
          <div
            style={{
              flex: 1,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              padding: '24px 8px 12px',
            }}
          >
            <div
              style={{
                width: 48,
                height: 48,
                borderRadius: '50%',
                backgroundColor: '#e6f4ff',
                color: '#1677ff',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 24,
                marginBottom: 12,
              }}
            >
              <RobotOutlined />
            </div>

            <Typography.Title level={4} style={{ marginBottom: 6, textAlign: 'center', fontWeight: 600 }}>
              真实口碑探店向导
            </Typography.Title>
            <Typography.Text
              type="secondary"
              style={{ fontSize: 13, textAlign: 'center', marginBottom: 24, maxWidth: 320, lineHeight: 1.5 }}
            >
              深挖小红书与大众点评真实就餐评价，深度排查水军营销与排队陷阱。
            </Typography.Text>

            {/* Quick Prompt Cards */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, width: '100%', maxWidth: 380 }}>
              {[
                {
                  icon: '🍲',
                  title: '成都火锅避坑推荐',
                  desc: '玉林附近，本地人常吃，人均100左右',
                  prompt: '成都玉林，本地人常去的老火锅，人均100，排队别太久，不要太甜太咸',
                },
                {
                  icon: '☕',
                  title: '广州地道老字号早茶',
                  desc: '越秀或荔湾区，人均80以内正宗早茶',
                  prompt: '广州越秀或荔湾区正宗早茶，两人人均80，虾饺要扎实',
                },
                {
                  icon: '🥩',
                  title: '上海静安商务宴请',
                  desc: '静安寺附近本帮菜，包厢安静不踩雷',
                  prompt: '上海静安寺附近，适合商务宴请的本帮菜餐厅，环境安静不踩雷',
                },
                {
                  icon: '🍢',
                  title: '西安回民街地道小吃',
                  desc: '避开主街游客陷阱，本地人认可老店',
                  prompt: '西安大皮院附近的本地回民街小吃，避开主街游客店，寻找本地人认可的老店',
                },
              ].map((card, idx) => (
                <Card
                  key={idx}
                  size="small"
                  hoverable
                  onClick={() => handleSendMessage(card.prompt)}
                  style={{
                    borderRadius: 12,
                    borderColor: '#ededed',
                    cursor: 'pointer',
                    boxShadow: '0 1px 4px rgba(0,0,0,0.02)',
                  }}
                  styles={{ body: { padding: '10px 12px' } }}
                >
                  <Space align="start" size={10}>
                    <span style={{ fontSize: 22 }}>{card.icon}</span>
                    <div>
                      <Typography.Text strong style={{ fontSize: 13, display: 'block' }}>
                        {card.title}
                      </Typography.Text>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        {card.desc}
                      </Typography.Text>
                    </div>
                  </Space>
                </Card>
              ))}
            </div>
          </div>
        ) : (
          /* Multi-turn Dialogue Stream */
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {sessionTurns.map((turn, turnIdx) => {
              const isLatest = turnIdx === sessionTurns.length - 1

              return (
                <MobileMessageBubble
                  key={turn.id}
                  turn={turn}
                  isLatest={isLatest}
                  isRunning={isRunning}
                  favorites={favorites}
                  onToggleFavorite={handleToggleFavorite}
                  onOpenProfile={openStandaloneProfile}
                  onAddToCompare={handleAddToCompare}
                  onFollowUpShop={(title) => {
                    setAttachedContext({ type: 'shop', title })
                    textareaRef.current?.focus()
                  }}
                  onOpenInspector={(tab) => openInspector(tab)}
                  feedbackRating={feedbackRating}
                  setFeedbackRating={setFeedbackRating}
                  hasCopied={hasCopied}
                  onCopyResponse={handleCopyResponse}
                  onRetryLastTurn={handleRetryLastTurn}
                />
              )
            })}

            <div ref={chatBottomRef} style={{ height: 12 }} />
          </div>
        )}
      </div>

      {/* 3. Mobile Bottom Input Bar */}
      <MobileInputBar
        inputText={inputText}
        setInputText={setInputText}
        isRunning={isRunning}
        attachedContext={attachedContext}
        setAttachedContext={setAttachedContext}
        onSendMessage={handleSendMessage}
        onStop={handleStopInvestigation}
        suggestions={suggestions}
        textareaRef={textareaRef}
      />

      {/* 4. Left Session Drawer */}
      <MobileSessionDrawer
        open={mobileDrawerOpen}
        onClose={() => setMobileDrawerOpen(false)}
        currentSessionId={currentSessionId}
        historyList={historyList}
        onSelectSession={handleSelectSession}
        onDeleteSession={handleDeleteSession}
        onStartNewChat={handleStartNewChat}
        mcpServices={mcpServices}
        accounts={accounts}
        onOpenLoginModal={(platform) => setLoginModalPlatform(platform)}
      />

      {/* 5. Mobile Inspector Bottom Sheet */}
      <MobileInspectorSheet
        open={rightPanelOpen}
        onClose={() => setRightPanelOpen(false)}
        activeTab={rightPanelTab}
        onChangeTab={(tab: RightPanelTab) => setRightPanelTab(tab)}
        evidenceItems={evidenceItems}
        recommendations={recommendations}
        controversies={controversies}
        profiles={profiles}
        selectedProfile={selectedProfile}
        onSetAttachedContext={setAttachedContext}
        onFocusTextarea={() => textareaRef.current?.focus()}
      />

      {/* 6. Standalone Profile Drawer */}
      <ShopProfileDrawer
        isOpen={isProfileDrawerOpen}
        profile={selectedProfile}
        recommendation={selectedRec}
        onClose={() => setIsProfileDrawerOpen(false)}
        onFollowUp={(shop) => {
          setAttachedContext({ type: 'shop', title: shop })
          textareaRef.current?.focus()
        }}
      />

      {/* 7. Comparison Matrix Modal */}
      <RestaurantComparisonModal
        isOpen={isCompareModalOpen}
        restaurants={compareList}
        onClose={() => setIsCompareModalOpen(false)}
        onRemoveRestaurant={(id) => setCompareList(compareList.filter((r) => r.id !== id))}
        onSelectForFollowUp={(r) => {
          setAttachedContext({ type: 'shop', title: r.name })
          textareaRef.current?.focus()
        }}
      />

      {/* 8. QR Login Modal */}
      {loginModalPlatform && (
        <QrLoginModal
          isOpen={true}
          platform={loginModalPlatform}
          onClose={() => setLoginModalPlatform(null)}
          onSuccess={() => {
            setAccounts(platformAccountsApi.getLocalAccounts())
            setLoginModalPlatform(null)
          }}
        />
      )}
    </div>
  )
}
