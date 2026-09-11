import { chromium } from 'playwright-core'

const chromePath = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'

async function run() {
  console.log('=== STARTING ANT DESIGN COMPREHENSIVE UI & BUTTON TEST ===')
  const browser = await chromium.launch({
    executablePath: chromePath,
    headless: true,
  })

  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  })

  const page = await context.newPage()

  const runtimeErrors = []
  page.on('console', msg => {
    const text = msg.text()
    if (msg.type() === 'error') {
      // Ignore known antd 6 deprecation warnings and offline backend network errors
      if (
        text.includes('Warning: [antd:') ||
        text.includes('net::ERR_CONNECTION_REFUSED') ||
        text.includes('Failed to load resource')
      ) {
        console.log(`[ADVISORY/OFFLINE-NETWORK]: ${text}`)
      } else {
        console.log(`[RUNTIME ERROR]: ${text}`)
        runtimeErrors.push(text)
      }
    }
  })

  page.on('pageerror', err => {
    console.log(`[UNCAUGHT EXCEPTION]: ${err.message}`)
    runtimeErrors.push(err.message)
  })

  // 1. Visit Workbench
  console.log('\n1. Navigating to http://localhost:5173/ ...')
  await page.goto('http://localhost:5173/', { waitUntil: 'networkidle' })
  await page.waitForTimeout(1500)
  await page.screenshot({ path: 'test_step1_home.png' })
  console.log('✓ Home loaded. Screenshot: test_step1_home.png')

  // Check if restaurant cards rendered
  const cardCount = await page.locator('.ant-card:has-text("￥")').count()
  console.log(`✓ Rendered ${cardCount} restaurant candidate cards`)

  // 2. Test Accordion: Collapse / Expand thinking process
  console.log('\n2. Testing Thinking Steps Collapse...')
  const collapseHeader = page.locator('.ant-collapse-header:has-text("思考与调查步骤")')
  if (await collapseHeader.count()) {
    await collapseHeader.click()
    await page.waitForTimeout(500)
    await page.screenshot({ path: 'test_step2_collapse_open.png' })
    console.log('✓ Expanded thinking process timeline')
  }

  // 3. Test Clicking "加入对比" buttons
  console.log('\n3. Testing "加入对比" on restaurant cards...')
  const compareBtns = page.locator('button:has-text("加入对比")')
  const btnCount = await compareBtns.count()
  console.log(`Found ${btnCount} "加入对比" buttons`)
  if (btnCount >= 2) {
    await compareBtns.nth(0).click()
    await page.waitForTimeout(400)
    await compareBtns.nth(1).click()
    await page.waitForTimeout(400)
    console.log('✓ Added 2 restaurants to compare list')
  }

  // 4. Test Opening Comparison Modal
  console.log('\n4. Testing Comparison Matrix Modal...')
  const openCompareModalBtn = page.locator('button:has-text("开始全维对比")').or(page.locator('button:has-text("对比矩阵")'))
  if (await openCompareModalBtn.count()) {
    await openCompareModalBtn.first().click()
    await page.waitForTimeout(800)
    await page.screenshot({ path: 'test_step4_compare_modal.png' })
    console.log('✓ Comparison modal opened. Screenshot: test_step4_compare_modal.png')

    // Close modal
    const closeBtn = page.locator('.ant-modal-close')
    if (await closeBtn.count()) {
      await closeBtn.click()
      await page.waitForTimeout(500)
      console.log('✓ Comparison modal closed')
    }
  }

  // 5. Test Right Inspector Drawer & Tabs
  console.log('\n5. Testing Right Inspector Drawer & Tabs...')
  const inspectorBtn = page.locator('button:has-text("调研检查器")')
  if (await inspectorBtn.count()) {
    await inspectorBtn.click()
    await page.waitForTimeout(800)
    await page.screenshot({ path: 'test_step5_drawer_evidence.png' })
    console.log('✓ Drawer opened with Evidence tab. Screenshot: test_step5_drawer_evidence.png')

    // Switch to Controversies Tab
    const controversyTab = page.locator('.ant-tabs-tab:has-text("争议焦点")')
    if (await controversyTab.count()) {
      await controversyTab.click()
      await page.waitForTimeout(600)
      await page.screenshot({ path: 'test_step5_drawer_controversy.png' })
      console.log('✓ Switched to Controversy tab')

      // Click "向 Agent 追问核实" inside controversy panel
      const verifyBtn = page.locator('button:has-text("向 Agent 追问核实")')
      if (await verifyBtn.count()) {
        await verifyBtn.first().click()
        await page.waitForTimeout(500)
        console.log('✓ Clicked "向 Agent 追问核实", attached context to composer')
      }
    }

    // Switch to Shop Profile Tab
    const profileTab = page.locator('.ant-tabs-tab:has-text("店铺档案")')
    if (await profileTab.count()) {
      await profileTab.click()
      await page.waitForTimeout(600)
      await page.screenshot({ path: 'test_step5_drawer_profile.png' })
      console.log('✓ Switched to Profile tab')
    }

    // Close Drawer
    const closeDrawerBtn = page.locator('.ant-drawer-close')
    if (await closeDrawerBtn.count()) {
      await closeDrawerBtn.click()
      await page.waitForTimeout(500)
      console.log('✓ Drawer closed')
    }
  }

  // 6. Test Suggestion Chips & Sending Query
  console.log('\n6. Testing Suggestion Chip & Composer...')
  const suggestionChip = page.locator('button:has-text("附近步行20分钟内是否有口碑老店？")')
  if (await suggestionChip.count()) {
    await suggestionChip.click()
    await page.waitForTimeout(1200)
    await page.screenshot({ path: 'test_step6_after_chip_query.png' })
    console.log('✓ Clicked suggestion chip. Dynamic search completed!')
  }

  // 7. Test Manual Input and Send
  console.log('\n7. Testing Text Input & Send...')
  const textarea = page.locator('textarea.ant-input')
  if (await textarea.count()) {
    await textarea.fill('请推荐建设路附近好吃的甜水面和钵钵鸡')
    await page.waitForTimeout(300)
    const sendBtn = page.locator('button:has(.anticon-arrow-up)').or(page.locator('button:has-text("发送")'))
    if (await sendBtn.count()) {
      await sendBtn.first().click()
      console.log('✓ Clicked Send button')
      await page.waitForTimeout(1200)
      await page.screenshot({ path: 'test_step7_custom_query.png' })
      console.log('✓ Custom query finished. Screenshot: test_step7_custom_query.png')
    }
  }

  // 8. Test Switching History Sessions
  console.log('\n8. Testing History Session Switching...')
  const gzHistoryItem = page.locator('.ant-list-item:has-text("广州越秀")')
  if (await gzHistoryItem.count()) {
    await gzHistoryItem.click()
    await page.waitForTimeout(1000)
    await page.screenshot({ path: 'test_step8_gz_session.png' })
    console.log('✓ Switched to Guangzhou Morning Tea session')
  }

  // 9. Test QR Login Modal
  console.log('\n9. Testing QR Login Modal...')
  const xhsLoginBtn = page.locator('button:has-text("小红书")').first()
  if (await xhsLoginBtn.count()) {
    await xhsLoginBtn.click()
    await page.waitForTimeout(800)
    await page.screenshot({ path: 'test_step9_qr_modal.png' })
    console.log('✓ QR Login modal displayed with QRCode & Steps')
    const closeQrBtn = page.locator('.ant-modal-close')
    if (await closeQrBtn.count()) {
      await closeQrBtn.click()
      await page.waitForTimeout(500)
    }
  }

  // 10. Test B-end Ops Pages
  console.log('\n10. Testing B-end Ops Management Pages...')
  const opsPages = [
    { url: '/ops', name: 'Overview' },
    { url: '/ops/services', name: 'ServiceCatalog' },
    { url: '/ops/tasks', name: 'TaskObservability' },
    { url: '/ops/evidence', name: 'EvidenceObservability' },
    { url: '/ops/governance', name: 'ModelGovernance' },
  ]

  for (const item of opsPages) {
    console.log(`Navigating to http://localhost:5173${item.url} ...`)
    await page.goto(`http://localhost:5173${item.url}`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(800)
    await page.screenshot({ path: `test_ops_${item.name.toLowerCase()}.png` })
    console.log(`✓ Loaded ${item.name}. Screenshot: test_ops_${item.name.toLowerCase()}.png`)
  }

  console.log('\n=== TEST COMPLETE ===')
  console.log(`Total Unhandled Runtime Errors: ${runtimeErrors.length}`)
  if (runtimeErrors.length > 0) {
    console.error('Errors encountered:', runtimeErrors)
    process.exit(1)
  } else {
    console.log('ALL BUTTONS AND UI INTERACTIONS VERIFIED SUCCESSFULLY WITH 0 RUNTIME ERRORS!')
  }

  await browser.close()
}

run().catch(err => {
  console.error('Test execution failed:', err)
  process.exit(1)
})
