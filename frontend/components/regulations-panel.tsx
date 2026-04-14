"use client"

import { useEffect, useMemo, useState } from "react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { BookOpen, Search, ExternalLink, Clock, Tag, Database } from "lucide-react"
import type { Regulation } from "@/lib/types"

interface RegulationsPanelProps {
  regulations: Regulation[]
  onRegulationsUpdated?: () => void | Promise<void>
}

interface SearchIngestResult {
  count: number
  results: Array<{
    bill_id: string
    status: "updated" | "no_change" | "skipped" | "error"
    reason?: string
    error?: string
  }>
}

interface SyncStatus {
  lastRunAt?: string | null
  lastSuccessAt?: string | null
  lastError?: string | null
  searchUrl?: string | null
  maxBills?: number | null
  schedulerEnabled?: boolean | null
  schedulerIntervalHours?: number | null
  stats?: {
    parsed?: number
    saved?: number
    skipped?: number
    errors?: number
  } | null
}

interface RagStatus {
  total_chunks: number
  source_type_counts: Record<string, number>
  is_ready: boolean
}

interface RegulationSource {
  id: string
  name: string
  source_type: "bills" | "handbook"
  enabled: boolean
  search_url?: string | null
  max_bills?: number | null
  source_url?: string | null
}

interface SyncSelectedResult {
  selected: string[]
  results: Array<{
    source_id: string
    source_type: "bills" | "handbook"
    status: "ok" | "skipped"
    reason?: string
    result?: SearchIngestResult
  }>
}

const DEFAULT_SOURCE_POOL: RegulationSource[] = [
  {
    id: "bills",
    name: "California ADU Bills",
    source_type: "bills",
    enabled: true,
    search_url:
      "https://leginfo.legislature.ca.gov/faces/billSearchClient.xhtml?author=All&lawCode=All&session_year=20252026&keyword=ADU&house=Both",
    max_bills: 50,
  },
  {
    id: "handbook",
    name: "California ADU Handbook",
    source_type: "handbook",
    enabled: true,
    source_url: "https://www.hcd.ca.gov/sites/default/files/docs/policy-and-research/adu-handbook-update.pdf",
  },
]

export function RegulationsPanel({ regulations, onRegulationsUpdated }: RegulationsPanelProps) {
  const [searchTerm, setSearchTerm] = useState("")
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [sources, setSources] = useState<RegulationSource[]>([])
  const [ingestResult, setIngestResult] = useState<SearchIngestResult | null>(null)
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null)
  const [handbookSyncStatus, setHandbookSyncStatus] = useState<SyncStatus | null>(null)
  const [ragStatus, setRagStatus] = useState<RagStatus | null>(null)
  const [isSyncing, setIsSyncing] = useState(false)
  const [isSavingSources, setIsSavingSources] = useState(false)
  const [isReindexing, setIsReindexing] = useState(false)
  const [ragActionMessage, setRagActionMessage] = useState<string | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [newSourceName, setNewSourceName] = useState("")
  const [newSourceType, setNewSourceType] = useState<"bills" | "handbook">("bills")
  const [newSourceUrl, setNewSourceUrl] = useState("")
  const [newSourceMaxBills, setNewSourceMaxBills] = useState(50)

  const backendBase = process.env.NEXT_PUBLIC_BACKEND_URL ?? ""
  const buildUrl = (path: string) => (backendBase ? `${backendBase}${path}` : path)

  const categories = Array.from(new Set(regulations.map((r) => r.category)))

  const latestRegulation = useMemo(() => {
    if (regulations.length === 0) return null
    return [...regulations].sort(
      (a, b) => new Date(b.lastUpdated).getTime() - new Date(a.lastUpdated).getTime()
    )[0]
  }, [regulations])

  const linkedSourcesCount = useMemo(
    () => regulations.filter((reg) => Boolean(reg.sourceUrl)).length,
    [regulations]
  )

  const filteredRegulations = regulations.filter((reg) => {
    const matchesSearch =
      reg.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
      reg.content.toLowerCase().includes(searchTerm.toLowerCase())
    const matchesCategory = !selectedCategory || reg.category === selectedCategory
    return matchesSearch && matchesCategory
  })

  const getCategoryColor = (category: string) => {
    switch (category) {
      case "height":
        return "bg-blue-100 text-blue-800"
      case "setback":
        return "bg-green-100 text-green-800"
      case "design":
        return "bg-amber-100 text-amber-800"
      default:
        return "bg-gray-100 text-gray-800"
    }
  }

  const formatDateTime = (value?: string | null) => {
    if (!value) return "N/A"
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return "N/A"
    return date.toLocaleString()
  }

  const formatRelativeTime = (value?: string | null) => {
    if (!value) return "N/A"
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return "N/A"
    const diffMinutes = Math.floor((Date.now() - date.getTime()) / 60000)
    if (diffMinutes < 1) return "Just now"
    if (diffMinutes < 60) return `${diffMinutes} min ago`
    if (diffMinutes < 1440) return `${Math.floor(diffMinutes / 60)} hr ago`
    const days = Math.floor(diffMinutes / 1440)
    return `${days} day${days > 1 ? "s" : ""} ago`
  }

  const loadSyncStatus = async () => {
    try {
      const [billResponse, handbookResponse] = await Promise.all([
        fetch(buildUrl("/api/regulations/sync-status")),
        fetch(buildUrl("/api/regulations/handbook-sync-status")),
      ])

      if (billResponse.ok) {
        const billData = (await billResponse.json()) as SyncStatus
        setSyncStatus(billData)
      }

      if (handbookResponse.ok) {
        const handbookData = (await handbookResponse.json()) as SyncStatus
        setHandbookSyncStatus(handbookData)
      }
    } catch {
      setSyncStatus(null)
      setHandbookSyncStatus(null)
    }
  }

  const loadRagStatus = async () => {
    try {
      const response = await fetch(buildUrl("/api/regulations/rag/status"))
      if (!response.ok) return
      const data = (await response.json()) as RagStatus
      setRagStatus(data)
    } catch {
      setRagStatus(null)
    }
  }

  const loadSources = async () => {
    const applyDefaults = () => setSources(DEFAULT_SOURCE_POOL)

    try {
      const primaryUrl = buildUrl("/api/regulations/sources")
      let response = await fetch(primaryUrl)

      if (!response.ok && backendBase) {
        response = await fetch("/api/regulations/sources")
      }

      if (!response.ok) {
        applyDefaults()
        return
      }

      const data = (await response.json()) as RegulationSource[]
      if (!Array.isArray(data) || data.length === 0) {
        applyDefaults()
        return
      }

      const hasBills = data.some((source) => source.id === "bills")
      const hasHandbook = data.some((source) => source.id === "handbook")
      if (!hasBills || !hasHandbook) {
        const merged = [...data]
        if (!hasBills) {
          merged.push(DEFAULT_SOURCE_POOL[0])
        }
        if (!hasHandbook) {
          merged.push(DEFAULT_SOURCE_POOL[1])
        }
        setSources(merged)
        return
      }

      setSources(data)
    } catch {
      applyDefaults()
    }
  }

  useEffect(() => {
    void loadSyncStatus()
    void loadRagStatus()
    void loadSources()
  }, [])

  const updateSource = (id: string, patch: Partial<RegulationSource>) => {
    setSources((prev) => prev.map((source) => (source.id === id ? { ...source, ...patch } : source)))
  }

  const handleAddSource = () => {
    const trimmedName = newSourceName.trim()
    const fallbackName = newSourceType === "bills" ? "New Bills Source" : "New Handbook Source"
    const name = trimmedName || fallbackName
    const safeName = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "") || "source"
    const id = `${safeName}-${Date.now()}`

    const newSource: RegulationSource =
      newSourceType === "bills"
        ? {
            id,
            name,
            source_type: "bills",
            enabled: true,
            search_url: newSourceUrl.trim(),
            max_bills: newSourceMaxBills,
          }
        : {
            id,
            name,
            source_type: "handbook",
            enabled: true,
            source_url: newSourceUrl.trim(),
          }

    setSources((prev) => [...prev, newSource])
    setNewSourceName("")
    setNewSourceUrl("")
    setNewSourceMaxBills(50)
  }

  const handleSaveSources = async () => {
    setIsSavingSources(true)
    setErrorMessage(null)
    try {
      const response = await fetch(buildUrl("/api/regulations/sources"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sources }),
      })
      if (!response.ok) {
        throw new Error(`Save sources failed: ${response.status}`)
      }
      await loadSources()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Failed to save sources")
    } finally {
      setIsSavingSources(false)
    }
  }

  const handleSyncSelected = async () => {
    setIsSyncing(true)
    setErrorMessage(null)
    setIngestResult(null)
    try {
      const selectedSourceIds = sources.filter((source) => source.enabled).map((source) => source.id)
      if (selectedSourceIds.length === 0) {
        throw new Error("Select at least one source to sync")
      }

      const response = await fetch(buildUrl("/api/regulations/sync-selected"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_ids: selectedSourceIds }),
      })
      if (!response.ok) {
        throw new Error(`Sync selected failed: ${response.status}`)
      }

      const data = (await response.json()) as SyncSelectedResult
      const billsResult = data.results.find((item) => item.source_type === "bills" && item.status === "ok")
      if (billsResult?.result) {
        setIngestResult(billsResult.result)
      }

      await loadSyncStatus()
      await loadRagStatus()
      if (onRegulationsUpdated) {
        await onRegulationsUpdated()
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Failed to sync selected sources")
    } finally {
      setIsSyncing(false)
    }
  }

  const handleReindex = async () => {
    setIsReindexing(true)
    setErrorMessage(null)
    setRagActionMessage(null)
    try {
      const response = await fetch(buildUrl("/api/regulations/rag/reindex"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ include_handbook: true, include_bills: true }),
      })
      const data = (await response.json()) as {
        indexed_docs?: number
        index_status?: RagStatus
        error?: string
      }
      if (!response.ok || data.error) {
        throw new Error(data.error ?? `Reindex failed: ${response.status}`)
      }
      if (data.index_status) {
        setRagStatus(data.index_status)
      }
      setRagActionMessage(`Reindex complete. Indexed ${data.indexed_docs ?? 0} documents.`)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Failed to reindex")
    } finally {
      setIsReindexing(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <BookOpen className="h-5 w-5" />
          <CardTitle>Regulation Knowledge Base</CardTitle>
        </div>
        <CardDescription>
          Current ADU regulations with version tracking and source references
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="rounded-lg border bg-muted/30 p-4 space-y-3">
          <div className="flex items-center justify-between gap-2">
            <div>
              <p className="text-sm font-medium">Sync & Index Management</p>
              <p className="text-xs text-muted-foreground">
                Sync regulation sources and manage local RAG index
              </p>
            </div>
            <Badge variant="outline">3.1</Badge>
          </div>

          <div className="mt-2 rounded-md border bg-background p-3 space-y-3">
            <div className="flex items-center justify-between gap-2">
              <p className="text-xs font-medium">Source Pool</p>
              <Badge variant="outline">{sources.length} sources</Badge>
            </div>

            <Collapsible className="rounded-md border p-3" defaultOpen={false}>
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs font-medium">Add Source</p>
                <CollapsibleTrigger asChild>
                  <Button type="button" variant="outline" size="sm">Expand</Button>
                </CollapsibleTrigger>
              </div>
              <CollapsibleContent className="mt-3 space-y-2">
                <div className="grid gap-2 sm:grid-cols-3">
                  <Input
                    value={newSourceName}
                    onChange={(e) => setNewSourceName(e.target.value)}
                    placeholder="Source name"
                  />
                  <select
                    className="h-9 rounded-md border bg-background px-3 text-sm"
                    value={newSourceType}
                    onChange={(e) => setNewSourceType(e.target.value as "bills" | "handbook")}
                  >
                    <option value="bills">bills</option>
                    <option value="handbook">handbook</option>
                  </select>
                  <Button type="button" variant="outline" onClick={handleAddSource}>
                    Add Source
                  </Button>
                </div>
                <div className="grid gap-2 sm:grid-cols-[1fr,120px]">
                  <Input
                    value={newSourceUrl}
                    onChange={(e) => setNewSourceUrl(e.target.value)}
                    placeholder={newSourceType === "bills" ? "LegInfo search URL" : "Handbook PDF URL"}
                  />
                  {newSourceType === "bills" ? (
                    <Input
                      value={String(newSourceMaxBills)}
                      onChange={(e) => setNewSourceMaxBills(Number(e.target.value) || 0)}
                      placeholder="Max bills"
                    />
                  ) : (
                    <div />
                  )}
                </div>
              </CollapsibleContent>
            </Collapsible>

            {sources.map((source) => (
              <Collapsible key={source.id} className="rounded-md border p-3" defaultOpen={false}>
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <p className="text-xs font-medium">{source.name}</p>
                    <Badge variant="outline">{source.source_type}</Badge>
                    <Badge variant={source.enabled ? "secondary" : "outline"}>
                      {source.enabled ? "Enabled" : "Disabled"}
                    </Badge>
                  </div>
                  <CollapsibleTrigger asChild>
                    <Button type="button" variant="outline" size="sm">Edit</Button>
                  </CollapsibleTrigger>
                </div>
                <CollapsibleContent className="mt-3 space-y-2">
                  <label className="flex items-center gap-2 text-xs font-medium">
                    <input
                      type="checkbox"
                      checked={source.enabled}
                      onChange={(e) => updateSource(source.id, { enabled: e.target.checked })}
                    />
                    Enabled
                  </label>

                  {source.source_type === "bills" ? (
                    <div className="grid gap-2 sm:grid-cols-[1fr,120px]">
                      <Input
                        value={source.search_url ?? ""}
                        onChange={(e) => updateSource(source.id, { search_url: e.target.value })}
                        placeholder="LegInfo search URL"
                      />
                      <Input
                        value={String(source.max_bills ?? 50)}
                        onChange={(e) => updateSource(source.id, { max_bills: Number(e.target.value) || 0 })}
                        placeholder="Max bills"
                      />
                    </div>
                  ) : (
                    <Input
                      value={source.source_url ?? ""}
                      onChange={(e) => updateSource(source.id, { source_url: e.target.value })}
                      placeholder="Handbook PDF URL"
                    />
                  )}
                </CollapsibleContent>
              </Collapsible>
            ))}

            <div className="flex flex-wrap items-center gap-2">
              <Button variant="outline" onClick={handleSaveSources} disabled={isSavingSources}>
                {isSavingSources ? "Saving Sources..." : "Save Source Settings"}
              </Button>
              <p className="text-xs text-muted-foreground">
                Handbook sync: {formatRelativeTime(handbookSyncStatus?.lastSuccessAt)}
              </p>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <Button onClick={handleSyncSelected} disabled={isSyncing}>
              {isSyncing ? "Syncing Selected..." : "Sync Selected Sources"}
            </Button>
            <Button variant="outline" onClick={handleReindex} disabled={isReindexing}>
              {isReindexing ? "Reindexing..." : "Reindex RAG"}
            </Button>
          </div>

          {errorMessage && (
            <div className="text-xs text-destructive">{errorMessage}</div>
          )}

          {ingestResult && (
            <div className="text-xs text-muted-foreground">
              Synced {ingestResult.count} bills. Updated:{" "}
              {ingestResult.results.filter((r) => r.status === "updated").length},
              No change:{" "}
              {ingestResult.results.filter((r) => r.status === "no_change").length},
              Skipped:{" "}
              {ingestResult.results.filter((r) => r.status === "skipped").length}
            </div>
          )}

          {ragActionMessage && (
            <div className="text-xs text-muted-foreground">{ragActionMessage}</div>
          )}

          <div className="grid gap-2 sm:grid-cols-3">
            <div className="rounded-md border bg-background p-3">
              <p className="text-xs text-muted-foreground">Last successful sync</p>
              <p className="text-sm font-medium">{formatRelativeTime(syncStatus?.lastSuccessAt)}</p>
              <p className="text-xs text-muted-foreground mt-1">
                {formatDateTime(syncStatus?.lastSuccessAt)}
              </p>
            </div>
            <div className="rounded-md border bg-background p-3">
              <p className="text-xs text-muted-foreground">Latest regulation update</p>
              <p className="text-sm font-medium">
                {formatRelativeTime(latestRegulation?.lastUpdated)}
              </p>
              <p className="text-xs text-muted-foreground mt-1">
                {formatDateTime(latestRegulation?.lastUpdated)}
              </p>
              {latestRegulation?.sourceUrl && (
                <Button variant="outline" size="sm" className="mt-2 h-7 text-xs" asChild>
                  <a href={latestRegulation.sourceUrl} target="_blank" rel="noreferrer">
                    <ExternalLink className="h-3 w-3 mr-1" />
                    Open latest source
                  </a>
                </Button>
              )}
            </div>
            <div className="rounded-md border bg-background p-3">
              <p className="text-xs text-muted-foreground">Source-linked regulations</p>
              <p className="text-sm font-medium">
                {linkedSourcesCount} of {regulations.length}
              </p>
              {syncStatus?.lastError ? (
                <p className="text-xs text-destructive mt-1 line-clamp-2">Last error: {syncStatus.lastError}</p>
              ) : (
                <p className="text-xs text-muted-foreground mt-1">No recent sync errors</p>
              )}
              {handbookSyncStatus?.lastError && (
                <p className="text-xs text-destructive mt-1 line-clamp-2">
                  Handbook error: {handbookSyncStatus.lastError}
                </p>
              )}
            </div>
          </div>

          <div className="rounded-md border bg-background p-3 space-y-2">
            <div className="flex items-center gap-2">
              <Database className="h-4 w-4" />
              <p className="text-xs font-medium">RAG Index</p>
            </div>
            <p className="text-xs text-muted-foreground">
              Status: {ragStatus?.is_ready ? "Ready" : "Not ready"} • Chunks: {ragStatus?.total_chunks ?? 0}
            </p>
            {ragStatus?.source_type_counts && (
              <div className="flex flex-wrap gap-2">
                {Object.entries(ragStatus.source_type_counts).map(([sourceType, count]) => (
                  <Badge key={sourceType} variant="outline" className="text-xs">
                    {sourceType}: {count}
                  </Badge>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="flex flex-col sm:flex-row gap-3">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search regulations..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="pl-9"
            />
          </div>
          <div className="flex gap-2 flex-wrap">
            <Button
              variant={selectedCategory === null ? "default" : "outline"}
              size="sm"
              onClick={() => setSelectedCategory(null)}
            >
              All
            </Button>
            {categories.map((cat) => (
              <Button
                key={cat}
                variant={selectedCategory === cat ? "default" : "outline"}
                size="sm"
                onClick={() => setSelectedCategory(cat)}
                className="capitalize"
              >
                {cat}
              </Button>
            ))}
          </div>
        </div>

        <div className="space-y-3">
          {filteredRegulations.map((reg) => (
            <div
              key={reg.id}
              className="border rounded-lg overflow-hidden"
            >
              <div
                className="p-4 cursor-pointer hover:bg-muted/50 transition-colors"
                onClick={() => setExpandedId(expandedId === reg.id ? null : reg.id)}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-1">
                      <h4 className="font-medium">{reg.title}</h4>
                      <Badge className={getCategoryColor(reg.category)}>
                        {reg.category}
                      </Badge>
                    </div>
                    <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground mb-1">
                      <span className="flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        Updated {formatRelativeTime(reg.lastUpdated)}
                      </span>
                      <span className="flex items-center gap-1">
                        <Tag className="h-3 w-3" />
                        {reg.source}
                      </span>
                    </div>
                    <p className="text-sm text-muted-foreground line-clamp-2">
                      {reg.content}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <Badge variant="outline">v{reg.version}</Badge>
                    {reg.sourceUrl && (
                      <Button variant="outline" size="sm" asChild>
                        <a href={reg.sourceUrl} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>
                          <ExternalLink className="h-3 w-3" />
                        </a>
                      </Button>
                    )}
                  </div>
                </div>
              </div>

              {expandedId === reg.id && (
                <div className="px-4 pb-4 pt-0 border-t bg-muted/30">
                  <div className="pt-4 space-y-3">
                    <p className="text-sm">{reg.content}</p>
                    <div className="flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
                      <span className="flex items-center gap-1">
                        <Tag className="h-3 w-3" />
                        {reg.source}
                      </span>
                      <span className="flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        Effective: {new Date(reg.effectiveDate).toLocaleDateString()}
                      </span>
                      <span className="flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        Updated: {new Date(reg.lastUpdated).toLocaleDateString()}
                      </span>
                    </div>
                    {reg.sourceUrl && (
                      <Button variant="outline" size="sm" className="mt-2" asChild>
                        <a href={reg.sourceUrl} target="_blank" rel="noreferrer">
                          <ExternalLink className="h-3 w-3 mr-1" />
                          View Full Text
                        </a>
                      </Button>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}

          {filteredRegulations.length === 0 && (
            <div className="text-center py-8 text-muted-foreground">
              <BookOpen className="h-8 w-8 mx-auto mb-2 opacity-50" />
              <p>No regulations found matching your criteria</p>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
