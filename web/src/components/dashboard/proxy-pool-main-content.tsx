import { useCallback, useEffect, useMemo, useState, type ComponentType } from "react"
import {
  Circle,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  Clock3,
  Plus,
  SlidersHorizontal,
  Trash2,
  Wifi,
  X,
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

type ProxyPoolType = "publish" | "monitor"
type ProxyProtocol = "http" | "https" | "socks5"
type ProxyStatus = "active" | "dead" | "slow" | "disabled"
type MonitorProxyDrawerId = "normal" | "abnormal" | "pending"
type ProxyDrawerId = MonitorProxyDrawerId

type ProxyServiceUnlock = {
  name?: string
  ok?: boolean
  latency_seconds?: number | null
}

type ProxyCheckResult = {
  success?: boolean
  status?: string
  message?: string
  task_id?: string
  real_ip?: string | null
  latency_ms?: number | null
  score?: number | null
  proxy_type?: string | null
  country?: string | null
  region?: string | null
  city?: string | null
  services?: ProxyServiceUnlock[]
  is_dead?: boolean
  error?: string | null
}

type ProxyRecord = {
  id: string
  ip: string
  port: number
  protocol: ProxyProtocol
  username?: string | null
  password_masked?: string | null
  region?: string | null
  type: ProxyPoolType
  status: ProxyStatus
  last_checked_at?: string | null
  last_latency_ms?: number | null
  last_error?: string | null
  last_check_result?: ProxyCheckResult | null
  created_at?: string
  updated_at?: string
}

type SingleFormState = {
  ip: string
  port: string
  username: string
  password: string
  region: string
  protocol: ProxyProtocol
}

type ProxyDrawer = {
  id: ProxyDrawerId
  label: string
  icon: ComponentType<{ className?: string }>
  emptyTitle: string
  emptyDescription: string
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000"

const protocolOptions: { id: ProxyProtocol; label: string }[] = [
  { id: "http", label: "HTTP" },
  { id: "https", label: "HTTPS" },
  { id: "socks5", label: "SOCKS5" },
]

const poolProxyDrawers: ProxyDrawer[] = [
  {
    id: "normal",
    label: "正常",
    icon: CheckCircle2,
    emptyTitle: "暂无正常代理",
    emptyDescription: "检测完成且状态正常的代理会显示在这里。",
  },
  {
    id: "abnormal",
    label: "异常",
    icon: CircleAlert,
    emptyTitle: "暂无异常代理",
    emptyDescription: "检测后状态异常（不可用/较慢/停用）的代理会显示在这里。",
  },
  {
    id: "pending",
    label: "待检测",
    icon: Clock3,
    emptyTitle: "暂无待检测代理",
    emptyDescription: "尚未执行健康检测的代理会显示在这里。",
  },
]

function getStatusLabel(status: string): string {
  if (status === "active") return "可用"
  if (status === "slow") return "较慢"
  if (status === "dead") return "不可用"
  if (status === "disabled") return "禁用"
  return status || "未知"
}

function getStatusClass(status: string): string {
  if (status === "active") {
    return "border-emerald-400/40 bg-emerald-500/10 text-emerald-300"
  }
  if (status === "slow") {
    return "border-amber-400/40 bg-amber-500/10 text-amber-300"
  }
  if (status === "dead") {
    return "border-red-400/40 bg-red-500/10 text-red-300"
  }
  if (status === "disabled") {
    return "border-zinc-500/40 bg-zinc-500/10 text-zinc-300"
  }
  return "border-white/[0.18] bg-white/[0.08] text-zinc-300"
}

function formatDateTime(value?: string | null): string {
  const normalized = String(value || "").trim()
  if (!normalized) return "-"
  return normalized.replace("T", " ").slice(0, 19)
}

function formatResolvedLocation(result?: ProxyCheckResult | null): string {
  if (!result) return "-"
  const parts = [result.country, result.region, result.city]
    .map((item) => String(item || "").trim())
    .filter(Boolean)
  return parts.length > 0 ? parts.join(" / ") : "-"
}

function isPendingDetection(proxy: ProxyRecord): boolean {
  return !String(proxy.last_checked_at || "").trim()
}

function resolveTwitterUnlockState(
  result?: ProxyCheckResult | null
): "ok" | "fail" | "unknown" {
  const services = Array.isArray(result?.services) ? result.services : []
  const twitterService = services.find((item) =>
    String(item?.name || "")
      .trim()
      .toLowerCase()
      .includes("twitter")
  )
  if (!twitterService) return "unknown"
  return twitterService.ok ? "ok" : "fail"
}

function isProxyDead(proxy: ProxyRecord): boolean {
  if (proxy.last_check_result?.is_dead) return true
  if (proxy.last_check_result?.error) return true
  if (proxy.status === "dead") return true
  return false
}

function extractFriendlyError(proxy: ProxyRecord): string {
  const result = proxy.last_check_result
  if (!result) return proxy.last_error || "未知错误"
  const err = String(result.error || "").trim()
  if (err) return err
  const msg = String(result.message || "").trim()
  if (msg) return msg
  return proxy.last_error || "未知错误"
}

function createDefaultSingleForm(): SingleFormState {
  return {
    ip: "",
    port: "10000",
    username: "",
    password: "",
    region: "",
    protocol: "http",
  }
}

function ProtocolSelector({
  value,
  onChange,
  disabled = false,
}: {
  value: ProxyProtocol
  onChange: (value: ProxyProtocol) => void
  disabled?: boolean
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {protocolOptions.map((option) => (
        <button
          key={option.id}
          type="button"
          onClick={() => onChange(option.id)}
          disabled={disabled}
          className={cn(
            "inline-flex h-8 items-center rounded-full border px-3 text-[13px] transition-colors disabled:cursor-not-allowed disabled:opacity-60",
            value === option.id
              ? "border-white/30 bg-white/[0.10] text-zinc-100"
              : "border-white/[0.12] text-zinc-400 hover:bg-white/[0.05] hover:text-zinc-200"
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

export function ProxyPoolMainContent({ poolType }: { poolType: ProxyPoolType }) {
  const poolLabel = poolType === "publish" ? "发布代理池" : "监控代理池"
  const [openMap, setOpenMap] = useState<Record<ProxyDrawerId, boolean>>({
    normal: true,
    abnormal: false,
    pending: false,
  })
  const [proxyItems, setProxyItems] = useState<ProxyRecord[]>([])
  const [selectedProxyId, setSelectedProxyId] = useState<string | null>(null)
  const [selectMode, setSelectMode] = useState(false)
  const [selectedProxyIds, setSelectedProxyIds] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [statusMessage, setStatusMessage] = useState<string | null>(null)

  const [singleOpen, setSingleOpen] = useState(false)
  const [batchOpen, setBatchOpen] = useState(false)
  const [singleForm, setSingleForm] = useState<SingleFormState>(createDefaultSingleForm)
  const [batchInput, setBatchInput] = useState("")
  const [batchProtocol, setBatchProtocol] = useState<ProxyProtocol>("http")
  const [batchRegion, setBatchRegion] = useState("")

  const [isSubmittingSingle, setIsSubmittingSingle] = useState(false)
  const [isSubmittingBatch, setIsSubmittingBatch] = useState(false)
  const [isTestingProxyId, setIsTestingProxyId] = useState<string | null>(null)
  const [isBatchTesting, setIsBatchTesting] = useState(false)
  const [isBatchDeleting, setIsBatchDeleting] = useState(false)
  const [isDeletingProxyId, setIsDeletingProxyId] = useState<string | null>(null)
  const [batchResult, setBatchResult] = useState<string | null>(null)

  const loadProxies = useCallback(async () => {
    setLoading(true)
    setErrorMessage(null)
    try {
      const response = await fetch(`${API_BASE}/api/proxies?type=${poolType}`)
      const payload = await response.json()
      if (!response.ok || !payload?.success) {
        throw new Error(payload?.message || "代理列表加载失败")
      }
      setProxyItems(Array.isArray(payload?.proxies) ? payload.proxies : [])
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "代理列表加载失败")
      setProxyItems([])
    } finally {
      setLoading(false)
    }
  }, [poolType])

  useEffect(() => {
    void loadProxies()
  }, [loadProxies])

  const monitorProxiesByStatus = useMemo(
    () => ({
      normal: proxyItems.filter(
        (item) => !isPendingDetection(item) && item.status === "active"
      ),
      abnormal: proxyItems.filter(
        (item) => !isPendingDetection(item) && item.status !== "active"
      ),
      pending: proxyItems.filter((item) => isPendingDetection(item)),
    }),
    [proxyItems]
  )

  const selectedProxy =
    proxyItems.find((item) => item.id === selectedProxyId) ?? null
  const selectedCheckResult = selectedProxy?.last_check_result ?? null
  const selectedUnlockServices = Array.isArray(selectedCheckResult?.services)
    ? selectedCheckResult.services
    : []
  const allImportedProxyIds = useMemo(() => proxyItems.map((item) => item.id), [proxyItems])
  const isAllSelected =
    allImportedProxyIds.length > 0 &&
    allImportedProxyIds.every((id) => selectedProxyIds.includes(id))

  useEffect(() => {
    if (selectedProxyId && !proxyItems.some((item) => item.id === selectedProxyId)) {
      setSelectedProxyId(null)
    }
  }, [proxyItems, selectedProxyId])

  useEffect(() => {
    if (!selectMode) {
      setSelectedProxyIds([])
      return
    }
    setSelectedProxyId(null)
  }, [selectMode])

  useEffect(() => {
    setSelectedProxyIds((prev) => prev.filter((id) => proxyItems.some((item) => item.id === id)))
  }, [proxyItems])

  const toggleProxySelect = (proxyId: string) => {
    setSelectedProxyIds((prev) =>
      prev.includes(proxyId) ? prev.filter((id) => id !== proxyId) : [...prev, proxyId]
    )
  }

  const handleToggleSelectAll = () => {
    setSelectedProxyIds((prev) => (prev.length === allImportedProxyIds.length ? [] : allImportedProxyIds))
  }

  const handleCreateSingle = async () => {
    const ip = singleForm.ip.trim()
    const portValue = Number(singleForm.port)
    if (!ip || !Number.isFinite(portValue) || portValue <= 0) {
      setErrorMessage("请填写有效的 ip 和 port")
      return
    }

    try {
      setIsSubmittingSingle(true)
      setErrorMessage(null)
      const response = await fetch(`${API_BASE}/api/proxies`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ip,
          port: portValue,
          username: singleForm.username.trim() || null,
          password: singleForm.password.trim() || null,
          protocol: singleForm.protocol,
          region: singleForm.region.trim() || null,
          type: poolType,
        }),
      })
      const payload = await response.json()
      if (!response.ok || !payload?.success) {
        throw new Error(payload?.message || "添加代理失败")
      }
      setSingleOpen(false)
      setSingleForm(createDefaultSingleForm())
      await loadProxies()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "添加代理失败")
    } finally {
      setIsSubmittingSingle(false)
    }
  }

  const handleCreateBatch = async () => {
    const items = batchInput
      .split(/\r?\n/)
      .map((item) => item.trim())
      .filter(Boolean)
    if (items.length === 0) {
      setErrorMessage("请至少输入一条代理记录")
      return
    }

    try {
      setIsSubmittingBatch(true)
      setErrorMessage(null)
      setBatchResult(null)
      const response = await fetch(`${API_BASE}/api/proxies/batch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          items,
          protocol: batchProtocol,
          region: batchRegion.trim() || null,
          type: poolType,
        }),
      })
      const payload = await response.json()
      if (!response.ok) {
        throw new Error(payload?.message || "批量添加请求失败")
      }

      const successCount = Number(payload?.success_count ?? 0)
      const failureCount = Number(payload?.failure_count ?? 0)
      if (successCount <= 0) {
        throw new Error(payload?.message || "批量添加失败")
      }

      let resultText = `批量添加完成：成功 ${successCount} 条，失败 ${failureCount} 条。`
      const failures = Array.isArray(payload?.failures) ? payload.failures : []
      if (failures.length > 0) {
        const preview = failures
          .slice(0, 2)
          .map(
            (item: { raw?: string; reason?: string }) =>
              `${item.raw ?? "unknown"} => ${item.reason ?? "失败"}`
          )
          .join("；")
        resultText += ` 示例失败：${preview}`
      }
      setBatchResult(resultText)
      setBatchInput("")
      await loadProxies()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "批量添加失败")
    } finally {
      setIsSubmittingBatch(false)
    }
  }

  const handleDeleteProxy = async (proxyId: string) => {
    const confirmed = window.confirm("确认删除该代理吗？")
    if (!confirmed) return
    try {
      setIsDeletingProxyId(proxyId)
      setErrorMessage(null)
      const response = await fetch(`${API_BASE}/api/proxies/${proxyId}`, {
        method: "DELETE",
      })
      const payload = await response.json()
      if (!response.ok || !payload?.success) {
        throw new Error(payload?.message || "删除代理失败")
      }
      if (selectedProxyId === proxyId) {
        setSelectedProxyId(null)
      }
      await loadProxies()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "删除代理失败")
    } finally {
      setIsDeletingProxyId(null)
    }
  }

  const handleTestProxy = async (proxyId: string) => {
    try {
      setIsTestingProxyId(proxyId)
      setErrorMessage(null)
      setStatusMessage(null)
      const response = await fetch(`${API_BASE}/api/proxies/${proxyId}/test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      })
      const payload = await response.json()
      if (!payload?.success) {
        setErrorMessage(payload?.message || "代理测试失败")
      }
      if (!response.ok && !payload?.success) {
        throw new Error(payload?.message || "代理测试失败")
      }
      await loadProxies()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "代理测试失败")
    } finally {
      setIsTestingProxyId(null)
    }
  }

  const handleTestSelectedProxies = async () => {
    if (selectedProxyIds.length === 0) {
      setErrorMessage("请先选择要检测的代理")
      return
    }

    try {
      setIsBatchTesting(true)
      setErrorMessage(null)
      setStatusMessage(null)

      const results = await Promise.all(
        selectedProxyIds.map(async (proxyId) => {
          try {
            const response = await fetch(`${API_BASE}/api/proxies/${proxyId}/test`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({}),
            })
            const payload = await response.json()
            return {
              proxyId,
              success: Boolean(payload?.success),
              message: String(payload?.message || "检测失败"),
            }
          } catch (error) {
            return {
              proxyId,
              success: false,
              message: error instanceof Error ? error.message : "检测失败",
            }
          }
        })
      )

      const successCount = results.filter((item) => item.success).length
      const failureCount = results.length - successCount
      let message = `健康检测完成：成功 ${successCount} 条，失败 ${failureCount} 条。`
      if (failureCount > 0) {
        const preview = results
          .filter((item) => !item.success)
          .slice(0, 2)
          .map((item) => `${item.proxyId.slice(0, 6)}... => ${item.message}`)
          .join("；")
        if (preview) {
          message += ` 示例失败：${preview}`
        }
      }
      setStatusMessage(message)
      await loadProxies()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "批量健康检测失败")
    } finally {
      setIsBatchTesting(false)
    }
  }

  const handleDeleteSelectedProxies = async () => {
    if (selectedProxyIds.length === 0) {
      setErrorMessage("请先选择要删除的代理")
      return
    }
    const confirmed = window.confirm(`确认删除选中的 ${selectedProxyIds.length} 条代理吗？`)
    if (!confirmed) return

    try {
      setIsBatchDeleting(true)
      setErrorMessage(null)
      setStatusMessage(null)

      let successCount = 0
      let failureCount = 0
      for (const proxyId of selectedProxyIds) {
        try {
          const response = await fetch(`${API_BASE}/api/proxies/${proxyId}`, {
            method: "DELETE",
          })
          const payload = await response.json()
          if (response.ok && payload?.success) {
            successCount++
          } else {
            failureCount++
          }
        } catch {
          failureCount++
        }
      }

      setSelectedProxyIds([])
      setStatusMessage(`删除完成：成功 ${successCount} 条，失败 ${failureCount} 条。`)
      await loadProxies()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "批量删除失败")
    } finally {
      setIsBatchDeleting(false)
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
                <span>{isAllSelected ? "取消全选" : "全选代理"}</span>
              </button>
              <button
                onClick={() => void handleTestSelectedProxies()}
                disabled={selectedProxyIds.length === 0 || isBatchTesting || isBatchDeleting}
                className="inline-flex items-center gap-1.5 rounded-full border border-white/[0.12] px-3.5 py-1 text-[13px] font-medium text-zinc-200 transition-colors duration-100 hover:bg-white/[0.05] disabled:cursor-not-allowed disabled:opacity-50"
              >
                <span>
                  {isBatchTesting
                    ? "检测中..."
                    : `健康度检测${selectedProxyIds.length > 0 ? ` (${selectedProxyIds.length})` : ""}`}
                </span>
              </button>
              <button
                onClick={() => void handleDeleteSelectedProxies()}
                disabled={selectedProxyIds.length === 0 || isBatchDeleting || isBatchTesting}
                className="inline-flex items-center gap-1.5 rounded-full border border-red-400/25 px-3.5 py-1 text-[13px] font-medium text-red-300 transition-colors duration-100 hover:bg-red-500/10 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Trash2 className="size-3.5" />
                <span>
                  {isBatchDeleting
                    ? "删除中..."
                    : `删除选中${selectedProxyIds.length > 0 ? ` (${selectedProxyIds.length})` : ""}`}
                </span>
              </button>
            </>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button className="inline-flex items-center gap-1.5 rounded-full bg-white px-3.5 py-1 text-[13px] font-medium text-black transition-colors duration-100 hover:bg-zinc-200">
                <Plus className="size-3.5" />
                <span>添加代理</span>
                <ChevronDown className="size-3.5" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-40 border-white/[0.12] bg-zinc-900 text-zinc-100">
              <DropdownMenuItem onSelect={() => setSingleOpen(true)}>添加单个代理</DropdownMenuItem>
              <DropdownMenuItem onSelect={() => setBatchOpen(true)}>批量添加代理</DropdownMenuItem>
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
            ) : proxyItems.length === 0 ? (
              <div className="mx-5 rounded-lg border border-white/[0.08] bg-white/[0.02] px-4 py-3 text-sm text-zinc-400">
                暂无代理记录。
              </div>
            ) : (
              <>
                {poolProxyDrawers.map((drawer) => {
                  const DrawerIcon = drawer.icon
                  const proxies = monitorProxiesByStatus[drawer.id]
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
                            <span className="text-zinc-500">({proxies.length})</span>
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
                          {proxies.length > 0 ? (
                            <ul className="divide-y divide-white/[0.05]">
                              {proxies.map((proxy) => {
                                const isSelected = selectedProxyId === proxy.id
                                const isChecked = selectedProxyIds.includes(proxy.id)
                                const rowCheckResult = proxy.last_check_result
                                const proxyIsDead = isProxyDead(proxy)
                                const rowScore = rowCheckResult?.score
                                const rowLatencyMs =
                                  rowCheckResult?.latency_ms ?? proxy.last_latency_ms
                                const twitterUnlockState =
                                  resolveTwitterUnlockState(rowCheckResult)
                                return (
                                  <li key={proxy.id}>
                                    <button
                                      type="button"
                                      onClick={() => {
                                        if (selectMode) {
                                          toggleProxySelect(proxy.id)
                                          return
                                        }
                                        setSelectedProxyId((prev) =>
                                          prev === proxy.id ? null : proxy.id
                                        )
                                      }}
                                      className={cn(
                                        "flex h-11 w-full items-center justify-between px-5 text-left transition-colors hover:bg-white/[0.025]",
                                        (isSelected || (selectMode && isChecked)) && "bg-white/[0.05]"
                                      )}
                                    >
                                      <div className="min-w-0 pr-3">
                                        <div className="flex min-w-0 items-center gap-2.5 text-sm text-zinc-200">
                                          {selectMode &&
                                            (isChecked ? (
                                              <CheckCircle2 className="size-4 shrink-0 text-emerald-400" />
                                            ) : (
                                              <Circle className="size-4 shrink-0 text-zinc-500" />
                                            ))}
                                          <Wifi className="size-4 shrink-0 text-zinc-500" />
                                          <span className="truncate">
                                            {proxy.ip}:{proxy.port}
                                          </span>
                                          <span className="mx-1 text-zinc-600">·</span>
                                          <div className="flex min-w-0 items-center gap-1 overflow-hidden">
                                            {proxyIsDead ? (
                                              <span className="inline-flex h-5 items-center rounded-full border border-red-400/35 bg-red-500/10 px-2 text-[10px] font-medium text-red-300">
                                                无效
                                              </span>
                                            ) : (
                                              <>
                                                <span className="inline-flex h-5 items-center rounded-full border border-white/[0.18] bg-white/[0.06] px-2 text-[10px] text-zinc-300">
                                                  评分 {rowScore ?? "-"}
                                                </span>
                                                <span className="inline-flex h-5 items-center rounded-full border border-white/[0.18] bg-white/[0.06] px-2 text-[10px] text-zinc-300">
                                                  延迟 {rowLatencyMs != null ? `${rowLatencyMs}ms` : "-"}
                                                </span>
                                                <span
                                                  className={cn(
                                                    "inline-flex h-5 items-center rounded-full border px-2 text-[10px]",
                                                    twitterUnlockState === "ok"
                                                      ? "border-emerald-400/35 bg-emerald-500/10 text-emerald-300"
                                                      : twitterUnlockState === "fail"
                                                        ? "border-red-400/35 bg-red-500/10 text-red-300"
                                                        : "border-white/[0.18] bg-white/[0.06] text-zinc-300"
                                                  )}
                                                >
                                                  推特
                                                  {twitterUnlockState === "ok"
                                                    ? " 已解锁"
                                                    : twitterUnlockState === "fail"
                                                      ? " 未解锁"
                                                      : " -"}
                                                </span>
                                              </>
                                            )}
                                          </div>
                                        </div>
                                      </div>
                                      <span className="shrink-0 text-xs tabular-nums text-zinc-500">
                                        {formatDateTime(proxy.created_at)}
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
              selectedProxy ? "w-[360px] xl:w-[420px] opacity-100" : "w-0 opacity-0"
            )}
          >
            <div
              className={cn(
                "min-h-0 h-full px-5 py-4 transition-opacity duration-200",
                selectedProxy ? "opacity-100 delay-75" : "pointer-events-none opacity-0"
              )}
            >
              {selectedProxy && (
                <div className="flex min-h-0 h-full flex-col">
                  <div className="flex items-start justify-between border-b border-white/[0.06] pb-3">
                    <div className="pr-3">
                      <p className="text-sm text-zinc-100">
                        {selectedProxy.ip}:{selectedProxy.port}
                      </p>
                      <p className="mt-1 text-xs leading-relaxed text-zinc-500">
                        {poolLabel} / {getStatusLabel(selectedProxy.status)}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => setSelectedProxyId(null)}
                      className="inline-flex size-7 items-center justify-center rounded-md text-zinc-500 transition-colors hover:bg-white/[0.04] hover:text-zinc-300"
                      aria-label="关闭详情面板"
                    >
                      <X className="size-4" />
                    </button>
                  </div>

                  <div className="mt-4 space-y-2 text-sm">
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-zinc-500">协议</span>
                      <span className="text-zinc-200">
                        {String(selectedProxy.protocol || "").toUpperCase()}
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-zinc-500">状态</span>
                      <span
                        className={cn(
                          "inline-flex h-6 items-center rounded-full border px-2.5 text-[11px]",
                          getStatusClass(selectedProxy.status)
                        )}
                      >
                        {getStatusLabel(selectedProxy.status)}
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-zinc-500">账号</span>
                      <span className="text-zinc-200">{selectedProxy.username || "-"}</span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-zinc-500">区域</span>
                      <span className="text-zinc-200">{selectedProxy.region || "-"}</span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-zinc-500">最近检测</span>
                      <span className="text-zinc-200">
                        {formatDateTime(selectedProxy.last_checked_at)}
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-zinc-500">延迟</span>
                      <span className="text-zinc-200">
                        {selectedCheckResult?.latency_ms != null
                          ? `${selectedCheckResult.latency_ms}ms`
                          : selectedProxy.last_latency_ms != null
                            ? `${selectedProxy.last_latency_ms}ms`
                          : "-"}
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-zinc-500">评分</span>
                      <span className="text-zinc-200">
                        {selectedCheckResult?.score != null ? selectedCheckResult.score : "-"}
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-zinc-500">落地 IP</span>
                      <span className="text-zinc-200">
                        {selectedCheckResult?.real_ip || "-"}
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-zinc-500">节点类型</span>
                      <span className="text-zinc-200">
                        {selectedCheckResult?.proxy_type || "-"}
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-zinc-500">落地位置</span>
                      <span className="text-zinc-200">
                        {formatResolvedLocation(selectedCheckResult)}
                      </span>
                    </div>
                  </div>

                  <div className="mt-5 min-h-0 flex-1 overflow-auto rounded-lg border border-white/[0.08] bg-black/35 p-3">
                    <p className="text-[11px] uppercase tracking-[0.12em] text-zinc-500">
                      检测结果
                    </p>
                    <div className="mt-2 text-[12px] leading-5 text-zinc-400">
                      <p>
                        {selectedCheckResult?.error
                          ? `❌ ${extractFriendlyError(selectedProxy)}`
                          : selectedCheckResult?.message ||
                            selectedProxy.last_error ||
                            "最近检测无错误"}
                      </p>
                      {selectedUnlockServices.length > 0 ? (
                        <div className="mt-2 space-y-1">
                          {selectedUnlockServices.map((service, index) => (
                            <p key={`${service.name || "service"}-${index}`}>
                              {service.ok ? "✅" : "❌"} {service.name || "unknown"}
                              {service.latency_seconds != null
                                ? ` (${service.latency_seconds}s)`
                                : ""}
                            </p>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  </div>

                  <div className="mt-3 flex justify-end gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      className="rounded-full border-white/[0.18] bg-white/[0.03] text-zinc-200 hover:bg-white/[0.08]"
                      onClick={() => void handleTestProxy(selectedProxy.id)}
                      disabled={
                        isTestingProxyId === selectedProxy.id ||
                        isDeletingProxyId === selectedProxy.id ||
                        isBatchTesting
                      }
                    >
                      <Wifi className="size-3.5" />
                      {isTestingProxyId === selectedProxy.id ? "测试中..." : "测试代理"}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      className="rounded-full border-red-400/40 bg-red-500/10 text-red-300 hover:bg-red-500/20"
                      onClick={() => void handleDeleteProxy(selectedProxy.id)}
                      disabled={
                        isDeletingProxyId === selectedProxy.id ||
                        isTestingProxyId === selectedProxy.id
                      }
                    >
                      <Trash2 className="size-3.5" />
                      {isDeletingProxyId === selectedProxy.id ? "删除中..." : "删除代理"}
                    </Button>
                  </div>
                </div>
              )}
            </div>
          </aside>
        </div>
      </main>

      <Dialog open={singleOpen} onOpenChange={setSingleOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>添加单个代理</DialogTitle>
            <DialogDescription>填写一条代理并选择协议类型。</DialogDescription>
          </DialogHeader>
          <div className="mt-4 space-y-4">
            <div>
              <p className="mb-2 text-xs tracking-[0.12em] uppercase text-zinc-500">代理协议</p>
              <ProtocolSelector
                value={singleForm.protocol}
                onChange={(value) =>
                  setSingleForm((prev) => ({
                    ...prev,
                    protocol: value,
                  }))
                }
                disabled={isSubmittingSingle}
              />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <input
                value={singleForm.ip}
                onChange={(event) =>
                  setSingleForm((prev) => ({ ...prev, ip: event.target.value }))
                }
                placeholder="IP 或域名"
                className="h-9 rounded-full border border-white/[0.12] bg-white/[0.03] px-4 text-[13px] text-zinc-200 placeholder:text-zinc-500 outline-none transition-colors focus:border-white/[0.22] focus:bg-white/[0.06]"
              />
              <input
                value={singleForm.port}
                onChange={(event) =>
                  setSingleForm((prev) => ({ ...prev, port: event.target.value }))
                }
                placeholder="端口"
                className="h-9 rounded-full border border-white/[0.12] bg-white/[0.03] px-4 text-[13px] text-zinc-200 placeholder:text-zinc-500 outline-none transition-colors focus:border-white/[0.22] focus:bg-white/[0.06]"
              />
              <input
                value={singleForm.username}
                onChange={(event) =>
                  setSingleForm((prev) => ({ ...prev, username: event.target.value }))
                }
                placeholder="用户名（可选）"
                className="h-9 rounded-full border border-white/[0.12] bg-white/[0.03] px-4 text-[13px] text-zinc-200 placeholder:text-zinc-500 outline-none transition-colors focus:border-white/[0.22] focus:bg-white/[0.06]"
              />
              <input
                value={singleForm.password}
                onChange={(event) =>
                  setSingleForm((prev) => ({ ...prev, password: event.target.value }))
                }
                placeholder="密码（可选）"
                className="h-9 rounded-full border border-white/[0.12] bg-white/[0.03] px-4 text-[13px] text-zinc-200 placeholder:text-zinc-500 outline-none transition-colors focus:border-white/[0.22] focus:bg-white/[0.06]"
              />
            </div>
            <input
              value={singleForm.region}
              onChange={(event) =>
                setSingleForm((prev) => ({ ...prev, region: event.target.value }))
              }
              placeholder="区域（可选，例如 us/jp/uk）"
              className="h-9 w-full rounded-full border border-white/[0.12] bg-white/[0.03] px-4 text-[13px] text-zinc-200 placeholder:text-zinc-500 outline-none transition-colors focus:border-white/[0.22] focus:bg-white/[0.06]"
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
            <DialogTitle>批量添加代理</DialogTitle>
            <DialogDescription>
              每行一条，支持 <code>host:port</code>、<code>host:port:user:pass</code> 或标准 URL 格式。
            </DialogDescription>
          </DialogHeader>
          <div className="mt-4 space-y-4">
            <div>
              <p className="mb-2 text-xs tracking-[0.12em] uppercase text-zinc-500">
                批量协议（统一套用）
              </p>
              <ProtocolSelector
                value={batchProtocol}
                onChange={setBatchProtocol}
                disabled={isSubmittingBatch}
              />
            </div>
            <textarea
              value={batchInput}
              onChange={(event) => setBatchInput(event.target.value)}
              placeholder={
                "62.112.11.191:12315\nasdata.lumidaili.com:10000:userID-xxx:pass\nhttp://user:pass@host:port"
              }
              className="min-h-[140px] w-full rounded-lg border border-white/[0.12] bg-white/[0.03] px-3 py-2 text-[13px] text-zinc-200 placeholder:text-zinc-500 outline-none transition-colors focus:border-white/[0.22] focus:bg-white/[0.06]"
            />
            <input
              value={batchRegion}
              onChange={(event) => setBatchRegion(event.target.value)}
              placeholder="区域（可选，例如 us/jp/uk）"
              className="h-9 w-full rounded-full border border-white/[0.12] bg-white/[0.03] px-4 text-[13px] text-zinc-200 placeholder:text-zinc-500 outline-none transition-colors focus:border-white/[0.22] focus:bg-white/[0.06]"
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
              {isSubmittingBatch ? "提交中..." : "开始批量添加"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
