import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
} from "react"
import { ChevronDown, X } from "lucide-react"
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible"
import { cn } from "@/lib/utils"

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000"

type StatusDrawer = {
  id: string
  label: string
  icon: ComponentType
  emptyTitle: string
  emptyDescription: string
}

type BackendTaskStatus = "pending" | "running" | "completed" | "failed"

type BackendTask = {
  id: string
  kind:
    | "collect-single-work"
    | "collect-author"
    | "collect-author-selective-download"
  task_type: "collect" | "publish"
  collect_mode: "single-work" | "author"
  title: string
  description: string
  status: BackendTaskStatus
  created_at: string
  updated_at: string
  started_at?: string | null
  ended_at?: string | null
  logs?: string[]
  error?: string | null
  result_summary?: {
    total_count?: number
    success_count?: number
    failure_count?: number
  }
  progress?: {
    current?: number
    total?: number
    percent?: number
  }
}

type TaskListItem = {
  id: string
  backendTaskId: string
  name: string
  description: string
  createdAt: string
  taskType: "采集任务" | "发布任务"
  collectMode: "指定作品采集" | "指定作者采集" | "不适用"
  status: BackendTaskStatus
  progressPercent: number
  progressText: string
  logs: string[]
  error: string | null
}

const statusTextMap: Record<BackendTaskStatus, string> = {
  pending: "排队中",
  running: "执行中",
  completed: "已完成",
  failed: "失败",
}

const TechnicalReviewIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
    <circle cx="7" cy="7" r="6" fill="none" stroke="#22c55e" strokeWidth="2" strokeDasharray="3.14 0" strokeDashoffset="-0.7" />
    <circle cx="7" cy="7" r="2" fill="none" stroke="#22c55e" strokeWidth="4" strokeDasharray="4.167846253762459 100" strokeDashoffset="0" transform="rotate(-90 7 7)" />
  </svg>
)

const PausedIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
    <circle cx="7" cy="7" r="6" fill="none" stroke="#0ea5e9" strokeWidth="2" strokeDasharray="3.14 0" strokeDashoffset="-0.7" />
    <circle cx="7" cy="7" r="2" fill="none" stroke="#0ea5e9" strokeWidth="4" strokeDasharray="6.2517693806436885 100" strokeDashoffset="0" transform="rotate(-90 7 7)" />
  </svg>
)

const CompletedIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
    <circle cx="7" cy="7" r="6" fill="none" stroke="#22c55e" strokeWidth="2" strokeDasharray="3.14 0" strokeDashoffset="-0.7" />
    <path d="M4.5 7L6.5 9L9.5 5" stroke="#22c55e" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

const ToDoIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
    <circle cx="7" cy="7" r="6" fill="none" stroke="#53565A" strokeWidth="2" strokeDasharray="3.14 0" strokeDashoffset="-0.7" />
    <circle cx="7" cy="7" r="2" fill="none" stroke="#53565A" strokeWidth="4" strokeDasharray="0 100" strokeDashoffset="0" transform="rotate(-90 7 7)" />
  </svg>
)

const BacklogIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
    <circle cx="7" cy="7" r="6" fill="none" stroke="#53565A" strokeWidth="2" strokeDasharray="1.4 1.74" strokeDashoffset="0.65" />
    <circle cx="7" cy="7" r="2" fill="none" stroke="#53565A" strokeWidth="4" strokeDasharray="0 100" strokeDashoffset="0" transform="rotate(-90 7 7)" />
  </svg>
)

const statusDrawers: StatusDrawer[] = [
  {
    id: "running",
    label: "进行中任务",
    icon: TechnicalReviewIcon,
    emptyTitle: "暂无进行中任务",
    emptyDescription: "当前没有正在执行的发布任务，可通过右上角创建新任务。",
  },
  {
    id: "recurring",
    label: "常驻任务",
    icon: PausedIcon,
    emptyTitle: "暂无常驻任务",
    emptyDescription: "还未配置常驻运行的任务策略，设置后会在这里持续展示。",
  },
  {
    id: "completed",
    label: "已完成任务",
    icon: CompletedIcon,
    emptyTitle: "暂无已完成任务",
    emptyDescription: "任务执行完成后会在这里沉淀，用于复盘和结果追踪。",
  },
  {
    id: "failed",
    label: "失败任务",
    icon: ToDoIcon,
    emptyTitle: "暂无失败任务",
    emptyDescription: "当前没有失败任务，系统状态稳定。",
  },
]

function formatDateLabel(value: string | undefined): string {
  if (!value) return "-"
  return value.slice(0, 10)
}

function normalizeProgress(task: BackendTask): { percent: number; text: string } {
  const rawCurrent = Number(task.progress?.current ?? 0)
  const rawTotal = Number(task.progress?.total ?? 1)
  const rawPercent = Number(task.progress?.percent ?? 0)
  const total = Number.isFinite(rawTotal) && rawTotal > 0 ? rawTotal : 1
  const current = Math.min(Math.max(Number.isFinite(rawCurrent) ? rawCurrent : 0, 0), total)
  let percent = Math.min(Math.max(Number.isFinite(rawPercent) ? rawPercent : 0, 0), 100)

  if (task.status === "completed") percent = 100
  if (task.status === "failed" && percent <= 0) {
    percent = Math.round((current / total) * 100)
  }

  return {
    percent,
    text: `${current}/${total}`,
  }
}

function mapCollectModeLabel(mode: string): TaskListItem["collectMode"] {
  if (mode === "author") return "指定作者采集"
  if (mode === "single-work") return "指定作品采集"
  return "不适用"
}

function mapTaskTypeLabel(taskType: string): TaskListItem["taskType"] {
  return taskType === "publish" ? "发布任务" : "采集任务"
}

function getProgressColor(status: BackendTaskStatus): string {
  if (status === "completed") return "bg-emerald-400"
  if (status === "failed") return "bg-rose-400"
  if (status === "running") return "bg-sky-400"
  return "bg-zinc-400"
}

export function TaskStatusDrawers() {
  const [openMap, setOpenMap] = useState<Record<string, boolean>>({
    running: true,
    recurring: false,
    completed: false,
    failed: false,
  })
  const [backendTasks, setBackendTasks] = useState<BackendTask[]>([])
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [selectedTaskFullLogs, setSelectedTaskFullLogs] = useState<string[]>([])
  const [isDeletingTask, setIsDeletingTask] = useState(false)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const logViewportRef = useRef<HTMLDivElement | null>(null)

  const fetchTasks = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/api/tasks?limit=200`)
      const payload = await response.json()
      if (!response.ok || !payload?.success) {
        throw new Error(payload?.message || "任务列表请求失败")
      }
      const tasks = Array.isArray(payload?.tasks) ? payload.tasks : []
      setBackendTasks(tasks as BackendTask[])
    } catch (error) {
      console.error("任务列表加载失败:", error)
    }
  }, [])

  useEffect(() => {
    void fetchTasks()

    const timer = window.setInterval(() => {
      void fetchTasks()
    }, 1800)

    const handleRefresh = () => {
      void fetchTasks()
    }
    window.addEventListener("tasks:refresh", handleRefresh)

    return () => {
      window.clearInterval(timer)
      window.removeEventListener("tasks:refresh", handleRefresh)
    }
  }, [fetchTasks])

  const tasksByStatus = useMemo(() => {
    const grouped: Record<string, TaskListItem[]> = {
      running: [],
      recurring: [],
      completed: [],
      failed: [],
    }

    backendTasks.forEach((task) => {
      const progress = normalizeProgress(task)
      const mapped: TaskListItem = {
        id: `backend-${task.id}`,
        backendTaskId: task.id,
        name: task.title || "未命名任务",
        description: task.error || task.description || "后台任务执行中",
        createdAt: formatDateLabel(task.created_at),
        taskType: mapTaskTypeLabel(task.task_type),
        collectMode: mapCollectModeLabel(task.collect_mode),
        status: task.status,
        progressPercent: progress.percent,
        progressText: progress.text,
        logs: Array.isArray(task.logs) ? task.logs : [],
        error: task.error || null,
      }

      if (task.status === "completed") {
        grouped.completed.push(mapped)
      } else if (task.status === "failed") {
        grouped.failed.push(mapped)
      } else {
        grouped.running.push(mapped)
      }
    })

    return grouped
  }, [backendTasks])

  const selectedTaskMeta = useMemo(() => {
    if (!selectedTaskId) return null

    for (const drawer of statusDrawers) {
      const tasks = tasksByStatus[drawer.id] ?? []
      const task = tasks.find((item) => item.id === selectedTaskId)
      if (task) {
        return { drawer, task }
      }
    }
    return null
  }, [selectedTaskId, tasksByStatus])

  const selectedTaskLogs = useMemo(() => {
    if (!selectedTaskMeta) return []
    if (selectedTaskFullLogs.length > 0) {
      return selectedTaskFullLogs
    }
    return selectedTaskMeta.task.logs
  }, [selectedTaskMeta, selectedTaskFullLogs])

  useEffect(() => {
    if (!selectedTaskMeta) {
      setSelectedTaskFullLogs([])
      return
    }

    let disposed = false
    setSelectedTaskFullLogs(selectedTaskMeta.task.logs)

    const fetchTaskDetailLogs = async () => {
      try {
        const response = await fetch(
          `${API_BASE}/api/tasks/${selectedTaskMeta.task.backendTaskId}`
        )
        const payload = await response.json()
        if (!response.ok || !payload?.success) {
          return
        }
        const logs = Array.isArray(payload?.task?.logs) ? payload.task.logs : []
        if (!disposed) {
          setSelectedTaskFullLogs(logs)
        }
      } catch (error) {
        console.error("任务详情日志加载失败:", error)
      }
    }

    void fetchTaskDetailLogs()
    const timer = window.setInterval(() => {
      void fetchTaskDetailLogs()
    }, 1200)

    return () => {
      disposed = true
      window.clearInterval(timer)
    }
  }, [selectedTaskMeta, selectedTaskMeta?.task.backendTaskId])

  useEffect(() => {
    if (!logViewportRef.current) return
    logViewportRef.current.scrollTop = logViewportRef.current.scrollHeight
  }, [selectedTaskLogs])

  const handleDeleteTask = async () => {
    if (!selectedTaskMeta) return
    try {
      setIsDeletingTask(true)
      setDeleteError(null)
      const response = await fetch(
        `${API_BASE}/api/tasks/${selectedTaskMeta.task.backendTaskId}`,
        {
          method: "DELETE",
        }
      )
      const payload = await response.json()
      if (!response.ok || !payload?.success) {
        throw new Error(payload?.message || "删除任务失败")
      }
      setSelectedTaskId(null)
      await fetchTasks()
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : "删除任务失败")
    } finally {
      setIsDeletingTask(false)
    }
  }

  return (
    <div className="h-full w-full overflow-hidden">
      <div className="flex h-full">
        <div className="min-w-0 flex-1 overflow-y-auto">
          {statusDrawers.map((drawer) => {
            const Icon = drawer.icon
            const isOpen = Boolean(openMap[drawer.id])
            const tasks = tasksByStatus[drawer.id] ?? []

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
                      <span className="flex size-4 items-center justify-center">
                        <Icon />
                      </span>
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
                    {tasks.length > 0 ? (
                      <ul className="divide-y divide-white/5">
                        {tasks.map((task) => {
                          const isSelected = selectedTaskId === task.id

                          return (
                            <li key={task.id}>
                              <button
                                type="button"
                                onClick={() =>
                                  setSelectedTaskId((prev) =>
                                    prev === task.id ? null : task.id
                                  )
                                }
                                className={cn(
                                  "flex h-11 w-full items-center justify-between px-5 text-left transition-colors hover:bg-white/2.5",
                                  isSelected && "bg-white/5"
                                )}
                              >
                                <div className="min-w-0 pr-3">
                                  <div className="flex items-center gap-2.5 truncate text-sm text-zinc-200">
                                    <span className="flex size-4 shrink-0 items-center justify-center">
                                      <BacklogIcon />
                                    </span>
                                    <span className="truncate">{task.name}</span>
                                    <span className="mx-1 text-zinc-600">·</span>
                                    <span className="truncate text-zinc-500">
                                      {task.description}
                                    </span>
                                  </div>
                                </div>
                                <span className="shrink-0 text-xs tabular-nums text-zinc-500">
                                  {task.createdAt}
                                </span>
                              </button>
                            </li>
                          )
                        })}
                      </ul>
                    ) : (
                      <div className="px-5 py-4">
                        <div className="min-w-0">
                          <p className="text-sm text-zinc-300">{drawer.emptyTitle}</p>
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
            selectedTaskMeta ? "w-90 xl:w-105 opacity-100" : "w-0 opacity-0"
          )}
        >
          <div
            className={cn(
              "min-h-0 h-full px-5 py-4 transition-opacity duration-200",
              selectedTaskMeta ? "opacity-100 delay-75" : "pointer-events-none opacity-0"
            )}
          >
            {selectedTaskMeta && (
              <div className="flex min-h-0 h-full flex-col">
                <div className="flex items-start justify-between border-b border-white/6 pb-3">
                  <div className="pr-3">
                    <p className="text-sm text-zinc-100">{selectedTaskMeta.task.name}</p>
                    <p className="mt-1 text-xs leading-relaxed text-zinc-500">
                      {selectedTaskMeta.task.description}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setSelectedTaskId(null)}
                    className="inline-flex size-7 items-center justify-center rounded-md text-zinc-500 transition-colors hover:bg-white/4 hover:text-zinc-300"
                    aria-label="关闭详情面板"
                  >
                    <X className="size-4" />
                  </button>
                </div>

                <div className="flex min-h-0 flex-1 flex-col py-4">
                  <div className="space-y-3">
                    <div className="flex items-center justify-between gap-3 text-sm">
                      <span className="text-zinc-500">任务类型</span>
                      <span className="text-zinc-200">{selectedTaskMeta.task.taskType}</span>
                    </div>
                    <div className="flex items-center justify-between gap-3 text-sm">
                      <span className="text-zinc-500">采集模式</span>
                      <span className="text-zinc-200">{selectedTaskMeta.task.collectMode}</span>
                    </div>
                    <div className="flex items-center justify-between gap-3 text-sm">
                      <span className="text-zinc-500">当前状态</span>
                      <span className="text-zinc-200">
                        {statusTextMap[selectedTaskMeta.task.status]}
                      </span>
                    </div>
                  </div>

                  <div className="mt-4">
                    <div className="mb-1 flex items-center justify-between text-[11px] text-zinc-500">
                      <span>执行进度</span>
                      <span>{selectedTaskMeta.task.progressText}</span>
                    </div>
                    <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/8">
                      <div
                        className={cn(
                          "h-full rounded-full transition-[width] duration-300",
                          getProgressColor(selectedTaskMeta.task.status)
                        )}
                        style={{ width: `${selectedTaskMeta.task.progressPercent}%` }}
                      />
                    </div>
                  </div>

                  <div className="mt-5 flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-white/8 bg-black/35 p-3">
                    <p className="text-[11px] uppercase tracking-[0.12em] text-zinc-500">
                      执行日志
                    </p>
                    <div
                      ref={logViewportRef}
                      className="mt-2 min-h-0 flex-1 space-y-1 overflow-auto overflow-x-hidden break-all pr-1 font-mono text-[11px] leading-5 text-zinc-400 [&::-webkit-scrollbar]:hidden [-ms-overflow-style:'none'] [scrollbar-width:'none']"
                    >
                      {selectedTaskLogs.length > 0 ? (
                        selectedTaskLogs.map((logLine, index) => (
                          <p key={`${selectedTaskMeta.task.id}-log-${index}`}>{logLine}</p>
                        ))
                      ) : (
                        <p className="text-zinc-500">暂无日志输出</p>
                      )}
                    </div>
                  </div>

                  {deleteError && (
                    <p className="mt-2 text-right text-[11px] text-red-300">{deleteError}</p>
                  )}

                  <button
                    type="button"
                    onClick={handleDeleteTask}
                    disabled={isDeletingTask}
                    className="mt-3 self-end inline-flex h-7 items-center justify-center rounded-full border border-red-400/40 bg-red-500/10 px-3.5 text-[12px] font-medium text-red-300 transition-colors hover:bg-red-500/20 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    {isDeletingTask ? "删除中..." : "删除任务"}
                  </button>
                </div>
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  )
}
