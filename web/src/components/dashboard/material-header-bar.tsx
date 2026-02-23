import { useCallback, useEffect, useState } from "react"
import { Chrome, Check, Loader2, Search, SlidersHorizontal, X } from "lucide-react"

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000"

type MaterialHeaderBarProps = {
  selectMode: boolean
  selectedCount: number
  isDeleting: boolean
  onToggleSelectMode: () => void
  onDeleteSelected: () => void | Promise<void>
}

type CookieStatus = "idle" | "loading" | "success" | "error"

export function MaterialHeaderBar({
  selectMode,
  selectedCount,
  isDeleting,
  onToggleSelectMode,
  onDeleteSelected,
}: MaterialHeaderBarProps) {
  const [cookieStatus, setCookieStatus] = useState<CookieStatus>("idle")
  const [cookieMsg, setCookieMsg] = useState("")
  const [cookieKeyCount, setCookieKeyCount] = useState<number | null>(null)

  /* 初始加载 cookie 状态 */
  useEffect(() => {
    fetch(`${API_BASE}/api/bilibili/cookie/status`)
      .then((r) => r.json())
      .then((d) => {
        if (d?.key_count) setCookieKeyCount(d.key_count)
      })
      .catch(() => {})
  }, [])

  const handleAutoDetect = useCallback(async () => {
    setCookieStatus("loading")
    setCookieMsg("")
    try {
      const res = await fetch(`${API_BASE}/api/bilibili/cookie/auto-detect`, {
        method: "POST",
      })
      const data = await res.json()
      console.log("[B站Cookie] 完整响应:", JSON.stringify(data, null, 2))
      if (data?.success) {
        const isLoggedIn = data.verify?.is_login === true
        setCookieStatus(isLoggedIn ? "success" : "error")
        setCookieMsg(data.message || "已更新")
        setCookieKeyCount(data.key_count ?? null)
        setTimeout(() => setCookieStatus("idle"), isLoggedIn ? 3000 : 6000)
      } else {
        setCookieStatus("error")
        setCookieMsg(data?.message || "获取失败")
        setTimeout(() => setCookieStatus("idle"), 5000)
      }
    } catch {
      setCookieStatus("error")
      setCookieMsg("请求失败，请检查后端是否运行")
      setTimeout(() => setCookieStatus("idle"), 5000)
    }
  }, [])

  return (
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

        {/* B站 Cookie 自动获取 */}
        <button
          onClick={() => void handleAutoDetect()}
          disabled={cookieStatus === "loading"}
          className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[13px] font-medium transition-colors duration-100 ${
            cookieStatus === "success"
              ? "border-emerald-400/40 bg-emerald-500/10 text-emerald-300"
              : cookieStatus === "error"
                ? "border-red-400/40 bg-red-500/10 text-red-300"
                : "border-white/[0.12] text-zinc-300 hover:bg-white/[0.05]"
          } disabled:cursor-not-allowed disabled:opacity-60`}
        >
          {cookieStatus === "loading" ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : cookieStatus === "success" ? (
            <Check className="size-3.5" />
          ) : cookieStatus === "error" ? (
            <X className="size-3.5" />
          ) : (
            <Chrome className="size-3.5" />
          )}
          <span>
            {cookieStatus === "loading"
              ? "获取中..."
              : cookieStatus === "success"
                ? cookieMsg
                : cookieStatus === "error"
                  ? cookieMsg
                  : `B站Cookie${cookieKeyCount ? ` (${cookieKeyCount})` : ""}`}
          </span>
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
  )
}
