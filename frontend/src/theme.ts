import type { GlobalThemeOverrides } from 'naive-ui'
import { tokens } from './design-tokens'

export const themeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: tokens.colors.brand500,
    primaryColorHover: tokens.colors.brand700,
    primaryColorPressed: tokens.colors.brand700,
    primaryColorSuppl: tokens.colors.brand500,

    infoColor: tokens.colors.info500,
    successColor: tokens.colors.success500,
    warningColor: tokens.colors.warning500,
    errorColor: tokens.colors.danger500,

    textColorBase: tokens.colors.textPrimary,
    textColor1: tokens.colors.textPrimary,
    textColor2: tokens.colors.textSecondary,
    textColor3: tokens.colors.textTertiary,
    textColorDisabled: tokens.colors.textDisabled,

    baseColor: tokens.colors.bgSurface,
    bodyColor: tokens.colors.bgCanvas,
    popoverColor: tokens.colors.bgSurface,
    cardColor: tokens.colors.bgSurface,
    modalColor: tokens.colors.bgSurface,

    dividerColor: tokens.colors.border,
    borderColor: tokens.colors.border,

    borderRadius: tokens.radius.field,
    borderRadiusSmall: tokens.radius.sm,

    fontFamily: 'Inter, "PingFang SC", system-ui, sans-serif',
    fontFamilyMono: '"JetBrains Mono", "SF Mono", Menlo, monospace',

    boxShadow1: tokens.shadow.xs,
    boxShadow2: tokens.shadow.sm,
    boxShadow3: tokens.shadow.lg,
  },
  Button: {
    heightSmall: '32px',
    heightMedium: '40px',
    heightLarge: '48px',
    paddingSmall: '0 12px',
    paddingMedium: '0 16px',
    paddingLarge: '0 20px',

    borderRadiusSmall: tokens.radius.control,
    borderRadiusMedium: tokens.radius.control,
    borderRadiusLarge: tokens.radius.control,

    fontSizeSmall: '13px',
    fontSizeMedium: '14px',
    fontSizeLarge: '16px',

    textColorGhost: tokens.colors.textPrimary,
    textColorGhostHover: tokens.colors.textPrimary,
    textColorGhostPressed: tokens.colors.textPrimary,

    colorDisabled: tokens.colors.bgSubtle,
    textColorDisabled: tokens.colors.textDisabled,
    borderDisabled: '1px solid transparent',
    colorDisabledPrimary: tokens.colors.bgSubtle,
    textColorDisabledPrimary: tokens.colors.textDisabled,
    borderDisabledPrimary: '1px solid transparent',
  },
  Input: {
    heightSmall: '32px',
    heightMedium: '40px',
    heightLarge: '48px',
    borderRadius: tokens.radius.field,
    paddingMedium: '0 12px',

    borderFocus: `1px solid ${tokens.colors.brand500}`,
    boxShadowFocus: tokens.shadow.focus,
    borderError: `1px solid ${tokens.colors.danger500}`,
    boxShadowFocusError: tokens.shadow.focusDanger,

    colorDisabled: tokens.colors.bgSubtle,
    textColorDisabled: tokens.colors.textDisabled,
    placeholderColorDisabled: tokens.colors.textTertiary,
  },
  Select: {
    peers: {
      InternalSelection: {
        borderRadius: tokens.radius.field,
        heightMedium: '36px',
        borderFocus: `1px solid ${tokens.colors.brand500}`,
        boxShadowFocus: tokens.shadow.focus,
      },
      InternalSelectMenu: {
        borderRadius: tokens.radius.popover,
        optionColorActive: tokens.colors.brand100,
        optionColorActivePending: tokens.colors.brand100,
        optionTextColorActive: tokens.colors.textPrimary,
      },
    },
  },
  Slider: {
    railHeight: '4px',
    handleSize: '16px',
    railColor: tokens.colors.bgDisabled,
    railColorHover: tokens.colors.textTertiary,
    fillColor: tokens.colors.brand500,
    fillColorHover: tokens.colors.brand500,
  },
  Checkbox: {
    sizeMedium: '16px',
    borderRadius: tokens.radius.xs,
    colorChecked: tokens.colors.brand500,
    borderChecked: `1px solid ${tokens.colors.brand500}`,
    borderFocus: `1px solid ${tokens.colors.brand500}`,
    boxShadowFocus: tokens.shadow.focus,
  },
  Radio: {
    radioSizeMedium: '16px',
    dotColorActive: tokens.colors.brand500,
    boxShadowFocus: tokens.shadow.focus,
  },
  Switch: {
    railHeightMedium: '18px',
    railWidthMedium: '32px',
    buttonHeightMedium: '14px',
    buttonWidthMedium: '14px',
    railColorActive: tokens.colors.brand500,
    boxShadowFocus: tokens.shadow.focus,
  },
  Card: {
    borderRadius: tokens.radius.dialog,
    borderColor: tokens.colors.border,
    color: tokens.colors.bgSurface,
    titleFontSizeMedium: '16px',
    paddingMedium: '20px',
  },
  Drawer: {
    bodyPadding: '24px',
    headerPadding: '20px 24px',
    footerPadding: '20px 24px',
  },
}
