import type { Regulation, RegulationChange, Query, AuditEntry } from "./types"

export const mockRegulations: Regulation[] = [
  {
    id: "1",
    title: "Maximum ADU Height",
    category: "height",
    content: "Detached ADUs may be up to 16 feet in height. ADUs attached to a primary dwelling may be up to 25 feet or the height of the primary dwelling, whichever is lower. Two-story ADUs are permitted in most zones.",
    effectiveDate: "2024-01-01",
    version: "3.2",
    source: "CA Government Code Section 65852.2",
    lastUpdated: "2024-01-15"
  },
  {
    id: "2",
    title: "Setback Requirements",
    category: "setback",
    content: "ADUs must maintain a 4-foot setback from side and rear property lines. No setback is required for conversions of existing structures or new construction in the same location and dimensions as an existing structure.",
    effectiveDate: "2024-01-01",
    version: "2.8",
    source: "CA Government Code Section 65852.2(c)",
    lastUpdated: "2024-02-10"
  },
  {
    id: "3",
    title: "Garage Door Design Standards",
    category: "design",
    content: "Garage doors shall not exceed 9 feet in height for single-car doors and 8 feet for double-car doors. Garage doors must be compatible with the architectural style of the primary dwelling.",
    effectiveDate: "2023-07-01",
    version: "1.5",
    source: "Local Municipal Code Section 17.52",
    lastUpdated: "2023-12-05"
  },
  {
    id: "4",
    title: "Floor Area Limits",
    category: "general",
    content: "Attached ADUs may be up to 50% of the existing primary dwelling floor area or 1,200 square feet, whichever is less. Detached ADUs may be up to 1,200 square feet regardless of primary dwelling size.",
    effectiveDate: "2024-01-01",
    version: "4.0",
    source: "CA Government Code Section 65852.2(a)(1)(B)",
    lastUpdated: "2024-01-01"
  },
  {
    id: "5",
    title: "Parking Requirements",
    category: "general",
    content: "No parking is required for ADUs located within half-mile of public transit, in historic districts, or when the ADU is part of an existing primary residence or accessory structure. Otherwise, one parking space may be required.",
    effectiveDate: "2024-01-01",
    version: "2.3",
    source: "CA Government Code Section 65852.2(d)",
    lastUpdated: "2024-03-01"
  }
]

export const mockChanges: RegulationChange[] = [
  {
    id: "1",
    regulationId: "1",
    title: "Height Limit Increase for Detached ADUs",
    changeType: "amended",
    summary: "Maximum height for detached ADUs increased from 16 feet to 18 feet in zones R-2 and R-3 to allow for more flexible design options.",
    previousVersion: "3.1",
    newVersion: "3.2",
    effectiveDate: "2024-04-01",
    impactLevel: "high",
    affectedApplications: 23,
    createdAt: "2024-03-15",
    isRead: false
  },
  {
    id: "2",
    regulationId: "4",
    title: "Floor Area Calculation Method Update",
    changeType: "amended",
    summary: "Clarification added that floor area calculations exclude covered patios and carports under 200 sq ft.",
    previousVersion: "3.9",
    newVersion: "4.0",
    effectiveDate: "2024-01-01",
    impactLevel: "medium",
    affectedApplications: 12,
    createdAt: "2024-01-05",
    isRead: true
  },
  {
    id: "3",
    regulationId: "5",
    title: "Transit Proximity Definition Expanded",
    changeType: "amended",
    summary: "Transit proximity for parking exemption expanded from 0.5 miles to 0.75 miles from transit stops.",
    previousVersion: "2.2",
    newVersion: "2.3",
    effectiveDate: "2024-03-01",
    impactLevel: "medium",
    affectedApplications: 8,
    createdAt: "2024-02-20",
    isRead: false
  },
  {
    id: "4",
    regulationId: "new",
    title: "New Solar Panel Requirements for ADUs",
    changeType: "new",
    summary: "New regulation requiring solar panel installation for ADUs over 800 sq ft in new construction projects.",
    previousVersion: "N/A",
    newVersion: "1.0",
    effectiveDate: "2024-06-01",
    impactLevel: "high",
    affectedApplications: 45,
    createdAt: "2024-03-01",
    isRead: false
  }
]

export const mockQueries: Query[] = [
  {
    id: "1",
    question: "Can I have a 2-story ADU?",
    answer: "Yes, two-story ADUs are permitted in most zones under current California law. Detached ADUs may be up to 16 feet in height, while attached ADUs may be up to 25 feet or the height of the primary dwelling, whichever is lower.",
    regulationVersion: "3.2",
    timestamp: "2024-03-18T10:30:00",
    category: "height"
  },
  {
    id: "2",
    question: "What's the maximum height for garage doors?",
    answer: "Garage doors shall not exceed 9 feet in height for single-car doors and 8 feet for double-car doors. They must be compatible with the architectural style of the primary dwelling.",
    regulationVersion: "1.5",
    timestamp: "2024-03-17T14:15:00",
    category: "design"
  },
  {
    id: "3",
    question: "What are current ADU setback requirements?",
    answer: "ADUs must maintain a 4-foot setback from side and rear property lines. No setback is required for conversions of existing structures or new construction in the same location and dimensions as an existing structure.",
    regulationVersion: "2.8",
    timestamp: "2024-03-16T09:45:00",
    category: "setback"
  }
]

export const mockAuditEntries: AuditEntry[] = [
  {
    id: "1",
    action: "Regulation Updated",
    regulationId: "1",
    regulationTitle: "Maximum ADU Height",
    previousVersion: "3.1",
    newVersion: "3.2",
    timestamp: "2024-03-15T08:00:00",
    user: "System (Auto-sync)",
    details: "Height limit increased from 16ft to 18ft for R-2/R-3 zones"
  },
  {
    id: "2",
    action: "Query Answered",
    regulationId: "1",
    regulationTitle: "Maximum ADU Height",
    previousVersion: "3.2",
    newVersion: "3.2",
    timestamp: "2024-03-18T10:30:00",
    user: "Planner: J. Smith",
    details: "Responded to 2-story ADU inquiry using version 3.2"
  },
  {
    id: "3",
    action: "Regulation Added",
    regulationId: "new",
    regulationTitle: "Solar Panel Requirements",
    previousVersion: "N/A",
    newVersion: "1.0",
    timestamp: "2024-03-01T12:00:00",
    user: "System (Auto-sync)",
    details: "New regulation from HCD regarding solar requirements"
  },
  {
    id: "4",
    action: "Alert Sent",
    regulationId: "5",
    regulationTitle: "Parking Requirements",
    previousVersion: "2.2",
    newVersion: "2.3",
    timestamp: "2024-02-20T16:30:00",
    user: "System",
    details: "Notification sent to 12 staff members regarding parking rule change"
  }
]
