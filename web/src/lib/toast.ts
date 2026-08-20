import { createContext, useContext } from 'react'
import type { ReactNode } from 'react'

export type ToastKind = 'info' | 'warn' | 'success' | 'error'

export type ToastAction = {
  label: string
  /** Return true to keep the toast open — used by the two-step accept. */
  onClick: () => boolean | void
  tone?: 'primary' | 'quiet'
}

export type Toast = {
  id: number
  kind: ToastKind
  title: string
  body?: ReactNode
  actions?: ToastAction[]
}

export const ToastContext = createContext<(t: Omit<Toast, 'id'>) => void>(() => {})

export const useToast = () => useContext(ToastContext)
