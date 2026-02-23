import { useCallback, useRef, useState } from "react"
import { MaterialHeaderBar } from "@/components/dashboard/material-header-bar"
import { MaterialFolderBrowser } from "@/components/dashboard/material-folder-browser"

export function MaterialMainContent() {
  const [selectMode, setSelectMode] = useState(false)
  const [selectedCount, setSelectedCount] = useState(0)
  const [isDeleting, setIsDeleting] = useState(false)
  const deleteHandlerRef = useRef<(() => Promise<void>) | null>(null)

  const handleToggleSelectMode = useCallback(() => {
    setSelectMode((prev) => !prev)
  }, [])

  const handleDeleteSelected = useCallback(async () => {
    const handler = deleteHandlerRef.current
    if (!handler) return
    await handler()
  }, [])

  return (
    <div className="flex h-full flex-col">
      <MaterialHeaderBar
        selectMode={selectMode}
        selectedCount={selectedCount}
        isDeleting={isDeleting}
        onToggleSelectMode={handleToggleSelectMode}
        onDeleteSelected={handleDeleteSelected}
      />
      <main className="min-h-0 flex-1 overflow-hidden">
        <MaterialFolderBrowser
          selectMode={selectMode}
          onSelectionCountChange={setSelectedCount}
          onDeletingChange={setIsDeleting}
          onRegisterDeleteHandler={(handler) => {
            deleteHandlerRef.current = handler
          }}
        />
      </main>
    </div>
  )
}
