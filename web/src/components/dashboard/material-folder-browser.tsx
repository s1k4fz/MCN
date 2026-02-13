import { useCallback, useEffect, useMemo, useState } from "react"
import {
  CheckCircle2,
  ChevronRight,
  Circle,
  Folder,
  FolderOpen,
  Loader2,
} from "lucide-react"
import { cn } from "@/lib/utils"

type FolderNode = {
  id: string
  name: string
  children: FolderNode[]
  authorUid?: string
  relativePath?: string
  isDir?: boolean
}

type RootFolder = FolderNode

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000"
const SPECIAL_BILIBILI_SUBFOLDER = "已采集未下载作者"
const BILIBILI_AUTHOR_SUBFOLDERS = new Set(["指定作者", SPECIAL_BILIBILI_SUBFOLDER])

const fallbackRootFolders: RootFolder[] = [
  {
    id: "bilibili",
    name: "哔哩哔哩",
    children: [
      { id: "bilibili-single", name: "单个作品", children: [] },
      { id: "bilibili-author", name: "指定作者", children: [] },
      {
        id: "bilibili-collected-authors",
        name: SPECIAL_BILIBILI_SUBFOLDER,
        children: [],
      },
    ],
  },
  {
    id: "xiaohongshu",
    name: "小红书",
    children: [
      { id: "xiaohongshu-single", name: "单个作品", children: [] },
      { id: "xiaohongshu-author", name: "指定作者", children: [] },
    ],
  },
  {
    id: "douyin",
    name: "抖音",
    children: [
      { id: "douyin-single", name: "单个作品", children: [] },
      { id: "douyin-author", name: "指定作者", children: [] },
    ],
  },
]

function asRecord(value: unknown): Record<string, unknown> {
  if (typeof value === "object" && value !== null) {
    return value as Record<string, unknown>
  }
  return {}
}

function asString(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim() ? value : fallback
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function normalizeNode(
  node: unknown,
  fallbackId: string,
  fallbackName: string
): FolderNode {
  const rawNode = asRecord(node)
  const id = asString(rawNode.id, fallbackId)
  const name = asString(rawNode.name, fallbackName)
  const rawChildren = asArray(rawNode.children)
  const authorUid =
    typeof rawNode.author_uid === "string" && rawNode.author_uid.trim()
      ? rawNode.author_uid.trim()
      : undefined
  const relativePath =
    typeof rawNode.relative_path === "string" && rawNode.relative_path.trim()
      ? rawNode.relative_path.trim()
      : undefined
  const isDir = typeof rawNode.is_dir === "boolean" ? rawNode.is_dir : undefined

  return {
    id,
    name,
    authorUid,
    relativePath,
    isDir,
    children: rawChildren.map((child, childIndex) =>
      normalizeNode(child, `${id}-${childIndex}`, "未命名目录")
    ),
  }
}

function ensureSpecialBilibiliSubfolder(roots: RootFolder[]): RootFolder[] {
  return roots.map((root) => {
    if (root.id !== "bilibili") {
      return root
    }
    if (root.children.some((child) => child.name === SPECIAL_BILIBILI_SUBFOLDER)) {
      return root
    }
    return {
      ...root,
      children: [
        ...root.children,
        {
          id: `${root.id}-${SPECIAL_BILIBILI_SUBFOLDER}`,
          name: SPECIAL_BILIBILI_SUBFOLDER,
          children: [],
        },
      ],
    }
  })
}

function normalizeRoots(roots: unknown[]): RootFolder[] {
  const normalized = roots.map((root, rootIndex) =>
    normalizeNode(root, `root-${rootIndex}`, "未命名平台")
  )

  return ensureSpecialBilibiliSubfolder(normalized)
}

function isAuthorNestedSubfolder(rootId: string, subfolderName: string): boolean {
  return rootId === "bilibili" && BILIBILI_AUTHOR_SUBFOLDERS.has(subfolderName)
}

function getMaterialDepth(relativePath?: string): number {
  if (!relativePath) return -1
  const parts = relativePath.split("/").filter(Boolean)
  if (parts.length === 0 || parts[0] !== "materials") return -1
  return parts.length - 1
}

type MaterialFolderBrowserProps = {
  selectMode: boolean
  onSelectionCountChange?: (count: number) => void
  onDeletingChange?: (isDeleting: boolean) => void
  onRegisterDeleteHandler?: (handler: (() => Promise<void>) | null) => void
}

export function MaterialFolderBrowser({
  selectMode,
  onSelectionCountChange,
  onDeletingChange,
  onRegisterDeleteHandler,
}: MaterialFolderBrowserProps) {
  const [rootFolders, setRootFolders] = useState<RootFolder[]>(fallbackRootFolders)
  const [activeRootId, setActiveRootId] = useState<string | null>(null)
  const [activeSubId, setActiveSubId] = useState<string | null>(null)
  const [activeThirdId, setActiveThirdId] = useState<string | null>(null)
  const [expandedAuthorSubId, setExpandedAuthorSubId] = useState<string | null>(null)
  const [activeAuthorFolderId, setActiveAuthorFolderId] = useState<string | null>(null)
  const [selectedPendingVideoFolders, setSelectedPendingVideoFolders] = useState<
    string[]
  >([])
  const [selectedDeletePaths, setSelectedDeletePaths] = useState<string[]>([])
  const [isDownloadingSelected, setIsDownloadingSelected] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const loadMaterialTree = useCallback(async () => {
    setLoading(true)
    try {
      const response = await fetch(`${API_BASE}/api/materials/tree`)
      if (!response.ok) return
      const data = await response.json()
      if (Array.isArray(data?.roots)) {
        setRootFolders(normalizeRoots(data.roots))
      }
    } catch {
      // keep fallback when backend unavailable
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadMaterialTree()
    const handleRefresh = () => {
      void loadMaterialTree()
    }
    window.addEventListener("materials:refresh", handleRefresh)
    return () => {
      window.removeEventListener("materials:refresh", handleRefresh)
    }
  }, [loadMaterialTree])

  const activeRoot = useMemo(
    () => rootFolders.find((folder) => folder.id === activeRootId) ?? null,
    [activeRootId, rootFolders]
  )

  const activeSub = useMemo(
    () => activeRoot?.children.find((folder) => folder.id === activeSubId) ?? null,
    [activeRoot, activeSubId]
  )

  const expandedAuthorSub = useMemo(
    () =>
      activeRoot?.children.find((folder) => folder.id === expandedAuthorSubId) ?? null,
    [activeRoot, expandedAuthorSubId]
  )

  const activeAuthorFolder = useMemo(
    () =>
      expandedAuthorSub?.children.find((folder) => folder.id === activeAuthorFolderId) ??
      null,
    [activeAuthorFolderId, expandedAuthorSub]
  )

  const isPendingAuthorContext = useMemo(
    () =>
      Boolean(
        activeRoot?.id === "bilibili" &&
          expandedAuthorSub?.name === SPECIAL_BILIBILI_SUBFOLDER &&
          activeAuthorFolder
      ),
    [activeAuthorFolder, activeRoot?.id, expandedAuthorSub?.name]
  )

  const activeThirdCandidates = useMemo(() => {
    if (activeSub) {
      return activeSub.children
    }
    if (activeAuthorFolder && !isPendingAuthorContext) {
      return activeAuthorFolder.children
    }
    return []
  }, [activeAuthorFolder, activeSub, isPendingAuthorContext])

  const activeThird = useMemo(
    () =>
      activeThirdCandidates.find((folder) => folder.id === activeThirdId) ?? null,
    [activeThirdCandidates, activeThirdId]
  )

  const rightPanelFolders = useMemo(() => {
    const nodes = activeSub
      ? activeSub.children
      : activeAuthorFolder
        ? activeAuthorFolder.children
        : []
    return nodes.map((child) => ({
      ...child,
      children: Array.isArray(child.children) ? child.children : [],
    }))
  }, [activeAuthorFolder, activeSub])

  const showRightPanel = Boolean(activeSub || activeAuthorFolder)
  const showFourthPanel = Boolean(
    activeThird && (activeSub || (activeAuthorFolder && !isPendingAuthorContext))
  )

  useEffect(() => {
    if (activeRootId && !rootFolders.some((folder) => folder.id === activeRootId)) {
      setActiveRootId(null)
      setActiveSubId(null)
      setActiveThirdId(null)
      setExpandedAuthorSubId(null)
      setActiveAuthorFolderId(null)
      setSelectedPendingVideoFolders([])
    }
  }, [activeRootId, rootFolders])

  useEffect(() => {
    if (
      activeSubId &&
      (!activeRoot || !activeRoot.children.some((folder) => folder.id === activeSubId))
    ) {
      setActiveSubId(null)
      setActiveThirdId(null)
    }
  }, [activeRoot, activeSubId])

  useEffect(() => {
    if (
      activeThirdId &&
      !activeThirdCandidates.some((folder) => folder.id === activeThirdId)
    ) {
      setActiveThirdId(null)
    }
  }, [activeThirdCandidates, activeThirdId])

  useEffect(() => {
    if (
      expandedAuthorSubId &&
      (!activeRoot ||
        !activeRoot.children.some((folder) => folder.id === expandedAuthorSubId))
    ) {
      setExpandedAuthorSubId(null)
      setActiveAuthorFolderId(null)
      setSelectedPendingVideoFolders([])
    }
  }, [activeRoot, expandedAuthorSubId])

  useEffect(() => {
    if (
      activeAuthorFolderId &&
      (!expandedAuthorSub ||
        !expandedAuthorSub.children.some((folder) => folder.id === activeAuthorFolderId))
    ) {
      setActiveAuthorFolderId(null)
      setSelectedPendingVideoFolders([])
    }
  }, [activeAuthorFolderId, expandedAuthorSub])

  useEffect(() => {
    setSelectedPendingVideoFolders([])
    setActionError(null)
  }, [activeAuthorFolderId, expandedAuthorSubId, isPendingAuthorContext])

  useEffect(() => {
    if (isPendingAuthorContext) {
      setActiveThirdId(null)
    }
  }, [isPendingAuthorContext])

  useEffect(() => {
    if (!selectMode) {
      setSelectedDeletePaths([])
      onDeletingChange?.(false)
    }
  }, [onDeletingChange, selectMode])

  useEffect(() => {
    onSelectionCountChange?.(selectMode ? selectedDeletePaths.length : 0)
  }, [onSelectionCountChange, selectMode, selectedDeletePaths.length])

  const togglePendingSelection = (videoFolderName: string) => {
    setSelectedPendingVideoFolders((prev) =>
      prev.includes(videoFolderName)
        ? prev.filter((item) => item !== videoFolderName)
        : [...prev, videoFolderName]
    )
  }

  const toggleDeleteSelection = (relativePath: string) => {
    setSelectedDeletePaths((prev) =>
      prev.includes(relativePath)
        ? prev.filter((item) => item !== relativePath)
        : [...prev, relativePath]
    )
  }

  const handleDeleteSelected = useCallback(async () => {
    if (!selectMode || selectedDeletePaths.length === 0) {
      return
    }

    try {
      onDeletingChange?.(true)
      setActionError(null)
      const response = await fetch(`${API_BASE}/api/materials/delete`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          paths: selectedDeletePaths,
        }),
      })
      const result = await response.json()
      if (!response.ok || !result?.success) {
        const failureText = Array.isArray(result?.failures)
          ? result.failures
              .slice(0, 3)
              .map((item: { path?: string; reason?: string }) =>
                `${item.path ?? "unknown"}: ${item.reason ?? "删除失败"}`
              )
              .join("；")
          : ""
        throw new Error(result?.message || failureText || "删除失败")
      }
      setSelectedDeletePaths([])
      await loadMaterialTree()
      window.dispatchEvent(new Event("materials:refresh"))
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "删除失败")
    } finally {
      onDeletingChange?.(false)
    }
  }, [loadMaterialTree, onDeletingChange, selectMode, selectedDeletePaths])

  const handleDownloadSelected = async () => {
    if (!isPendingAuthorContext || !activeAuthorFolder) {
      return
    }
    if (selectedPendingVideoFolders.length === 0) {
      return
    }

    try {
      setIsDownloadingSelected(true)
      setActionError(null)
      const response = await fetch(
        `${API_BASE}/api/tasks/collect/author/selective-download`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            platform: "bilibili",
            author_uid: activeAuthorFolder.authorUid ?? activeAuthorFolder.name,
            selected_video_folders: selectedPendingVideoFolders,
          }),
        }
      )
      if (!response.ok) {
        throw new Error(`下载请求失败: ${response.status}`)
      }
      const result = await response.json()
      if (!result?.success) {
        throw new Error(result?.message || "下载任务创建失败")
      }
      setSelectedPendingVideoFolders([])
      window.dispatchEvent(new Event("tasks:refresh"))
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "下载失败")
    } finally {
      setIsDownloadingSelected(false)
    }
  }

  useEffect(() => {
    if (!onRegisterDeleteHandler) return
    if (!selectMode) {
      onRegisterDeleteHandler(null)
      return
    }
    onRegisterDeleteHandler(handleDeleteSelected)
    return () => onRegisterDeleteHandler(null)
  }, [handleDeleteSelected, onRegisterDeleteHandler, selectMode])

  const isPathSelectedForDelete = (relativePath?: string) =>
    Boolean(relativePath && selectedDeletePaths.includes(relativePath))

  return (
    <div className="flex h-full overflow-hidden">
      <section className="min-w-0 flex-1 overflow-auto">
        <ul className="divide-y divide-white/5 border-y border-white/5">
          {rootFolders.map((folder) => {
            const isActive = activeRootId === folder.id
            return (
              <li key={folder.id}>
                <button
                  type="button"
                  onClick={() => {
                    setActiveRootId((prev) => (prev === folder.id ? null : folder.id))
                    setActiveSubId(null)
                    setActiveThirdId(null)
                    setExpandedAuthorSubId(null)
                    setActiveAuthorFolderId(null)
                    setSelectedPendingVideoFolders([])
                  }}
                  className={cn(
                    "flex h-11 w-full items-center justify-between px-5 text-left transition-colors",
                    isActive ? "bg-white/5" : "hover:bg-white/2.5"
                  )}
                >
                  <span className="flex min-w-0 items-center gap-2.5 text-sm text-zinc-200">
                    {isActive ? (
                      <FolderOpen className="size-4 shrink-0 text-zinc-300" />
                    ) : (
                      <Folder className="size-4 shrink-0 text-zinc-400" />
                    )}
                    <span className="truncate">{folder.name}</span>
                  </span>
                  <span className="flex shrink-0 items-center gap-2 text-xs text-zinc-500">
                    <span>{folder.children.length}</span>
                    <ChevronRight className="size-3.5" />
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
        {!loading && rootFolders.length === 0 && (
          <div className="px-5 py-4 text-xs text-zinc-500">暂无目录数据</div>
        )}
      </section>

      <aside
        className={cn(
          "shrink-0 overflow-hidden border-l border-white/5 bg-black/25 transition-[width,opacity,transform] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]",
          activeRoot ? "w-85 opacity-100 translate-x-0" : "w-0 opacity-0 translate-x-2"
        )}
      >
        <div
          className={cn(
            "h-full transition-opacity duration-200",
            activeRoot ? "opacity-100 delay-75" : "pointer-events-none opacity-0"
          )}
        >
          {activeRoot && (
            <ul className="divide-y divide-white/5 border-y border-white/5">
              {activeRoot.children.map((child) => {
                const isNestedAuthorFolder = isAuthorNestedSubfolder(
                  activeRoot.id,
                  child.name
                )
                const isActive = activeSubId === child.id
                const isNestedExpanded = expandedAuthorSubId === child.id
                const hasNestedAuthorSelected =
                  isNestedAuthorFolder &&
                  isNestedExpanded &&
                  activeAuthorFolderId !== null

                return (
                  <li key={child.id}>
                    <button
                      type="button"
                      onClick={() => {
                        if (isNestedAuthorFolder) {
                          setExpandedAuthorSubId((prev) =>
                            prev === child.id ? null : child.id
                          )
                          setActiveAuthorFolderId(null)
                          setActiveSubId(null)
                          setActiveThirdId(null)
                          return
                        }
                        setActiveSubId((prev) => (prev === child.id ? null : child.id))
                        setActiveThirdId(null)
                        setExpandedAuthorSubId(null)
                        setActiveAuthorFolderId(null)
                        setSelectedPendingVideoFolders([])
                      }}
                      className={cn(
                        "flex h-11 w-full items-center justify-between px-5 text-left text-sm transition-colors",
                        isActive || isNestedExpanded || hasNestedAuthorSelected
                          ? "bg-white/5 text-zinc-200"
                          : "text-zinc-300 hover:bg-white/2.5"
                      )}
                    >
                      <span className="flex min-w-0 items-center gap-2.5">
                        {isActive || isNestedExpanded ? (
                          <FolderOpen className="size-4 shrink-0 text-zinc-300" />
                        ) : (
                          <Folder className="size-4 shrink-0 text-zinc-500" />
                        )}
                        <span className="truncate">{child.name}</span>
                      </span>
                      <span className="flex shrink-0 items-center gap-2 text-xs text-zinc-500">
                        <span>{child.children.length}</span>
                        <ChevronRight
                          className={cn(
                            "size-3.5 transition-transform duration-200",
                            isNestedAuthorFolder && isNestedExpanded && "rotate-90"
                          )}
                        />
                      </span>
                    </button>

                    {isNestedAuthorFolder && isNestedExpanded && (
                      <ul className="divide-y divide-white/4 border-t border-white/5 bg-black/30">
                        {child.children.length > 0 ? (
                          child.children.map((authorFolder) => {
                            const isAuthorActive =
                              activeAuthorFolderId === authorFolder.id
                            const canDeleteAuthorFolder = Boolean(
                              selectMode &&
                                authorFolder.relativePath &&
                                authorFolder.isDir !== false &&
                                getMaterialDepth(authorFolder.relativePath) === 3
                            )
                            const isAuthorSelectedForDelete = isPathSelectedForDelete(
                              authorFolder.relativePath
                            )
                            return (
                              <li key={authorFolder.id}>
                                <button
                                  type="button"
                                  onClick={() => {
                                    setActiveAuthorFolderId((prev) =>
                                      prev === authorFolder.id ? null : authorFolder.id
                                    )
                                    setActiveSubId(null)
                                    setActiveThirdId(null)
                                  }}
                                  className={cn(
                                    "flex h-10 w-full items-center justify-between pl-10 pr-5 text-left text-sm transition-colors",
                                    isAuthorActive
                                      ? "bg-white/6 text-zinc-100"
                                      : "text-zinc-300 hover:bg-white/3"
                                  )}
                                >
                                  <span className="flex min-w-0 items-center gap-2.5">
                                    {canDeleteAuthorFolder && authorFolder.relativePath && (
                                      <span
                                        role="button"
                                        tabIndex={0}
                                        onClick={(event) => {
                                          event.stopPropagation()
                                          toggleDeleteSelection(authorFolder.relativePath!)
                                        }}
                                        onKeyDown={(event) => {
                                          if (event.key === "Enter" || event.key === " ") {
                                            event.preventDefault()
                                            event.stopPropagation()
                                            toggleDeleteSelection(authorFolder.relativePath!)
                                          }
                                        }}
                                        className="inline-flex size-4 shrink-0 items-center justify-center"
                                      >
                                        {isAuthorSelectedForDelete ? (
                                          <CheckCircle2 className="size-4 shrink-0 text-red-400" />
                                        ) : (
                                          <Circle className="size-4 shrink-0 text-zinc-500" />
                                        )}
                                      </span>
                                    )}
                                    {isAuthorActive ? (
                                      <FolderOpen className="size-4 shrink-0 text-zinc-300" />
                                    ) : (
                                      <Folder className="size-4 shrink-0 text-zinc-500" />
                                    )}
                                    <span className="truncate">{authorFolder.name}</span>
                                  </span>
                                  <span className="flex shrink-0 items-center gap-2 text-xs text-zinc-500">
                                    <span>{authorFolder.children.length}</span>
                                    <ChevronRight className="size-3.5" />
                                  </span>
                                </button>
                              </li>
                            )
                          })
                        ) : (
                          <li>
                            <div className="px-10 py-3 text-xs text-zinc-500">
                              暂无作者目录
                            </div>
                          </li>
                        )}
                      </ul>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      </aside>

      <aside
        className={cn(
          "shrink-0 overflow-hidden border-l border-white/5 bg-black/20 transition-[width,opacity,transform] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]",
          showRightPanel
            ? "w-90 opacity-100 translate-x-0"
            : "w-0 opacity-0 translate-x-2"
        )}
      >
        <div
          className={cn(
            "h-full transition-opacity duration-200",
            showRightPanel ? "opacity-100 delay-100" : "pointer-events-none opacity-0"
          )}
        >
          {showRightPanel && (
            <>
              {isPendingAuthorContext && !selectMode && (
                <div className="flex items-center justify-between border-y border-white/5 bg-black/35 px-4 py-2">
                  <p className="text-xs text-zinc-400">
                    已选 {selectedPendingVideoFolders.length} 个作品
                  </p>
                  <button
                    type="button"
                    onClick={handleDownloadSelected}
                    disabled={
                      selectedPendingVideoFolders.length === 0 || isDownloadingSelected
                    }
                    className="inline-flex h-7 items-center gap-1 rounded-full border border-white/14 px-3 text-xs text-zinc-200 transition-colors hover:bg-white/6 disabled:cursor-not-allowed disabled:opacity-45"
                  >
                    {isDownloadingSelected ? (
                      <Loader2 className="size-3.5 animate-spin" />
                    ) : null}
                    <span>下载选中</span>
                  </button>
                </div>
              )}
              {actionError && (
                <div className="border-b border-white/5 px-4 py-2 text-xs text-red-300">
                  {actionError}
                </div>
              )}

              <ul className="divide-y divide-white/5 border-b border-white/5">
                {rightPanelFolders.length > 0 ? (
                  rightPanelFolders.map((child) => {
                    if (isPendingAuthorContext) {
                      if (selectMode) {
                        return (
                          <li key={child.id}>
                            <div className="flex h-11 w-full items-center justify-between px-5 text-left text-sm text-zinc-300">
                              <span className="flex min-w-0 items-center gap-2.5">
                                <Folder className="size-4 shrink-0 text-zinc-500" />
                                <span className="min-w-0 truncate">{child.name}</span>
                              </span>
                              <span className="text-xs text-zinc-500">
                                {child.children.length}
                              </span>
                            </div>
                          </li>
                        )
                      }

                      const isSelected = selectedPendingVideoFolders.includes(child.name)
                      return (
                        <li key={child.id}>
                          <button
                            type="button"
                            onClick={() => togglePendingSelection(child.name)}
                            className={cn(
                              "flex h-11 w-full items-center justify-between px-5 text-left text-sm transition-colors",
                              isSelected
                                ? "bg-white/6 text-zinc-100"
                                : "text-zinc-300 hover:bg-white/3"
                            )}
                          >
                            <span className="flex min-w-0 items-center gap-2.5">
                              {isSelected ? (
                                <CheckCircle2 className="size-4 shrink-0 text-emerald-400" />
                              ) : (
                                <Circle className="size-4 shrink-0 text-zinc-500" />
                              )}
                              <span className="min-w-0 truncate">{child.name}</span>
                            </span>
                            <span className="text-xs text-zinc-500">
                              {child.children.length}
                            </span>
                          </button>
                        </li>
                      )
                    }

                    const isInteractive = Boolean(
                      activeSub || (activeAuthorFolder && !isPendingAuthorContext)
                    )
                    const isActive = isInteractive && activeThirdId === child.id
                    const canDeleteThirdFolder = Boolean(
                      selectMode &&
                        child.relativePath &&
                        child.isDir !== false &&
                        (
                          (activeSub && getMaterialDepth(child.relativePath) === 3) ||
                          (activeAuthorFolder &&
                            !isPendingAuthorContext &&
                            getMaterialDepth(child.relativePath) === 4)
                        )
                    )
                    const isThirdFolderSelectedForDelete = isPathSelectedForDelete(
                      child.relativePath
                    )
                    if (!isInteractive) {
                      return (
                        <li key={child.id}>
                          <div className="flex h-11 w-full items-center gap-2.5 px-5 text-sm text-zinc-300">
                            <Folder className="size-4 shrink-0 text-zinc-500" />
                            <span className="min-w-0 truncate">{child.name}</span>
                          </div>
                        </li>
                      )
                    }

                    return (
                      <li key={child.id}>
                        <button
                          type="button"
                          onClick={() => {
                            setActiveThirdId((prev) => (prev === child.id ? null : child.id))
                          }}
                          className={cn(
                            "flex h-11 w-full items-center justify-between px-5 text-left text-sm transition-colors",
                            isActive
                              ? "bg-white/5 text-zinc-200"
                              : "text-zinc-300 hover:bg-white/2.5"
                          )}
                        >
                          <span className="flex min-w-0 items-center gap-2.5">
                            {canDeleteThirdFolder && child.relativePath && (
                              <span
                                role="button"
                                tabIndex={0}
                                onClick={(event) => {
                                  event.stopPropagation()
                                  toggleDeleteSelection(child.relativePath!)
                                }}
                                onKeyDown={(event) => {
                                  if (event.key === "Enter" || event.key === " ") {
                                    event.preventDefault()
                                    event.stopPropagation()
                                    toggleDeleteSelection(child.relativePath!)
                                  }
                                }}
                                className="inline-flex size-4 shrink-0 items-center justify-center"
                              >
                                {isThirdFolderSelectedForDelete ? (
                                  <CheckCircle2 className="size-4 shrink-0 text-red-400" />
                                ) : (
                                  <Circle className="size-4 shrink-0 text-zinc-500" />
                                )}
                              </span>
                            )}
                            {isActive ? (
                              <FolderOpen className="size-4 shrink-0 text-zinc-300" />
                            ) : (
                              <Folder className="size-4 shrink-0 text-zinc-500" />
                            )}
                            <span className="min-w-0 truncate">{child.name}</span>
                          </span>
                          <span className="flex shrink-0 items-center gap-2 text-xs text-zinc-500">
                            <span>{child.children.length}</span>
                            <ChevronRight className="size-3.5" />
                          </span>
                        </button>
                      </li>
                    )
                  })
                ) : (
                  <li>
                    <div className="px-5 py-4 text-xs text-zinc-500">暂无详细目录</div>
                  </li>
                )}
              </ul>
            </>
          )}
        </div>
      </aside>

      <aside
        className={cn(
          "shrink-0 overflow-hidden border-l border-white/5 bg-black/15 transition-[width,opacity,transform] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)]",
          showFourthPanel
            ? "w-85 opacity-100 translate-x-0"
            : "w-0 opacity-0 translate-x-2"
        )}
      >
        <div
          className={cn(
            "h-full transition-opacity duration-200",
            showFourthPanel
              ? "opacity-100 delay-100"
              : "pointer-events-none opacity-0"
          )}
        >
          {showFourthPanel && activeThird && (
            <ul className="divide-y divide-white/5 border-y border-white/5">
              {activeThird.children.length > 0 ? (
                activeThird.children.map((child) => {
                  const canDeleteFile = Boolean(
                    selectMode &&
                      child.relativePath &&
                      child.isDir === false &&
                      [4, 5].includes(getMaterialDepth(child.relativePath))
                  )
                  const isFileSelectedForDelete = isPathSelectedForDelete(
                    child.relativePath
                  )

                  if (canDeleteFile && child.relativePath) {
                    return (
                      <li key={child.id}>
                        <button
                          type="button"
                          onClick={() => toggleDeleteSelection(child.relativePath!)}
                          className="flex h-11 w-full items-center gap-2.5 px-5 text-left text-sm text-zinc-300 transition-colors hover:bg-white/2.5"
                        >
                          {isFileSelectedForDelete ? (
                            <CheckCircle2 className="size-4 shrink-0 text-red-400" />
                          ) : (
                            <Circle className="size-4 shrink-0 text-zinc-500" />
                          )}
                          <Folder className="size-4 shrink-0 text-zinc-500" />
                          <span className="min-w-0 truncate">{child.name}</span>
                        </button>
                      </li>
                    )
                  }

                  return (
                    <li key={child.id}>
                      <div className="flex h-11 w-full items-center gap-2.5 px-5 text-sm text-zinc-300">
                        <Folder className="size-4 shrink-0 text-zinc-500" />
                        <span className="min-w-0 truncate">{child.name}</span>
                      </div>
                    </li>
                  )
                })
              ) : (
                <li>
                  <div className="px-5 py-4 text-xs text-zinc-500">暂无详细文件</div>
                </li>
              )}
            </ul>
          )}
        </div>
      </aside>
    </div>
  )
}
