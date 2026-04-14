export interface Regulation {
  id: string
  title: string
  category: "height" | "setback" | "design" | "general"
  content: string
  effectiveDate: string
  version: string
  source: string
  sourceUrl?: string
  lastUpdated: string
}

export interface RegulationChange {
  id: string
  regulationId: string
  title: string
  changeType: "new" | "amended" | "repealed"
  summary: string
  previousVersion: string
  newVersion: string
  effectiveDate: string
  impactLevel: "high" | "medium" | "low"
  affectedApplications: number
  createdAt: string
  isRead: boolean
}

export interface Query {
  id: string
  question: string
  answer: string
  regulationVersion: string
  timestamp: string
  category: string
}

export interface AuditEntry {
  id: string
  action: string
  regulationId: string
  regulationTitle: string
  previousVersion: string
  newVersion: string
  timestamp: string
  user: string
  details: string
}
