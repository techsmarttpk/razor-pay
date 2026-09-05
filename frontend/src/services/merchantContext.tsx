import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { api } from './api'
import type { Merchant } from '../types'

interface MerchantCtx {
  merchants: Merchant[]
  merchantId: string | undefined
  setMerchantId: (id: string | undefined) => void
}

const Ctx = createContext<MerchantCtx>({ merchants: [], merchantId: undefined, setMerchantId: () => {} })

export function MerchantProvider({ children }: { children: ReactNode }) {
  const [merchants, setMerchants] = useState<Merchant[]>([])
  const [merchantId, setMerchantId] = useState<string | undefined>(undefined)

  useEffect(() => {
    api.merchants().then(setMerchants).catch(() => {})
  }, [])

  return <Ctx.Provider value={{ merchants, merchantId, setMerchantId }}>{children}</Ctx.Provider>
}

export function useMerchant() {
  return useContext(Ctx)
}
