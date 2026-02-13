import { useEffect, useMemo, useState, type ComponentType } from "react"
import {
  Circle,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  Clock3,
  Plus,
  ShieldCheck,
  SlidersHorizontal,
  X,
} from "lucide-react"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { cn } from "@/lib/utils"

type ProxyPoolType = "publish" | "monitor"
type ProxyStatus = "available" | "unstable" | "cooldown"
type ConnectivityState = "idle" | "testing" | "success" | "failed"

type ProxyDrawer = {
  id: ProxyStatus
  label: string
  icon: ComponentType<{ className?: string }>
  emptyTitle: string
  emptyDescription: string
}

type ProxyItem = {
  id: string
  endpoint: string
  description: string
  updatedAt: string
  provider: string
  region: string
  protocol: string
  successRate: string
  status: ProxyStatus
}

type FilterOption = {
  id: "all" | ProxyStatus
  label: string
  icon: ComponentType<{ className?: string }>
}

const filters: FilterOption[] = [
  { id: "all", label: "全部代理", icon: ShieldCheck },
  { id: "available", label: "可用代理", icon: CheckCircle2 },
  { id: "unstable", label: "异常代理", icon: CircleAlert },
  { id: "cooldown", label: "待验证代理", icon: Clock3 },
]

const proxyDrawers: ProxyDrawer[] = [
  {
    id: "available",
    label: "可用代理",
    icon: CheckCircle2,
    emptyTitle: "暂无可用代理",
    emptyDescription: "代理连通性通过后会展示在这里。",
  },
  {
    id: "unstable",
    label: "异常代理",
    icon: CircleAlert,
    emptyTitle: "暂无异常代理",
    emptyDescription: "请求超时或失败率异常的代理会被归类到这里。",
  },
  {
    id: "cooldown",
    label: "待验证代理",
    icon: Clock3,
    emptyTitle: "暂无待验证代理",
    emptyDescription: "被临时限流后进入冷却期的代理会在这里等待恢复。",
  },
]

function getMockProxyItems(poolType: ProxyPoolType): ProxyItem[] {
  if (poolType === "publish") {
    return [
      {
        id: "publish-proxy-1",
        endpoint: "45.67.12.80:8080",
        description: "主发布出口代理，峰值稳定",
        updatedAt: "2026-02-12",
        provider: "ProxyLab",
        region: "US-East",
        protocol: "HTTP",
        successRate: "98.4%",
        status: "available",
      },
      {
        id: "publish-proxy-2",
        endpoint: "31.92.16.44:3128",
        description: "备用发布代理，低时延",
        updatedAt: "2026-02-11",
        provider: "ProxyLab",
        region: "EU-West",
        protocol: "HTTPS",
        successRate: "96.9%",
        status: "available",
      },
      {
        id: "publish-proxy-3",
        endpoint: "103.220.15.9:7890",
        description: "最近有突发丢包",
        updatedAt: "2026-02-11",
        provider: "NetBridge",
        region: "AP-SG",
        protocol: "SOCKS5",
        successRate: "81.2%",
        status: "unstable",
      },
      {
        id: "publish-proxy-4",
        endpoint: "172.77.6.52:9000",
        description: "触发限频，已自动冷却",
        updatedAt: "2026-02-10",
        provider: "NetBridge",
        region: "US-West",
        protocol: "HTTP",
        successRate: "74.1%",
        status: "cooldown",
      },
    ]
  }

  return [
    {
      id: "monitor-proxy-1",
      endpoint: "111.14.8.90:8800",
      description: "数据监控轮询主代理",
      updatedAt: "2026-02-12",
      provider: "EdgeProxy",
      region: "JP-Tokyo",
      protocol: "HTTPS",
      successRate: "97.6%",
      status: "available",
    },
    {
      id: "monitor-proxy-2",
      endpoint: "67.45.129.13:8081",
      description: "高并发监控备用代理",
      updatedAt: "2026-02-11",
      provider: "EdgeProxy",
      region: "US-Central",
      protocol: "HTTP",
      successRate: "95.8%",
      status: "available",
    },
    {
      id: "monitor-proxy-3",
      endpoint: "88.31.72.200:8899",
      description: "偶发连接复位",
      updatedAt: "2026-02-10",
      provider: "TunnelHub",
      region: "EU-Central",
      protocol: "SOCKS5",
      successRate: "79.5%",
      status: "unstable",
    },
    {
      id: "monitor-proxy-4",
      endpoint: "121.204.67.14:443",
      description: "被目标平台限流，冷却中",
      updatedAt: "2026-02-09",
      provider: "TunnelHub",
      region: "AP-HK",
      protocol: "HTTPS",
      successRate: "71.0%",
      status: "cooldown",
    },
  ]
}

function formatDateLabel(value: Date = new Date()): string {
  return value.toISOString().slice(0, 10)
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms)
  })
}

function buildSeed(input: string): number {
  return input.split("").reduce((sum, char) => sum + char.charCodeAt(0), 0)
}

function evaluateConnectivity(proxy: ProxyItem): {
  reachable: boolean
  latencyMs: number
  status: ProxyStatus
  successRate: string
} {
  const seed = buildSeed(proxy.endpoint)
  const reachable = seed % 4 !== 0
  const latencyMs = 90 + (seed % 260)
  const status: ProxyStatus = !reachable
    ? "cooldown"
    : latencyMs > 220
      ? "unstable"
      : "available"
  const ratio = reachable
    ? 90 + (seed % 10) + ((seed >> 1) % 10) / 10
    : 45 + (seed % 25) + ((seed >> 2) % 10) / 10
  return {
    reachable,
    latencyMs,
    status,
    successRate: `${Math.min(ratio, 99.9).toFixed(1)}%`,
  }
}

function getConnectivityBadgeLabel(state: ConnectivityState): string {
  if (state === "testing") return "测试中"
  if (state === "success") return "联通正常"
  if (state === "failed") return "联通失败"
  return ""
}

export function ProxyPoolMainContent({ poolType }: { poolType: ProxyPoolType }) {
  const [activeFilter, setActiveFilter] = useState<FilterOption["id"]>("all")
  const [openMap, setOpenMap] = useState<Record<ProxyStatus, boolean>>({
    available: true,
    unstable: false,
    cooldown: false,
  })
  const [proxyItems, setProxyItems] = useState<ProxyItem[]>(() =>
    getMockProxyItems(poolType)
  )
  const [selectedProxyId, setSelectedProxyId] = useState<string | null>(null)
  const [selectMode, setSelectMode] = useState(false)
  const [selectedProxyIds, setSelectedProxyIds] = useState<string[]>([])
  const [isDeleting, setIsDeleting] = useState(false)
  const [isTestingConnectivity, setIsTestingConnectivity] = useState(false)
  const [connectivityStateById, setConnectivityStateById] = useState<
    Record<string, ConnectivityState>
  >({})
  const [latencyById, setLatencyById] = useState<Record<string, number>>({})

  useEffect(() => {
    setProxyItems(getMockProxyItems(poolType))
    setSelectedProxyId(null)
    setSelectMode(false)
    setSelectedProxyIds([])
    setIsTestingConnectivity(false)
    setConnectivityStateById({})
    setLatencyById({})
  }, [poolType])

  const itemsByStatus = useMemo(() => {
    return {
      available: proxyItems.filter((item) => item.status === "available"),
      unstable: proxyItems.filter((item) => item.status === "unstable"),
      cooldown: proxyItems.filter((item) => item.status === "cooldown"),
    }
  }, [proxyItems])

  const selectedProxy =
    proxyItems.find((item) => item.id === selectedProxyId) ?? null

  const poolLabel = poolType === "publish" ? "发布代理池" : "监控代理池"
  const selectableProxyIds = useMemo(() => {
    if (activeFilter === "all") {
      return proxyItems.map((item) => item.id)
    }
    return proxyItems.filter((item) => item.status === activeFilter).map((item) => item.id)
  }, [activeFilter, proxyItems])
  const selectedCount = selectedProxyIds.length
  const allVisibleSelected =
    selectableProxyIds.length > 0 &&
    selectableProxyIds.every((id) => selectedProxyIds.includes(id))

  const handleToggleSelectMode = () => {
    setSelectMode((prev) => {
      const next = !prev
      if (next) {
        setSelectedProxyId(null)
      } else {
        setSelectedProxyIds([])
      }
      return next
    })
  }

  const toggleProxySelection = (proxyId: string) => {
    setSelectedProxyIds((prev) =>
      prev.includes(proxyId) ? prev.filter((id) => id !== proxyId) : [...prev, proxyId]
    )
  }

  const handleToggleSelectAll = () => {
    if (selectableProxyIds.length === 0) return
    setSelectedProxyIds((prev) => {
      const isAllSelected = selectableProxyIds.every((id) => prev.includes(id))
      if (isAllSelected) {
        return prev.filter((id) => !selectableProxyIds.includes(id))
      }
      return Array.from(new Set([...prev, ...selectableProxyIds]))
    })
  }

  const handleTestSelectedConnectivity = async () => {
    if (selectedProxyIds.length === 0 || isTestingConnectivity) return
    setIsTestingConnectivity(true)

    setConnectivityStateById((prev) => {
      const next = { ...prev }
      selectedProxyIds.forEach((id) => {
        next[id] = "testing"
      })
      return next
    })

    const results = await Promise.all(
      selectedProxyIds.map(async (id, index) => {
        const proxy = proxyItems.find((item) => item.id === id)
        if (!proxy) return null
        await sleep(220 + index * 90 + (buildSeed(proxy.endpoint) % 160))
        const result = evaluateConnectivity(proxy)
        return { id, ...result }
      })
    )

    const resultMap = new Map(
      results
        .filter((result): result is NonNullable<typeof result> => Boolean(result))
        .map((result) => [result.id, result])
    )

    setProxyItems((prev) =>
      prev.map((item) => {
        const result = resultMap.get(item.id)
        if (!result) return item
        return {
          ...item,
          status: result.status,
          successRate: result.successRate,
          updatedAt: formatDateLabel(),
        }
      })
    )

    setConnectivityStateById((prev) => {
      const next = { ...prev }
      resultMap.forEach((result, id) => {
        next[id] = result.reachable ? "success" : "failed"
      })
      return next
    })

    setLatencyById((prev) => {
      const next = { ...prev }
      resultMap.forEach((result, id) => {
        next[id] = result.latencyMs
      })
      return next
    })

    setIsTestingConnectivity(false)
  }

  const handleDeleteSelected = async () => {
    if (selectedProxyIds.length === 0 || isDeleting) return
    setIsDeleting(true)

    // 模拟API调用延迟
    await sleep(600)

    setProxyItems((prev) => prev.filter((item) => !selectedProxyIds.includes(item.id)))
    setSelectedProxyIds([])
    setIsDeleting(false)
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-11 shrink-0 items-center justify-between border-b border-white/8 px-5">
        <div className="flex items-center gap-0.5">
          <button className="mr-1 inline-flex items-center gap-1.5 rounded-full border border-white/12 px-3 py-1 text-[13px] font-medium text-zinc-300 transition-colors duration-100 hover:bg-white/5">
            <SlidersHorizontal className="size-3.5" />
            <span>筛选</span>
          </button>
          <button
            onClick={handleToggleSelectMode}
            className={cn(
              "mr-1 inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[13px] font-medium transition-colors duration-100",
              selectMode
                ? "border-white/26 bg-white/10 text-zinc-100"
                : "border-white/12 text-zinc-300 hover:bg-white/5"
            )}
          >
            <span>{selectMode ? "退出选择" : "选择"}</span>
          </button>
          {selectMode && (
            <button
              onClick={handleToggleSelectAll}
              className="mr-1 inline-flex items-center gap-1.5 rounded-full border border-white/12 px-3 py-1 text-[13px] font-medium text-zinc-300 transition-colors duration-100 hover:bg-white/5"
            >
              <span>{allVisibleSelected ? "取消全选" : "全选"}</span>
            </button>
          )}

          {filters.map((filter) => {
            const isActive = activeFilter === filter.id
            const Icon = filter.icon
            return (
              <button
                key={filter.id}
                onClick={() => setActiveFilter(filter.id)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[13px] font-medium transition-colors duration-100",
                  isActive
                    ? "bg-white/10 text-zinc-100"
                    : "text-zinc-500 hover:text-zinc-300 hover:bg-white/4"
                )}
              >
                <Icon className="size-3.5" />
                <span>{filter.label}</span>
              </button>
            )
          })}
        </div>

        <div className="flex items-center gap-2">
          {selectMode && (
            <>
              <button
                onClick={() => void handleTestSelectedConnectivity()}
                disabled={selectedCount === 0 || isTestingConnectivity || isDeleting}
                className="inline-flex h-7 items-center justify-center rounded-full border border-emerald-400/40 bg-emerald-500/10 px-3.5 text-[12px] font-medium text-emerald-300 transition-colors hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isTestingConnectivity
                  ? "测试中..."
                  : `测试联通${selectedCount > 0 ? ` (${selectedCount})` : ""}`}
              </button>

              <button
                onClick={() => void handleDeleteSelected()}
                disabled={selectedCount === 0 || isDeleting || isTestingConnectivity}
                className="inline-flex h-7 items-center justify-center rounded-full border border-red-400/40 bg-red-500/10 px-3.5 text-[12px] font-medium text-red-300 transition-colors hover:bg-red-500/20 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isDeleting
                  ? "删除中..."
                  : `删除代理${selectedCount > 0 ? ` (${selectedCount})` : ""}`}
              </button>
            </>
          )}

          <button className="inline-flex items-center gap-1.5 rounded-full bg-white px-3.5 py-1 text-[13px] font-medium text-black transition-colors duration-100 hover:bg-zinc-200">
            <Plus className="size-3.5" />
            <span>新增代理</span>
          </button>
        </div>
      </div>

      <main className="min-h-0 flex-1 overflow-hidden">
        <div className="h-full w-full overflow-hidden">
          <div className="flex h-full">
            <div className="min-w-0 flex-1 overflow-y-auto">
              {proxyDrawers.map((drawer) => {
                const isOpen = Boolean(openMap[drawer.id])
                const proxies = itemsByStatus[drawer.id]
                const shouldRenderDrawer =
                  activeFilter === "all" || activeFilter === drawer.id
                if (!shouldRenderDrawer) return null

                const DrawerIcon = drawer.icon

                return (
                  <Collapsible
                    key={drawer.id}
                    open={isOpen}
                    onOpenChange={(open) =>
                      setOpenMap((prev) => ({ ...prev, [drawer.id]: open }))
                    }
                    className="border-b border-white/5 first:border-t first:border-white/5"
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
                      <div className="overflow-hidden border-t border-white/5 bg-white/1">
                        {proxies.length > 0 ? (
                          <ul className="divide-y divide-white/5">
                            {proxies.map((proxy) => {
                              const isSelected = selectMode
                                ? selectedProxyIds.includes(proxy.id)
                                : selectedProxyId === proxy.id
                              const connectivityState =
                                connectivityStateById[proxy.id] ?? "idle"
                              const connectivityLabel =
                                getConnectivityBadgeLabel(connectivityState)
                              return (
                                <li key={proxy.id}>
                                  <button
                                    type="button"
                                    onClick={() => {
                                      if (selectMode) {
                                        toggleProxySelection(proxy.id)
                                        return
                                      }
                                      setSelectedProxyId((prev) =>
                                        prev === proxy.id ? null : proxy.id
                                      )
                                    }}
                                    className={cn(
                                      "flex h-11 w-full items-center justify-between px-5 text-left transition-colors hover:bg-white/2.5",
                                      isSelected && "bg-white/5"
                                    )}
                                  >
                                    <div className="min-w-0 pr-3">
                                      <div className="flex items-center gap-2.5 truncate text-sm text-zinc-200">
                                        {selectMode ? (
                                          isSelected ? (
                                            <CheckCircle2 className="size-4 shrink-0 text-emerald-400" />
                                          ) : (
                                            <Circle className="size-4 shrink-0 text-zinc-500" />
                                          )
                                        ) : null}
                                        <ShieldCheck className="size-4 shrink-0 text-zinc-500" />
                                        <span className="truncate">{proxy.endpoint}</span>
                                      </div>
                                    </div>
                                    <span className="flex shrink-0 items-center gap-2">
                                      {connectivityLabel && (
                                        <span
                                          className={cn(
                                            "inline-flex h-5 items-center rounded-full border px-2 text-[10px] font-medium",
                                            connectivityState === "testing" &&
                                              "border-sky-400/40 bg-sky-500/10 text-sky-300",
                                            connectivityState === "success" &&
                                              "border-emerald-400/40 bg-emerald-500/10 text-emerald-300",
                                            connectivityState === "failed" &&
                                              "border-red-400/40 bg-red-500/10 text-red-300"
                                          )}
                                        >
                                          {connectivityLabel}
                                        </span>
                                      )}
                                      <span className="text-xs tabular-nums text-zinc-500">
                                        {proxy.updatedAt}
                                      </span>
                                    </span>
                                  </button>
                                </li>
                              )
                            })}
                          </ul>
                        ) : (
                          <div className="px-5 py-4">
                            <div className="min-w-0">
                              <p className="text-sm text-zinc-300">
                                {drawer.emptyTitle}
                              </p>
                              <p className="mt-1 text-xs leading-relaxed text-zinc-500">
                                {drawer.emptyDescription}
                              </p>
                            </div>
                          </div>
                        )}
                      </div>
                    </CollapsibleContent>
                  </Collapsible>
                )
              })}
            </div>

            <aside
              className={cn(
                "min-h-0 shrink-0 overflow-hidden border-l border-white/6 bg-black/30 transition-[width,opacity] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]",
                selectedProxy ? "w-90 xl:w-105 opacity-100" : "w-0 opacity-0"
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
                    <div className="flex items-start justify-between border-b border-white/6 pb-3">
                      <div className="pr-3">
                        <p className="text-sm text-zinc-100">{selectedProxy.endpoint}</p>
                        <p className="mt-1 text-xs leading-relaxed text-zinc-500">
                          {selectedProxy.description}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => setSelectedProxyId(null)}
                        className="inline-flex size-7 items-center justify-center rounded-md text-zinc-500 transition-colors hover:bg-white/4 hover:text-zinc-300"
                        aria-label="关闭代理详情面板"
                      >
                        <X className="size-4" />
                      </button>
                    </div>

                    <div className="flex min-h-0 flex-1 flex-col py-4">
                      <div className="space-y-3">
                        <div className="flex items-center justify-between gap-3 text-sm">
                          <span className="text-zinc-500">所属池</span>
                          <span className="text-zinc-200">{poolLabel}</span>
                        </div>
                        <div className="flex items-center justify-between gap-3 text-sm">
                          <span className="text-zinc-500">服务商</span>
                          <span className="text-zinc-200">{selectedProxy.provider}</span>
                        </div>
                        <div className="flex items-center justify-between gap-3 text-sm">
                          <span className="text-zinc-500">区域</span>
                          <span className="text-zinc-200">{selectedProxy.region}</span>
                        </div>
                        <div className="flex items-center justify-between gap-3 text-sm">
                          <span className="text-zinc-500">协议</span>
                          <span className="text-zinc-200">{selectedProxy.protocol}</span>
                        </div>
                        <div className="flex items-center justify-between gap-3 text-sm">
                          <span className="text-zinc-500">成功率</span>
                          <span className="text-zinc-200">{selectedProxy.successRate}</span>
                        </div>
                        <div className="flex items-center justify-between gap-3 text-sm">
                          <span className="text-zinc-500">联通状态</span>
                          <span
                            className={cn(
                              "text-zinc-200",
                              (connectivityStateById[selectedProxy.id] ?? "idle") ===
                                "success" && "text-emerald-300",
                              (connectivityStateById[selectedProxy.id] ?? "idle") ===
                                "failed" && "text-red-300",
                              (connectivityStateById[selectedProxy.id] ?? "idle") ===
                                "testing" && "text-sky-300"
                            )}
                          >
                            {getConnectivityBadgeLabel(
                              connectivityStateById[selectedProxy.id] ?? "idle"
                            ) || "未测试"}
                          </span>
                        </div>
                        {latencyById[selectedProxy.id] != null && (
                          <div className="flex items-center justify-between gap-3 text-sm">
                            <span className="text-zinc-500">最近延迟</span>
                            <span className="text-zinc-200">
                              {latencyById[selectedProxy.id]} ms
                            </span>
                          </div>
                        )}
                      </div>

                      <div className="mt-5 flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-white/8 bg-black/35 p-3">
                        <p className="text-[11px] uppercase tracking-[0.12em] text-zinc-500">
                          代理备注
                        </p>
                        <div className="mt-2 min-h-0 flex-1 overflow-auto pr-1 text-[12px] leading-6 text-zinc-400 [&::-webkit-scrollbar]:hidden [-ms-overflow-style:'none'] [scrollbar-width:'none']">
                          <p>
                            当前为样式迁移占位内容。下一步可接入代理实时探活、延迟曲线、
                            失败原因采样与自动熔断策略。
                          </p>
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </aside>
          </div>
        </div>
      </main>
    </div>
  )
}
