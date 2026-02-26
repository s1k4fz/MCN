import { useCallback, useEffect, useMemo, useState, type ComponentType } from "react"
import {
  CheckCircle2,
  ChevronDown,
  Circle,
  CircleAlert,
  Link2,
  Link2Off,
  Loader2,
  Plus,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
  UserRound,
  Wifi,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { cn } from "@/lib/utils"

type AccountStatus = "active" | "abnormal" | "unverified"

type AccountItem = {
  id: string
  platform: string
  account: string
  email?: string | null
  status: AccountStatus
  verify_status?: string | null
  verify_message?: string | null
  verify_checked_at?: string | null
  verify_http_status?: number | null
  verify_latency_ms?: number | null
  password_masked?: string | null
  twofa_masked?: string | null
  token_masked?: string | null
  cookies_masked?: string | null
  email_password_masked?: string | null
  extra_fields?: Record<string, string>
  created_at?: string
  updated_at?: string
}

type SingleAccountForm = {
  account: string
  password: string
  twofa: string
  token: string
  cookies: string
  email: string
  emailPassword: string
}

// ---------- 代理绑定相关类型 ----------

type ProxyItem = {
  id: string
  ip: string
  port: number
  protocol: string
  type: string
  status: string
  username?: string | null
}

type BindingItem = {
  account_uid: string
  proxy_id: string
  proxy_label?: string | null
  proxy_status?: string | null
}

type BindingVerifyResult = {
  success: boolean
  account: string
  proxy: string
  summary: string
  exit_ip?: string | null
  twitter?: {
    success: boolean
    status: string
    message: string
    latency_ms?: number | null
  } | null
}

type AccountDrawer = {
  id: AccountStatus
  label: string
  icon: ComponentType<{ className?: string }>
  emptyTitle: string
  emptyDescription: string
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000"

const accountDrawers: AccountDrawer[] = [
  {
    id: "active",
    label: "正常账号",
    icon: CheckCircle2,
    emptyTitle: "暂无正常账号",
    emptyDescription: "验证通过的账号会显示在这里。",
  },
  {
    id: "abnormal",
    label: "异常账号",
    icon: CircleAlert,
    emptyTitle: "暂无异常账号",
    emptyDescription: "被封禁、锁定或不可用的账号会显示在这里。",
  },
  {
    id: "unverified",
    label: "待验证账号",
    icon: CircleAlert,
    emptyTitle: "暂无待验证账号",
    emptyDescription: "新导入的账号会显示在这里，验证后自动归类。",
  },
]

function createDefaultSingleForm(): SingleAccountForm {
  return {
    account: "",
    password: "",
    twofa: "",
    token: "",
    cookies: "",
    email: "",
    emailPassword: "",
  }
}

function getStatusLabel(status: string): string {
  if (status === "active") return "正常"
  if (status === "abnormal") return "异常"
  if (status === "unverified") return "待验证"
  return status || "未知"
}

function getVerifyStatusLabel(status?: string | null): string {
  const value = String(status || "").trim().toLowerCase()
  if (!value) return "-"
  if (value === "active") return "正常"
  if (value === "protected") return "私密正常"
  if (value === "suspended") return "封禁"
  if (value === "locked") return "锁定"
  if (value === "not_found") return "不存在"
  if (value === "rate_limited") return "限流"
  if (value === "auth_token_expired") return "Token失效"
  if (value === "token_missing") return "缺少Token"
  if (value.startsWith("http_error_")) return `HTTP异常(${value.replace("http_error_", "")})`
  if (value.startsWith("unavailable_")) return `不可用(${value.replace("unavailable_", "")})`
  return value
}

function formatDateTime(value?: string): string {
  const normalized = String(value || "").trim()
  if (!normalized) return "-"
  return normalized.replace("T", " ").slice(0, 19)
}

type AccountMainContentProps = {
  pool?: "monitor" | "publish"
}

export function AccountMainContent({ pool }: AccountMainContentProps = {}) {
  const poolLabel = pool === "monitor" ? "监控" : pool === "publish" ? "发布" : ""
  const [openMap, setOpenMap] = useState<Record<AccountStatus, boolean>>({
    active: true,
    abnormal: false,
    unverified: true,
  })
  const [accountItems, setAccountItems] = useState<AccountItem[]>([])
  const [selectedAccountId, setSelectedAccountId] = useState<string | null>(null)
  const [selectMode, setSelectMode] = useState(false)
  const [selectedAccountIds, setSelectedAccountIds] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [statusMessage, setStatusMessage] = useState<string | null>(null)

  const [singleOpen, setSingleOpen] = useState(false)
  const [batchOpen, setBatchOpen] = useState(false)
  const [singleForm, setSingleForm] = useState<SingleAccountForm>(createDefaultSingleForm)
  const [batchRawText, setBatchRawText] = useState("")
  const [batchDelimiter, setBatchDelimiter] = useState("----")
  const [batchFieldTemplate, setBatchFieldTemplate] = useState(
    "account,password,email,email_password,2fa,token"
  )
  const [batchResult, setBatchResult] = useState<string | null>(null)

  const [isSubmittingSingle, setIsSubmittingSingle] = useState(false)
  const [isSubmittingBatch, setIsSubmittingBatch] = useState(false)
  const [isDeletingAccountId, setIsDeletingAccountId] = useState<string | null>(null)
  const [isBatchDeleting, setIsBatchDeleting] = useState(false)
  const [isVerifyingStatus, setIsVerifyingStatus] = useState(false)

  // ---------- 代理绑定相关 state ----------
  const [publishProxies, setPublishProxies] = useState<ProxyItem[]>([])
  const [bindings, setBindings] = useState<BindingItem[]>([])
  const [selectedProxyId, setSelectedProxyId] = useState<string | null>(null)
  const [isBinding, setIsBinding] = useState(false)
  const [isUnbinding, setIsUnbinding] = useState(false)
  const [isVerifyingBinding, setIsVerifyingBinding] = useState(false)
  const [bindingVerifyResult, setBindingVerifyResult] = useState<BindingVerifyResult | null>(null)
  const [isBatchBinding, setIsBatchBinding] = useState(false)
  const [isBatchVerifyingBinding, setIsBatchVerifyingBinding] = useState(false)

  const loadAccounts = useCallback(async () => {
    setLoading(true)
    setErrorMessage(null)
    try {
      const params = new URLSearchParams({ platform: "twitter" })
      if (pool) params.set("pool", pool)
      const response = await fetch(`${API_BASE}/api/accounts?${params}`)
      const payload = await response.json()
      if (!response.ok || !payload?.success) {
        throw new Error(payload?.message || "账号列表加载失败")
      }
      setAccountItems(Array.isArray(payload?.accounts) ? payload.accounts : [])
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "账号列表加载失败")
      setAccountItems([])
    } finally {
      setLoading(false)
    }
  }, [pool])

  useEffect(() => {
    void loadAccounts()
  }, [loadAccounts])

  // ---------- 加载发布代理列表 + 绑定关系 ----------

  const proxyType = pool === "monitor" ? "monitor" : "publish"

  const loadProxiesAndBindings = useCallback(async () => {
    try {
      const [proxyRes, bindingRes] = await Promise.all([
        fetch(`${API_BASE}/api/proxies?type=${proxyType}`),
        fetch(`${API_BASE}/api/bindings`),
      ])
      const proxyPayload = await proxyRes.json()
      const bindingPayload = await bindingRes.json()

      if (proxyPayload?.success) {
        const proxies: ProxyItem[] = (proxyPayload.proxies ?? []).filter(
          (p: ProxyItem) => p.type === proxyType && (p.status === "active" || p.status === "slow")
        )
        setPublishProxies(proxies)
      }
      if (bindingPayload?.success) {
        setBindings(bindingPayload.bindings ?? [])
      }
    } catch {
      // 静默失败，不影响主流程
    }
  }, [proxyType])

  useEffect(() => {
    void loadProxiesAndBindings()
  }, [loadProxiesAndBindings])

  // 当前选中账号的绑定信息
  const currentBinding = useMemo(
    () => bindings.find((b) => b.account_uid === selectedAccountId) ?? null,
    [bindings, selectedAccountId]
  )

  // 选中账号变化时，重置绑定相关 UI 状态
  useEffect(() => {
    setBindingVerifyResult(null)
    setSelectedProxyId(currentBinding?.proxy_id ?? null)
  }, [selectedAccountId, currentBinding])

  // ---------- 绑定操作 ----------

  const handleBindProxy = async () => {
    if (!selectedAccountId || !selectedProxyId) return
    try {
      setIsBinding(true)
      setErrorMessage(null)
      const response = await fetch(`${API_BASE}/api/bindings`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account_id: selectedAccountId, proxy_id: selectedProxyId }),
      })
      const payload = await response.json()
      if (!payload?.success) throw new Error(payload?.message || "绑定失败")
      setStatusMessage(payload.message)
      await loadProxiesAndBindings()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "绑定失败")
    } finally {
      setIsBinding(false)
    }
  }

  const handleUnbindProxy = async () => {
    if (!selectedAccountId) return
    try {
      setIsUnbinding(true)
      setErrorMessage(null)
      const response = await fetch(`${API_BASE}/api/bindings/${selectedAccountId}`, {
        method: "DELETE",
      })
      const payload = await response.json()
      if (!payload?.success) throw new Error(payload?.message || "解绑失败")
      setStatusMessage(payload.message)
      setSelectedProxyId(null)
      setBindingVerifyResult(null)
      await loadProxiesAndBindings()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "解绑失败")
    } finally {
      setIsUnbinding(false)
    }
  }

  const handleVerifyBinding = async () => {
    if (!selectedAccountId || !currentBinding) return
    try {
      setIsVerifyingBinding(true)
      setBindingVerifyResult(null)
      const response = await fetch(
        `${API_BASE}/api/bindings/verify-by-account/${selectedAccountId}`,
        { method: "POST" }
      )
      const payload = await response.json()
      if (!payload?.success) throw new Error(payload?.message || "验证失败")
      setBindingVerifyResult(payload.verification)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "绑定验证失败")
    } finally {
      setIsVerifyingBinding(false)
    }
  }

  // ---------- 批量绑定空闲代理 ----------

  const handleBatchAutoBind = async () => {
    if (selectedAccountIds.length === 0) {
      setErrorMessage("请先选择要绑定的账号")
      return
    }
    try {
      setIsBatchBinding(true)
      setErrorMessage(null)
      setStatusMessage(null)
      const response = await fetch(`${API_BASE}/api/bindings/batch-auto-bind`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account_ids: selectedAccountIds, proxy_type: proxyType }),
      })
      const payload = await response.json()
      if (!payload?.success && payload?.bound_count === 0) {
        throw new Error(payload?.message || "批量绑定失败")
      }
      setStatusMessage(payload.message)
      // 打印详细结果到控制台
      console.group("[批量绑定] 结果")
      ;(payload.results ?? []).forEach((r: Record<string, unknown>, i: number) => {
        if (r.success) {
          console.log(`[${i + 1}] ✅ ${r.account_name} → ${r.proxy_label}`)
        } else {
          console.error(`[${i + 1}] ❌ ${r.account_name}: ${r.message}`)
        }
      })
      console.groupEnd()
      await loadProxiesAndBindings()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "批量绑定失败")
    } finally {
      setIsBatchBinding(false)
    }
  }

  // ---------- 批量验证绑定状态 ----------

  const handleBatchVerifyBinding = async () => {
    if (selectedAccountIds.length === 0) {
      setErrorMessage("请先选择要验证的账号")
      return
    }
    try {
      setIsBatchVerifyingBinding(true)
      setErrorMessage(null)
      setStatusMessage(null)
      const response = await fetch(`${API_BASE}/api/bindings/batch-verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account_ids: selectedAccountIds }),
      })
      const payload = await response.json()
      if (!response.ok || !payload?.success) {
        throw new Error(payload?.message || "批量验证失败")
      }
      setStatusMessage(payload.message)
      // 打印详细结果到控制台
      console.group("[批量验证绑定] 结果")
      ;(payload.results ?? []).forEach((r: Record<string, unknown>, i: number) => {
        if (r.success) {
          console.log(`[${i + 1}] ✅ ${r.account_name}: ${r.summary}`)
        } else {
          console.error(`[${i + 1}] ❌ ${r.account_name}: ${r.summary}`)
        }
      })
      console.groupEnd()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "批量验证失败")
    } finally {
      setIsBatchVerifyingBinding(false)
    }
  }

  const accountsByStatus = useMemo(
    () => ({
      active: accountItems.filter((item) => item.status === "active"),
      abnormal: accountItems.filter((item) => item.status === "abnormal"),
      unverified: accountItems.filter((item) => item.status === "unverified"),
    }),
    [accountItems]
  )

  const selectedAccount =
    accountItems.find((item) => item.id === selectedAccountId) ?? null

  const allImportedAccountIds = useMemo(
    () => accountItems.map((item) => item.id),
    [accountItems]
  )
  const isAllSelected =
    allImportedAccountIds.length > 0 &&
    allImportedAccountIds.every((id) => selectedAccountIds.includes(id))

  useEffect(() => {
    if (!selectMode) {
      setSelectedAccountIds([])
      return
    }
    setSelectedAccountId(null)
  }, [selectMode])

  useEffect(() => {
    setSelectedAccountIds((prev) =>
      prev.filter((id) => accountItems.some((item) => item.id === id))
    )
  }, [accountItems])

  const toggleAccountSelect = (accountId: string) => {
    setSelectedAccountIds((prev) =>
      prev.includes(accountId) ? prev.filter((id) => id !== accountId) : [...prev, accountId]
    )
  }

  const handleToggleSelectAll = () => {
    setSelectedAccountIds((prev) => (prev.length === allImportedAccountIds.length ? [] : allImportedAccountIds))
  }

  const handleCreateSingle = async () => {
    if (!singleForm.account.trim()) {
      setErrorMessage("账号不能为空")
      return
    }

    try {
      setIsSubmittingSingle(true)
      setErrorMessage(null)
      const response = await fetch(`${API_BASE}/api/accounts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          platform: "twitter",
          account: singleForm.account.trim(),
          password: singleForm.password.trim() || null,
          twofa: singleForm.twofa.trim() || null,
          token: singleForm.token.trim() || null,
          cookies: singleForm.cookies.trim() || null,
          email: singleForm.email.trim() || null,
          email_password: singleForm.emailPassword.trim() || null,
          status: "active",
          pool: pool || null,
        }),
      })
      const payload = await response.json()
      if (!response.ok || !payload?.success) {
        throw new Error(payload?.message || "添加账号失败")
      }
      setSingleOpen(false)
      setSingleForm(createDefaultSingleForm())
      await loadAccounts()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "添加账号失败")
    } finally {
      setIsSubmittingSingle(false)
    }
  }

  const handleCreateBatch = async () => {
    const delimiter = batchDelimiter || ""
    if (!delimiter) {
      setErrorMessage("分隔符不能为空")
      return
    }
    const fieldOrder = batchFieldTemplate
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean)
    if (fieldOrder.length === 0) {
      setErrorMessage("字段模板不能为空")
      return
    }
    if (!batchRawText.trim()) {
      setErrorMessage("导入内容不能为空")
      return
    }

    try {
      setIsSubmittingBatch(true)
      setErrorMessage(null)
      setBatchResult(null)
      const response = await fetch(`${API_BASE}/api/accounts/batch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          platform: "twitter",
          raw_text: batchRawText,
          delimiter,
          field_order: fieldOrder,
          status: "active",
          pool: pool || null,
        }),
      })
      const payload = await response.json()
      if (!response.ok) {
        throw new Error(payload?.message || "批量导入请求失败")
      }

      const successCount = Number(payload?.success_count ?? 0)
      const failureCount = Number(payload?.failure_count ?? 0)
      if (successCount <= 0) {
        throw new Error(payload?.message || "批量导入失败")
      }

      let resultText = `批量导入完成：成功 ${successCount} 条，失败 ${failureCount} 条。`
      const failures = Array.isArray(payload?.failures) ? payload.failures : []
      if (failures.length > 0) {
        const preview = failures
          .slice(0, 2)
          .map(
            (item: { line_number?: number; reason?: string }) =>
              `第${item.line_number ?? "-"}行: ${item.reason ?? "失败"}`
          )
          .join("；")
        resultText += ` 示例失败：${preview}`
      }

      setBatchResult(resultText)
      setBatchRawText("")
      await loadAccounts()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "批量导入失败")
    } finally {
      setIsSubmittingBatch(false)
    }
  }

  const handleDeleteAccount = async (accountId: string) => {
    const confirmed = window.confirm("确认删除该账号吗？")
    if (!confirmed) return

    try {
      setIsDeletingAccountId(accountId)
      setErrorMessage(null)
      const response = await fetch(`${API_BASE}/api/accounts/${accountId}`, {
        method: "DELETE",
      })
      const payload = await response.json()
      if (!response.ok || !payload?.success) {
        throw new Error(payload?.message || "删除账号失败")
      }

      if (selectedAccountId === accountId) {
        setSelectedAccountId(null)
      }
      setSelectedAccountIds((prev) => prev.filter((id) => id !== accountId))
      await loadAccounts()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "删除账号失败")
    } finally {
      setIsDeletingAccountId(null)
    }
  }

  const handleDeleteSelectedAccounts = async () => {
    if (selectedAccountIds.length === 0) {
      setErrorMessage("请先选择要删除的账号")
      return
    }
    const confirmed = window.confirm(`确认删除选中的 ${selectedAccountIds.length} 个账号吗？`)
    if (!confirmed) return

    try {
      setIsBatchDeleting(true)
      setErrorMessage(null)
      const failures: string[] = []
      for (const accountId of selectedAccountIds) {
        try {
          const response = await fetch(`${API_BASE}/api/accounts/${accountId}`, {
            method: "DELETE",
          })
          const payload = await response.json()
          if (!response.ok || !payload?.success) {
            throw new Error(payload?.message || "删除账号失败")
          }
        } catch (error) {
          failures.push(error instanceof Error ? error.message : "删除账号失败")
        }
      }

      if (failures.length > 0) {
        setErrorMessage(`批量删除完成，但有 ${failures.length} 条失败`)
      }
      setSelectedAccountIds([])
      setSelectedAccountId(null)
      await loadAccounts()
    } finally {
      setIsBatchDeleting(false)
    }
  }

  const handleVerifySelectedAccountsStatus = async () => {
    if (selectedAccountIds.length === 0) {
      setErrorMessage("请先选择要验证状态的账号")
      return
    }

    try {
      setIsVerifyingStatus(true)
      setErrorMessage(null)
      setStatusMessage(null)
      const response = await fetch(`${API_BASE}/api/accounts/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          account_ids: selectedAccountIds,
        }),
      })
      const payload = await response.json()
      console.groupCollapsed(
        `[账号验证] response status=${response.status} success=${Boolean(payload?.success)}`
      )
      console.log("payload:", payload)
      const resultItems = Array.isArray(payload?.results) ? payload.results : []
      resultItems.forEach((item: Record<string, unknown>, index: number) => {
        const status = String(item?.verify_status || "unknown")
        if (
          status === "active" ||
          status === "protected" ||
          status === "suspended" ||
          status === "locked" ||
          status === "not_found" ||
          status.startsWith("unavailable_")
        ) {
          console.log(`[账号验证][${index + 1}]`, item)
        } else {
          console.error(`[账号验证][${index + 1}][FAILED]`, item)
        }
      })
      const failureDetails = Array.isArray(payload?.failure_details)
        ? payload.failure_details
        : []
      if (failureDetails.length > 0) {
        console.error("[账号验证] failure_details:", failureDetails)
      }
      console.groupEnd()
      if (!response.ok || !payload?.success) {
        throw new Error(payload?.message || "账号状态验证失败")
      }

      const successCount = Number(payload?.success_count ?? 0)
      const failureCount = Number(payload?.failure_count ?? 0)
      let message = `验证完成：成功 ${successCount} 个，失败 ${failureCount} 个。`
      if (Array.isArray(payload?.missing_ids) && payload.missing_ids.length > 0) {
        message += `（缺失账号 ${payload.missing_ids.length} 个）`
      }
      if (failureCount > 0) {
        message += "（失败详情见浏览器控制台）"
      }
      setStatusMessage(message)
      await loadAccounts()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "账号状态验证失败")
    } finally {
      setIsVerifyingStatus(false)
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-11 shrink-0 items-center justify-between border-b border-white/[0.08] px-5">
        <div className="flex items-center gap-0.5">
          <button
            onClick={() => setSelectMode((prev) => !prev)}
            className={cn(
              "mr-1 inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[13px] font-medium transition-colors duration-100",
              selectMode
                ? "border-white/[0.24] bg-white/[0.10] text-zinc-100"
                : "border-white/[0.12] text-zinc-300 hover:bg-white/[0.05]"
            )}
          >
            <SlidersHorizontal className="size-3.5" />
            <span>选择</span>
          </button>
        </div>
        <div className="flex items-center gap-2">
          {selectMode && (
            <>
              <button
                onClick={handleToggleSelectAll}
                className="inline-flex items-center gap-1.5 rounded-full border border-white/[0.12] px-3.5 py-1 text-[13px] font-medium text-zinc-200 transition-colors duration-100 hover:bg-white/[0.05]"
              >
                <span>{isAllSelected ? "取消全选" : "全选账号"}</span>
              </button>
              <button
                onClick={() => void handleVerifySelectedAccountsStatus()}
                disabled={selectedAccountIds.length === 0 || isVerifyingStatus || isBatchDeleting}
                className="inline-flex items-center gap-1.5 rounded-full border border-white/[0.12] px-3.5 py-1 text-[13px] font-medium text-zinc-200 transition-colors duration-100 hover:bg-white/[0.05] disabled:cursor-not-allowed disabled:opacity-50"
              >
                <span>
                  {isVerifyingStatus
                    ? "验证中..."
                    : `验证状态${selectedAccountIds.length > 0 ? ` (${selectedAccountIds.length})` : ""}`}
                </span>
              </button>
              <button
                onClick={() => void handleDeleteSelectedAccounts()}
                disabled={selectedAccountIds.length === 0 || isBatchDeleting || isVerifyingStatus}
                className="inline-flex items-center gap-1.5 rounded-full border border-red-400/40 bg-red-500/10 px-3.5 py-1 text-[13px] font-medium text-red-300 transition-colors duration-100 hover:bg-red-500/20 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <span>
                  {isBatchDeleting
                    ? "删除中..."
                    : `删除选中${selectedAccountIds.length > 0 ? ` (${selectedAccountIds.length})` : ""}`}
                </span>
              </button>
              <button
                onClick={() => void handleBatchAutoBind()}
                disabled={selectedAccountIds.length === 0 || isBatchBinding || isBatchDeleting}
                className="inline-flex items-center gap-1.5 rounded-full border border-emerald-400/40 bg-emerald-500/10 px-3.5 py-1 text-[13px] font-medium text-emerald-300 transition-colors duration-100 hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Link2 className="size-3.5" />
                <span>
                  {isBatchBinding
                    ? "绑定中..."
                    : `绑定代理${selectedAccountIds.length > 0 ? ` (${selectedAccountIds.length})` : ""}`}
                </span>
              </button>
              <button
                onClick={() => void handleBatchVerifyBinding()}
                disabled={selectedAccountIds.length === 0 || isBatchVerifyingBinding || isBatchDeleting}
                className="inline-flex items-center gap-1.5 rounded-full border border-blue-400/40 bg-blue-500/10 px-3.5 py-1 text-[13px] font-medium text-blue-300 transition-colors duration-100 hover:bg-blue-500/20 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <ShieldCheck className="size-3.5" />
                <span>
                  {isBatchVerifyingBinding
                    ? "验证中..."
                    : `验证绑定${selectedAccountIds.length > 0 ? ` (${selectedAccountIds.length})` : ""}`}
                </span>
              </button>
            </>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button className="inline-flex items-center gap-1.5 rounded-full bg-white px-3.5 py-1 text-[13px] font-medium text-black transition-colors duration-100 hover:bg-zinc-200">
                <Plus className="size-3.5" />
                <span>添加账号</span>
                <ChevronDown className="size-3.5" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="end"
              className="w-40 border-white/[0.12] bg-zinc-900 text-zinc-100"
            >
              <DropdownMenuItem onSelect={() => setSingleOpen(true)}>
                添加单个账号
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => setBatchOpen(true)}>
                批量添加账号
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {errorMessage && (
        <div className="border-b border-red-400/20 bg-red-500/10 px-5 py-2 text-xs text-red-300">
          {errorMessage}
        </div>
      )}
      {statusMessage && (
        <div className="border-b border-emerald-400/20 bg-emerald-500/10 px-5 py-2 text-xs text-emerald-300">
          {statusMessage}
        </div>
      )}

      <main className="min-h-0 flex-1 overflow-hidden">
        <div className="flex h-full">
          <section className="min-w-0 flex-1 overflow-y-auto">
            {loading ? (
              <div className="px-5 text-sm text-zinc-400">加载中...</div>
            ) : accountItems.length === 0 ? (
              <div className="mx-5 rounded-lg border border-white/[0.08] bg-white/[0.02] px-4 py-3 text-sm text-zinc-400">
                暂无账号数据。
              </div>
            ) : (
              <>
                {accountDrawers.map((drawer) => {
                  const DrawerIcon = drawer.icon

                  const accounts = accountsByStatus[drawer.id]
                  const isOpen = Boolean(openMap[drawer.id])
                  return (
                    <Collapsible
                      key={drawer.id}
                      open={isOpen}
                      onOpenChange={(open) =>
                        setOpenMap((prev) => ({ ...prev, [drawer.id]: open }))
                      }
                      className="border-b border-white/[0.05] first:border-t first:border-white/[0.05]"
                    >
                      <CollapsibleTrigger asChild>
                        <button className="flex h-11 w-full items-center bg-black/45 px-5 text-left transition-colors hover:bg-black/35">
                          <span className="flex items-center gap-2.5 text-sm text-zinc-200">
                            <ChevronDown
                              className={cn(
                                "size-4 text-zinc-500 transition-transform duration-200 ease-out",
                                isOpen && "rotate-180"
                              )}
                            />
                            <DrawerIcon className="size-4 text-zinc-300" />
                            <span>{drawer.label}</span>
                            <span className="text-zinc-500">({accounts.length})</span>
                          </span>
                        </button>
                      </CollapsibleTrigger>
                      <CollapsibleContent
                        forceMount
                        className={cn(
                          "grid transition-[grid-template-rows,opacity] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]",
                          isOpen
                            ? "grid-rows-[1fr] opacity-100"
                            : "grid-rows-[0fr] opacity-0"
                        )}
                      >
                        <div className="overflow-hidden border-t border-white/[0.05] bg-white/[0.01]">
                          {accounts.length > 0 ? (
                            <ul className="divide-y divide-white/[0.05]">
                              {accounts.map((item) => {
                                const isSelected = selectedAccountId === item.id
                                const isChecked = selectedAccountIds.includes(item.id)
                                return (
                                  <li key={item.id}>
                                    <button
                                      type="button"
                                      onClick={() => {
                                        if (selectMode) {
                                          toggleAccountSelect(item.id)
                                          return
                                        }
                                        setSelectedAccountId((prev) =>
                                          prev === item.id ? null : item.id
                                        )
                                      }}
                                      className={cn(
                                        "flex h-11 w-full items-center justify-between px-5 text-left transition-colors hover:bg-white/[0.025]",
                                        (isSelected || (selectMode && isChecked)) && "bg-white/[0.05]"
                                      )}
                                    >
                                      <div className="min-w-0 pr-3">
                                        <div className="flex items-center gap-2.5 truncate text-sm text-zinc-200">
                                          {selectMode &&
                                            (isChecked ? (
                                              <CheckCircle2 className="size-4 shrink-0 text-emerald-400" />
                                            ) : (
                                              <Circle className="size-4 shrink-0 text-zinc-500" />
                                            ))}
                                          <UserRound className="size-4 shrink-0 text-zinc-500" />
                                          <span className="truncate">{item.account}</span>
                                          <span className="mx-1 text-zinc-600">·</span>
                                          <span className="truncate text-zinc-500">
                                            {item.email || "未填写邮箱"}
                                          </span>
                                          {(() => {
                                            const b = bindings.find((b) => b.account_uid === item.id)
                                            return b ? (
                                              <span className="ml-1 shrink-0 rounded bg-emerald-500/15 px-1 py-0.5 text-[10px] text-emerald-400">
                                                <Link2 className="mr-0.5 inline size-2.5" />代理
                                              </span>
                                            ) : null
                                          })()}
                                        </div>
                                      </div>
                                      <span className="shrink-0 text-xs tabular-nums text-zinc-500">
                                        {formatDateTime(item.created_at)}
                                      </span>
                                    </button>
                                  </li>
                                )
                              })}
                            </ul>
                          ) : (
                            <div className="px-5 py-4">
                              <p className="text-sm text-zinc-300">{drawer.emptyTitle}</p>
                              <p className="mt-1 text-xs leading-relaxed text-zinc-500">
                                {drawer.emptyDescription}
                              </p>
                            </div>
                          )}
                        </div>
                      </CollapsibleContent>
                    </Collapsible>
                  )
                })}
              </>
            )}
          </section>

          <aside
            className={cn(
              "min-h-0 shrink-0 overflow-hidden border-l border-white/[0.06] bg-black/30 transition-[width,opacity] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]",
              selectedAccount ? "w-[360px] xl:w-[420px] opacity-100" : "w-0 opacity-0"
            )}
          >
            <div
              className={cn(
                "min-h-0 h-full px-5 py-4 transition-opacity duration-200",
                selectedAccount ? "opacity-100 delay-75" : "pointer-events-none opacity-0"
              )}
            >
              {selectedAccount && (
                <div className="flex h-full min-h-0 flex-col">
                  <div className="border-b border-white/[0.06] pb-3">
                    <p className="text-sm text-zinc-100">{selectedAccount.account}</p>
                    <p className="mt-1 text-xs text-zinc-500">
                      平台: {selectedAccount.platform} / 状态: {getStatusLabel(selectedAccount.status)}
                    </p>
                  </div>
                  <div className="mt-4 space-y-2 text-sm">
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-zinc-500">密码</span>
                      <span className="text-zinc-200">{selectedAccount.password_masked || "-"}</span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-zinc-500">2FA</span>
                      <span className="text-zinc-200">{selectedAccount.twofa_masked || "-"}</span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-zinc-500">Token</span>
                      <span className="text-zinc-200">{selectedAccount.token_masked || "-"}</span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-zinc-500">Cookies</span>
                      <span className="text-zinc-200">{selectedAccount.cookies_masked || "-"}</span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-zinc-500">邮箱</span>
                      <span className="text-zinc-200">{selectedAccount.email || "-"}</span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-zinc-500">邮箱密码</span>
                      <span className="text-zinc-200">
                        {selectedAccount.email_password_masked || "-"}
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-zinc-500">更新时间</span>
                      <span className="text-zinc-200">{formatDateTime(selectedAccount.updated_at)}</span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-zinc-500">验证状态</span>
                      <span className="text-zinc-200">
                        {getVerifyStatusLabel(selectedAccount.verify_status)}
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-zinc-500">最近验证</span>
                      <span className="text-zinc-200">
                        {formatDateTime(selectedAccount.verify_checked_at || undefined)}
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-zinc-500">验证延迟</span>
                      <span className="text-zinc-200">
                        {selectedAccount.verify_latency_ms != null
                          ? `${selectedAccount.verify_latency_ms}ms`
                          : "-"}
                      </span>
                    </div>
                  </div>

                  {/* ====== 代理绑定区块 ====== */}
                  <div className="mt-5 rounded-lg border border-white/[0.08] bg-black/35 p-3">
                    <p className="flex items-center gap-1.5 text-[11px] uppercase tracking-[0.12em] text-zinc-500">
                      <Wifi className="size-3" />
                      代理绑定
                    </p>

                    {/* 当前绑定状态 */}
                    <div className="mt-2.5 text-[12px] leading-5">
                      {currentBinding ? (
                        <div className="flex items-center gap-1.5 text-emerald-400">
                          <Link2 className="size-3" />
                          <span>已绑定: {currentBinding.proxy_label ?? currentBinding.proxy_id}</span>
                          {currentBinding.proxy_status && (
                            <span className={cn(
                              "ml-1 rounded px-1 py-0.5 text-[10px]",
                              currentBinding.proxy_status === "active"
                                ? "bg-emerald-500/20 text-emerald-400"
                                : "bg-amber-500/20 text-amber-400"
                            )}>
                              {currentBinding.proxy_status}
                            </span>
                          )}
                        </div>
                      ) : (
                        <div className="flex items-center gap-1.5 text-zinc-500">
                          <Link2Off className="size-3" />
                          <span>未绑定代理</span>
                        </div>
                      )}
                    </div>

                    {/* 代理选择下拉 */}
                    <div className="mt-2.5">
                      <select
                        className="h-7 w-full rounded border border-white/[0.12] bg-zinc-900 px-2 text-[12px] text-zinc-200 outline-none focus:border-zinc-500"
                        value={selectedProxyId ?? ""}
                        onChange={(e) => setSelectedProxyId(e.target.value || null)}
                      >
                        <option value="">选择{poolLabel || "发布"}代理...</option>
                        {publishProxies.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.protocol}://{p.ip}:{p.port} ({p.status})
                          </option>
                        ))}
                      </select>
                    </div>

                    {/* 操作按钮 */}
                    <div className="mt-2.5 flex gap-2">
                      <Button
                        size="sm"
                        className="h-7 rounded-full bg-white px-3 text-[11px] text-black hover:bg-zinc-200"
                        disabled={!selectedProxyId || isBinding}
                        onClick={() => void handleBindProxy()}
                      >
                        {isBinding ? (
                          <><Loader2 className="mr-1 size-3 animate-spin" />绑定中</>
                        ) : (
                          <><Link2 className="mr-1 size-3" />绑定</>
                        )}
                      </Button>
                      {currentBinding && (
                        <>
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-7 rounded-full border-red-400/40 bg-red-500/10 px-3 text-[11px] text-red-300 hover:bg-red-500/20"
                            disabled={isUnbinding}
                            onClick={() => void handleUnbindProxy()}
                          >
                            {isUnbinding ? (
                              <><Loader2 className="mr-1 size-3 animate-spin" />解绑中</>
                            ) : (
                              <><Link2Off className="mr-1 size-3" />解绑</>
                            )}
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-7 rounded-full border-blue-400/40 bg-blue-500/10 px-3 text-[11px] text-blue-300 hover:bg-blue-500/20"
                            disabled={isVerifyingBinding}
                            onClick={() => void handleVerifyBinding()}
                          >
                            {isVerifyingBinding ? (
                              <><Loader2 className="mr-1 size-3 animate-spin" />验证中</>
                            ) : (
                              <><ShieldCheck className="mr-1 size-3" />验证绑定</>
                            )}
                          </Button>
                        </>
                      )}
                    </div>

                    {/* 验证结果展示 */}
                    {bindingVerifyResult && (
                      <div className={cn(
                        "mt-2.5 rounded border p-2 text-[11px] leading-4",
                        bindingVerifyResult.success
                          ? "border-emerald-400/30 bg-emerald-500/10 text-emerald-300"
                          : "border-red-400/30 bg-red-500/10 text-red-300"
                      )}>
                        <p className="font-medium">{bindingVerifyResult.summary}</p>
                        {bindingVerifyResult.exit_ip && (
                          <p className="mt-1 text-zinc-400">
                            出口IP: {bindingVerifyResult.exit_ip}
                          </p>
                        )}
                        {bindingVerifyResult.twitter && (
                          <p className="mt-1 text-zinc-400">
                            Twitter: {bindingVerifyResult.twitter.status} - {bindingVerifyResult.twitter.message}
                            {bindingVerifyResult.twitter.latency_ms != null && (
                              <span className="ml-1 text-zinc-500">
                                ({bindingVerifyResult.twitter.latency_ms}ms)
                              </span>
                            )}
                          </p>
                        )}
                      </div>
                    )}
                  </div>

                  <div className="mt-5 min-h-0 flex-1 overflow-auto rounded-lg border border-white/[0.08] bg-black/35 p-3">
                    <p className="text-[11px] uppercase tracking-[0.12em] text-zinc-500">原始导入字段</p>
                    {selectedAccount.verify_message && (
                      <p className="mt-2 text-[12px] leading-5 text-amber-300">
                        验证信息: {selectedAccount.verify_message}
                      </p>
                    )}
                    <div className="mt-2 space-y-1 text-[12px] leading-5 text-zinc-400">
                      {selectedAccount.extra_fields &&
                      Object.keys(selectedAccount.extra_fields).length > 0 ? (
                        Object.entries(selectedAccount.extra_fields).map(([key, value]) => (
                          <p key={key}>
                            {key}: {value || "-"}
                          </p>
                        ))
                      ) : (
                        <p>无</p>
                      )}
                    </div>
                  </div>

                  <Button
                    size="sm"
                    variant="outline"
                    className="mt-3 self-end rounded-full border-red-400/40 bg-red-500/10 text-red-300 hover:bg-red-500/20"
                    onClick={() => void handleDeleteAccount(selectedAccount.id)}
                    disabled={isDeletingAccountId === selectedAccount.id}
                  >
                    <Trash2 className="size-3.5" />
                    {isDeletingAccountId === selectedAccount.id ? "删除中..." : "删除账号"}
                  </Button>
                </div>
              )}
            </div>
          </aside>
        </div>
      </main>

      <Dialog open={singleOpen} onOpenChange={setSingleOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>添加单个账号</DialogTitle>
            <DialogDescription>填写账号与凭证信息，保存到本地账号池。</DialogDescription>
          </DialogHeader>
          <div className="mt-4 grid grid-cols-2 gap-2">
            <input
              value={singleForm.account}
              onChange={(event) =>
                setSingleForm((prev) => ({ ...prev, account: event.target.value }))
              }
              placeholder="账号（必填）"
              className="h-9 rounded-full border border-white/[0.12] bg-white/[0.03] px-4 text-[13px] text-zinc-200 placeholder:text-zinc-500 outline-none transition-colors focus:border-white/[0.22] focus:bg-white/[0.06]"
            />
            <input
              value={singleForm.password}
              onChange={(event) =>
                setSingleForm((prev) => ({ ...prev, password: event.target.value }))
              }
              placeholder="密码"
              className="h-9 rounded-full border border-white/[0.12] bg-white/[0.03] px-4 text-[13px] text-zinc-200 placeholder:text-zinc-500 outline-none transition-colors focus:border-white/[0.22] focus:bg-white/[0.06]"
            />
            <input
              value={singleForm.twofa}
              onChange={(event) =>
                setSingleForm((prev) => ({ ...prev, twofa: event.target.value }))
              }
              placeholder="2FA / TOTP"
              className="h-9 rounded-full border border-white/[0.12] bg-white/[0.03] px-4 text-[13px] text-zinc-200 placeholder:text-zinc-500 outline-none transition-colors focus:border-white/[0.22] focus:bg-white/[0.06]"
            />
            <input
              value={singleForm.token}
              onChange={(event) =>
                setSingleForm((prev) => ({ ...prev, token: event.target.value }))
              }
              placeholder="Token (auth_token)"
              className="h-9 rounded-full border border-white/[0.12] bg-white/[0.03] px-4 text-[13px] text-zinc-200 placeholder:text-zinc-500 outline-none transition-colors focus:border-white/[0.22] focus:bg-white/[0.06]"
            />
            <textarea
              value={singleForm.cookies}
              onChange={(event) =>
                setSingleForm((prev) => ({ ...prev, cookies: event.target.value }))
              }
              placeholder="完整 Cookies（从浏览器复制，格式: key1=val1; key2=val2; ...）"
              rows={3}
              className="rounded-xl border border-white/[0.12] bg-white/[0.03] px-4 py-2 text-[13px] text-zinc-200 placeholder:text-zinc-500 outline-none transition-colors focus:border-white/[0.22] focus:bg-white/[0.06] resize-y"
            />
            <input
              value={singleForm.email}
              onChange={(event) =>
                setSingleForm((prev) => ({ ...prev, email: event.target.value }))
              }
              placeholder="邮箱"
              className="h-9 rounded-full border border-white/[0.12] bg-white/[0.03] px-4 text-[13px] text-zinc-200 placeholder:text-zinc-500 outline-none transition-colors focus:border-white/[0.22] focus:bg-white/[0.06]"
            />
            <input
              value={singleForm.emailPassword}
              onChange={(event) =>
                setSingleForm((prev) => ({ ...prev, emailPassword: event.target.value }))
              }
              placeholder="邮箱密码"
              className="h-9 rounded-full border border-white/[0.12] bg-white/[0.03] px-4 text-[13px] text-zinc-200 placeholder:text-zinc-500 outline-none transition-colors focus:border-white/[0.22] focus:bg-white/[0.06]"
            />
          </div>
          <DialogFooter>
            <Button
              variant="ghost"
              className="h-8 rounded-full border border-white/[0.12] px-4 hover:bg-white/[0.05]"
              onClick={() => setSingleOpen(false)}
              disabled={isSubmittingSingle}
            >
              取消
            </Button>
            <Button
              className="h-8 rounded-full bg-white px-4 text-black hover:bg-zinc-200"
              onClick={() => void handleCreateSingle()}
              disabled={isSubmittingSingle}
            >
              {isSubmittingSingle ? "提交中..." : "确认添加"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={batchOpen} onOpenChange={setBatchOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>批量导入账号</DialogTitle>
            <DialogDescription>
              可自定义字段模板和分隔符，按“每行一个账号”导入。
            </DialogDescription>
          </DialogHeader>
          <div className="mt-4 space-y-3">
            <input
              value={batchDelimiter}
              onChange={(event) => setBatchDelimiter(event.target.value)}
              placeholder="分隔符（例如 ----，或 ,）"
              className="h-9 w-full rounded-full border border-white/[0.12] bg-white/[0.03] px-4 text-[13px] text-zinc-200 placeholder:text-zinc-500 outline-none transition-colors focus:border-white/[0.22] focus:bg-white/[0.06]"
            />
            <input
              value={batchFieldTemplate}
              onChange={(event) => setBatchFieldTemplate(event.target.value)}
              placeholder="字段模板，逗号分隔（如 account,password,2fa,token）"
              className="h-9 w-full rounded-full border border-white/[0.12] bg-white/[0.03] px-4 text-[13px] text-zinc-200 placeholder:text-zinc-500 outline-none transition-colors focus:border-white/[0.22] focus:bg-white/[0.06]"
            />
            <textarea
              value={batchRawText}
              onChange={(event) => setBatchRawText(event.target.value)}
              placeholder={
                "JessicaFer20452----oC7rFGm9GT----stepanova.7pziv@rambler.ru----wSBrH0Bs42xDWD----RHW65QIADO2QBWMU----f5ee5a62f08ddc..."
              }
              className="min-h-[180px] w-full rounded-lg border border-white/[0.12] bg-white/[0.03] px-3 py-2 text-[13px] text-zinc-200 placeholder:text-zinc-500 outline-none transition-colors focus:border-white/[0.22] focus:bg-white/[0.06]"
            />
            {batchResult && (
              <div className="rounded-md border border-emerald-400/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
                {batchResult}
              </div>
            )}
          </div>
          <DialogFooter>
            <Button
              variant="ghost"
              className="h-8 rounded-full border border-white/[0.12] px-4 hover:bg-white/[0.05]"
              onClick={() => setBatchOpen(false)}
              disabled={isSubmittingBatch}
            >
              关闭
            </Button>
            <Button
              className="h-8 rounded-full bg-white px-4 text-black hover:bg-zinc-200"
              onClick={() => void handleCreateBatch()}
              disabled={isSubmittingBatch}
            >
              {isSubmittingBatch ? "导入中..." : "开始导入"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
