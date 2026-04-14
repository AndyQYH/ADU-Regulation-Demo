"use client"

import { useEffect, useState } from "react"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { DashboardStats } from "@/components/dashboard-stats"
import { QueryPanel } from "@/components/query-panel"
import { AlertsPanel } from "@/components/alerts-panel"
import { RegulationsPanel } from "@/components/regulations-panel"
import { AuditTrail } from "@/components/audit-trail"
import { mockQueries } from "@/lib/mock-data"
import type { Query, Regulation, RegulationChange, AuditEntry } from "@/lib/types"
import { Building2, MessageCircle, Bell, BookOpen, ScrollText } from "lucide-react"

export default function ADUKnowledgeManagement() {
  const [queries, setQueries] = useState<Query[]>(mockQueries)
  const [changes, setChanges] = useState<RegulationChange[]>([])
  const [auditEntries, setAuditEntries] = useState<AuditEntry[]>([])
  const [regulations, setRegulations] = useState<Regulation[]>([])
  const [lastSyncTime, setLastSyncTime] = useState("Never")

  const loadRegulations = async () => {
    try {
      const response = await fetch("/api/regulations/knowledge-base?limit=100")
      if (!response.ok) return
      const data = (await response.json()) as Regulation[]
      setRegulations(data)
    } catch {
      setRegulations([])
    }
  }

  const loadAlerts = async () => {
    try {
      const response = await fetch("/api/regulations/alerts?limit=100")
      if (!response.ok) return
      const data = (await response.json()) as RegulationChange[]
      setChanges(data)
    } catch {
      setChanges([])
    }
  }

  const loadAudit = async () => {
    try {
      const response = await fetch("/api/regulations/audit?limit=100")
      if (!response.ok) return
      const data = (await response.json()) as AuditEntry[]
      setAuditEntries(data)
    } catch {
      setAuditEntries([])
    }
  }

  const loadSyncStatus = async () => {
    try {
      const response = await fetch("/api/regulations/sync-status")
      if (!response.ok) return
      const data = (await response.json()) as {
        lastSuccessAt?: string | null
        lastRunAt?: string | null
      }
      const timestamp = data.lastSuccessAt || data.lastRunAt
      if (!timestamp) {
        setLastSyncTime("Never")
        return
      }

      const syncDate = new Date(timestamp)
      const now = new Date()
      const diffMinutes = Math.floor((now.getTime() - syncDate.getTime()) / 60000)
      if (diffMinutes < 1) {
        setLastSyncTime("Just now")
      } else if (diffMinutes < 60) {
        setLastSyncTime(`${diffMinutes} min ago`)
      } else if (diffMinutes < 1440) {
        const hours = Math.floor(diffMinutes / 60)
        setLastSyncTime(`${hours} hr ago`)
      } else {
        const days = Math.floor(diffMinutes / 1440)
        setLastSyncTime(`${days} day${days > 1 ? "s" : ""} ago`)
      }
    } catch {
      setLastSyncTime("Unknown")
    }
  }

  const refreshRegulationData = async () => {
    await Promise.all([loadRegulations(), loadAlerts(), loadAudit(), loadSyncStatus()])
  }

  useEffect(() => {
    void refreshRegulationData()
  }, [])

  const handleNewQuery = (query: Query) => {
    setQueries((prev) => [query, ...prev])
    
    // Add to audit trail
    const auditEntry: AuditEntry = {
      id: Date.now().toString(),
      action: "Query Answered",
      regulationId: query.id,
      regulationTitle: `${query.category.charAt(0).toUpperCase() + query.category.slice(1)} Regulation`,
      previousVersion: query.regulationVersion,
      newVersion: query.regulationVersion,
      timestamp: query.timestamp,
      user: "Current User",
      details: `Query: "${query.question.substring(0, 50)}..."`,
    }
    setAuditEntries((prev) => [auditEntry, ...prev])
  }

  const handleMarkRead = (id: string) => {
    setChanges((prev) =>
      prev.map((change) =>
        change.id === id ? { ...change, isRead: true } : change
      )
    )
  }

  const pendingAlerts = changes.filter((c) => !c.isRead).length

  return (
    <div className="min-h-screen bg-muted/30">
      {/* Header */}
      <header className="bg-background border-b sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 py-4">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-primary rounded-lg">
              <Building2 className="h-6 w-6 text-primary-foreground" />
            </div>
            <div>
              <h1 className="text-xl font-semibold">ADU Regulation Knowledge System</h1>
              <p className="text-sm text-muted-foreground">
                California ADU Law Tracking & Compliance
              </p>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 py-6 space-y-6">
        {/* Stats Overview */}
        <DashboardStats
          totalRegulations={regulations.length}
          pendingAlerts={pendingAlerts}
          queriesThisMonth={queries.length}
          lastSyncTime={lastSyncTime}
        />

        {/* Main Tabs */}
        <Tabs defaultValue="query" className="space-y-4">
          <TabsList className="grid grid-cols-4 w-full max-w-2xl">
            <TabsTrigger value="query" className="flex items-center gap-2">
              <MessageCircle className="h-4 w-4" />
              <span className="hidden sm:inline">Query</span>
            </TabsTrigger>
            <TabsTrigger value="alerts" className="flex items-center gap-2">
              <Bell className="h-4 w-4" />
              <span className="hidden sm:inline">Alerts</span>
              {pendingAlerts > 0 && (
                <span className="ml-1 bg-destructive text-destructive-foreground text-xs rounded-full px-1.5 py-0.5">
                  {pendingAlerts}
                </span>
              )}
            </TabsTrigger>
            <TabsTrigger value="regulations" className="flex items-center gap-2">
              <BookOpen className="h-4 w-4" />
              <span className="hidden sm:inline">Regulations</span>
            </TabsTrigger>
            <TabsTrigger value="audit" className="flex items-center gap-2">
              <ScrollText className="h-4 w-4" />
              <span className="hidden sm:inline">Audit Trail</span>
            </TabsTrigger>
          </TabsList>

          <TabsContent value="query">
            <QueryPanel recentQueries={queries} onNewQuery={handleNewQuery} />
          </TabsContent>

          <TabsContent value="alerts">
            <AlertsPanel changes={changes} onMarkRead={handleMarkRead} />
          </TabsContent>

          <TabsContent value="regulations">
            <RegulationsPanel regulations={regulations} onRegulationsUpdated={refreshRegulationData} />
          </TabsContent>

          <TabsContent value="audit">
            <AuditTrail entries={auditEntries} />
          </TabsContent>
        </Tabs>
      </main>

      {/* Footer */}
      <footer className="border-t mt-12 py-4 text-center text-sm text-muted-foreground">
        <p>ADU Regulation Knowledge Management System • Data sourced from California HCD</p>
      </footer>
    </div>
  )
}
