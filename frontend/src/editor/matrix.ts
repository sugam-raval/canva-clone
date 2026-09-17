/**
 * Affine matrix helpers.
 *
 * The draw list carries raw affine matrices (canvas2d convention). Konva expresses a
 * node's transform as translate/rotate/skew/scale, so a matrix has to be decomposed
 * before it can be applied. The decomposition below is exact for the matrices the
 * renderer produces (translate * rotate * flip), so nothing is lost.
 */

import type { Matrix2D } from '../lib/types'

export interface Decomposed {
  x: number; y: number
  rotation: number      // degrees, Konva's unit
  scaleX: number; scaleY: number
  skewX: number
}

export function decompose(m: Matrix2D): Decomposed {
  const { a, b, c, d, e, f } = m
  const determinant = a * d - b * c
  const scaleX = Math.hypot(a, b)
  const rotation = Math.atan2(b, a)

  // A zero-scale axis makes the remaining terms meaningless; fall back to identity
  // rather than emitting NaNs that would blank the canvas.
  if (scaleX === 0 || determinant === 0) {
    return { x: e, y: f, rotation: 0, scaleX: scaleX || 1, scaleY: 1, skewX: 0 }
  }

  const scaleY = determinant / scaleX
  const skewX = (a * c + b * d) / determinant

  return {
    x: e,
    y: f,
    rotation: (rotation * 180) / Math.PI,
    scaleX,
    scaleY,
    skewX,
  }
}

export function multiply(m: Matrix2D, n: Matrix2D): Matrix2D {
  return {
    a: m.a * n.a + m.c * n.b,
    b: m.b * n.a + m.d * n.b,
    c: m.a * n.c + m.c * n.d,
    d: m.b * n.c + m.d * n.d,
    e: m.a * n.e + m.c * n.f + m.e,
    f: m.b * n.e + m.d * n.f + m.f,
  }
}

export function invert(m: Matrix2D): Matrix2D | null {
  const determinant = m.a * m.d - m.b * m.c
  if (Math.abs(determinant) < 1e-12) return null
  return {
    a: m.d / determinant,
    b: -m.b / determinant,
    c: -m.c / determinant,
    d: m.a / determinant,
    e: (m.c * m.f - m.d * m.e) / determinant,
    f: (m.b * m.e - m.a * m.f) / determinant,
  }
}

export function apply(m: Matrix2D, x: number, y: number): [number, number] {
  return [m.a * x + m.c * y + m.e, m.b * x + m.d * y + m.f]
}
