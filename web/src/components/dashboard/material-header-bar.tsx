import { useCallback, useEffect, useRef, useState } from "react"
import { ClipboardPaste, Search, SlidersHorizontal } from "lucide-react"

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000"

type MaterialHeaderBarProps = {
  selectMode: boolean
  selectedCount: number
  isDeleting: boolean
  onToggleSelectMode: () => void
  onDeleteSelected: () => void | Promise<void>
}

/* ------------------------------------------------------------------ */
/*  Cookie 粘贴弹窗                                                    */
/* ------------------------------------------------------------------ */
function CookiePasteDialog({
  platform,
  label,
  open,
  onClose,
}: {
  platform: "bilibili" | "douyin" | "xiaohongshu" | "longmao"
  label: string
  open: boolean
  onClose: () => void
}) {
  const [value, setValue] = useState("")
  const [status, setStatus] = useState<"idle" | "loading" | "success" | "error">("idle")
  const [msg, setMsg] = useState("")
  const [loadingExisting, setLoadingExisting] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const getUrl = platform === "longmao"
    ? `${API_BASE}/api/longmao/token/get`
    : `${API_BASE}/api/${platform}/cookie/get`
  const setUrl = platform === "longmao"
    ? `${API_BASE}/api/longmao/token/set`
    : `${API_BASE}/api/${platform}/cookie/set`

  useEffect(() => {
    if (open) {
      setStatus("idle")
      setMsg("")
      setLoadingExisting(true)
      fetch(getUrl)
        .then((r) => r.json())
        .then((d) => {
          setValue(d?.cookie ?? "")
        })
        .catch(() => setValue(""))
        .finally(() => {
          setLoadingExisting(false)
          setTimeout(() => textareaRef.current?.focus(), 50)
        })
    }
  }, [open, platform])

  const handleSubmit = async () => {
    const trimmed = value.trim()
    if (!trimmed) return
    setStatus("loading")
    try {
      const res = await fetch(setUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cookie: trimmed }),
      })
      const data = await res.json()
      if (data?.success) {
        setStatus("success")
        setMsg(data.message || "已保存")
        setTimeout(() => onClose(), 1500)
      } else {
        setStatus("error")
        setMsg(data?.message || "保存失败")
      }
    } catch {
      setStatus("error")
      setMsg("请求失败，请检查后端是否运行")
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div
        className="w-[480px] rounded-xl border border-white/[0.1] bg-zinc-900 p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="mb-3 text-sm font-medium text-zinc-200">
          粘贴{label} {platform === "longmao" ? "Token" : "Cookie"}
        </h3>
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={platform === "longmao"
            ? "请从浏览器 LocalStorage 中复制 Token 并粘贴到此处..."
            : `请从浏览器开发者工具中复制${label}的 Cookie 并粘贴到此处...`}
          className="h-28 w-full resize-none rounded-lg border border-white/[0.1] bg-black/30 px-3 py-2 text-xs text-zinc-300 placeholder:text-zinc-600 outline-none focus:border-white/[0.2]"
        />
        {msg && (
          <p className={`mt-2 text-xs ${status === "success" ? "text-emerald-400" : "text-red-400"}`}>
            {msg}
          </p>
        )}
        <div className="mt-3 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded-lg border border-white/[0.1] px-3 py-1.5 text-xs text-zinc-400 hover:bg-white/[0.05]"
          >
            取消
          </button>
          <button
            onClick={() => void handleSubmit()}
            disabled={!value.trim() || status === "loading"}
            className="rounded-lg border border-white/[0.14] bg-white/[0.08] px-3 py-1.5 text-xs text-zinc-200 hover:bg-white/[0.12] disabled:cursor-not-allowed disabled:opacity-40"
          >
            {status === "loading" ? "保存中..." : "保存"}
          </button>
        </div>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  主组件                                                              */
/* ------------------------------------------------------------------ */
export function MaterialHeaderBar({
  selectMode,
  selectedCount,
  isDeleting,
  onToggleSelectMode,
  onDeleteSelected,
}: MaterialHeaderBarProps) {
  /* B站 Cookie 状态 */
  const [cookieKeyCount, setCookieKeyCount] = useState<number | null>(null)

  /* 抖音 / 小红书 Cookie 状态 */
  const [douyinKeyCount, setDouyinKeyCount] = useState<number | null>(null)
  const [xhsKeyCount, setXhsKeyCount] = useState<number | null>(null)

  /* Longmao Token 状态 */
  const [longmaoSet, setLongmaoSet] = useState(false)

  /* 粘贴弹窗 */
  const [pasteDialog, setPasteDialog] = useState<{ platform: "bilibili" | "douyin" | "xiaohongshu" | "longmao"; label: string } | null>(null)

  /* 初始加载所有 cookie / token 状态 */
  useEffect(() => {
    fetch(`${API_BASE}/api/bilibili/cookie/status`)
      .then((r) => r.json())
      .then((d) => { if (d?.key_count) setCookieKeyCount(d.key_count) })
      .catch(() => {})

    fetch(`${API_BASE}/api/douyin/cookie/status`)
      .then((r) => r.json())
      .then((d) => { if (d?.key_count) setDouyinKeyCount(d.key_count) })
      .catch(() => {})

    fetch(`${API_BASE}/api/xiaohongshu/cookie/status`)
      .then((r) => r.json())
      .then((d) => { if (d?.key_count) setXhsKeyCount(d.key_count) })
      .catch(() => {})

    fetch(`${API_BASE}/api/longmao/token/status`)
      .then((r) => r.json())
      .then((d) => { setLongmaoSet(!!d?.is_set) })
      .catch(() => {})
  }, [])

  /* 关闭弹窗后刷新对应平台的 key count */
  const handleDialogClose = useCallback(() => {
    const platform = pasteDialog?.platform
    setPasteDialog(null)
    if (platform === "bilibili") {
      fetch(`${API_BASE}/api/bilibili/cookie/status`)
        .then((r) => r.json())
        .then((d) => { if (d?.key_count) setCookieKeyCount(d.key_count) })
        .catch(() => {})
    } else if (platform === "douyin") {
      fetch(`${API_BASE}/api/douyin/cookie/status`)
        .then((r) => r.json())
        .then((d) => { if (d?.key_count) setDouyinKeyCount(d.key_count) })
        .catch(() => {})
    } else if (platform === "xiaohongshu") {
      fetch(`${API_BASE}/api/xiaohongshu/cookie/status`)
        .then((r) => r.json())
        .then((d) => { if (d?.key_count) setXhsKeyCount(d.key_count) })
        .catch(() => {})
    } else if (platform === "longmao") {
      fetch(`${API_BASE}/api/longmao/token/status`)
        .then((r) => r.json())
        .then((d) => { setLongmaoSet(!!d?.is_set) })
        .catch(() => {})
    }
  }, [pasteDialog])

  return (
    <>
      <div className="flex h-11 shrink-0 items-center justify-between border-b border-white/[0.08] px-5">
        <div className="flex items-center gap-2">
          <button className="inline-flex items-center gap-1.5 rounded-full border border-white/[0.12] px-3 py-1 text-[13px] font-medium text-zinc-300 transition-colors duration-100 hover:bg-white/[0.05]">
            <SlidersHorizontal className="size-3.5" />
            <span>筛选</span>
          </button>
          <button
            onClick={onToggleSelectMode}
            className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[13px] font-medium transition-colors duration-100 ${
              selectMode
                ? "border-white/[0.24] bg-white/[0.10] text-zinc-100"
                : "border-white/[0.12] text-zinc-300 hover:bg-white/[0.05]"
            }`}
          >
            <span>选择</span>
          </button>
          {selectMode && (
            <button
              onClick={() => void onDeleteSelected()}
              disabled={selectedCount === 0 || isDeleting}
              className="inline-flex items-center gap-1.5 rounded-full border border-red-400/40 bg-red-500/10 px-3 py-1 text-[13px] font-medium text-red-300 transition-colors duration-100 hover:bg-red-500/20 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <span>{isDeleting ? "删除中..." : `删除${selectedCount > 0 ? ` (${selectedCount})` : ""}`}</span>
            </button>
          )}

          <div className="mx-1 h-4 w-px bg-white/[0.08]" />

          {/* B站 Cookie 粘贴 */}
          <button
            onClick={() => setPasteDialog({ platform: "bilibili", label: "B站" })}
            className="inline-flex items-center gap-1.5 rounded-full border border-white/[0.12] px-3 py-1 text-[13px] font-medium text-zinc-300 transition-colors duration-100 hover:bg-white/[0.05]"
          >
            <ClipboardPaste className="size-3.5" />
            <span>B站Cookie{cookieKeyCount ? ` (${cookieKeyCount})` : ""}</span>
          </button>

          {/* 抖音 Cookie 粘贴 */}
          <button
            onClick={() => setPasteDialog({ platform: "douyin", label: "抖音" })}
            className="inline-flex items-center gap-1.5 rounded-full border border-white/[0.12] px-3 py-1 text-[13px] font-medium text-zinc-300 transition-colors duration-100 hover:bg-white/[0.05]"
          >
            <ClipboardPaste className="size-3.5" />
            <span>抖音Cookie{douyinKeyCount ? ` (${douyinKeyCount})` : ""}</span>
          </button>

          {/* 小红书 Cookie 粘贴 */}
          <button
            onClick={() => setPasteDialog({ platform: "xiaohongshu", label: "小红书" })}
            className="inline-flex items-center gap-1.5 rounded-full border border-white/[0.12] px-3 py-1 text-[13px] font-medium text-zinc-300 transition-colors duration-100 hover:bg-white/[0.05]"
          >
            <ClipboardPaste className="size-3.5" />
            <span>小红书Cookie{xhsKeyCount ? ` (${xhsKeyCount})` : ""}</span>
          </button>

          {/* Longmao Token 粘贴 */}
          <button
            onClick={() => setPasteDialog({ platform: "longmao", label: "解析Token" })}
            className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[13px] font-medium transition-colors duration-100 ${
              longmaoSet
                ? "border-emerald-400/30 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/15"
                : "border-white/[0.12] text-zinc-300 hover:bg-white/[0.05]"
            }`}
          >
            <ClipboardPaste className="size-3.5" />
            <span>解析Token{longmaoSet ? " ✓" : ""}</span>
          </button>
        </div>

        <div className="inline-flex h-8 w-[260px] items-center gap-2 rounded-full border border-white/[0.12] bg-white/[0.03] px-3 text-zinc-400 transition-colors focus-within:border-white/[0.18] focus-within:bg-white/[0.05]">
          <Search className="size-3.5 shrink-0 text-zinc-500" />
          <input
            type="text"
            placeholder="搜索素材 / 作者"
            className="h-full w-full bg-transparent text-[13px] text-zinc-200 placeholder:text-zinc-500 outline-none"
          />
        </div>
      </div>

      {/* Cookie 粘贴弹窗 */}
      {pasteDialog && (
        <CookiePasteDialog
          platform={pasteDialog.platform}
          label={pasteDialog.label}
          open
          onClose={handleDialogClose}
        />
      )}
    </>
  )
}
