import { watch, onUnmounted } from 'vue'
import type { Ref } from 'vue'

interface SparklineOptions {
  color?: string
  lineWidth?: number
  thresholdWarn?: number
  thresholdCritical?: number
  maxValue?: number
}

/**
 * Draws a mini sparkline on a <canvas> element whenever `data` changes.
 * Pure canvas — zero external dependencies.
 */
export function useSparkline(
  canvas: Ref<HTMLCanvasElement | null>,
  data: Ref<number[]>,
  options: SparklineOptions = {},
) {
  const {
    color = 'var(--accent-blue)',
    lineWidth = 1.5,
    thresholdWarn,
    thresholdCritical,
  } = options

  function draw() {
    const el = canvas.value
    if (!el || data.value.length < 2) return

    const ctx = el.getContext('2d')
    if (!ctx) return

    const w = el.width
    const h = el.height
    const vals = data.value
    const dataMin = Math.min(...vals)
    const dataMax = Math.max(...vals)
    const range = dataMax - dataMin || 1

    ctx.clearRect(0, 0, w, h)

    // ── Threshold lines ───────────────────────────────────────────────────────
    function yForValue(v: number) {
      return h - ((v - dataMin) / range) * h * 0.9 - h * 0.05
    }

    if (thresholdCritical !== undefined) {
      const yC = yForValue(thresholdCritical)
      ctx.strokeStyle = 'rgba(255, 77, 106, 0.4)'
      ctx.lineWidth = 1
      ctx.setLineDash([3, 3])
      ctx.beginPath()
      ctx.moveTo(0, yC)
      ctx.lineTo(w, yC)
      ctx.stroke()
    }
    if (thresholdWarn !== undefined) {
      const yW = yForValue(thresholdWarn)
      ctx.strokeStyle = 'rgba(255, 179, 71, 0.35)'
      ctx.lineWidth = 1
      ctx.setLineDash([3, 3])
      ctx.beginPath()
      ctx.moveTo(0, yW)
      ctx.lineTo(w, yW)
      ctx.stroke()
    }
    ctx.setLineDash([])

    // ── Area fill ─────────────────────────────────────────────────────────────
    const gradient = ctx.createLinearGradient(0, 0, 0, h)
    gradient.addColorStop(0, color.startsWith('#') || color.startsWith('rgb')
      ? color + '40' : 'rgba(74,158,255,0.25)')
    gradient.addColorStop(1, 'transparent')

    ctx.beginPath()
    vals.forEach((v, i) => {
      const x = (i / (vals.length - 1)) * w
      const y = yForValue(v)
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)
    })
    ctx.lineTo(w, h)
    ctx.lineTo(0, h)
    ctx.closePath()
    ctx.fillStyle = gradient
    ctx.fill()

    // ── Line ──────────────────────────────────────────────────────────────────
    ctx.strokeStyle = color.startsWith('#') || color.startsWith('rgb')
      ? color : '#4a9eff'
    ctx.lineWidth = lineWidth
    ctx.lineJoin = 'round'
    ctx.beginPath()
    vals.forEach((v, i) => {
      const x = (i / (vals.length - 1)) * w
      const y = yForValue(v)
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)
    })
    ctx.stroke()

    // ── Last-value dot ────────────────────────────────────────────────────────
    const lastX = w
    const lastY = yForValue(vals[vals.length - 1])
    ctx.beginPath()
    ctx.arc(lastX - 1, lastY, 2.5, 0, Math.PI * 2)
    ctx.fillStyle = ctx.strokeStyle
    ctx.fill()
  }

  const stop = watch([canvas, data], draw, { immediate: true, deep: true })
  onUnmounted(stop)
}
