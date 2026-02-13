import { useMemo, useState, type ComponentType } from "react"
import {
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  PauseCircle,
  Plus,
  SlidersHorizontal,
  UserRound,
  X,
} from "lucide-react"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { cn } from "@/lib/utils"

type AccountStatus = "healthy" | "risk" | "paused"

type AccountDrawer = {
  id: AccountStatus
  label: string
  icon: ComponentType<{ className?: string }>
  emptyTitle: string
  emptyDescription: string
}

type AccountItem = {
  id: string
  name: string
  description: string
  createdAt: string
  platform: string
  proxyPool: string
  status: AccountStatus
}

type FilterOption = {
  id: "all" | AccountStatus
  label: string
  icon: ComponentType<{ className?: string }>
}

const filters: FilterOption[] = [
  { id: "all", label: "全部账号", icon: UserRound },
  { id: "healthy", label: "正常账号", icon: CheckCircle2 },
  { id: "risk", label: "风控账号", icon: CircleAlert },
  { id: "paused", label: "停用账号", icon: PauseCircle },
]

const accountDrawers: AccountDrawer[] = [
  {
    id: "healthy",
    label: "正常账号",
    icon: CheckCircle2,
    emptyTitle: "暂无正常账号",
    emptyDescription: "接入并验证账号后，会在这里展示可用账号。",
  },
  {
    id: "risk",
    label: "风控账号",
    icon: CircleAlert,
    emptyTitle: "暂无风控账号",
    emptyDescription: "触发风控或限流的账号将进入该列表，便于集中处理。",
  },
  {
    id: "paused",
    label: "停用账号",
    icon: PauseCircle,
    emptyTitle: "暂无停用账号",
    emptyDescription: "手动停用或失效的账号会展示在这里。",
  },
]

const accountItems: AccountItem[] = [
  {
    id: "account-x-01",
    name: "@mcn_global_ops",
    description: "Twitter/X 主发布账号",
    createdAt: "2026-02-12",
    platform: "Twitter/X",
    proxyPool: "发布代理池",
    status: "healthy",
  },
  {
    id: "account-x-02",
    name: "@mcn_backup_a",
    description: "备用账号 A，低频发布",
    createdAt: "2026-02-11",
    platform: "Twitter/X",
    proxyPool: "发布代理池",
    status: "healthy",
  },
  {
    id: "account-x-03",
    name: "@mcn_risk_check",
    description: "近期出现验证码校验",
    createdAt: "2026-02-10",
    platform: "Twitter/X",
    proxyPool: "监控代理池",
    status: "risk",
  },
  {
    id: "account-x-04",
    name: "@mcn_pause_sample",
    description: "人工暂停，等待凭证更新",
    createdAt: "2026-02-08",
    platform: "Twitter/X",
    proxyPool: "发布代理池",
    status: "paused",
  },
]

export function AccountMainContent() {
  const [activeFilter, setActiveFilter] = useState<FilterOption["id"]>("all")
  const [openMap, setOpenMap] = useState<Record<AccountStatus, boolean>>({
    healthy: true,
    risk: false,
    paused: false,
  })
  const [selectedAccountId, setSelectedAccountId] = useState<string | null>(null)

  const itemsByStatus = useMemo(() => {
    return {
      healthy: accountItems.filter((item) => item.status === "healthy"),
      risk: accountItems.filter((item) => item.status === "risk"),
      paused: accountItems.filter((item) => item.status === "paused"),
    }
  }, [])

  const selectedAccount =
    accountItems.find((item) => item.id === selectedAccountId) ?? null

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-11 shrink-0 items-center justify-between border-b border-white/8 px-5">
        <div className="flex items-center gap-0.5">
          <button className="mr-1 inline-flex items-center gap-1.5 rounded-full border border-white/12 px-3 py-1 text-[13px] font-medium text-zinc-300 transition-colors duration-100 hover:bg-white/5">
            <SlidersHorizontal className="size-3.5" />
            <span>筛选</span>
          </button>

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

        <button className="inline-flex items-center gap-1.5 rounded-full bg-white px-3.5 py-1 text-[13px] font-medium text-black transition-colors duration-100 hover:bg-zinc-200">
          <Plus className="size-3.5" />
          <span>新增账号</span>
        </button>
      </div>

      <main className="min-h-0 flex-1 overflow-hidden">
        <div className="h-full w-full overflow-hidden">
          <div className="flex h-full">
            <div className="min-w-0 flex-1 overflow-y-auto">
              {accountDrawers.map((drawer) => {
                const isOpen = Boolean(openMap[drawer.id])
                const accounts = itemsByStatus[drawer.id]
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
                        {accounts.length > 0 ? (
                          <ul className="divide-y divide-white/5">
                            {accounts.map((account) => {
                              const isSelected = selectedAccountId === account.id

                              return (
                                <li key={account.id}>
                                  <button
                                    type="button"
                                    onClick={() =>
                                      setSelectedAccountId((prev) =>
                                        prev === account.id ? null : account.id
                                      )
                                    }
                                    className={cn(
                                      "flex h-11 w-full items-center justify-between px-5 text-left transition-colors hover:bg-white/2.5",
                                      isSelected && "bg-white/5"
                                    )}
                                  >
                                    <div className="min-w-0 pr-3">
                                      <div className="flex items-center gap-2.5 truncate text-sm text-zinc-200">
                                        <UserRound className="size-4 shrink-0 text-zinc-500" />
                                        <span className="truncate">{account.name}</span>
                                        <span className="mx-1 text-zinc-600">·</span>
                                        <span className="truncate text-zinc-500">
                                          {account.description}
                                        </span>
                                      </div>
                                    </div>
                                    <span className="shrink-0 text-xs tabular-nums text-zinc-500">
                                      {account.createdAt}
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
                selectedAccount ? "w-90 xl:w-105 opacity-100" : "w-0 opacity-0"
              )}
            >
              <div
                className={cn(
                  "min-h-0 h-full px-5 py-4 transition-opacity duration-200",
                  selectedAccount
                    ? "opacity-100 delay-75"
                    : "pointer-events-none opacity-0"
                )}
              >
                {selectedAccount && (
                  <div className="flex min-h-0 h-full flex-col">
                    <div className="flex items-start justify-between border-b border-white/6 pb-3">
                      <div className="pr-3">
                        <p className="text-sm text-zinc-100">{selectedAccount.name}</p>
                        <p className="mt-1 text-xs leading-relaxed text-zinc-500">
                          {selectedAccount.description}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => setSelectedAccountId(null)}
                        className="inline-flex size-7 items-center justify-center rounded-md text-zinc-500 transition-colors hover:bg-white/4 hover:text-zinc-300"
                        aria-label="关闭账号详情面板"
                      >
                        <X className="size-4" />
                      </button>
                    </div>

                    <div className="flex min-h-0 flex-1 flex-col py-4">
                      <div className="space-y-3">
                        <div className="flex items-center justify-between gap-3 text-sm">
                          <span className="text-zinc-500">平台</span>
                          <span className="text-zinc-200">{selectedAccount.platform}</span>
                        </div>
                        <div className="flex items-center justify-between gap-3 text-sm">
                          <span className="text-zinc-500">代理池</span>
                          <span className="text-zinc-200">{selectedAccount.proxyPool}</span>
                        </div>
                        <div className="flex items-center justify-between gap-3 text-sm">
                          <span className="text-zinc-500">创建日期</span>
                          <span className="text-zinc-200">{selectedAccount.createdAt}</span>
                        </div>
                      </div>

                      <div className="mt-5 flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-white/8 bg-black/35 p-3">
                        <p className="text-[11px] uppercase tracking-[0.12em] text-zinc-500">
                          账号备注
                        </p>
                        <div className="mt-2 min-h-0 flex-1 overflow-auto pr-1 text-[12px] leading-6 text-zinc-400 [&::-webkit-scrollbar]:hidden [-ms-overflow-style:'none'] [scrollbar-width:'none']">
                          <p>
                            当前为样式迁移占位区域，可在下一步接入账号授权信息、健康检查日志、
                            Cookie 到期时间与平台限流状态等真实数据。
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
