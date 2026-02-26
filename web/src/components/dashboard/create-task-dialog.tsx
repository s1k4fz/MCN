import { useMemo, useState } from "react"
import {
  CircleDot,
  Database,
  Download,
  FileVideo,
  Minus,
  Plus,
  ScanSearch,
  UserRound,
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
import { cn } from "@/lib/utils"

type TaskType = "collect" | null
type CollectMode = "single-work" | "author" | null
type AuthorPlatform = "bilibili" | "douyin" | "xiaohongshu" | null
type AuthorCollectAction = "data-only" | "collect-download" | null

type CreateTaskDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreate?: (payload: {
    taskType: NonNullable<TaskType>
    collectMode: CollectMode
    title: string
    description: string
    workLinks: string[]
    authorPlatform: AuthorPlatform
    authorCollectAction: AuthorCollectAction
    authorUids: string[]
  }) => void | Promise<void>
}

export function CreateTaskDialog({
  open,
  onOpenChange,
  onCreate,
}: CreateTaskDialogProps) {
  const [taskType, setTaskType] = useState<TaskType>(null)
  const [collectMode, setCollectMode] = useState<CollectMode>(null)
  const [workLinks, setWorkLinks] = useState<string[]>([""])
  const [authorPlatform, setAuthorPlatform] = useState<AuthorPlatform>(null)
  const [authorCollectAction, setAuthorCollectAction] =
    useState<AuthorCollectAction>(null)
  const [authorUids, setAuthorUids] = useState<string[]>([""])
  const [taskTitle, setTaskTitle] = useState("")
  const [taskDescription, setTaskDescription] = useState("")
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const defaultTaskMeta = useMemo(() => {
    if (taskType === "collect" && collectMode === "single-work") {
      return {
        title: "指定作品采集任务",
        description: "按作品链接执行批量采集。",
      }
    }
    if (taskType === "collect" && collectMode === "author") {
      return {
        title: "指定作者采集任务",
        description: "按作者 UID 执行采集流程。",
      }
    }
    if (taskType === "collect") {
      return {
        title: "采集任务",
        description: "执行内容采集流程。",
      }
    }
    return {
      title: "新任务",
      description: "任务描述",
    }
  }, [taskType, collectMode])

  const canCreate = useMemo(() => {
    if (!taskType) return false
    if (!collectMode) return false
    if (collectMode === "single-work") {
      return workLinks.some((link) => link.trim().length > 0)
    }
    if (collectMode === "author") {
      return (
        authorPlatform !== null &&
        Boolean(authorCollectAction) &&
        authorUids.some((uid) => uid.trim().length > 0)
      )
    }
    return true
  }, [taskType, collectMode, workLinks, authorCollectAction, authorPlatform, authorUids])

  const handleClose = (nextOpen: boolean) => {
    onOpenChange(nextOpen)
    if (!nextOpen) {
      setTaskType(null)
      setCollectMode(null)
      setWorkLinks([""])
      setAuthorPlatform(null)
      setAuthorCollectAction(null)
      setAuthorUids([""])
      setTaskTitle("")
      setTaskDescription("")
      setErrorMessage(null)
      setIsSubmitting(false)
    }
  }

  const handleCreate = async () => {
    if (!taskType) return
    const title = taskTitle.trim() || defaultTaskMeta.title
    const description = taskDescription.trim() || defaultTaskMeta.description
    try {
      setIsSubmitting(true)
      setErrorMessage(null)
      await onCreate?.({
        taskType,
        collectMode,
        title,
        description,
        workLinks: workLinks.map((link) => link.trim()).filter(Boolean),
        authorPlatform,
        authorCollectAction,
        authorUids: authorUids.map((uid) => uid.trim()).filter(Boolean),
      })
      handleClose(false)
    } catch (error) {
      const message = error instanceof Error ? error.message : "创建任务失败"
      setErrorMessage(message)
    } finally {
      setIsSubmitting(false)
    }
  }

  const addWorkLinkField = () => {
    setWorkLinks((prev) => [...prev, ""])
  }

  const updateWorkLink = (index: number, value: string) => {
    setWorkLinks((prev) => prev.map((link, i) => (i === index ? value : link)))
  }

  const removeWorkLinkField = (index: number) => {
    setWorkLinks((prev) => {
      if (prev.length <= 1) return [""]
      return prev.filter((_, i) => i !== index)
    })
  }

  const addAuthorUidField = () => {
    setAuthorUids((prev) => [...prev, ""])
  }

  const updateAuthorUid = (index: number, value: string) => {
    setAuthorUids((prev) => prev.map((uid, i) => (i === index ? value : uid)))
  }

  const removeAuthorUidField = (index: number) => {
    setAuthorUids((prev) => {
      if (prev.length <= 1) return [""]
      return prev.filter((_, i) => i !== index)
    })
  }

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>创建任务</DialogTitle>
          <DialogDescription>
            选择任务类型后继续配置对应模式。
          </DialogDescription>
        </DialogHeader>

        <div className="mt-5 space-y-5">
          <div>
            <p className="mb-2 text-xs tracking-[0.12em] uppercase text-zinc-500">
              任务类型
            </p>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                onClick={() => {
                  setTaskType("collect")
                }}
                className={cn(
                  "inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[13px] transition-colors",
                  taskType === "collect"
                    ? "border-white/30 bg-white/[0.10] text-zinc-100"
                    : "border-white/[0.12] text-zinc-400 hover:bg-white/[0.05] hover:text-zinc-200"
                )}
              >
                <ScanSearch className="size-3.5 shrink-0" />
                <span>采集任务</span>
              </button>

            </div>
          </div>

          {taskType === "collect" && (
            <div>
              <p className="mb-2 text-xs tracking-[0.12em] uppercase text-zinc-500">
                采集模式
              </p>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setCollectMode("single-work")
                  }}
                  className={cn(
                    "inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[13px] transition-colors",
                    collectMode === "single-work"
                      ? "border-white/30 bg-white/[0.10] text-zinc-100"
                      : "border-white/[0.12] text-zinc-400 hover:bg-white/[0.05] hover:text-zinc-200"
                  )}
                >
                  <FileVideo className="size-3.5 shrink-0" />
                  <span>指定作品采集</span>
                </button>

                <button
                  type="button"
                  onClick={() => {
                    setCollectMode("author")
                  }}
                  className={cn(
                    "inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[13px] transition-colors",
                    collectMode === "author"
                      ? "border-white/30 bg-white/[0.10] text-zinc-100"
                      : "border-white/[0.12] text-zinc-400 hover:bg-white/[0.05] hover:text-zinc-200"
                  )}
                >
                  <UserRound className="size-3.5 shrink-0" />
                  <span>指定作者采集</span>
                </button>
              </div>
            </div>
          )}

          {taskType === "collect" && collectMode === "author" && (
            <div className="space-y-4">
              <div>
                <p className="mb-2 text-xs tracking-[0.12em] uppercase text-zinc-500">
                  采集平台
                </p>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => setAuthorPlatform("bilibili")}
                    className={cn(
                      "inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[13px] transition-colors",
                      authorPlatform === "bilibili"
                        ? "border-white/30 bg-white/[0.10] text-zinc-100"
                        : "border-white/[0.12] text-zinc-400 hover:bg-white/[0.05] hover:text-zinc-200"
                    )}
                  >
                    <CircleDot className="size-3.5 shrink-0" />
                    <span>B站</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => {
                      setAuthorPlatform("douyin")
                      setAuthorCollectAction(null)
                    }}
                    className={cn(
                      "inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[13px] transition-colors",
                      authorPlatform === "douyin"
                        ? "border-white/30 bg-white/[0.10] text-zinc-100"
                        : "border-white/[0.12] text-zinc-400 hover:bg-white/[0.05] hover:text-zinc-200"
                    )}
                  >
                    <CircleDot className="size-3.5 shrink-0" />
                    <span>抖音</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => {
                      setAuthorPlatform("xiaohongshu")
                      setAuthorCollectAction(null)
                    }}
                    className={cn(
                      "inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[13px] transition-colors",
                      authorPlatform === "xiaohongshu"
                        ? "border-white/30 bg-white/[0.10] text-zinc-100"
                        : "border-white/[0.12] text-zinc-400 hover:bg-white/[0.05] hover:text-zinc-200"
                    )}
                  >
                    <CircleDot className="size-3.5 shrink-0" />
                    <span>小红书</span>
                  </button>
                </div>
              </div>

              {authorPlatform && (
                <div>
                  <p className="mb-2 text-xs tracking-[0.12em] uppercase text-zinc-500">
                    采集方式
                  </p>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() => setAuthorCollectAction("data-only")}
                      className={cn(
                        "inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[13px] transition-colors",
                        authorCollectAction === "data-only"
                          ? "border-white/30 bg-white/[0.10] text-zinc-100"
                          : "border-white/[0.12] text-zinc-400 hover:bg-white/[0.05] hover:text-zinc-200"
                      )}
                    >
                      <Database className="size-3.5 shrink-0" />
                      <span>只采集数据</span>
                    </button>

                    <button
                      type="button"
                      onClick={() => setAuthorCollectAction("collect-download")}
                      className={cn(
                        "inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-[13px] transition-colors",
                        authorCollectAction === "collect-download"
                          ? "border-white/30 bg-white/[0.10] text-zinc-100"
                          : "border-white/[0.12] text-zinc-400 hover:bg-white/[0.05] hover:text-zinc-200"
                      )}
                    >
                      <Download className="size-3.5 shrink-0" />
                      <span>采集并下载</span>
                    </button>
                  </div>
                </div>
              )}

              {authorPlatform && authorCollectAction && (
                <div>
                  <div className="mb-2 flex items-center justify-between">
                    <p className="text-xs tracking-[0.12em] uppercase text-zinc-500">
                      {authorPlatform === "bilibili" ? "作者 UID" : "作者链接 / ID"}
                    </p>
                    <button
                      type="button"
                      onClick={addAuthorUidField}
                      className="inline-flex h-7 items-center gap-1 rounded-full border border-white/[0.12] px-2.5 text-xs text-zinc-400 transition-colors hover:bg-white/[0.05] hover:text-zinc-200"
                    >
                      <Plus className="size-3.5 shrink-0" />
                      <span>添加</span>
                    </button>
                  </div>
                  <div className="space-y-2">
                    {authorUids.map((uid, index) => (
                      <div key={`author-uid-${index}`} className="flex items-center gap-2">
                        <input
                          value={uid}
                          onChange={(event) => updateAuthorUid(index, event.target.value)}
                          placeholder={
                            authorPlatform === "bilibili"
                              ? `请输入作者 UID ${index + 1}（纯数字）`
                              : authorPlatform === "douyin"
                                ? `请输入作者主页链接或 sec_user_id ${index + 1}`
                                : `请输入作者主页链接或 user_id ${index + 1}`
                          }
                          className="h-9 w-full rounded-full border border-white/[0.12] bg-white/[0.03] px-4 text-[13px] text-zinc-200 placeholder:text-zinc-500 outline-none transition-colors focus:border-white/[0.22] focus:bg-white/[0.06]"
                        />
                        <button
                          type="button"
                          onClick={() => removeAuthorUidField(index)}
                          className="inline-flex size-9 shrink-0 items-center justify-center rounded-full border border-white/[0.12] text-zinc-400 transition-colors hover:bg-white/[0.05] hover:text-zinc-200 disabled:cursor-not-allowed disabled:opacity-40"
                          disabled={authorUids.length === 1}
                          aria-label="删除该作者 UID 输入框"
                        >
                          <Minus className="size-3.5" />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {taskType === "collect" && collectMode === "single-work" && (
            <div>
              <div className="mb-2 flex items-center justify-between">
                <p className="text-xs tracking-[0.12em] uppercase text-zinc-500">
                  作品链接
                </p>
                <button
                  type="button"
                  onClick={addWorkLinkField}
                  className="inline-flex h-7 items-center gap-1 rounded-full border border-white/[0.12] px-2.5 text-xs text-zinc-400 transition-colors hover:bg-white/[0.05] hover:text-zinc-200"
                >
                  <Plus className="size-3.5" />
                  <span>添加</span>
                </button>
              </div>
              <div className="space-y-2">
                {workLinks.map((link, index) => (
                  <div key={`work-link-${index}`} className="flex items-center gap-2">
                    <input
                      value={link}
                      onChange={(event) => updateWorkLink(index, event.target.value)}
                      placeholder={`请输入作品链接 ${index + 1}`}
                      className="h-9 w-full rounded-full border border-white/[0.12] bg-white/[0.03] px-4 text-[13px] text-zinc-200 placeholder:text-zinc-500 outline-none transition-colors focus:border-white/[0.22] focus:bg-white/[0.06]"
                    />
                    <button
                      type="button"
                      onClick={() => removeWorkLinkField(index)}
                      className="inline-flex size-9 shrink-0 items-center justify-center rounded-full border border-white/[0.12] text-zinc-400 transition-colors hover:bg-white/[0.05] hover:text-zinc-200 disabled:cursor-not-allowed disabled:opacity-40"
                      disabled={workLinks.length === 1}
                      aria-label="删除该作品链接输入框"
                    >
                      <Minus className="size-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {taskType && (
            <div>
              <p className="mb-2 text-xs tracking-[0.12em] uppercase text-zinc-500">
                任务信息
              </p>
              <div className="space-y-2">
                <input
                  value={taskTitle}
                  onChange={(event) => setTaskTitle(event.target.value)}
                  placeholder={`任务标题（留空默认：${defaultTaskMeta.title}）`}
                  className="h-9 w-full rounded-full border border-white/[0.12] bg-white/[0.03] px-4 text-[13px] text-zinc-200 placeholder:text-zinc-500 outline-none transition-colors focus:border-white/[0.22] focus:bg-white/[0.06]"
                />
                <input
                  value={taskDescription}
                  onChange={(event) => setTaskDescription(event.target.value)}
                  placeholder={`任务描述（留空默认：${defaultTaskMeta.description}）`}
                  className="h-9 w-full rounded-full border border-white/[0.12] bg-white/[0.03] px-4 text-[13px] text-zinc-200 placeholder:text-zinc-500 outline-none transition-colors focus:border-white/[0.22] focus:bg-white/[0.06]"
                />
              </div>
            </div>
          )}

        </div>

        {errorMessage && (
          <div className="mt-3 rounded-md border border-red-400/30 bg-red-500/10 px-3 py-2 text-xs text-red-300">
            {errorMessage}
          </div>
        )}

        <DialogFooter>
          <Button
            variant="ghost"
            className="h-8 rounded-full border border-white/[0.12] px-4 hover:bg-white/[0.05]"
            onClick={() => handleClose(false)}
            disabled={isSubmitting}
          >
            取消
          </Button>
          <Button
            className="h-8 rounded-full bg-white px-4 text-black hover:bg-zinc-200"
            onClick={handleCreate}
            disabled={!canCreate || isSubmitting}
          >
            {isSubmitting ? "处理中..." : "创建任务"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
