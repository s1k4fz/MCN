import { useState } from "react"
import {
  CircleDot,
  CheckCircle2,
  XCircle,
  RefreshCw,
  ListFilter,
  SlidersHorizontal,
  Plus,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { CreateTaskDialog } from "@/components/dashboard/create-task-dialog"

interface FilterOption {
  id: string
  label: string
  icon: React.ComponentType<{ className?: string }>
}

const filters: FilterOption[] = [
  { id: "all", label: "全部任务", icon: ListFilter },
  { id: "running", label: "进行中", icon: CircleDot },
  { id: "completed", label: "已完成", icon: CheckCircle2 },
  { id: "failed", label: "执行失败", icon: XCircle },
  { id: "recurring", label: "常驻任务", icon: RefreshCw },
]

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000"

type CreateTaskPayload = {
  taskType: "collect"
  collectMode: "single-work" | "author" | null
  title: string
  description: string
  workLinks: string[]
  authorPlatform: "bilibili" | "douyin" | "xiaohongshu" | null
  authorCollectAction: "data-only" | "collect-download" | null
  authorUids: string[]
}

export function TaskFilterBar() {
  const [active, setActive] = useState("all")
  const [createOpen, setCreateOpen] = useState(false)

  const handleCreateTask = async (payload: CreateTaskPayload) => {
    if (payload.taskType !== "collect") {
      return
    }

    if (payload.collectMode === "author") {
      const response = await fetch(`${API_BASE}/api/tasks/collect/author`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          platform: payload.authorPlatform,
          collect_action: payload.authorCollectAction,
          uids: payload.authorUids,
          title: payload.title,
          description: payload.description,
        }),
      })

      const result = await response.json()
      if (!response.ok || !result?.success) {
        throw new Error(result?.message || `指定作者采集请求失败: ${response.status}`)
      }
      window.dispatchEvent(new Event("tasks:refresh"))
      return
    }

    if (payload.collectMode !== "single-work") {
      return
    }

    const response = await fetch(`${API_BASE}/api/tasks/collect/single-work`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        links: payload.workLinks,
        title: payload.title,
        description: payload.description,
      }),
    })

    const result = await response.json()
    if (!response.ok || !result?.success) {
      throw new Error(result?.message || `采集请求失败: ${response.status}`)
    }
    window.dispatchEvent(new Event("tasks:refresh"))
  }

  return (
    <>
      <div className="flex h-11 shrink-0 items-center justify-between border-b border-white/[0.08] px-5">
        <div className="flex items-center gap-0.5">
          <button className="mr-1 inline-flex items-center gap-1.5 rounded-full border border-white/[0.12] px-3 py-1 text-[13px] font-medium text-zinc-300 transition-colors duration-100 hover:bg-white/[0.05]">
            <SlidersHorizontal className="size-3.5" />
            <span>筛选</span>
          </button>

          {filters.map((filter) => {
            const isActive = active === filter.id
            const Icon = filter.icon
            return (
              <button
                key={filter.id}
                onClick={() => setActive(filter.id)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[13px] font-medium transition-colors duration-100",
                  isActive
                    ? "bg-white/[0.10] text-zinc-100"
                    : "text-zinc-500 hover:text-zinc-300 hover:bg-white/[0.04]"
                )}
              >
                <Icon className="size-3.5" />
                <span>{filter.label}</span>
              </button>
            )
          })}
        </div>

        <button
          onClick={() => setCreateOpen(true)}
          className="inline-flex items-center gap-1.5 rounded-full bg-white px-3.5 py-1 text-[13px] font-medium text-black transition-colors duration-100 hover:bg-zinc-200"
        >
          <Plus className="size-3.5" />
          <span>创建任务</span>
        </button>
      </div>

      <CreateTaskDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreate={handleCreateTask}
      />
    </>
  )
}
