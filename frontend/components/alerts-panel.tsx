"use client"

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Bell, AlertTriangle, CheckCircle, Info, FileWarning } from "lucide-react"
import type { RegulationChange } from "@/lib/types"

interface AlertsPanelProps {
  changes: RegulationChange[]
  onMarkRead: (id: string) => void
}

export function AlertsPanel({ changes, onMarkRead }: AlertsPanelProps) {
  const unreadCount = changes.filter((c) => !c.isRead).length

  const getImpactIcon = (level: string) => {
    switch (level) {
      case "high":
        return <AlertTriangle className="h-4 w-4 text-red-500" />
      case "medium":
        return <Info className="h-4 w-4 text-amber-500" />
      default:
        return <CheckCircle className="h-4 w-4 text-green-500" />
    }
  }

  const getImpactBadge = (level: string) => {
    switch (level) {
      case "high":
        return "bg-red-100 text-red-800 border-red-200"
      case "medium":
        return "bg-amber-100 text-amber-800 border-amber-200"
      default:
        return "bg-green-100 text-green-800 border-green-200"
    }
  }

  const getChangeTypeBadge = (type: string) => {
    switch (type) {
      case "new":
        return "bg-blue-100 text-blue-800"
      case "amended":
        return "bg-amber-100 text-amber-800"
      case "repealed":
        return "bg-red-100 text-red-800"
      default:
        return "bg-gray-100 text-gray-800"
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Bell className="h-5 w-5" />
            <CardTitle>Regulation Change Alerts</CardTitle>
            {unreadCount > 0 && (
              <Badge variant="destructive" className="ml-2">
                {unreadCount} new
              </Badge>
            )}
          </div>
        </div>
        <CardDescription>
          Monitoring California Housing and Community Development (HCD) updates
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {changes.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <Bell className="h-8 w-8 mx-auto mb-2 opacity-50" />
              <p>No regulation changes to report</p>
            </div>
          ) : (
            changes.map((change) => (
              <div
                key={change.id}
                className={`p-4 border rounded-lg space-y-3 transition-colors ${
                  !change.isRead ? "bg-blue-50/50 border-blue-200" : ""
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-start gap-2">
                    {getImpactIcon(change.impactLevel)}
                    <div>
                      <h4 className="font-medium text-sm">{change.title}</h4>
                      <p className="text-xs text-muted-foreground">
                        Effective: {new Date(change.effectiveDate).toLocaleDateString()}
                      </p>
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <Badge className={getChangeTypeBadge(change.changeType)}>
                      {change.changeType}
                    </Badge>
                    <Badge variant="outline" className={getImpactBadge(change.impactLevel)}>
                      {change.impactLevel} impact
                    </Badge>
                  </div>
                </div>

                <p className="text-sm text-muted-foreground">{change.summary}</p>

                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-4 text-xs text-muted-foreground">
                    <span>
                      Version: {change.previousVersion} → {change.newVersion}
                    </span>
                    {change.affectedApplications > 0 && (
                      <span className="flex items-center gap-1">
                        <FileWarning className="h-3 w-3" />
                        {change.affectedApplications} pending applications affected
                      </span>
                    )}
                  </div>
                  {!change.isRead && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => onMarkRead(change.id)}
                    >
                      Mark as read
                    </Button>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      </CardContent>
    </Card>
  )
}
