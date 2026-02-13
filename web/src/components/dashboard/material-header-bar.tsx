import { Search, SlidersHorizontal } from "lucide-react"

type MaterialHeaderBarProps = {
  selectMode: boolean
  selectedCount: number
  isDeleting: boolean
  onToggleSelectMode: () => void
  onDeleteSelected: () => void | Promise<void>
}

export function MaterialHeaderBar({
  selectMode,
  selectedCount,
  isDeleting,
  onToggleSelectMode,
  onDeleteSelected,
}: MaterialHeaderBarProps) {
  return (
    <div className="flex h-11 shrink-0 items-center justify-between border-b border-white/8 px-5">
      <div className="flex items-center gap-2">
        <button className="inline-flex items-center gap-1.5 rounded-full border border-white/12 px-3 py-1 text-[13px] font-medium text-zinc-300 transition-colors duration-100 hover:bg-white/5">
          <SlidersHorizontal className="size-3.5" />
          <span>筛选</span>
        </button>
        <button
          onClick={onToggleSelectMode}
          className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[13px] font-medium transition-colors duration-100 ${
            selectMode
              ? "border-white/24 bg-white/10 text-zinc-100"
              : "border-white/12 text-zinc-300 hover:bg-white/5"
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
      </div>

      <div className="inline-flex h-8 w-65 items-center gap-2 rounded-full border border-white/12 bg-white/3 px-3 text-zinc-400 transition-colors focus-within:border-white/18 focus-within:bg-white/5">
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
