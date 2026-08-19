import { createContext, useContext } from 'react'

export type ToastKind = 'info' | 'warn'
export type Toast = { id: number; kind: ToastKind; title: string; body?: string }

export const ToastContext = createContext<(t: Omit<Toast, 'id'>) => void>(() => {})

export const useToast = () => useContext(ToastContext)
